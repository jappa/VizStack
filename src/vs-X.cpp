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
// vs-X
//
// VizStack's X server wrapper. This will be the mechanism through which the X server will be launched.
// 
// This program mimics the X server in the way that it handles signals like SIGUSR1, SIGHUP and SIGTERM.
// So, in a way, it is _almost_ a replacement program for the X server.
//
// The reasons to create this wrapper
//   1. Start X servers that run in an exact, known configuration
//   2. Keep track of when X servers are ready, by notifying the visualization stack.
//   3. Allow only those who have the rights to start X servers.
//
// The overall flow of this program is
//
// 1. Determine whether the configuration is standalone or not.
// 2. If this is a standalone configuration, then get the X configuration from a known location, convert it
//    into a configuration file and start the X server.
// 
// 3. If not a standalone configuration, then contact the System State Manager, giving it the following information
//    - X server number whose startup is being requested.
//    - Invoking username
//
// 4. The system state manager will return back the XML configuration, which we convert to the real configuration.
// 5. Start the real X server with this configuration
// 6. After the real X server has started up (SIGUSR1), intimate the SSM about successful startup. Update SSM with the
//    X server-centric view of the configuration.
// 7. When the real X server dies, intimate the SSM about the same.
// 8. If the SSM sends a message asking for the X server to be killed, then do the same.
// 
// NOTE: This is intended to be an SUID root binary.
// To improve "security" w.r.t using X, execute permissions for everyone could be removed from it (except the owner, i.e. root).
// This way, the access to the X server would only be through vs-X.
//
// With VizStack, one or more X servers (on the same machine) can start up or shut down almost at the same time
// With the 180 series drivers, I've observed that this causes the machine to lock-up. Adding a delay between X
// server startups fixed the startup crash. However, the crash then shifted to the cleanup part. VizStack, in a 
// bid to ensure cleanup, terminates the X server by disconnecting the SSM socket connection. When vs-X detects
// the disconnected SSM socket, it signals the X server to terminate, waits for the X server to dies, and then
// finally exits. This resulted in the X servers trying to cleanup at the same time.
//
// What are the solutions ? 
//   1. get nvidia to fix it 
//   2. workaround this
//
// I'm sticking to (2)...
//
// The code below serializes startup and shutdown of X servers. The serialization is implemented via a named
// semaphore. The semaphore is taken before starting and stopping X servers, and released after the operation is
// complete.
//
// Doing just an exclusive access didn't work. So I'm adding a few seconds of sleep next.
//
// I've incorporated a 5 second delay below. This was derived from experimentation on a 
// xw8600s with two FX 56800. Note that on a system with a lot of GPUs, this would result in
// a good amount of delay if a single job used a lot of X servers. This would affect the failure
// timeout values used in the client API, for instance.
//
// FIXME: Is there a way to find a good timeout value ? I need to push this to a configuration
// file.
//
// At this time, it looks like (5+2)*(number_of_gpus) in the system is a good timeout value for
// the client API.
//
// We use file locking in /var/lock/vs-X to implement exclusive access. This works pretty well,
// and given that /var/lock is guaranteed not be in NFS, shouldn't pose a problem.
// I had to remove the semaphore based solution. Once my X servers wouldn't start and I imagine
// some cleanup path had missed unlocking the semaphore.
//
// File locks are more reliable because they are given up when the process exits ! The result is
// less flaky software !
//

#define XSERVER_LOCK_DELAY 5

//#define USE_MUNGE

#include <unistd.h>
#include <stdlib.h>

#include <sys/stat.h>
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
#include <map>
#include <algorithm>

#include <sys/types.h>
#include <sys/socket.h>
#include <sys/un.h>

#include <netdb.h>
#include "vsdomparser.hpp"

#include <X11/Xlib.h>
#include <X11/Xauth.h>
#include "vscommon.h"

using namespace std;

int g_signotify_pipe[2];

bool g_debugPrints=false;

enum WrapperConnStatus { SUCCESSFULLY_CONNECTED, ALREADY_CONNECTED, SHARE_LIMIT_REACHED, CONNECTION_DENIED };
struct OptVal
{
	string name;
	string value;
};

void addNotification(int whichPipe[2], unsigned char c)
{
	// we check this since the child might have closed the pipe
	// to indicate no signal handling needed
	if (whichPipe[1] != -1) 
	{
		write(whichPipe[1], &c, 1);
	}
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

#define XSERVER_PATH_1 "/usr/bin/X" // RHEL 5.1, above?
#define XSERVER_PATH_2 "/usr/X11R6/bin/X" // Older RHEL, SLES

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
void parentWaitTillSUIDExits(int ssmSocket, bool isShared, int suidChildPid, int origParentPipe[2], int connToWrapper)
{
	struct sigaction sighandler;
	sighandler.sa_handler = parent_sighdlr;
	sighandler.sa_flags = SA_RESTART;
	sigemptyset(&sighandler.sa_mask);

	// close the read end of the pipe, since we don't want any information
	// from the child process.
	close(origParentPipe[0]);

	// We handle these signals
	sigaction(SIGINT, &sighandler, NULL);
	sigaction(SIGTERM, &sighandler, NULL);
	sigaction(SIGUSR1, &sighandler, NULL);

	fd_set rfds;
	bool loopDone = false;
	int retCode = 0;

	if(g_debugPrints)
		printf("Parent INFO: Parent waiting for SUID child to exit\n");

	int readFD = g_parent_sig_pipe[0];

	while(!loopDone)
	{
		FD_ZERO (&rfds);
		FD_SET(readFD, &rfds);

		int maxFD = readFD;

		if(ssmSocket!=-1)
		{
			FD_SET(ssmSocket, &rfds);
			if (ssmSocket>maxFD) maxFD=ssmSocket;
		}

		if(connToWrapper!=-1)
		{
			FD_SET(connToWrapper, &rfds);
			if (connToWrapper>maxFD) maxFD=connToWrapper;
		}
		// NOTE: Infinite timeout select below
		int ret;
  		ret = select(maxFD + 1, &rfds, NULL, NULL, NULL);

		// Handle Errors in select
		if (ret<0)
		{
			// FIXME: humm - what can we do here ?
			continue;
		}

		if((connToWrapper!=-1) && (FD_ISSET(connToWrapper, &rfds)))
		{
			// activity on the socket to the wrapper means that the
			// X server is exiting.
			close(connToWrapper);
			if((!isShared) && (suidChildPid!=-1))
				kill(suidChildPid, SIGTERM);
			else
				loopDone = true;
		}
		if((ssmSocket!=-1) && (FD_ISSET(ssmSocket, &rfds)))
		{
			// activity on the socket to the SSM means that the
			// X server is exiting.
			close(ssmSocket);
			if((!isShared) && (suidChildPid!=-1))
				kill(suidChildPid, SIGTERM);
			else
				loopDone = true;
		}

		if(!FD_ISSET(readFD, &rfds))
			continue;

		// determine what signal we received by
		// reading the pipe
		char buf=0;
		RETRY_ON_EINTR(ret, read(readFD, &buf, 1));

		switch(buf)
		{
			case CODE_SIGCHLD:
			// handling SIGCHLD is how we get out of the loop and exit from the main program
			{
				int exitstatus;
				if(waitpid(suidChildPid, &exitstatus, WNOHANG)==suidChildPid)
				{
					if(!isShared)
						loopDone = true;
					retCode = -1;
					if(g_debugPrints)
						printf("Parent INFO: Parent got SIGCHLD. Exiting...\n");
					if(WIFEXITED(exitstatus))
					{
						retCode = exitstatus;
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
				// Propagate TERM signal to the child if the server is not shared.
				if((suidChildPid != -1) && (!isShared))
				{
					// propagate TERM to child X server. When that exits, we get SIGCHLD and then we exit
					if(g_debugPrints)
						printf("Parent INFO: Parent got SIGTERM. Propagating to SUID child...\n");
					kill(suidChildPid, SIGTERM);
				}
				else
					loopDone = true;
				break;
			case CODE_SIGINT:
				// propagate INT to child X server if the server is not shared.
				// When that exits, we get SIGCHLD and then we exit
				if((suidChildPid != -1) && (!isShared))
				{
					if(g_debugPrints)
						printf("Parent INFO: Parent got SIGINT. Propagating to SUID child...\n");
					if(kill(suidChildPid, SIGINT)<0)
					{
						perror("Failed to kill parent SUID");
					}
				}
				else
					loopDone = true;
				break;
			case CODE_SIGUSR1:
				// propagate USR1 to parent. Child will not send us USR1 unless the signal mask
				// was setup for it properly. And who will setup the signal mask ? The caller program, of course !
				// This is relevant for both GDM as well as xinit
				if(g_debugPrints)
					printf("Parent INFO: Parent got SIGUSR1. Propagating to original parent process(%d) to signal server ready...\n", getppid());
				if(kill(getppid(), SIGUSR1)!=0)
				{
					perror("Propagating SIGUSR1 to parent failed");
				}
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

	if(g_debugPrints)
		printf("Parent INFO: Exiting...\n");
	if(suidChildPid==-1)
		exit(0);

	exit(retCode);
}

int g_lockFD = -1;
bool g_haveLock = false;

#define X_LOCK_FILE "/var/lock/vs-X"
bool take_lock()
{
	g_lockFD = open("/var/lock/vs-X", O_WRONLY | O_CREAT | O_TRUNC , S_IRUSR | S_IWUSR);
	if(g_lockFD==-1)
	{
		perror("ERROR: Failed to create lock file '" X_LOCK_FILE "'. Reason :");
		return false;
	}

	int ret;
	RETRY_ON_EINTR(ret, flock(g_lockFD,  LOCK_EX));
	if (ret==-1)
	{
		perror("ERROR: Failed to lock '" X_LOCK_FILE "'. Reason :");
		close(g_lockFD);
		g_lockFD = -1;
		return false;
	}

	g_haveLock = true;
	return true;
}

int g_perServerLockFD = -1;
bool take_per_server_lock(const char*xdisplay)
{
	string lockPath = "/var/run/vizstack/.exclusive.vs-X";
	lockPath += (xdisplay+1);

	g_perServerLockFD = open(lockPath.c_str(), O_WRONLY | O_CREAT | O_TRUNC , S_IRUSR | S_IWUSR);
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

	return true;
}

void free_lock()
{
	int ret;
	RETRY_ON_EINTR(ret, flock(g_lockFD,  LOCK_UN));
	
	close(g_lockFD);
	g_lockFD = -1;
	g_haveLock = false;
}

bool have_lock()
{
	return g_haveLock;
}

void take_lock_once()
{
	if(have_lock())
		return;
	take_lock();
}

void free_lock_once()
{
	if(!have_lock())
		return;
	free_lock();
}

void getACL(VSDOMNode configNode, vector<int>& serverACL)
{
	serverACL.clear();

	vector<VSDOMNode> vOwnerNode = configNode.getChildNodes("owner");

	unsigned int i;
	for(i=0;i<vOwnerNode.size();i++)
	{
		VSDOMNode &ownerNode = vOwnerNode[i];

		int ownerUid = ownerNode.getValueAsInt();
		serverACL.push_back(ownerUid);
	}
}

void daemonize()
{
	// fork to remove dependency on parent process
	pid_t pid;
	pid = fork();
	if (pid<0)
	{
		exit(-1);
	}
	if(pid>0)
	{
		exit(0);
	}

	// Ignore various TTY signals in the this process (daemon)
	signal(SIGTSTP,SIG_IGN); 
	signal(SIGTTOU,SIG_IGN);
	signal(SIGTTIN,SIG_IGN);

	// change file mode mask
	umask(0);

	// create a new SID for this daemon
	int sid = setsid();
	if (sid<0)
	{
		perror("Unable to create a new session");
		exit(-1);
	}

	// Change directory to the root directory
	if(chdir("/") < 0)
	{
		perror("Unable to chdir to root directory");
		exit(-1);
	}

	// Redirect standard files to /dev/null
	freopen( "/dev/null", "r", stdin);
	if(!g_debugPrints)
	{
		freopen( "/dev/null", "w", stdout);
		freopen( "/dev/null", "w", stderr);
	}
}

struct ConnClient
{
	int fd;
	int uid;
};

void waitChildExit(int childpid)
{
	int exitstatus;
	while(1)
	{
		// did our child X server exit ?
		int ret = waitpid(childpid, &exitstatus, 0);
		if (ret==ECHILD)
			break;
		if (ret==childpid)
			break;
		if (ret==EINVAL)
		{
			perror("Invalid args");
			break;
		}
	}
}

int main(int argc, char**argv)
{
	char x_config_path[4096];
	char xorg_config_path[4096];
	char serverinfo_path[4096];
	int ssmSocket=-1;
	char myHostName[256];
	int origParentPipe[2];
	int userUid, rootParentPid;
	int ownerUid;
	bool ignoreMissingDevices = false;
	bool isShared = false;
	int serverSocket = -1;
	int maxClients = 1;
	vector<int> serverACL;

	if(getenv("VS_X_DEBUG"))
	{
		g_debugPrints = true;
	}

	// Create /var/run/vizstack. No failure if we are unable to create it
	mkdir("/var/run/vizstack", 0755); // user=> rwx, others => rx

	if(access("/var/run/vizstack", F_OK)!=0)
	{
		fprintf(stderr, "ERROR: Directory /var/run/vizstack does not exist, or could not be created. I cannot proceed without this.\n");
		exit(-1);
	}

	userUid = ownerUid = getuid(); // This function can't fail :-)

	// Switch to effective ID of the invoking user. We'll switch back
	// to root when needed
	// There are two reasons for this
	// #1 => the vizstack wrapper determines the invoking user for the
	// X server using the effective ID
	// #2 => why run with unnecessary privileges ??
	seteuid(userUid);

	//fprintf(stderr, "User ID = %d Group ID = %d\n", getuid(), getgid());
	//fprintf(stderr, "Effective User ID = %d Group ID = %d\n", geteuid(), getegid());
	rootParentPid = getpid();

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
	char xdisplay[256];
	char *xauthority = 0;
	char user_xauthority_path[4096];
	strcpy(user_xauthority_path, "");

	struct passwd pwd, *ppwd;
	char pwd_buffer[2048];
	char *xuser=NULL;
	int rgsPromptUser = 0;
	int serverFor = -1;
	char *allocId ="";

	// Default value of DISPLAY. May be overridden on the command line
	strcpy(xdisplay, ":0");

	// Create argument list for X server
	vector<char*> childArgs;
	// X server is the child process
	char *cmd=NULL;

	childArgs.push_back(NULL); // NOTE: this will be filled later
	for (int i=1;i<argc;i++)
	{
		//
		// ensure that some args can't be used --
		// e.g -layout, -config, -sharevts, -novtswitch
		// we'll use these ourselves, and overrides don't make sense on the command line
		//
		if((strcmp(argv[i],"-config")==0) || (strcmp(argv[i],"-layout")==0) || (strcmp(argv[i],"-sharevts")==0) || (strcmp(argv[i],"-novtswitch")==0))
		{
			fprintf(stderr, "ERROR: You're not allowed to use the command line argument '%s'. Usage of this is limited to VizStack.\n", argv[i]);
			exit(-1);
		}
		else
		if(argv[i][0]==':')
		{
			// this is the display
			strcpy(xdisplay,argv[i]);
		}
		else
		if(strcmp(argv[i],"-auth")==0)
		{
			xauthority = strdup(argv[i+1]);
			// this is an SUID root binary. We will copy this file as the authority file
			// later one. We should't allow a user to copy arbitrary files, this will be
			// a security hole
			if(access(xauthority, R_OK)!=0)
			{
				perror("Access denied to auth file");
				exit(-1);
			}
		}
		else
		if(strcmp(argv[i],"--rgs-prompt-user")==0)
		{
			rgsPromptUser = 1;
			continue; // don't propagate this option to X since it does not understand it
		}
		else
		if(strcmp(argv[i],"--ignore-missing-devices")==0)
		{
			ignoreMissingDevices = true;
			continue;
		}
		else
		if(strcmp(argv[i],"--allocId")==0)
		{
			int id=atoi(argv[i+1]);
			char back2text[20];
			sprintf(back2text,"%d", id);
			if((strcmp(back2text, argv[i+1])!=0) || (id<=0))
			{
				fprintf(stderr,"Please enter a valid integer value for allocId. Value='%s' Conversion='%s'",argv[i+1], back2text);
				exit(-1);
			}
			allocId = strdup(back2text);
			i+=1;
			continue;
		}
		else
		if(strcmp(argv[i],"--server-for")==0)
		{
			if(userUid!=0)
			{
				fprintf(stderr, "--server-for is allowed only if you start the server as the root user\n");
				exit(-1);
			}
			serverFor = atoi(argv[i+1]);
			userUid = ownerUid = serverFor; // override the uid
			i+= 1;
			continue;
		}
		
		childArgs.push_back(argv[i]);
	}

#if 0
	printf("ARGS are :\n");
	for(int i=0;i<argc;i++)
		printf("%d='%s'\n", i, argv[i]);
#endif

	// Find the invoking user ID
	if(getpwuid_r(getuid(), &pwd, pwd_buffer, sizeof(pwd_buffer), &ppwd)!=0)
	{
		perror("ERROR : Failed to username of invoking user\n");
		exit(-1);
	}

	xuser = strdup(pwd.pw_name);

	// Check if SIGUSR1 is set to IGN. If so, then we'll need
	// to propagate SIGUSR1 to the parent.
	struct sigaction usr1;
	sigaction(SIGUSR1, NULL, &usr1);
	if(usr1.sa_handler == SIG_IGN)
	{
		if(g_debugPrints)
			printf("INFO : vs-X parent process requested SIGUSR1 notification\n");
		notifyParent=1;
	}


	// Create a pipe to detect death of the parent process
	if (pipe(origParentPipe)<0)
	{
		perror("ERROR : Could not create pipe. System may be running out of resources");
		exit(-1);
	}

	VSDOMNode serverConfig;
	VSDOMParser *configParser = 0;
	bool configInTempFile = false;
	
	if(g_standalone)
	{
		sprintf(x_config_path, "/etc/vizstack/standalone/Xconfig-%s.xml", xdisplay+1);
		configInTempFile = false;

		VSDOMParserErrorHandler errorHandler;
		configParser = new VSDOMParser;
		errorHandler.resetErrors();
		VSDOMDoc *config = configParser->ParseFile(x_config_path, errorHandler);
		if(!config)
		{
			// Print out warning and error messages
			vector<string> msgs;
			errorHandler.getMessages (msgs);
			for (unsigned int i = 0; i < msgs.size (); i++)
				cout << msgs[i] << endl;

			fprintf(stderr, "ERROR - bad configuration XML for server %s\n", xdisplay);
			exit(-1);
		}

		serverConfig = config->getRootNode();
	}
	else
	{
		// connect to the master, retrieve the configuration for the specified display
		// check whether the user corresponds to the current user.
		// next, dump the config in a file and set x_config_path to that. Phew!


		// if the SSM is on the same machine, then our identity changes to localhost
		if(g_ssmHost == "localhost")
			strcpy(myHostName, g_ssmHost.c_str());

		ssmSocket = connectToSSM(g_ssmHost, g_ssmPort);

		// identify ourselves as an X client.
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
		myIdentity += "<allocId>";
		myIdentity += allocId;
		myIdentity += "</allocId>";
		// if we are running a server for another user, ask for a change of identity as well
		if(serverFor != -1)
		{
			char sServerFor[256];
			sprintf(sServerFor, "%d", serverFor);
			myIdentity += "<serverFor>";
			myIdentity += sServerFor;
			myIdentity += "</serverFor>";
		}
		myIdentity += "</xclient>";

		if(!authenticateToSSM(myIdentity, ssmSocket))
		{
			fprintf(stderr, "ERROR - Unable to authenticate myself to SSM.\n");
			closeSocket(ssmSocket);
			exit(-1);
		}

		// Authentication done, so now we need to get the X configuration
		// of this server from the SSM
		if(g_debugPrints)
			fprintf(stderr, "Getting server configuration from SSM...\n");
		char *serverConfiguration = getServerConfig(myHostName, xdisplay, ssmSocket);

		// Validate the XML
		// FIXME: force the document to use serverconfig.xsd. This may catch any errors
		// in the serverconfig
		VSDOMParserErrorHandler errorHandler;
		configParser = new VSDOMParser;
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
		serverConfig = retValNode.getChildNode("server");
	}

	{
		getACL(serverConfig, serverACL);

		if(serverACL.size()==0)
		{
			fprintf(stderr, "ERROR: Can't proceed; the owner(s) for the X server is not specified by the SSM\n");
			delete configParser;
			closeSocket(ssmSocket);
			exit(-1);
		}

		// don't allow people who don't have access to this X server to start it.
		// no special cases for root!
		{
			unsigned int i;
			for(i=0;i<serverACL.size();i++)
			{
				ownerUid = serverACL[i];

				if(ownerUid == -1) // everybody has access to the server
				{
					ownerUid = userUid;
				}

				// Allow the owner of this server to start the X server.
				if(ownerUid == userUid)
				{
					break;
				}
			}

			if(serverACL.size() == i)
			{
				fprintf(stderr, "ERROR: You(uid=%d) don't have permission to start the X server %s.\n",ownerUid,xdisplay);
				delete configParser;
				closeSocket(ssmSocket);
				exit(-1);
			}
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
		if (svType != "normal")
		{
			fprintf(stderr, "ERROR: vs-X manages only 'normal' X servers. It can't manage servers of type '%s'\n",svType.c_str());
			delete configParser;
			closeSocket(ssmSocket);
			exit(-1);
		}

		VSDOMNode svSharedNode = serverConfig.getChildNode("shared");
		if(svSharedNode.isEmpty())
		{
			isShared = false;
		}
		else
		{
			// we shouldn't end up in zero, as the schema will not allow for this.
			isShared = svSharedNode.getValueAsInt(); 
		}
		VSDOMNode svMaxShareCountNode = serverConfig.getChildNode("maxShareCount");
		if(!svMaxShareCountNode.isEmpty())
		{
			// FIXME we shouldn't end up in zero, as the schema will not allow for this.
			maxClients = svMaxShareCountNode.getValueAsInt(); 
		}

		// Translate owner UID to name
		struct passwd pwd, *ppwd;
		char pwd_buffer[2048];
		if(getpwuid_r(ownerUid, &pwd, pwd_buffer, sizeof(pwd_buffer), &ppwd)!=0)
		{
			perror("ERROR : Failed to find username of invoking user\n");
			exit(-1);
		}

		xuser = strdup(pwd.pw_name);
	}

	//
	// Setup for handling the child process exiting very quickly
	// we register SIGCHLD before forking off
	//
	pipe(g_parent_sig_pipe);

	if (isShared)
	{
		// Try to connect to a running X server wrapper
		// inability to connect implies that we need to start one afresh
		serverSocket = socket(AF_UNIX, SOCK_STREAM, 0);
		if(serverSocket < 0)
		{
			perror("ERROR - Unable to create a socket");
			exit(-1);
		}

		struct sockaddr_un sa;
		sa.sun_family = AF_UNIX;
		string serverSocketAddr = "/var/run/vizstack/socket-";
		serverSocketAddr += xdisplay;
		strcpy(sa.sun_path, serverSocketAddr.c_str()); // on Linux, the path limit seems to be 118
		
		bool doRetry = false;
		do
		{
			doRetry = false;
			if(connect(serverSocket, (sockaddr*) &sa, sizeof(sa.sun_family)+sizeof(sa.sun_path))==0)
			{
				// get the response to our connection
				char *response = read_message(serverSocket);

				if(!response)
				{
					// wrapper could not process our connection request
					fprintf(stderr,"Unexpected response. Wrapper could not process out connection request. Perhaps it is shutting down? Delaying for some time\n");
					doRetry=true;
				}
				else
				{
					WrapperConnStatus status;
					memcpy(&status, response, sizeof(status));
					switch(status)
					{
						case ALREADY_CONNECTED:
							// abort here, saying that server is already running
							fprintf(stderr, "X server %s is already running for you.\n", xdisplay);
							exit(1);
							break;
						case SUCCESSFULLY_CONNECTED:
							fprintf(stderr, "X server %s is ready for you.\n", xdisplay);
							{
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
								if(!write_message(ssmSocket, notifyMessage.c_str(), notifyMessage.size()))
								{
									fprintf(stderr,"ERROR - Unable to send start message to SSM\n");
									exit(-1);
								}

								if(notifyParent)
								{
									if(g_debugPrints)
										printf("INFO: Sending SIGUSR1 to parent to signal server ready.\n");
									kill(getppid(), SIGUSR1);
								}
							}
							parentWaitTillSUIDExits(ssmSocket, isShared, -1, origParentPipe, serverSocket);
							break;
						case CONNECTION_DENIED:
							fprintf(stderr, "You do not have access to X server %s.\n", xdisplay);
							exit(-1);
							break;
						case SHARE_LIMIT_REACHED:
							fprintf(stderr, "Configured maximum number of users are already connected to the X server %s.\n", xdisplay);
							exit(-1);
							break;
					}
				}
			}
			else
			{
				perror("Connect failed");
			}
		} while(doRetry);

		close(serverSocket);
		serverSocket = -1;
	}

	struct sigaction sighandler;
	sighandler.sa_handler = parent_sighdlr;
	sighandler.sa_flags = SA_RESTART;
	sigemptyset(&sighandler.sa_mask);
	sigaction(SIGCHLD, &sighandler, NULL);

	// Get back our root privileges.
	// We need to do this before the fork, else
	// 	
	if(seteuid(0)==-1)
	{
		perror("FATAL - unable to elevate privileges to root\n");
		exit(-1);
	}

	// Take a per server lock to ensure that only one process
	// can enter this important path!
	// Note: we don't give up this - it is given up
	// automatically when the program exits. This ensures we
	// will not need to do any cleanup
	if(!take_per_server_lock(xdisplay))
	{
		fprintf(stderr,"Unable to acquire lock. Exiting...");
		exit(-1);
	}

	// Fork here to control SUID child
	// Fork is needed else the caller of the vs-X cannot control the
	// SUID child!
	int suidChildPid = fork();
	if(suidChildPid != 0)
	{
		// FD gets duplicated on fork, so we close it here
		close(g_perServerLockFD);

		seteuid(userUid); // give up privileges again

		serverSocket = -1;
		if(isShared)
		{
			// wait for child to come up
			serverSocket = socket(AF_UNIX, SOCK_STREAM, 0);
			if(serverSocket < 0)
			{
				perror("ERROR - Unable to create a socket");
				exit(-1);
			}

			struct sockaddr_un sa;
			sa.sun_family = AF_UNIX;
			string serverSocketAddr = "/var/run/vizstack/socket-";
			serverSocketAddr += xdisplay;
			strcpy(sa.sun_path, serverSocketAddr.c_str()); // on Linux, the path limit seems to be 118
			// FIXME: rationalize the delay below. Does it make sense to put a retry loop here ?
			sleep(XSERVER_LOCK_DELAY*2+1); // give time for the daemon process to accept connections
			if(connect(serverSocket, (sockaddr*) &sa, sizeof(sa.sun_family)+sizeof(sa.sun_path))==0)
			{
				// get the response to our connection
				char *response = read_message(serverSocket);

				if(!response)
				{
					// wrapper could not process our connection request
					fprintf(stderr,"Unexpected response\n");
				}
				else
				{
					WrapperConnStatus status;
					memcpy(&status, response, sizeof(status));
					if(status != SUCCESSFULLY_CONNECTED)
					{
						fprintf(stderr,"Unexpected status :");
						switch(status)
						{
							case CONNECTION_DENIED:
								fprintf(stderr, "CONNECTION_DENIED"); break;
							case ALREADY_CONNECTED:
								fprintf(stderr, "ALREADY_CONNECTED"); break;
							case SHARE_LIMIT_REACHED:
								fprintf(stderr, "SHARE_LIMIT_REACHED"); break;
							default:
								fprintf(stderr, "Unknown status code"); break;
						}
						fprintf(stderr, "\n");
					}
					else
					{
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
						if(!write_message(ssmSocket, notifyMessage.c_str(), notifyMessage.size()))
						{
							fprintf(stderr,"ERROR - Unable to send start message to SSM\n");
							exit(-1);
						}
						fprintf(stderr,"Connected successfully to daemon. X server %s is ready\n",xdisplay);

						if(notifyParent)
						{
							if(g_debugPrints)
								printf("INFO: Sending SIGUSR1 to parent to signal server ready.\n");
							kill(getppid(), SIGUSR1);
						}
					}
				}
			}
			else
			{
				// FIXME: we need to do something better here ?
				perror("FATAL - Unexpected error connecting to server.");
				exit(-1);
			}
		}
		else
		{
			// parent process gives up SSM connection, but child continues to keep it
			close(ssmSocket);
			ssmSocket = -1;
		}

		parentWaitTillSUIDExits(ssmSocket, isShared, suidChildPid, origParentPipe, serverSocket);
	}

	close(g_parent_sig_pipe[1]);
	close(g_parent_sig_pipe[0]);
	g_parent_sig_pipe[0] = g_parent_sig_pipe[1] = -1;

	// Close the write end since we don't need to communicate
	// anything to the parent process
	close(origParentPipe[1]);

	// Now shift to become the root user, else the RGS module loaded by the X server 
	// crashes on startup.
	//
	// This is done by setting the both real user id and group id to 0. (setting only the real
	// user ID does not do the trick. group id must change as well)
	//
	// This approach is implemented with the assumption that this binary is SUID(and SGID) root.
	//
	// Becoming the root is a necessity for the following reason:
	//
	// The RGS module crashes on startup from the X server, if the X server is not run by
	// the root user.
	//
	int status;
	status = setreuid(0, 0);
	if (status != 0)
	{
        	perror("ERROR: Unable to set effective user id to root");
	        exit(-1);
	}
	status = setregid(0, 0);
	if (status != 0)
	{
        	perror("ERROR: Unable to set effective group id to root");
	        exit(-1);
	}

	// Determine the right X server to use. This differs across distros.
	if(access(XSERVER_PATH_1, X_OK)==0)
	{
		childArgs[0]=XSERVER_PATH_1;
	}
	else
	if(access(XSERVER_PATH_2, X_OK)==0)
	{
		childArgs[0]=XSERVER_PATH_2;
	}
	else
	{
		fprintf(stderr, "ERROR : Cannot find an appropriate X server. Cannot continue.\n");
		exit(-1);
	}

	// Register SIGCHLD handler first so that we get exit notifications from our child X
	// server
	struct sigaction siginfo;
	siginfo.sa_handler = sigchild_handler;
	siginfo.sa_flags = SA_RESTART; 
	sigemptyset (&siginfo.sa_mask);
	sigaction(SIGCHLD, &siginfo, NULL);

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

	// Create a lock file for exclusive access
	// need to do this before creating the configuration files. Why?
	// If we don't do this now, an X server that is cleaning up may
	// erase our config files. Also, the X server that is cleaning
	// up will not get enough time to cleanup things like its 
	// sockets
	//
	if(!take_lock())
	{
		fprintf(stderr,"Unable to acquire lock. Exiting...");
		exit(-1);
	}

	// if the X server is shared, then create a local socket for getting
	// sharing requests
	string serverSocketAddr;
	if(isShared)
	{
		serverSocket = socket(AF_UNIX, SOCK_STREAM, 0);
		if(serverSocket < 0)
		{
			perror("ERROR - Unable to create a socket");
			exit(-1);
		}
		struct sockaddr_un sa;
		memset(&sa, 0, sizeof(sa));
		sa.sun_family = AF_UNIX;
		serverSocketAddr = "/var/run/vizstack/socket-";
		serverSocketAddr += xdisplay;
		strcpy(sa.sun_path, serverSocketAddr.c_str()); // on Linux, the path limit seems to be 118

		// if the bind below fails, then something is really
		// wrong. We got in because we got an exclusive lock
		// onto a per server lcok file - so nobody else could
		// be trying the bind
		//
		// FIXME: we can unlink the bound socket here, can't
		// we ?
		int oldmask = umask(0);
		bool bindSuccess = false;
		if(bind(serverSocket,(struct sockaddr *)&sa,sizeof(sa))==0)
		{
			bindSuccess = true;
		}
		if(!bindSuccess)
		{
			perror("Bind failed - cannot start server.");
			exit(-1);
		}
		umask(oldmask);

		// set a queue length of 5 (an arbitrary number) for incoming requests
		listen(serverSocket, 5);
		fprintf(stderr, "Wrapper server socket listening...\n");
	}
	else
	{
		serverSocket  = -1;
	}

	//
	// Generate the xorg.conf file name
	// This will be /var/run/vizstack/xorg-0.conf, where 0 is the X server number
	// We don't keep this file in /etc/X11. Creating a file in /etc/X11 would allow
	// regular users of X to use it later. We want to avoid this.
	//
	sprintf(xorg_config_path, "/var/run/vizstack/xorg-%s.conf", xdisplay+1); // NOTE: remove the colon to have filenames without colons. Windows doesn't like colons in filenames.
	sprintf(serverinfo_path, "/var/run/vizstack/serverinfo-%s.xml", xdisplay+1); // NOTE: remove the colon to have filenames without colons. Windows doesn't like colons in filenames.

	// Need to create the config file before we fork off the X server
	if(g_standalone)
	{
		sprintf(x_config_path, "/etc/vizstack/standalone/Xconfig-%s.xml", xdisplay+1);
		configInTempFile = false;
	}
	else
	{
		VSDOMParserErrorHandler errorHandler;
		// write the configuration to the right file
		configInTempFile = true;
		sprintf(x_config_path,"/var/run/vizstack/xconfig-%s.xml", xdisplay+1);

		// Serialize the XML into the temporary file. 
		if(!serverConfig.writeXML(x_config_path, errorHandler))
		{
			fprintf(stderr, "ERROR - error while writing out the X config file\n");
			unlink(x_config_path);
			closeSocket(ssmSocket);
			if(serverSocket != -1)
			{
				close(serverSocket);
				unlink(serverSocketAddr.c_str());
			}
			exit(-1);
		}

	}

	// If an authority file was specified, then copy it to a known place so that
	// access is easy...
	if(xauthority)
	{
		sprintf(user_xauthority_path, "/var/run/vizstack/Xauthority-%s", xdisplay+1);
		string cmd;
		cmd = "/opt/vizstack/bin/vs-generate-authfile ";
		cmd += xdisplay;
		cmd += " ";
		cmd += xauthority;
		cmd += " ";
		cmd += user_xauthority_path;
		if(system(cmd.c_str())!=0)
		{
			fprintf(stderr, "ERROR: Failed to create authority file for user access.\n");
			if(serverSocket != -1)
			{
				close(serverSocket);
				unlink(serverSocketAddr.c_str());
			}
			exit(-1);
		}
		if(chown(user_xauthority_path, ownerUid, 0)!=0)
		{
			fprintf(stderr, "ERROR: Failed to set owner of the X authority file.\n");
			if(serverSocket != -1)
			{
				close(serverSocket);
				unlink(serverSocketAddr.c_str());
			}
			exit(-1);
		}
		if(chmod(user_xauthority_path, S_IRUSR)!=0)
		{
			fprintf(stderr, "ERROR: Failed to change mode of the X authority file.\n");
			if(serverSocket != -1)
			{
				close(serverSocket);
				unlink(serverSocketAddr.c_str());
			}
			exit(-1);
		}
	}

	// convert the config file into a proper X server configuration file
	// that we can use as input to the X server
	char genCmd[4096];
	sprintf(genCmd, "/opt/vizstack/bin/vs-generate-xconfig --edid-output-prefix=/var/run/vizstack/.vizstack-temp-edid- --input=%s --output=%s --server-info=%s", x_config_path, xorg_config_path, serverinfo_path);
	if(ignoreMissingDevices)
		strcat(genCmd, " --ignore-missing-devices");
	int ret = system(genCmd);
	if(ret!=0)
	{
		fprintf(stderr, "Failed to generate X configuration. Exiting...\n");
		if(serverSocket != -1)
		{
			close(serverSocket);
			unlink(serverSocketAddr.c_str());
		}
		exit(ret);
	}

	int usesAllGPUs = 0;
	VSDOMParser *infoParser = new VSDOMParser;
	vector<OptVal> cmdArgVal;
	VSDOMDoc *serverinfo;
	{
		// Find information from the serverinfo file.
		//
		VSDOMParserErrorHandler errorHandler;
		serverinfo = infoParser->ParseFile(serverinfo_path, errorHandler);
		if(!serverinfo)
		{
			cerr << "ERROR: Unable to get serverinfo." << endl; //FIXME: This must never happen
			if(serverSocket != -1)
			{
				close(serverSocket);
				unlink(serverSocketAddr.c_str());
			}
			exit(-1);
		}

		VSDOMNode rootNode = serverinfo->getRootNode();
		VSDOMNode usesAllGPUNode = rootNode.getChildNode("uses_all_gpus");
		usesAllGPUs = usesAllGPUNode.getValueAsInt();

		vector<VSDOMNode> cmdArgNodes = rootNode.getChildNodes("x_cmdline_arg");
		for(unsigned int i=0;i<cmdArgNodes.size();i++)
		{
			OptVal ov;
			ov.name = cmdArgNodes[i].getChildNode("name").getValueAsString();
			VSDOMNode valNode = cmdArgNodes[i].getChildNode("value");
			if(!valNode.isEmpty())
				ov.value = valNode.getValueAsString();

			// don't allow anybody to sabotage our scheme - silently ignore such options!
			if((ov.name == "-config") || (ov.name=="-sharevts") || (ov.name=="-novtswitch") || (ov.name=="+xinerama") || (ov.name=="-xinerama") || (ov.name=="-layout"))
				continue;
	
			cmdArgVal.push_back(ov);
		}
	}

	if(g_debugPrints)
		fprintf(stderr, "Done processing serverinfo file.\n");

	// fill in the configuration file name on the child X server's command line
	childArgs.push_back("-config");
	childArgs.push_back(xorg_config_path);
	if(usesAllGPUs==0) // If the X server does not use all GPUs in the system, then we need to use sharevts & novtswitch
	{
		childArgs.push_back("-sharevts");
		childArgs.push_back("-novtswitch");
	}
	for(unsigned int i=0;i<cmdArgVal.size();i++)
	{
		childArgs.push_back(strdup(cmdArgVal[i].name.c_str()));
		if(cmdArgVal[i].value.size()>0)
			childArgs.push_back(strdup(cmdArgVal[i].value.c_str()));
	}
	childArgs.push_back(NULL);

	if(isShared)
	{
		daemonize();
	}

	pid_t childpid = fork();

	if (childpid<0)
	{
		perror("ERROR : vs-X failed - fork error");
		if(serverSocket != -1)
		{
			close(serverSocket);
			unlink(serverSocketAddr.c_str());
		}
		exit(-1);
	}

	if (childpid==0)
	{
		// Reset child's signal handlers to the default.
		siginfo.sa_handler = SIG_DFL;
		siginfo.sa_flags = SA_RESTART; 
		sigemptyset (&siginfo.sa_mask);
		sigaction(SIGHUP, &siginfo, NULL);
		sigaction(SIGTERM, &siginfo, NULL);
		sigaction(SIGINT, &siginfo, NULL);

		// FD gets duplicated on fork, so we close it here
		close(g_perServerLockFD);

		// FD gets duplicated, so we free it here
		// This child process inherits the shared lock.
		// So, if we use lock_free(), then it's equivalent
		// to giving up the lock. So, we just need to close 
		// the FD here.
		close(g_lockFD);

		// Close the FDs on the child
		// FIXME: more elegant and generic code could close all FDs till MAX_FD
		close(g_signotify_pipe[0]);
		close(g_signotify_pipe[1]);
		close(origParentPipe[0]);

		// Close the connection to the System State Manager.
		// We need to do this since we'll exec the X server next
		close(ssmSocket);

		// close the wrapper's listening socket
		close(serverSocket);

		// Set SIGUSR1 to IGN. This will cause the X server we 'exec'
		// next to send the parent a SIGUSR1. This signal will indicate
		// to the parent that it is ready to accept connections.

		struct sigaction usr1;
		usr1.sa_handler = SIG_IGN;
		usr1.sa_flags = SA_RESTART; 
		sigaction(SIGUSR1, &usr1, NULL);

		// Start the X server as the child process
		execv(childArgs[0], &childArgs[0]);

		// If exec returns, an error happened
		perror("ERROR : vs-X failed - exec failed");
		exit(-1);
	}

	// Shared "root" servers give up their connection to the SSM
	// This way, they decouple their lifetime from that of the allocation
	// itself.
	if(isShared)
	{
		close(ssmSocket);
		ssmSocket = -1;

		// Shared "root" servers connect as regular clients to get
		// access to things like the ACL
		ssmSocket = connectToSSM(g_ssmHost, g_ssmPort);
		if(ssmSocket==-1)
		{
			kill(childpid, SIGTERM);
			waitChildExit(childpid);
			if(serverSocket!=-1)
			{
				close(serverSocket);
				unlink(serverSocketAddr.c_str());
			}
			exit(-1);
		}

		// identify ourselves as a regular client.
		string myIdentity = "<client />";

		if(!authenticateToSSM(myIdentity, ssmSocket))
		{
			fprintf(stderr, "ERROR - Unable to authenticate to SSM\n");
			kill(childpid, SIGTERM);
			waitChildExit(childpid);
			closeSocket(ssmSocket);
			if(serverSocket != -1)
			{
				close(serverSocket);
				unlink(serverSocketAddr.c_str());
			}
			exit(-1);
		}
	}

	// Control will come here in the parent - i.e. the original vs-X process

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
	char xuser_filename[256];
	int retCode=0;
	bool loopDone=false;

	sprintf(xuser_filename, "/var/run/vizstack/xuser-%s", xdisplay+1);


	vector<ConnClient> connectedClients;
	ConnClient parentClient = { -1, userUid };
	connectedClients.push_back(parentClient); // make an entry for the parent process

	while(!loopDone)
	{
		FD_ZERO (&rfds);
		FD_SET (g_signotify_pipe[0], &rfds);
		int maxFD = g_signotify_pipe[0];

		// if all the clients have disconnected, then we need to
		// kill the X server and shutdown
		if (connectedClients.size()==0)
		{	
			take_lock_once ();

			if(g_debugPrints)
				printf("INFO : All clients for shared vs-X have exited. So killing X server using SIGTERM\n");
			kill(childpid, SIGTERM);
			// delay a bit to give time for thing to stabilize. This has
			// been done to avoid X servers cleaning up in rapid succession.
			sleep(XSERVER_LOCK_DELAY);
			closeSocket(ssmSocket);
			ssmSocket = -1;
		}


		// Monitor the SSM socket.
		// SSM will close the socket when it wants us to exit
		// In the future we can use this to do X related activities from the
		// SSM.
		if(ssmSocket != -1)
			FD_SET(ssmSocket, &rfds);
		if (ssmSocket>maxFD)
			maxFD = ssmSocket;
		// Monitor parent process exit
		if(origParentPipe[0]!=-1)
			FD_SET(origParentPipe[0], &rfds);
		if (origParentPipe[0]>maxFD)
			maxFD = origParentPipe[0];

		if(xInitDone)
		{
			for(vector<ConnClient>::iterator pConnectedClients=connectedClients.begin(); pConnectedClients!=connectedClients.end(); pConnectedClients++)
			{
				int fd = pConnectedClients->fd;
				if (fd!=-1)
				{
					FD_SET(fd, &rfds);
					if(fd>maxFD) maxFD = fd;
				}
			}
			// monitor shared server requests
			if(isShared)
			{
				FD_SET(serverSocket, &rfds);
				if (serverSocket>maxFD)
					maxFD = serverSocket;
			}
		}

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
  		ret = select(maxFD + 1, &rfds, NULL, NULL, NULL);

		// Handle Errors in select
		if (ret<0)
		{
			// FIXME: humm - what can we do here ?
			continue;
		}


		// Handle SSM socket activity
		if((ssmSocket!=-1) && FD_ISSET(ssmSocket, &rfds))
		{
			// Do a read of 1 byte
			char buf=0;
			char *msg = read_message(ssmSocket);

			// If the SSM closes the socket (or some other error occurs)
			// then we act as if we had got SIGTERM
			if(msg==0)
			{
				if(g_debugPrints)
					printf("INFO : SSM closed connection. Killing X server using SIGTERM\n");

				take_lock_once ();

				kill(childpid, SIGTERM);
				// delay a bit to give time for thing to stabilize. This has
				// been done to avoid X servers cleaning up in rapid succession.
				sleep(XSERVER_LOCK_DELAY);

				closeSocket(ssmSocket);
				ssmSocket = -1;
			}

			if(msg)	
				delete []msg;
		}

		// Handle activity on connected sockets
		// also, check server ACL and disconnect clients whose access has been revoked.
		vector<int> eraseList;
		for(vector<ConnClient>::iterator pConnectedClients=connectedClients.begin(); pConnectedClients!=connectedClients.end(); pConnectedClients++)
		{
			int fd = pConnectedClients->fd;
			int uid = pConnectedClients->uid;
			if ((fd!=-1) && FD_ISSET(fd, &rfds))
			{
				close(fd);
				eraseList.insert(eraseList.begin(), pConnectedClients-connectedClients.begin());
			}
		}

		// remove the FDs from the table
		for(unsigned int i=0;i<eraseList.size();i++)
		{
			int uid = connectedClients[eraseList[i]].uid;
			connectedClients.erase(connectedClients.begin()+eraseList[i]);

			// check if the user id has other connections to the server
			bool remainsConnected = false;
			for(unsigned int j=0;j<connectedClients.size();j++)
			{
				if (connectedClients[j].uid==uid)
					remainsConnected = true;
			}

			// if the user has no other connections to the server
			// then we remove access to the user
			if(!remainsConnected)
			{
				setenv("XAUTHORITY",user_xauthority_path, 1);
				setenv("DISPLAY",xdisplay, 1);

				// Translate owner UID to name
				struct passwd pwd, *ppwd;
				char pwd_buffer[2048];
				if(getpwuid_r(uid, &pwd, pwd_buffer, sizeof(pwd_buffer), &ppwd)!=0)
				{
					perror("ERROR : Failed to find username of invoking user\n");
				}
				else
				{
					char cmd[4096];
					sprintf(cmd, "xhost -si:localuser:%s",pwd.pw_name);
					if(system(cmd)!=0)
					{
						fprintf(stderr,"Failed to add access for remove access for user %s\n",pwd.pw_name);
					}
					else
					{
						if(g_debugPrints)
							printf("Successfully removed access for user %s\n", pwd.pw_name);
					}
				}
			}
		}

		// attend to connection requests on the local socket only after X has
		// finished initialization ?
		if((xInitDone) && (isShared))
		{
			// Proceed only if
			// there is a connection request on our socket AND
			// a. we are standalone OR
			// b. we are connected to the SSM (to get the new ACL)
			if(FD_ISSET(serverSocket, &rfds) && (g_standalone || (ssmSocket!=-1)))
			{
				if(!g_standalone)
				{
					char *serverConfiguration = getServerConfig(myHostName, xdisplay, ssmSocket);
					if(!serverConfiguration)
					{
						closeSocket(ssmSocket);
						if(serverSocket != -1)
						{
							close(serverSocket);
							unlink(serverSocketAddr.c_str());
						}
						kill(childpid, SIGTERM);
						waitChildExit(childpid);
						exit(-1);
					}

					VSDOMParserErrorHandler errorHandler;
					configParser = new VSDOMParser;
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
						kill(childpid, SIGTERM);
						waitChildExit(childpid);
						closeSocket(ssmSocket);
						if(serverSocket != -1)
						{
							close(serverSocket);
							unlink(serverSocketAddr.c_str());
						}
						exit(-1);
					}

					//printf("Fresh server configuration is \n%s\n", serverConfiguration);
					VSDOMNode rootNode = config->getRootNode();
					VSDOMNode responseNode = rootNode.getChildNode("response");
					int status = responseNode.getChildNode("status").getValueAsInt();
					if(status!=0)
					{
						string msg = responseNode.getChildNode("message").getValueAsString();
						fprintf(stderr, "ERROR - Failure returned from SSM : %s\n", msg.c_str());
						delete configParser;
						kill(childpid, SIGTERM);
						waitChildExit(childpid);
						closeSocket(ssmSocket);
						if(serverSocket != -1)
						{
							close(serverSocket);
							unlink(serverSocketAddr.c_str());
						}
						exit(-1);
					}

					VSDOMNode retValNode = responseNode.getChildNode("return_value");
					serverConfig = retValNode.getChildNode("server");

					getACL(serverConfig, serverACL);
					VSDOMNode svMaxShareCountNode = serverConfig.getChildNode("maxShareCount");
					if(!svMaxShareCountNode.isEmpty())
					{
						// FIXME we shouldn't end up in zero, as the schema will not allow for this.
						maxClients = svMaxShareCountNode.getValueAsInt(); 
					}
					delete config;
					delete []serverConfiguration;
				}

				struct sockaddr addr;
				socklen_t addrlen = sizeof(addr);
				int fd = accept(serverSocket, &addr, &addrlen);
				struct ucred cr;
				socklen_t len=sizeof(cr);
				getsockopt(fd, SOL_SOCKET, SO_PEERCRED, &cr, &len);
				fprintf(stderr, "Connected socket for pid=%d uid=%d gid=%d\n", cr.pid, cr.uid, cr.gid);

				WrapperConnStatus returnStatus=CONNECTION_DENIED;

				// parent process connecting to us ?
				if(cr.pid==rootParentPid)
				{
					connectedClients[0].fd = fd;
					returnStatus = SUCCESSFULLY_CONNECTED;
					fprintf(stderr, "SUCCESS for parent uid=%d PID=%d\n", cr.uid, cr.pid);
				}
				else
				// maximum clients reached ?
				if (connectedClients.size()==maxClients)
				{
					returnStatus = SHARE_LIMIT_REACHED;
					fprintf(stderr, "Maximum number of users reached for X server %s. Denying request.\n", xdisplay);
				}
				else
				// allow anyone if ACL has a -1
				if ((serverACL.size()==1) && (serverACL[0]==-1))
				{
					ConnClient cl = { fd, cr.uid };
					connectedClients.push_back(cl);
					fprintf(stderr, "SUCCESS for [everyone] uid=%d PID=%d\n", cr.uid, cr.pid);
					returnStatus = SUCCESSFULLY_CONNECTED;
				}
				else
				// disallow if not listed in the ACL
				if ((find(serverACL.begin(), serverACL.end(),cr.uid)==serverACL.end()))
				{
					returnStatus = CONNECTION_DENIED;
					fprintf(stderr, "uid %d does not have access to X server %s. Denying request.\n", cr.uid, xdisplay);
				}
				else
				{
					// Check if the userid connecting is permitted to connect
					// A user can be an owner more than once, so we need to watch out!

					vector<int> currentUsers;
					for(unsigned int i=0;i<connectedClients.size();i++)
					{
						currentUsers.push_back(connectedClients[i].uid);
					}

					// create a list of users we allow next to connect
					vector<int> allowedUsers;
					allowedUsers = serverACL;
					// remove connected users from allowed users. The remaining users will be
					// allowed to connect
					for(unsigned int i=0;i<connectedClients.size();i++)
					{
						allowedUsers.erase(find(allowedUsers.begin(), allowedUsers.end(), connectedClients[i].uid));
					}

					if(find(allowedUsers.begin(), allowedUsers.end(), cr.uid)==allowedUsers.end())
					{
						returnStatus = ALREADY_CONNECTED;
						fprintf(stderr, "X server(s) already running for uid = %d pid = %d\n", cr.uid, cr.pid);
					}
					else
					{
						ConnClient cl = { fd, cr.uid };
						connectedClients.push_back(cl);
						fprintf(stderr, "SUCCESS for uid=%d PID=%d\n", cr.uid, cr.pid);
						returnStatus = SUCCESSFULLY_CONNECTED;
					}
				}

				if (returnStatus==SUCCESSFULLY_CONNECTED)
				{
					setenv("XAUTHORITY",user_xauthority_path, 1);
					setenv("DISPLAY",xdisplay, 1);

					// Translate owner UID to name
					struct passwd pwd, *ppwd;
					char pwd_buffer[2048];
					if(getpwuid_r(cr.uid, &pwd, pwd_buffer, sizeof(pwd_buffer), &ppwd)!=0)
					{
						perror("ERROR : Failed to find username of invoking user\n");
					}
					else
					{
						char cmd[4096];
						sprintf(cmd, "xhost +si:localuser:%s",pwd.pw_name);
						if(system(cmd)!=0)
						{
							fprintf(stderr, "Failed to add access to user %s\n", pwd.pw_name);
						}
						else
						{
							if(g_debugPrints)
								printf("Successfully added access for user %s\n", pwd.pw_name);
						}
					}
				}
				// send the response
				if(!write_message(fd, (char *)&returnStatus, sizeof(returnStatus)))
				{
					fprintf(stderr, "Unable to send status to client...\n");
				}

				if (returnStatus!=SUCCESSFULLY_CONNECTED)
				{
					close(fd);
				}
			}
		}

		// Handle parent exit
		if((origParentPipe[0]!=-1) && FD_ISSET(origParentPipe[0], &rfds))
		{
				// Do a read of 1 byte
				char buf=0;
				RETRY_ON_EINTR(ret, read(origParentPipe[0], &buf, 1));

				// If the parent dies, then we kill the child
				// this way we ensure cleanup in all cases.
				if(ret==0)
				{
						close(origParentPipe[0]);
						origParentPipe[0] = -1;

						if(!isShared)
						{
							// kill child X server only if the server is not shared
							// if the server is shared, we'll wait for all clients to 
							// disconnect to kill the X server
							if(g_debugPrints)
								printf("INFO : Parent vs-X died. Killing X server using SIGTERM\n");

							take_lock_once();

							kill(childpid, SIGTERM);
							// delay a bit to give time for thing to stabilize. This has
							// been done to avoid X servers cleaning up in rapid succession.
							sleep(XSERVER_LOCK_DELAY);
						}
				}
				else
				{
					// free our X server lock
					free_lock_once();
					fprintf(stderr, "FATAL: Bad case - parent isn't supposed to write to us!\n");
					kill(childpid, SIGTERM);
					waitChildExit(childpid);
					if(serverSocket != -1)
					{
						close(serverSocket);
						unlink(serverSocketAddr.c_str());
					}
					exit(-1);
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
						else
						{
							if(g_debugPrints)
								fprintf(stderr, "Child X server exited in an unrecognized way!\n");
						}
					}
					else
					{
						// other child process exits cause us to come here.
						// we use "xauth" and when that exits, we'll come here.
						// ignore this
					}
				}
				break;
			case CODE_SIGUSR1: 
				// Do SIGUSR1 handling only once.
				// Why ? Sometimes I have noticed that I get a SIGUSR1 everytime
				// a client connects and disconnects
				if(!xInitDone)
				{
					// If the server is a shared server, then we don't directly 
					// intimate parents of server availability. The connecting 
					// client will do this when it gets "SUCCESSFULLY_CONNECTED"
					if((notifyParent) && (!isShared))
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

					// delay a bit to give time for the driver to initialize.
					// this takes more time compared to just X server startup.
					// X server possibly allows connections before the driver completely inits
					sleep(XSERVER_LOCK_DELAY);

					// free our X server lock so that other X servers can start
					free_lock();

					//
					// Record the name of the user for whom this X server is intended in /var/run/vizstack/rgsuser
					// This information can be used to find who owns the X server. At the time of this writing,
					// it is intended to be used by the RGS PAM module to restrict access to the X server.
					//
					if(g_debugPrints)
						printf("INFO : Creating record of X server allocation\n");
					FILE *fp=fopen(xuser_filename,"w");
					if(fp==NULL)
					{
						perror("ERROR: Unable to access vizstack xuser files");
						exit(-1);
					}

					// record our PID as the X server's PID
					// this allows us to track X server kills directly
					fprintf(fp, "%s %d %d", xuser, getpid(), rgsPromptUser); 
					fclose(fp);

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
					// X server is available. Shared root servers don't need to do this, since
					// the other procs will handle this
					if((!isShared) && (ssmSocket != -1))
					{
							if(!write_message(ssmSocket, notifyMessage.c_str(), notifyMessage.size()))
							{
								fprintf(stderr,"ERROR - Unable to send start message to SSM\n");
								kill(childpid, SIGTERM);
								waitChildExit(childpid);
								if(serverSocket != -1)
								{
									close(serverSocket);
									unlink(serverSocketAddr.c_str());
								}
								exit(-1);
							}
					}

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

				take_lock_once();

				kill(childpid, SIGTERM);
				// delay a bit to give time for thing to stabilize. This has
				// been done to avoid X servers cleaning up in rapid succession.
				sleep(XSERVER_LOCK_DELAY);
				break;

			case CODE_SIGINT: 
				if(g_debugPrints)
					printf("INFO : Propagating SIGINT to child X server as SIGTERM\n");

				take_lock_once();
				kill(childpid, SIGTERM);
				// delay a bit to give time for thing to stabilize. This has
				// been done to avoid X servers cleaning up in rapid succession.
				sleep(XSERVER_LOCK_DELAY);
				break;
			default:
				fprintf(stderr,"Unknown value in signal buffer\n");
				break;
		}
	}

	if(xInitDone)
	{
		// Remove the X usage record, if we created one
		if(g_debugPrints)
			printf("INFO : Removing record of X server allocation.\n");
		unlink(xuser_filename); 
	}

	//  delete all the temporary edids created
	VSDOMNode rootNode = serverinfo->getRootNode();
	vector<VSDOMNode> tempEdidNodes = rootNode.getChildNodes("temp_edid_file");
	for(unsigned int i=0;i<tempEdidNodes.size();i++)
	{
		string fname=tempEdidNodes[i].getValueAsString();
		unlink(fname.c_str());
	}
	delete infoParser;

	// remove the other temporary config files we created:
	//    1. the X config file
	//    2. the serverinfo file
	unlink(xorg_config_path);
	unlink(serverinfo_path);
	if(strlen(user_xauthority_path)>0)
	{
		unlink(user_xauthority_path);
	}
	if(configInTempFile)
	{
		unlink(x_config_path);
	}

	// Update System State Manager with information that the X server has stopped.
	// NOTE: we need to do this after removing the X org file, else there is a chance of
	// an improper config file in place. This is not a big problem, but it's nice to be
	// consistent
	if(xInitDone)
	{
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

		// no need to do the intimation if we are the root X server (for a shared server)
		if((!isShared) && (ssmSocket!=-1))
		{
			if(!write_message(ssmSocket, notifyMessage.c_str(), notifyMessage.size()))
			{
				fprintf(stderr,"ERROR - Unable to send start message to SSM\n");
			}
		}
	}

	// close the connection to the SSM
	if(ssmSocket!=-1)
		closeSocket(ssmSocket);

	// cleanup the wrapper sockets
	if(serverSocket != -1)
	{
		if(g_debugPrints)
			printf("INFO : Freeing our local socket\n");
		close(serverSocket);
		unlink(serverSocketAddr.c_str());
		serverSocket  = -1;
	}

	// When we come here, then the X server will not be running
	// but we'll have the lock, so release it
	if(have_lock())
	{
		if(g_debugPrints)
			printf("INFO : Freeing our lock\n");
		free_lock();
	}

	if(g_debugPrints)
		printf("INFO : Exiting X server wrapper...\n");

	exit(retCode);
}
