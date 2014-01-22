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


#
# Implementation of the "local" scheduler
#
#
# The simplest of scheduler interface implementations -
#   This just runs programs on the local node!
#
# What's the benefit of a local scheduler ?
#   - Parallel programs can be run on a single node with the same
#     VizJob api.
#   - this allows customers to use  scripts like Ensight, Amira on
#     the local node.
# 
import scheduler
import launcher
import os
import subprocess
import process
import socket
import copy

class VizProcess(process.Process):
    	def __init__(self, proc):
		self.proc = proc
		self.retCode = None
		self.savedStdOut = None
		self.savedStdErr = None

	def __del__(self):
		self.kill()

	def wait(self):
		self.savedStdOut, self.savedStdErr = self.proc.communicate() # To avoid the wait below from blocking
		try:
			self.proc.wait() # FIXME: this infinite wait is not good ??
		except OSError, e:
			pass
		self.retCode = self.proc.returncode
		self.proc = None

	def getSubprocessObject(self):
		return self.proc

	def getStdOut(self):
		return self.savedStdOut

	def getStdErr(self):
		return self.savedStdErr

	def getExitCode(self):
		return self.retCode

	def kill(self, signal=15): # Default to SIGTERM(15), and not SIGKILL(9)
		if self.proc is None:
			return
		try:
			os.kill(self.proc.pid, signal)
		except OSError, e:
			pass
		self.wait()

class LocalReservation(launcher.Launcher):

	rootNodeName = "LocalReservation"

	def __init__(self, sched=None):
		self.sched = sched
		self.__isCopy = False

	def __del__(self):
		self.deallocate()

	def __getstate__(self):
		sched_save = self.sched
		del self.sched
		odict = self.__dict__.copy()
		self.sched = sched_save
		return odict

	def __setstate__(self, dict):
		"""
		This function is implemented to keep track of deepcopies.  If deepcopy is used,
		then this function will be used

		If isCopy is true, then the destructor will not remove the allocation.
		"""
		self.__dict__.update(dict)
		self.sched = None
		self.__isCopy = True

	def deallocate(self):
		if not self.__isCopy:
			if self.sched is not None:
				self.sched.deallocate(self)
		self.sched = None

	def run(self, args, node, inFile=None, outFile=None, errFile=None, launcherEnv=None):
		if node not in ["localhost"]:
			if node != socket.gethostname():
				# FIXME: raise the right type of error - please !
				raise "You are limited to run commands on the localnode (localhost) when using this scheduler"
		cmd_list = copy.copy(args)

		# Use the aew to prevent leftover proceses. Use "-ignorestdin" to prevent stdin processing from 
		# the app execution wrapper. This aids proper cleanup.
		cmd_list = ["/opt/vizstack/bin/vs-aew", "-ignorestdin"] + cmd_list

		# NOTE: close_fds = True as we don't want the child to inherit our FDs and then 
		# choke other things ! e.g. the SSM will not clean up a connection if close_fds is not set to True
		
		proc = subprocess.Popen(cmd_list, stdout=outFile, stderr=errFile, stdin=inFile, close_fds=True, env=launcherEnv)
		return VizProcess(proc)

	def serializeToXML(self):
		return "<%s />"%(LocalReservation.rootNodeName)

	def deserializeFromXML(self, domNode):
		if domNode.nodeName != LocalReservation.rootNodeName:
			raise ValueError, "Failed to deserialize LocalReservation. Programmatic Error"

class LocalScheduler(scheduler.Scheduler):

	def __init__(self, nodeList, params):
		self.allocations = []
        	self.nodeList = nodeList # FIXME: we could validate if we can resolve these names
		if len(nodeList)==0:
			raise ValueError, "I need one or more nodes to manage, you gave me none!"
		if params != "":
			raise ValueError, "Params must be empty for local runner. Incorrect value '%s'"%(params)

	def getNodeNames(self):
		return self.nodeList

	def allocate(self, uid, gid, nodeList):
		for nodeName in nodeList:
			if nodeName not in self.nodeList:
				raise ValueError, "Node '%s' is not managed by this Local Scheduler"%(nodeName)
		alloc = LocalReservation(self)
		self.allocations.append(alloc)
		return alloc

	def getUnusableNodes(self):
		return []

	def deallocate(self, allocObj):
		for idx in range(len(self.allocations)):
			if allocObj is self.allocations[idx]:
				self.allocations.pop(idx)
				return
		print "No such allocation was allocated by the Local Scheduler"
