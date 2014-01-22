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

#include <unistd.h>
#include <stdlib.h>

#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <pwd.h>
#include <stdio.h>
#include <errno.h>
#include <signal.h>
#include <string.h>

#define TEMPLATE_GDM_CONF "/etc/vizstack/templates/gdm.conf"
#define RUNTIME_GDM_CONF "/var/run/vizstack/gdm.conf"

int g_signotify_pipe[2];

#define CODE_SIGCHLD '0'
#define CODE_SIGUSR1  '1'
#define CODE_SIGHUP   '2'
#define CODE_SIGTERM  '3'
#define CODE_SIGINT   '4'

bool g_debugPrints=false;

// GDM paths we know
// FIXME: we could push this to a config file hmmm
//
#define GDM_PATH_1 "/opt/gnome/sbin/gdm" // SLES 10 SP 2
#define GDM_PATH_2 "/usr/sbin/gdm"       // RHEL

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
	

void addNotification(int fd[2], unsigned char c)
{
	write(fd[1], &c, 1);
}

void sigterm_handler(int sig)
{
	addNotification(g_signotify_pipe, CODE_SIGTERM);
}

void sigint_handler(int sig)
{
	addNotification(g_signotify_pipe, CODE_SIGINT);
}

void sigchild_handler(int sig)
{
	addNotification(g_signotify_pipe, CODE_SIGCHLD);
}

int g_parent_sig_pipe[2];
void parent_sighdlr(int sig)
{
	switch(sig)
	{
		case SIGTERM:
			addNotification(g_parent_sig_pipe, CODE_SIGTERM);
			break;
		case SIGINT:
			addNotification(g_parent_sig_pipe, CODE_SIGINT);
			break;
		case SIGUSR1:
			addNotification(g_parent_sig_pipe, CODE_SIGUSR1);
			break;
		case SIGCHLD:
			addNotification(g_parent_sig_pipe, CODE_SIGCHLD);
			break;
	}
}

//
// Function called by main program before it forks off to
// create the SUID root X server
//
void parentWaitTillSUIDExits(int suidChildPid, int origParentPipe[2])
{

	struct sigaction sighandler;

	// close the read end of the pipe, since we don't want any information
	// from the child process.
	close(origParentPipe[0]);

	pipe(g_parent_sig_pipe);

	sighandler.sa_handler = parent_sighdlr;
	sighandler.sa_flags = SA_RESTART;
	sigemptyset(&sighandler.sa_mask);

	// We handle these signals
	sigaction(SIGINT, &sighandler, NULL);
	sigaction(SIGTERM, &sighandler, NULL);
	sigaction(SIGCHLD, &sighandler, NULL);

	fd_set rfds;
	bool loopDone = false;
	int retCode = 0;

	while(!loopDone)
	{
		FD_ZERO (&rfds);
		FD_SET(g_parent_sig_pipe[0], &rfds);

		// NOTE: Infinite timeout select below
		int ret;
  		RETRY_ON_EINTR(ret,select (g_parent_sig_pipe[0] + 1, &rfds, NULL, NULL, NULL));

		// Handle Errors in select
		if (ret==-1)
		{
			// FIXME: humm - what can we do here ?
			continue;
		}

		// determine what signal we received by
		// reading the pipe
		char buf=0;
		RETRY_ON_EINTR(ret, read(g_parent_sig_pipe[0], &buf, 1));

		switch(buf)
		{
			case CODE_SIGCHLD:
			// handling SIGCHLD is how we get out of the loop and exit from the main program
			{
				loopDone = true;
				retCode = -1;
				int exitstatus;
				if(waitpid(suidChildPid, &exitstatus, WNOHANG)==suidChildPid)
				{
					if(WIFEXITED(exitstatus))
					{
						retCode = WEXITSTATUS(exitstatus);
					}
					else
					if(WIFSIGNALED(exitstatus))
					{
						// XXX : This rarely seems to show up in practise, due to signal handling
						// by the X server
						retCode = 128+WTERMSIG(exitstatus);
					}
				}
				break;
			}
			case CODE_SIGTERM:
			// propagate TERM to child X server. When that exits, we get SIGCHLD and then we exit
				kill(suidChildPid, SIGTERM);
				break;
			case CODE_SIGINT:
			// propagate INT to child X server. When that exits, we get SIGCHLD and then we exit
				kill(suidChildPid, SIGINT);
				break;
		}

	}

	// in fact, I think the below line is redundant code
	// why ? if normal control comes here, then the child has
	// already died. 
	// 
	// The real reason we use this pipe is : if this process is
	// forcefully terminated - e.g. by kill -9, then the child
	// will be able to detect that quickly, and kill the real X server
	// termination of us 
	close(origParentPipe[1]);

	exit(retCode);
}

int main(int argc, char **argv)
{
	int origParentPipe[2];
	int userUid;

	// Create /var/run/vizstack. No failure if we are unable to create it
	mkdir("/var/run/vizstack", 0755); // user=> rwx, others => rx

	if(access("/var/run/vizstack", F_OK)!=0)
	{
		fprintf(stderr, "ERROR: Directory /var/vizstack does not exist, or could not be created. I cannot proceed without this.\n");
		exit(-1);
	}

	if(getenv("VS_X_DEBUG"))
	{
		g_debugPrints = true;
	}

	userUid = getuid(); // get user ID to ask for the server to run for this account

	struct passwd pwd, *ppwd;
	char pwd_buffer[2048];

	// Find the invoking user ID
	if(getpwuid_r(getuid(), &pwd, pwd_buffer, sizeof(pwd_buffer), &ppwd)!=0)
	{
		perror("ERROR : Failed to find username of invoking user\n");
		exit(-1);
	}

	// Create a pipe to detect death of the parent process
	if (pipe(origParentPipe)<0)
	{
		perror("FATAL : Could not create pipe. System may be running out of resources");
		exit(-1);
	}

	// Fork here to control SUID child
	// Fork is needed else the caller of the GDMlauncher cannot control the
	// SUID child!
	int suidChildPid = fork();
	if(suidChildPid != 0)
	{
		parentWaitTillSUIDExits(suidChildPid, origParentPipe);
	}

	// Close the write end since we don't need to communicate
	// anything to the parent process
	close(origParentPipe[1]);

	if(pipe(g_signotify_pipe)!=0)
	{
		perror("ERROR: Unable to create resources for running this program.");
		exit(-1);
	}

	// Now shift to become the root user, since GDM needs to be run only as root
	// This is done by setting the real uid to 0.
	// This approach works as this binary is expected to be SUID root.
	int status;
	status = setreuid(0, 0);
	if (status != 0)
	{
        	perror("ERROR: Unable to set real user id to root");
	        exit(-1);
	}
	status = setregid(0, 0);
	if (status != 0)
	{
        	perror("ERROR: Unable to set real group id to root");
	        exit(-1);
	}

	// Check that the template gdm.conf can be found.
	FILE *fp = fopen(TEMPLATE_GDM_CONF, "r");
	if(!fp)
	{
		perror("ERROR : Unable to find the template gdm.conf file " TEMPLATE_GDM_CONF );
		char hostname[4096];
		strcpy(hostname,"");
		gethostname(hostname, sizeof(hostname));
		fprintf(stderr, "\n\nPlease contact your system administrator and ensure that the node '%s' has been setup sppropriately for RGS.\n",hostname);
		fprintf(stderr, "The instructions needed to do the setup are at the top of the file /etc/vizstack/templates/gdm.conf.template\n");
		exit(-1);
	}
	fclose(fp);

	// Patch the config file for the real user
	char cmd[256]; 
	char uidAsString[256];
	sprintf(uidAsString, "%d", userUid);
	sprintf(cmd, "sed %s -es/@@USER@@/%s/g -es/@@UID@@/%s/g > %s", TEMPLATE_GDM_CONF, pwd.pw_name, uidAsString, RUNTIME_GDM_CONF);
	if(system(cmd)!=0)
	{
		fprintf(stderr, "ERROR : Unable to generate a config file for the GDM session\n");
		exit(-1);
	}

	// Signal handlers for TERM and INT
	// This is done _after_ the system() call, else we'll have other SIGCHLD signals to
	// handle as well
	struct sigaction siginfo;
	siginfo.sa_handler = sigint_handler;
	siginfo.sa_flags = SA_RESTART; 
	sigemptyset (&siginfo.sa_mask);
	sigaction(SIGINT, &siginfo, NULL);

	siginfo.sa_handler = sigterm_handler;
	siginfo.sa_flags = SA_RESTART; 
	sigemptyset (&siginfo.sa_mask);
	sigaction(SIGTERM, &siginfo, NULL);

	siginfo.sa_handler = sigchild_handler;
	siginfo.sa_flags = SA_RESTART; 
	sigemptyset (&siginfo.sa_mask);
	sigaction(SIGCHLD, &siginfo, NULL);

	int childpid = fork();

	if(childpid<0)
	{
		fprintf(stderr,"CRITICAL ERROR : Couldn't fork!\n");
		exit(-1);
	}

	if(childpid==0)
	{
		// close the read end of the pipe. since we exec GDM next
		close(origParentPipe[0]);

		// child, we will exec GDM here in foreground mode
		char **childArgs=new char *[4];

		// Find the right GDM binary
		if(access(GDM_PATH_1, X_OK)==0)
		{
			childArgs[0]=GDM_PATH_1;
		}
		else
		if(access(GDM_PATH_2, X_OK)==0)
		{
			childArgs[0]=GDM_PATH_2;
		}
		else
		{
			fprintf(stderr, "ERROR : Cannot find gdm. Cannot continue.\n");
			exit(-1);
		}

		childArgs[1]="-nodaemon";
		char configOption[4096];
		sprintf(configOption,"--config=%s", RUNTIME_GDM_CONF);
		childArgs[2]=configOption;
		childArgs[3]=NULL;
		execv(childArgs[0], childArgs);

		// If exec failed, then we have an error
		perror("ERROR : failed to start GDM");
		exit(-1);
	}

	// the parent comes here
	// wait for GDM to exit
	// while handling signals at the same time
	fd_set rfds;
	bool loopDone=false;
	int retCode=0;

	while(!loopDone)
	{
		FD_ZERO (&rfds);
		FD_SET (g_signotify_pipe[0], &rfds);
		int maxFD = g_signotify_pipe[0];

		if(origParentPipe[0]!=-1)
			FD_SET (origParentPipe[0], &rfds);
		if (origParentPipe[0]>maxFD)
			maxFD = origParentPipe[0];

		if(g_debugPrints)
			printf("INFO : Waiting for child GDM\n");

		// NOTE: Infinite timeout select below
		int ret;
  		RETRY_ON_EINTR(ret,select (maxFD + 1, &rfds, NULL, NULL, NULL));

		// Handle Errors in select
		if (ret==-1)
		{
			// FIXME: humm - what can we do here ?
		}

		if ((origParentPipe[0]!=-1) && FD_ISSET(origParentPipe[0], &rfds))
		{
			// Do a read of 1 byte
			char buf=0;
			RETRY_ON_EINTR(ret, read(origParentPipe[0], &buf, 1));

			// If the SSM closes the socket, then we act as if we had got
			// SIGTERM
			if(ret==0)
			{
				if(g_debugPrints)
					printf("INFO : Parent closed connection. Killing GDM using SIGTERM\n");
				kill(childpid, SIGTERM);
				close(origParentPipe[0]);
				origParentPipe[0]=-1;
			}
			else
			{
				fprintf(stderr, "FATAL: Bad case - parent isn't supposed to write to us!\n");
				exit(-1);
			}
		}

		// determine what signal we received by
		// reading the pipe
		char buf=0;
		RETRY_ON_EINTR(ret, read(g_signotify_pipe[0], &buf, 1));

		switch(buf)
		{
			case CODE_SIGCHLD:
				// GDM exited
				{
					if(g_debugPrints)
						printf("INFO : GDM exited\n");
					loopDone = true;
					retCode = -1;
					int exitstatus;
					if(waitpid(childpid, &exitstatus, WNOHANG)==childpid)
					{
						if(WIFEXITED(exitstatus))
						{
							if(g_debugPrints)
								printf("INFO : Child X server exited\n");
							retCode = exitstatus;
						}
						else
							if(WIFSIGNALED(exitstatus))
							{

								// XXX : This rarely seems to show up in practise, due to signal handling
								// by the X server
								if(g_debugPrints)
									printf("INFO : Child X server killed by signal %d\n", WTERMSIG(exitstatus));

								retCode = 128+WTERMSIG(exitstatus);
							}
					}
				}
				break;
			case CODE_SIGTERM: 
				if(g_debugPrints)
					printf("INFO : Propagating SIGTERM to child\n");
				kill(childpid, SIGTERM);
				break;

			case CODE_SIGINT:
				if(g_debugPrints)
					printf("INFO : Propagating SIGINT to child\n");
				kill(childpid, SIGINT);
				break;
		}
	}

	unlink(RUNTIME_GDM_CONF);
	exit(retCode);
}
