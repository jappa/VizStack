/*
* VizStack - A Framework to manage visualization resources

* Copyright (C) 2009-2010 Hewlett-Packard
* 
* This program is free software; you can redistribute it and/or
* modify it under the terms of the GNU General Public License
* as published by the Free Software Foundation; either version 2
* of the License, or (at your option) any later version.
* 
* This program is distributed in the hope that it will be useful,
* but WITHOUT ANY WARRANTY; without even the implied warranty of
* MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
* GNU General Public License for more details.
* 
* You should have received a copy of the GNU General Public License
* along with this program; if not, write to the Free Software
* Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
*/

//
// vs-aew
//
// VizStack's application execution wrapper.
//
// Serves two purposes
//
// 1. Creates a process group, and then runs the real application.
//    This ensures that when this process dies, all children
//    (direct and otherwise) get a HUP message, with the default 
//    action of exit.
//
// 2. Responds to closure of STDIN by sending the TERM signal to
//    the application. This is done to make it possible to 
//    reach to closure of a passwordless SSH session. Typically,
//    when an SSH session gets closed the apps keep running. By
//    reacting to closure of STDIN, we achieve a roundabout way
//    of finding out that the SSH session exited.
//
#include <sys/select.h>
#include <sys/time.h>
#include <sys/types.h>
#include <unistd.h>
#include <sys/wait.h>
#include <stdio.h>
#include <unistd.h>
#include <stdlib.h>
#include <errno.h>
#include <signal.h>
#include <string.h>

int g_signotify_pipe[2];
#define CODE_SIGCHLD '0'
#define CODE_SIGUSR1  '1'
#define CODE_SIGHUP   '2'
#define CODE_SIGTERM  '3'
#define CODE_SIGINT   '4'

void addNotification(int whichPipe[2], unsigned char c)
{
	write(whichPipe[1], &c, 1);
}

void sigchild_handler(int sig)
{
	addNotification(g_signotify_pipe, CODE_SIGCHLD);
}
void sigint_handler(int sig)
{
	addNotification(g_signotify_pipe, CODE_SIGINT);
}
void sigterm_handler(int sig)
{
	// Handle TERM once. We have a loop which guarantees a KILL after a timeout.
	static bool termProcessed = false;
	if(!termProcessed)
		addNotification(g_signotify_pipe, CODE_SIGTERM);
	termProcessed = true;
}

#define RETRY_ON_EINTR(ret, x)  { \
	while(1) { \
		ret = x; \
		if(ret == -1) { \
			if(errno==EINTR) \
				 continue; \
		} \
		else \
			break; \
	} \
}
int main(int argc, char** argv)
{
	if(argc<2)
	{
		fprintf(stderr, "You need to specify atleast a program to run.\n");
		exit(-1);
	}

	// When the user did SSH and directly executed this program, 
	// I notice that the program is already a process group leader !
	// SSH probably does this. We avoid failure by not trying to create
	// a process group if we're already the leader of one !
	if(getpgid(getpid())!=getpid())
	{
		int ret = setpgid(0,0);
		if(ret<0)
		{
			perror("vs-aew : Couldn't create a process group");
			exit(-1);
		}
	}

	if(pipe(g_signotify_pipe)<0)
	{
		perror("vs-aew : Failed to create pipe!");
		exit(-1);
	}

	bool hasStdin = true;
	int cmdBase = 1;
	if(strcmp(argv[1],"-ignorestdin")==0)
	{
		hasStdin = false;
		cmdBase=2;
		if(argc<3)
		{
			fprintf(stderr, "You need to specify atleast a program to run.\n");
			exit(-1);
		}
	}

	int childIO[2];
	if(hasStdin)
	{
		if(pipe(childIO)<0)
		{
			perror("vs-aew : Failed to create pipe!");
			exit(-1);
		}
	}


	// Register SIGCHLD handler first so that we get exit notifications from our child
	// app
	struct sigaction siginfo;
	siginfo.sa_handler = sigchild_handler;
	siginfo.sa_flags = SA_RESTART; 
	sigemptyset (&siginfo.sa_mask);
	sigaction(SIGCHLD, &siginfo, NULL);

	siginfo.sa_handler = sigint_handler;
	siginfo.sa_flags = SA_RESTART; 
	sigemptyset (&siginfo.sa_mask);
	sigaction(SIGINT, &siginfo, NULL);

	siginfo.sa_handler = sigterm_handler;
	siginfo.sa_flags = SA_RESTART; 
	sigemptyset (&siginfo.sa_mask);
	sigaction(SIGTERM, &siginfo, NULL);

	int childpid = fork();
	if(childpid<0)
	{
		perror("vs-aew : failed to start application");
		exit(-1);
	}

	if(childpid==0)
	{
		close(g_signotify_pipe[0]);
		close(g_signotify_pipe[1]);

		if(hasStdin)
		{
			// close the write end; we don't need it
			close(childIO[1]);
			dup2(childIO[0], 0);
			close(childIO[0]); // close after duplication
		}
		//char *newenviron[] = { NULL };
		//execve(argv[1], argv+1, newenviron);
		execvp(argv[cmdBase], argv+cmdBase);
		perror("vs-aew : Failed to start application");
		fprintf(stderr, "The program specified to run was '%s'\n", argv[cmdBase]);
		exit(-1);
	}

	// close the read end - we don't need it
	if (hasStdin)
		close(childIO[0]);

	int retCode = 0;
	bool loopDone = false;
	unsigned int kill9timeout = 0;
	unsigned int killTimeout = -1;
	bool killDone = false;

#define KILLTIMEOUT 20

	while(!loopDone)
	{
		if(killTimeout==0)
		{
			// If kill timeout expired, then send the term signal
			if(!killDone)
			{
				kill(0, SIGTERM);
				kill9timeout = KILLTIMEOUT;
			}
			killTimeout = -1;
		}
		if(kill9timeout >0)
		{
			kill9timeout--;
			if(kill9timeout==0)
			{
				fprintf(stderr, "Timeout. Terminating child processes in the process group.\n");
				kill(0, SIGKILL);
			}
		}
		else
		// Kill everyone if our parent process died !
		if(getppid()==1)
		{
			if(!killDone)
			{
				kill(0, SIGTERM);
				kill9timeout = KILLTIMEOUT;
				killDone = true;
			}
		}

		fd_set rfds;
		FD_ZERO(&rfds);
		if(hasStdin)
		{
			FD_SET(0,&rfds); // set to react to stdin
		}
		FD_SET (g_signotify_pipe[0], &rfds);

		struct timeval tv;
		tv.tv_sec = 1;
		tv.tv_usec = 0;

		int ret = select(g_signotify_pipe[0]+1, &rfds,  NULL, NULL, &tv);

		if(killTimeout>0)
		{
			killTimeout --;
		}

		if(ret<0)
		{
			if(errno==EINTR)
				continue;
			else
			{
				perror("vs-aew : unexpected problem doing select");
				exit(-1);
			}
		}

		if(FD_ISSET(g_signotify_pipe[0], &rfds))
		{
			// determine what signal we received by
			// reading the pipe
			char buf=0;
			RETRY_ON_EINTR(ret, read(g_signotify_pipe[0], &buf, 1));
			switch(buf)
			{
				case CODE_SIGCHLD:
					// a child process exited.
					{
						int exitstatus;
						int retpid;
						// did our child X server exit ?
						if((retpid=waitpid(childpid, &exitstatus, WNOHANG))==childpid)
						{
							loopDone = true;
							retCode = -1;
							if(WIFEXITED(exitstatus))
							{
								retCode = WEXITSTATUS(exitstatus);
							}
							else
							if(WIFSIGNALED(exitstatus))
							{
								retCode = 128+WTERMSIG(exitstatus);
							}
						}
						else
						{
							if(retpid!=0)
							{
								// other child process exits cause us to come here.
								fprintf(stderr, "FATAL: Bad case. pid=%d - we aren't supposed to have any other child processes!\n",retpid);
								exit(-1);
							}
						}
					}
					break;
				case CODE_SIGTERM: 
					kill(0, SIGTERM);
					//fprintf(stderr, "vs-aew : Propagating SIGTERM to process group(all child procs)\n");
					if(kill9timeout==0)
						kill9timeout = KILLTIMEOUT;
					break;

				case CODE_SIGINT: 
					kill(0, SIGINT);
					//fprintf(stderr, "vs-aew : Propagating SIGINT to process group(all child procs)\n");
					if(kill9timeout==0)
						kill9timeout = KILLTIMEOUT;
					break;
			}
		}

		// don't proceed if there's nothing on stdin
		// All the code after this check handles input from stdin
		if((!hasStdin) || (!FD_ISSET(0, &rfds)))
			continue;

		char buf[8192];
		int nRead = read(0, buf, sizeof(buf));
		if(nRead<0)
		{
			if(errno==EINTR)
				continue;
			else
			{
				perror("vs-aew : unexpected problem doing select");
				exit(-1);
			}
		}
		else
		if(nRead>0)
		{
			char *writep = buf;
			int nRemaining = nRead;
			do
			{
				int nWritten = write(childIO[1], writep, nRemaining);
				if(nWritten<0)
				{
					if(errno==EINTR)
						continue;
					else
					{
						perror("vs-aew : unexpected problem doing select");
						exit(-1);
					}
				}
				else
				if(nWritten==0)
					break;
				else
				{
					nRemaining -= nWritten;
				}
			}while(nRemaining>0);
		}
		else
		{
			// nRead = 0 means EOF!
			// close child's STDIN
			close(childIO[1]);

			// Any interactive process will react in a couple of seconds by reading stdin
			killTimeout = 2;
		}
	}

	exit(retCode);
}
