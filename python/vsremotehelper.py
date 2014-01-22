# VizStack - A Framework to manage visualization resources

# Copyright (C) 2009-2010 Hewlett-Packard
# 
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

"""
vsremotehelper.py

Helper module for Remote Access applications. These
applications are basically automations over an SSH
channel, where a script running on the VizStack system
does all the work.

Interaction with the script happens over stdin/out.
"""
import sys
import os
import select
from xml.dom import minidom
def sendMessage(msg):
	"""
	Send a message by printing out to stdout.
	The flush ensures that the message really reaches
	the remote end
	"""
	print '%s\n'%(msg)
	sys.stdout.flush()

def getMessage():
	"""
	Get a full DOM tree from stdin
	"""
	total_data = ''
	dom = None
	while dom is None:
		data = sys.stdin.read(1)
		# EOF, so bail out
		if len(data)==0:
			break
		total_data = total_data + data
		try:
			dom = minidom.parseString(total_data)
		except:
			dom = None
		# if we got a full DOM tree, then that's our command
		if dom != None:
			break
	return dom

def waitProcessStdin(pid=None):
	"""
	waits for a process to exit,
	or for stdin to close.

	Returns 0 if the process exited, 1 if stdin got an exit command or was closed
	Returns 2 if app hasn't none of these two 
	"""
	(rr, wr, er) = select.select([sys.stdin],[],[], 1.0)
	if pid is not None:
		ret = os.waitpid(pid, os.P_NOWAIT)
		if ret[0]==pid:
			send_remote("<resp><ret err='0' message='Remote session ended' /></resp>")
			return 0 # child PID died normally
	if sys.stdin in rr:
		cmd = sys.stdin.readline()
		cmd=cmd.rstrip()
                if(cmd=='exit') or (len(cmd)==0):
       	                return 1
	if len(rr)==0:
		return 2

