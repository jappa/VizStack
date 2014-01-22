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
# Implementation of the "SSH" scheduler
#
# Uses SSH to run application components on nodes.
# Relies on setup of passwordless SSH for painless
# operation.
# 
# 
import scheduler
import launcher
import localscheduler
import os
import subprocess
import process
import socket
import copy

class SSHReservation(launcher.Launcher):

	rootNodeName = "SSHReservation"

	def __init__(self, sched=None):
		self.sched = sched
		self.__isCopy = False

	def __del__(self):
		self.deallocate()

	def __getstate__(self):
		sched_save = self.sched
		del self.sched
		odict = self.__dict__.copy()
		self.sched= sched_save
		return odict

	def __setstate__(self, dict):
		"""
		This function is implemented to keep track of deepcopies.  If deepcopy is used,
		then this function will be used, and we'll ensure that the procs are set to
		empty.

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
		# Use the VizStack application execution wrapper to ensure cleanup when SSH
		# exits
		cmd_list = copy.copy(args)
		cmd_list = [ 'ssh' , node, '/opt/vizstack/bin/vs-aew' ] + cmd_list

		# NOTE: close_fds = True as we don't want the child to inherit our FDs and then 
		# choke other things ! e.g. the SSM will not clean up a connection if close_fds is not set to True
		proc = subprocess.Popen(cmd_list, stdout=outFile, stderr=errFile, stdin=inFile, close_fds=True, env=launcherEnv)
		return localscheduler.VizProcess(proc)

	def serializeToXML(self):
		return "<%s />"%(SSHReservation.rootNodeName)

	def deserializeFromXML(self, domNode):
		if domNode.nodeName != SSHReservation.rootNodeName:
			raise ValueError, "Failed to deserialize SSHReservation. Programmatic Error"

class SSHScheduler(scheduler.Scheduler):

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
		alloc = SSHReservation(self)
		self.allocations.append(alloc)
		return alloc

	def getUnusableNodes(self):
		return []

	def deallocate(self, allocObj):
		for idx in range(len(self.allocations)):
			if allocObj is self.allocations[idx]:
				self.allocations.pop(idx)
				return
		print "No such allocation was allocated by the SSHScheduler"
