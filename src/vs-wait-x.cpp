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
// replacement for user-auth-add
//
// Adds access to the X server for the invoking user
// Connect to the X server and wait till it exits.
//
// Typically meant to be invoked as a client program by
// xinit
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <iostream>
#include <sys/select.h>
#include <string>
#include <sys/types.h>
#include <pwd.h>
#include <signal.h>

using namespace std;

int main()
{
        struct passwd pwd, *ppwd;
        char pwd_buffer[2048];

        // Find the invoking user ID
        if(getpwuid_r(getuid(), &pwd, pwd_buffer, sizeof(pwd_buffer), &ppwd)!=0)
        {
                perror("ERROR : Failed to username of invoking user\n");
                exit(-1);
        }

	Display *dpy = XOpenDisplay(0);
	if(!dpy)
	{
		cerr << "==============================" << endl;
		cerr << "FATAL error"<< endl;
		cerr << "Unable to connect to X server." << endl;
		cerr << "==============================" << endl;
		exit(-1);
	}
#if 1
	string cmd;
	cmd = "xhost +si:localuser:";
	cmd += pwd.pw_name;
	int ret = system(cmd.c_str());
	if(ret != 0)
	{
		cerr << "Failed to add user access to X server. Exiting." << endl;
		exit(-1);
	}
#endif
	// Get the FD of the connection to the X server. This lets
	// us implement "wait-on-exit".
	//
	// Note that in case of a single X server being shared 
	// multiple times by the same user, this does not work!
	// Why ? Because the X server does not exit.
	//
	// However, the X server process does exit. That should
	// be enough for xinit to kill us...
	int xfd = ConnectionNumber(dpy);

	while(1)
	{
		fd_set rfds;
		FD_ZERO(&rfds);
		FD_SET(xfd, &rfds);
		int ret = select(xfd+1, &rfds, NULL, NULL, NULL);
		if(ret==1)
		{
			cout << "X connection closed" << endl;
			break;
		}
	}

	// In the normal vizstack scheme, xinit is used to start
	// vs-X and this client. Sometimes, I have observed that
	// xinit continues to run inspite of both child processes
	// having exited. So, I explicitly kill the parent xinit
	// process at the end
	kill(getppid(), SIGTERM);

	exit(0);
}
