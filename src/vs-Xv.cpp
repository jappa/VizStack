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
// vs-Xv
//
// VizStack's virtual X server wrapper. This is be the mechanism through which the virtual X servers
// (e.g. TurboVNC) are launched. Doing so helps us keep track of which virtual servers are running.
//
// Note that tracking and controlling virtual servers can be hard, since these X servers run at port
// numbers higher than 1024. We provide this wrapper as a way to ensure authenticated startup/exit.
// A rogue user could still run X servers at will - and VizStack cannot prevent this without help
// from outside.
//
// This program mimics the X server in the way that it handles signals like SIGUSR1, SIGHUP and SIGTERM.
// So, in a way, it is _almost_ a replacement program for the X server.
//

#include <unistd.h>
#include <stdlib.h>

#include <sys/types.h>
#include <sys/wait.h>
#include <fcntl.h>

#include <pwd.h>
#include <stdio.h>
#include <errno.h>
#include <signal.h>
#include <string.h>
#include <sys/file.h>

#include <iostream>

#include <sys/types.h>
#include <sys/socket.h>
#include <sys/un.h>

#include <netdb.h>
#include "vsdomparser.hpp"
#include "vscommon.h"

using namespace std;

int g_signotify_pipe[2];

bool g_debugPrints=false;

#define CODE_SIGCHLD '0'
#define CODE_SIGUSR1  '1'
#define CODE_SIGHUP   '2'
#define CODE_SIGTERM  '3'
#define CODE_SIGINT   '4'

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
	
void addNotification(int whichPipe[2], unsigned char c)
{
	write(whichPipe[1], &c, 1);
}

void sigchild_handler(int sig)
{
	addNotification(g_signotify_pipe, CODE_SIGCHLD);
}

void usr1_handler(int sig)
{
	addNotification(g_signotify_pipe, CODE_SIGUSR1);
}

void hup_handler(int sig)
{
	addNotification(g_signotify_pipe, CODE_SIGHUP);
}

void term_handler(int sig)
{
	addNotification(g_signotify_pipe, CODE_SIGTERM);
}

void int_handler(int sig)
{
	addNotification(g_signotify_pipe, CODE_SIGINT);
}

void tvnc_cleanup(const char *display)
{
	char fname[256];
	sprintf(fname, "/tmp/.X%s-lock", display+1);
	unlink(fname);

	sprintf(fname, "/tmp/.X11-unix/X%s", display+1);
	unlink(fname);
}

int g_perServerLockFD = -1;
bool take_per_server_lock(const char*xdisplay)
{
	string lockPath = "/tmp/.exclusive.vs-Xv";
	lockPath += (xdisplay+1);

	mode_t oldMask = umask(0);
	// NOTE: everyone has access to the lock file. 
	g_perServerLockFD = open(lockPath.c_str(), O_WRONLY | O_CREAT | O_TRUNC , S_IRWXU | S_IRWXG | S_IRWXO);
	if(g_perServerLockFD==-1)
	{
		perror("ERROR: Failed to create per server lock file. Reason :");
		return false;
	}

	int ret;
	RETRY_ON_EINTR(ret, flock(g_perServerLockFD,  LOCK_EX));
	if (ret==-1)
	{
		perror("ERROR: Failed to lock per server lock file. Reason :");
		close(g_perServerLockFD);
		g_perServerLockFD = -1;
		return false;
	}

	umask(oldMask);
	return true;
}



int main(int argc, char**argv)
{
	int ssmSocket=-1;
	char myHostName[256];
	int userUid;

	if (argc<2)
	{
		fprintf(stderr, "ERROR: You need to specify a virtual X server to use as the first argument.\n");
		exit(-1);
	}

	// Ensure that the virtual X server is executable
	if(access(argv[2], X_OK)!=0)
	{
		fprintf(stderr, "ERROR : Specified X server(%s) is not executable. Cannot continue.\n", argv[2]);
		exit(-1);
	}
	if(argv[1][0]!=':')
	{
		fprintf(stderr, "Bad DISPLAY value %s\n", argv[1]);
		exit(1);
	}

	char xdisplay[256];
	strcpy(xdisplay,argv[1]);

	if(getenv("VS_X_DEBUG"))
	{
		g_debugPrints = true;
	}

	userUid = getuid(); // This function can't fail :-)

	if(gethostname(myHostName, sizeof(myHostName))<0)
	{
		perror("ERROR: Unable to get my hostname");
		exit(-1);
	}

	// Start using the XML parser
	VSDOMParser::Initialize();

	if(!getSystemType())
	{
		return -1;
	}

	int notifyParent=0; // Notify parent process of X server readiness by SIGUSR1 ?


	// Create argument list for X server
	char **childArgs=new char*[argc+10]; // NOTE: why +n ? we need the extra space later to add the "-config", and "-sharevts" arguments.
	// X server is the child process
	char *cmd=NULL;

	childArgs[0]=argv[2]; // arg2 => the virtual X server is what we'll execute
	childArgs[1]=argv[1]; // arg1 => the DISPLAY value
	int destIndex=2;
	for (int i=3;i<argc;i++)
	{
		childArgs[destIndex++]=argv[i];
	}
	childArgs[destIndex]=0; // NULL terminate list

	if(!g_standalone)
	{
		// connect to the master, retrieve the configuration for the specified display
		// check whether the user corresponds to the current user.
		// next, dump the config in a file and set x_config_path to that. Phew!

		struct hostent* hp;
		struct hostent ret;
		char buffer[1000];
		int h_errnop;

		// If the master is on "localhost", then we use Unix Domain Sockets
		if(g_ssmHost == "localhost")
		{
			ssmSocket = socket(AF_UNIX, SOCK_STREAM, 0);
			if(ssmSocket < 0)
			{
				perror("ERROR - Unable to create a socket to communicate with the SSM");
				exit(-1);
			}

			struct sockaddr_un sa;
			sa.sun_family = AF_UNIX;
			strcpy(sa.sun_path, g_ssmPort.c_str()); // on Linux, the path limit seems to be 118
			if(connect(ssmSocket, (sockaddr*) &sa, sizeof(sa.sun_family)+sizeof(sa.sun_path))<0)
			{
				perror("ERROR - Unable to connect to the local SSM");
				closeSocket(ssmSocket);
				exit(-1);
			}

			strcpy(myHostName, "localhost"); // our identity changes...

		}
		else
		{
			// resolve the SSM host first
			gethostbyname_r(g_ssmHost.c_str(), &ret, buffer, sizeof(buffer), &hp, &h_errnop);
			if(!hp)
			{
				perror("ERROR - unable to resolve SSM hostname");
				exit(-1);
			}

			ssmSocket = socket(AF_INET, SOCK_STREAM, 0);
			if(ssmSocket < 0)
			{
				perror("ERROR - Unable to create a socket to communicate with the SSM");
				exit(-1);
			}

			struct sockaddr_in si;
			si.sin_family = AF_INET;
			si.sin_port = htons(atoi(g_ssmPort.c_str()));
			memcpy((void*)&si.sin_addr.s_addr, hp->h_addr, 4); // Copying an IPv4 address => 4 bytes

			// Connect to the SSM
			if(connect(ssmSocket, (sockaddr*) &si, sizeof(si))<0)
			{
				perror("ERROR - Unable to connect to the SSM");
				closeSocket(ssmSocket);
				exit(-1);
			}
		}

		string myIdentity;
		myIdentity = "<xclient>";
		myIdentity += "<server>";
		myIdentity += "<hostname>";
		myIdentity += myHostName;
		myIdentity += "</hostname>";
		myIdentity += "<server_number>";
		myIdentity += (xdisplay+1);
		myIdentity += "</server_number>";
		myIdentity += "</server>";
		myIdentity += "</xclient>";

		char *encodedCred = 0;
		if(g_ssmHost == "localhost")
			encodedCred = strdup(myIdentity.c_str());
		else
		{
			// If the SSM is not on a local host, then it uses Munge to authenticate us.
			// We need to send out a a munge encoded packet in the beginning
			// so we need to call munge next, and use that to authenticate.
			encodedCred = munge_encode(myIdentity.c_str());

			if(!encodedCred)
			{
				fprintf(stderr,"ERROR - Unable to create a munge credential\n");
				closeSocket(ssmSocket);
				exit(-1);
			}
		}
		if(!write_message(ssmSocket, encodedCred, strlen(encodedCred)))
		{
			fprintf(stderr,"ERROR - Unable to send my identity to SSM\n");
			free(encodedCred);
			closeSocket(ssmSocket);
			exit(-1);
		}

		// Free the memory
		free(encodedCred);
		encodedCred = 0;

		// Authentication done, so now we need to get the X configuration
		// of this server from the SSM
		// we do this by sending a query message to the SSM
		char message[1024];
		sprintf(message,
			"<ssm>\n"
			"	<get_serverconfig>\n"
			"		<server>\n"
			"			<hostname>%s</hostname>\n"
			"			<server_number>%s</server_number>\n"
			"		</server>\n"
			"	</get_serverconfig>\n"
			"</ssm>\n", myHostName, xdisplay+1);

		if(!write_message(ssmSocket, message, strlen(message)))
		{
			fprintf(stderr, "ERROR - unable to send the query message to SSM\n");
			closeSocket(ssmSocket);
			exit(-1);
		}

		char *serverConfiguration = 0;
		if((serverConfiguration = read_message(ssmSocket))==0)
		{
			fprintf(stderr, "ERROR - unable to receive X configuration\n");
			closeSocket(ssmSocket);
			exit(-1);
		}

		// Validate the XML
		// FIXME: force the document to use serverconfig.xsd. This may catch any errors
		// in the serverconfig
		VSDOMParserErrorHandler errorHandler;
		VSDOMParser *configParser = new VSDOMParser;
		errorHandler.resetErrors();
		VSDOMDoc *config = configParser->ParseString(serverConfiguration, errorHandler);
		if(!config)
		{
			// Print out warning and error messages
			vector<string> msgs;
			errorHandler.getMessages (msgs);
			for (unsigned int i = 0; i < msgs.size (); i++)
				cout << msgs[i] << endl;

			fprintf(stderr, "ERROR - bad return XML from SSM.\n");
			fprintf(stderr, "Return XML was --\n");
			fprintf(stderr, "----------------------------------------------\n");
			fprintf(stderr, "%s", serverConfiguration);
			fprintf(stderr, "\n----------------------------------------------\n");
			closeSocket(ssmSocket);
			exit(-1);
		}

		// Ensure that return status is "success"
		VSDOMNode rootNode = config->getRootNode();
		VSDOMNode responseNode = rootNode.getChildNode("response");
		int status = responseNode.getChildNode("status").getValueAsInt();
		if(status!=0)
		{
			string msg = responseNode.getChildNode("message").getValueAsString();
			fprintf(stderr, "ERROR - Failure returned from SSM : %s\n", msg.c_str());
			delete configParser;
			closeSocket(ssmSocket);
			exit(-1);
		}
		
		VSDOMNode retValNode = responseNode.getChildNode("return_value");
		VSDOMNode serverConfig = retValNode.getChildNode("server");
		VSDOMNode ownerNode = serverConfig.getChildNode("owner");
		if(ownerNode.isEmpty())
		{
			fprintf(stderr, "ERROR: Can't proceed; the owner for the X server is not specified by the SSM\n");
			delete configParser;
			closeSocket(ssmSocket);
			exit(-1);
		}
		VSDOMNode svTypeNode = serverConfig.getChildNode("server_type");
		if(svTypeNode.isEmpty())
		{
			fprintf(stderr, "ERROR: Can't proceed; the type of the X server was not specified by the SSM\n");
			delete configParser;
			closeSocket(ssmSocket);
			exit(-1);
		}
		string svType = svTypeNode.getValueAsString();
		if (svType != "virtual")
		{
			fprintf(stderr, "ERROR: vs-X manages only 'virtual' X servers. It can't manage servers of type '%s'\n",svType.c_str());
			delete configParser;
			closeSocket(ssmSocket);
			exit(-1);
		}
		int ownerUid = ownerNode.getValueAsInt();
		// Allow the owner of this server to start the X server.
		if(ownerUid != userUid)
		{
			fprintf(stderr, "ERROR: You don't have permission to start the X server %s. It is owned by used ID=%d\n",xdisplay, ownerUid);
			delete configParser;
			closeSocket(ssmSocket);
			exit(-1);
		}
		delete configParser;
	}

	// Take an exclusive lock for this virtual server
	// This tries to prevent race conditions between this
	// process cleaning up the locks & VNC process creating
	// the lock
	if(!take_per_server_lock(xdisplay))
	{
		fprintf(stderr, "ERROR: Cannot continue.\n");
		exit(-1);
	}

	// Register SIGCHLD handler first so that we get exit notifications from our child X
	// server
	struct sigaction siginfo;
	siginfo.sa_handler = sigchild_handler;
	siginfo.sa_flags = SA_RESTART; 
	sigemptyset (&siginfo.sa_mask);
	sigaction(SIGCHLD, &siginfo, NULL);

	// fill in the configuration file name on the child X server's command line
	childArgs[destIndex]=NULL;

	// Check if SIGUSR1 is set to IGN. If so, then we'll need
	// to propagate SIGUSR1 to the parent.
	struct sigaction usr1;
	sigaction(SIGUSR1, NULL, &usr1);
	if(usr1.sa_handler == SIG_IGN)
	{
		if(g_debugPrints)
			printf("INFO : Parent requested SIGUSR1 notification\n");
		notifyParent=1;
	}

	// Activate signal handler for SIGUSR1
	//
	// We need to do this before the fork to avoid timing
	// issues
	//
	pipe(g_signotify_pipe);
	usr1.sa_handler = usr1_handler;
	usr1.sa_flags = SA_RESTART; 
	sigemptyset (&usr1.sa_mask);
	sigaction(SIGUSR1, &usr1, NULL);

	pid_t childpid = fork();

	if (childpid<0)
	{
		perror("ERROR : vs-Xv failed - fork error");
		exit(-1);
	}

	if (childpid==0)
	{
		// FD gets duplicated on fork, so we close it here
		close(g_perServerLockFD);

		// Close the FDs on the child
		// FIXME: more elegant and generic code could close all FDs till MAX_FD
		close(g_signotify_pipe[0]);
		close(g_signotify_pipe[1]);

		// Close the connection to the System State Manager.
		// We need to do this since we'll exec the X server next
		close(ssmSocket);

		// Set SIGUSR1 to IGN. This will cause the X server we 'exec'
		// next to send the parent a SIGUSR1. This signal will indicate
		// to the parent that it is ready to accept connections.

		struct sigaction usr1;
		usr1.sa_handler = SIG_IGN;
		usr1.sa_flags = SA_RESTART; 
		sigaction(SIGUSR1, &usr1, NULL);

		// Start the X server as the child process
		execv(childArgs[0], childArgs);

		// If exec returns, an error happened
		perror("ERROR : vs-Xv failed - exec failed");
		exit(-1);
	}

	// Control will come here in the parent - i.e. the original vs-Xv process

	// Register the HUP & TERM handlers, since we'll need to propagate these
	// explicitly to the child X server we started
	// Also, propagate SIGINT to the child

	siginfo.sa_handler = hup_handler;
	siginfo.sa_flags = SA_RESTART; 
	sigemptyset (&siginfo.sa_mask);
	sigaction(SIGHUP, &siginfo, NULL);

	siginfo.sa_handler = term_handler;
	siginfo.sa_flags = SA_RESTART; 
	sigemptyset (&siginfo.sa_mask);
	sigaction(SIGTERM, &siginfo, NULL);

	siginfo.sa_handler = int_handler;
	siginfo.sa_flags = SA_RESTART; 
	sigemptyset (&siginfo.sa_mask);
	sigaction(SIGINT, &siginfo, NULL);

	// We wait for one of the following events
	// a. Child X server exit (i.e. SIGCHLD)
	// b. SIGUSR1 signal from child process - i.e. X server
	// c. Signals to pass on to the child X server
	//     - SIGHUP
	//     - SIGTERM
	//     - SIGINT (^C)
	//

	fd_set rfds;

	bool xInitDone = false;
	int retCode=0;
	bool loopDone=false;

	while(!loopDone)
	{
		FD_ZERO (&rfds);
		FD_SET (g_signotify_pipe[0], &rfds);
		int maxFD = g_signotify_pipe[0];

		// Monitor the SSM socket.
		// SSM will close the socket when it wants us to exit
		// In the future we can use this to do X related activities from the
		// SSM.
		if(ssmSocket != -1)
			FD_SET(ssmSocket, &rfds);
		if (ssmSocket>maxFD)
			maxFD = ssmSocket;

		if(g_debugPrints)
			printf("INFO : Waiting for child process\n");

		// NOTE: Infinite timeout select below
		int ret;

		// FIXME: we need to add a timeout below
		// why ? currently, we're sending TERM to the X server
		// to kill it. That's a safe thing to do. But what if the
		// X server doesn't die. Killing it -9 is bad since that may
		// cause system instability (mild word for "hard hang"!)
		// We can help in this situation by
		// waiting <n> seconds for the child to die
		// if the child doesn't die during that time, then kill -9 it
		// send information about kill -9 to SSM, since this is a really 
		// bad case.
  		RETRY_ON_EINTR(ret,select (maxFD + 1, &rfds, NULL, NULL, NULL));

		// Handle Errors in select
		if (ret==-1)
		{
			// FIXME: humm - what can we do here ?
		}

		// Handle SSM socket activity
		if((ssmSocket!=-1) && FD_ISSET(ssmSocket, &rfds))
		{
			// Do a read of 1 byte
			char buf=0;
			RETRY_ON_EINTR(ret, read(ssmSocket, &buf, 1));

			// If the SSM closes the socket, then we act as if we had got
			// SIGTERM
			if(ret==0)
			{
				if(g_debugPrints)
					printf("INFO : SSM closed connection. Killing X server using SIGTERM\n");

				kill(childpid, SIGTERM);
				closeSocket(ssmSocket);
				ssmSocket = -1;
			}
		}

		// All processing after this is for the notify pipe
		// if there's nothing to do there, then just continue
		if (!FD_ISSET(g_signotify_pipe[0], &rfds))
			continue;

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
					// did our child X server exit ?
					if(waitpid(childpid, &exitstatus, WNOHANG)==childpid)
					{
						loopDone = true;
						retCode = -1;
						if(WIFEXITED(exitstatus))
						{
							if(g_debugPrints)
								printf("INFO : Child X server exited\n");
							retCode = WEXITSTATUS(exitstatus);
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
					else
					{
						// other child process exits cause us to come here.
						fprintf(stderr, "FATAL: Bad case - we aren't supposed to have any other child processes!\n");
						// free our X server lock
						exit(-1);
					}
				}
				break;
			case CODE_SIGUSR1: 
				// Do SIGUSR1 handling only once.
				// Why ? Sometimes I have noticed that I get a SIGUSR1 everytime
				// a client connects and disconnects
				if(!xInitDone)
				{
					if(g_debugPrints)
						printf("INFO : Creating record of X server allocation\n");

					xInitDone = true; // remember that we suceeded in creating the X server

					// Tell the SSM that we're up!
					string notifyMessage = 
						"<ssm>"
							"<update_x_avail>"
								"<newState>1</newState>"
									"<server>";
					notifyMessage += "<hostname>";
					notifyMessage += myHostName;
					notifyMessage += "</hostname>";
					notifyMessage += "<server_number>";
					notifyMessage += (xdisplay+1);
					notifyMessage += "</server_number>";
					notifyMessage +=
									"</server>"
								"</update_x_avail>"
						"</ssm>";

					// if we're not running standalone, then intimate the SSM that this
					// X server is available.
					if(ssmSocket != -1)
					{
							if(!write_message(ssmSocket, notifyMessage.c_str(), notifyMessage.size()))
							{
									fprintf(stderr,"ERROR - Unable to send start message to SSM\n");
									exit(-1);
							}
					}

					if(notifyParent)
					{
						if(g_debugPrints)
							printf("INFO : Propagating SIGUSR1 to parent\n");
						kill(getppid(), SIGUSR1);
					}
					else
					{
						if(g_debugPrints)
							printf("INFO : No action taken on SIGUSR1 from child X server\n");
					}

					// TODO: Update System State Manager with information that the X server has started.
				}
				break;

			case CODE_SIGHUP: 
				if(g_debugPrints)
					printf("INFO : Propagating SIGHUP to child\n");
				kill(childpid, SIGHUP);
				break;

			case CODE_SIGTERM: 
				if(g_debugPrints)
					printf("INFO : Propagating SIGTERM to child\n");

				tvnc_cleanup(xdisplay);
				kill(childpid, SIGTERM);
				break;

			case CODE_SIGINT: 
				if(g_debugPrints)
					printf("INFO : Propagating SIGINT to child\n");

				tvnc_cleanup(xdisplay);
				kill(childpid, SIGTERM);
				break;
		}
	}

	if(xInitDone)
	{
		// Remove the X usage record, if we created one
		if(g_debugPrints)
			printf("INFO : Removing record of X server allocation.\n");
	}

	// Update System State Manager with information that the X server has stopped.
	// NOTE: we need to do this after removing the X org file, else there is a chance of
	// an improper config file in place. This is not a big problem, but it's nice to be
	// consistent
	string notifyMessage = 
		"<ssm>"
			"<update_x_avail>"
				"<newState>0</newState>"
					"<server>";
	notifyMessage += "<hostname>";
	notifyMessage += myHostName;
	notifyMessage += "</hostname>";
	notifyMessage += "<server_number>";
	notifyMessage += (xdisplay+1);
	notifyMessage += "</server_number>";
	notifyMessage += "</server>"
				"</update_x_avail>"
		"</ssm>";

	// Cleanup the TVNC files
	tvnc_cleanup(xdisplay);

	if(ssmSocket!=-1)
	{
			if(!write_message(ssmSocket, notifyMessage.c_str(), notifyMessage.size()))
			{
					fprintf(stderr,"ERROR - Unable to send start message to SSM\n");
			}
	}

	// close the connection to the SSM
	if(ssmSocket!=-1)
		closeSocket(ssmSocket);

	exit(retCode);
}
