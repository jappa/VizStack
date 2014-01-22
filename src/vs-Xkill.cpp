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

#include <sys/types.h>
#include <sys/wait.h>
#include <pwd.h>
#include <stdio.h>
#include <errno.h>
#include <signal.h>
#include <string.h>

void usage(int retCode=0)
{
	FILE *out=stdout;
	if(retCode!=0)
	{
		out=stderr;
	}

	fprintf(out,"Usage: Xkill [display]\n\n");
	fprintf(out,"display corresponds to the X server you wish to kill, with a default value of :0\n");
	fprintf(out,"A regular(i.e. non-root) user is not allowed to kill the X server(s) started by other users\n");
	exit(retCode);
}

int main(int argc, char **argv)
{
	struct passwd pwd, *ppwd;
	char pwd_buffer[2048];
	char *display=NULL;
	if(argc>2)
		usage(-1);

	// Find the invoking user ID
	if(getpwuid_r(getuid(), &pwd, pwd_buffer, sizeof(pwd_buffer), &ppwd)!=0)
	{
		perror("ERROR : Failed to username of invoking user\n");
		exit(-1);
	}

	if(argc==1)
	{
		display=":0";
	}
	else
	{
		int dispNum=atoi(argv[1]+1);
		char dispStr[256];
		sprintf(dispStr,":%d",dispNum);

		if((argv[1][0]!=':') || (strcmp(dispStr, argv[1])!=0) || (dispNum<0))
		{
			fprintf(stderr, "ERROR : Invalid display value '%s'.\n", argv[1]);
			usage(-1);
		}

		display=argv[1];
	}
	char xuser_filename[4096];
	sprintf(xuser_filename, "/var/run/vizstack/xuser-%s",display+1);
	FILE *fp=fopen(xuser_filename, "r");
	if(fp==NULL)
	{
		fprintf(stderr, "The specified X server (on %s) is not running", display);
		exit(-1);
	}

	char username[4096]; // Safe static sizes I think !!
	int pid;
	int rgsPromptUser;
	char linebuffer[4096];

	if(fgets(linebuffer, sizeof(linebuffer), fp)==NULL)
	{
		fprintf(stderr, "Unable to get contents from vizstack xuser file");
		exit(-1);
	}
	if(sscanf(linebuffer, "%s %d %d", username, &pid, &rgsPromptUser)!=3)
	{
		fprintf(stderr, "Parse error on vizstack xuser file for display %s", display);
		exit(-1);
	}
	fclose(fp);

	if((getuid()!=0) && (strcmp(username, pwd.pw_name)!=0))
	{
		fprintf(stderr, "You do not have permission to kill the specified X session(%s)\n", display);
		exit(-1);
	}

	// Now shift to become the root user, to kill em all :-)
	// This is done by setting the real uid to 0.
	// This approach works as this binary is expected to be SUID root.
	int status;
	status = setreuid(0, 0);
	if (status != 0)
	{
        	perror("ERROR: Unable to set real id to euid");
	        exit(-1);
	}

	if(strcmp(username, pwd.pw_name)==0)
	{
		printf("Killing X server '%s'\n", display);
	}
	else
	{
		printf("Killing X server '%s' belonging to user '%s'\n", display, username);
	}

	// Finally, kill the thing!
	if(kill(pid, SIGTERM)<0)
	{
		if(errno==EPERM)
		{
			// FIXME: this can't happen!
		}
		else
		if(errno==ESRCH)
		{
			fprintf(stderr, "The X server doesn't seem to exist. Probably it's already died ?\n");
			// process does not exist!
			// so delete the file
			unlink(xuser_filename);
			exit(-1);
		}
	}

	// Check for some time for the server to die
	bool success=false;
	int exitDelay=10; // FIXME: we should wait for longer & initimate users about progress.
	for(int i=0;i<exitDelay;i++)
	{
		sleep(1);

		if(getpgid(pid)!=0) // This is just a way to see if the process exists
		{
			// If a process doesn't exist, then we get ESRCH as the errno
			// This process is running as root, so other return values are
			// not possible
			if(errno==ESRCH)
			{
				success=true;
				break;
			}
			
		}
	}

	if(!success)
	{
		fprintf(stderr, "X server didn't die in %d seconds. Try kill -9\n", exitDelay);
		exit(-1);
	}


	exit(0);
}
