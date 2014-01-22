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
// pam_vizstack_rgs_setuser.c
//
// PAM module to automatically input the name of the user who
// owns the X server for which this module is invoked.
//
// Sets pam_user to the person starting the X server.
//
// This module is intended to be used inside /etc/pam.d/rgsender.
// This module is intended to be chained with other authentication
// methods. The idea is that this module will restrict access to
// the user who started the X server. Since the user name is filled
// in automatically, the user running the RGS client only gets a 
// password prompt.
//
// Note #1: You will need to include this module at the top of
// /etc/pam.d/rgsender, like below --

/*
#%PAM-1.0
auth  required  pam_vizstack_rgs_setuser.so
auth  required  pam_env.so
auth  required  pam_nologin.so
auth  required  pam_stack.so service=system-auth
*/

// Including it at the top will prevent user being prompted for
// username, thus enforcing security.
//
// Note #2: Not chaining this module with other methods will result
// in a BIG SECURITY HOLE. You may choose to chain this module
// with password entry methods like pam_unix.
//
// At your discretion, you may choose external authentication
// methods like firewall or switch configuration. But these are
// not done by VizStack itself. So be very careful if you choose
// these methods.
//
// Started off with boilerplate code from pam_permit.c, and most 
// of it thrown away
//

#include <stdio.h>

/*
 * here, we make definitions for the externally accessible functions
 * in this file (these definitions are required for static modules
 * but strongly encouraged generally) they are used to instruct the
 * modules include file to define their prototypes.
 */

#define PAM_SM_AUTH
#define PAM_SM_ACCOUNT
#define PAM_SM_SESSION
#define PAM_SM_PASSWORD

#include <security/pam_modules.h>
#include <security/_pam_macros.h>

/* --- authentication management functions --- */
#define UNUSED

PAM_EXTERN int
pam_sm_authenticate(pam_handle_t *pamh, int flags UNUSED,
		    int argc UNUSED, const char **argv UNUSED)
{
	int retval;
	char *display=getenv("DISPLAY");
	char xuser_filename[256];
	sprintf(xuser_filename, "/var/run/vizstack/xuser-%s",display+1);
	FILE *fp=fopen(xuser_filename, "r");
	if(fp==NULL)
	{
		//fprintf(stderr, "The specified X server is not running");
		return PAM_USER_UNKNOWN;
	}

	char username[4096]; // Safe static sizes I think !!
	int pid;
	int rgsPromptUser;
	char linebuffer[4096];

	if(fgets(linebuffer, sizeof(linebuffer), fp)==NULL)
	{
		//fprintf(stderr, "Unable to get contents from vizstack xuser file");
		return PAM_USER_UNKNOWN;
	}
	if(sscanf(linebuffer, "%s %d %d", username, &pid, &rgsPromptUser)!=3)
	{
		//fprintf(stderr, "Parse error on vizstack xuser file");
		return PAM_USER_UNKNOWN;
	}
	fclose(fp);

	if(rgsPromptUser==0)
	{
		retval = pam_set_item(pamh, PAM_USER, (const void *) username);
		if (retval != PAM_SUCCESS)
			return PAM_USER_UNKNOWN;
	}

	return PAM_SUCCESS;
}

PAM_EXTERN int
pam_sm_setcred(pam_handle_t *pamh UNUSED, int flags UNUSED,
	       int argc UNUSED, const char **argv UNUSED)
{
     return PAM_SUCCESS;
}

/* --- account management functions --- */

PAM_EXTERN int
pam_sm_acct_mgmt(pam_handle_t *pamh UNUSED, int flags UNUSED,
		 int argc UNUSED, const char **argv UNUSED)
{
     return PAM_SUCCESS;
}

/* --- password management --- */

PAM_EXTERN int
pam_sm_chauthtok(pam_handle_t *pamh UNUSED, int flags UNUSED,
		 int argc UNUSED, const char **argv UNUSED)
{
     return PAM_SUCCESS;
}

/* --- session management --- */

PAM_EXTERN int
pam_sm_open_session(pam_handle_t *pamh UNUSED, int flags UNUSED,
		    int argc UNUSED, const char **argv UNUSED)
{
    return PAM_SUCCESS;
}

PAM_EXTERN int
pam_sm_close_session(pam_handle_t *pamh UNUSED, int flags UNUSED,
		     int argc UNUSED, const char **argv UNUSED)
{
     return PAM_SUCCESS;
}

/* end of module definition */

#ifdef PAM_STATIC

/* static module data */

struct pam_module _pam_permit_modstruct = {
    "pam_vizstack_rgs_setuser",
    pam_sm_authenticate,
    pam_sm_setcred,
    pam_sm_acct_mgmt,
    pam_sm_open_session,
    pam_sm_close_session,
    pam_sm_chauthtok
};

#endif
