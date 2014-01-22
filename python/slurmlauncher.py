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

import scheduler
import subprocess
import string
import launcher
import random
import sys
import slurmscheduler
import localscheduler
import domutil
import time
import copy

class SLURMLauncher(launcher.Launcher):

    rootNodeName = "SLURMReservation"

    def serializeToXML(self):
        ret = "<%s>"%(SLURMLauncher.rootNodeName)
        ret = ret + "%d"%(self.schedId)
        ret = ret + "</%s>"%(SLURMLauncher.rootNodeName)
        return ret

    def deserializeFromXML(self, domNode):
        if domNode.nodeName != SLURMLauncher.rootNodeName:
            raise ValueError, "Failed to deserialize SLURMLauncher. Programmatic error"

        try:
	        self.schedId = int(domutil.getValue(domNode))
        except ValueError, e:
            raise ValueError, "Failed to deserialize SLURMLauncher. Invalid scheduler ID '%s'"%(domutil.getValue(domNode))

        self.nodeList = None
        self.scheduler = None

    def __init__(self, schedId=None, nodeList=None, scheduler=None):
        self.__isCopy = False
        self.schedId = schedId
        # nodeList and scheduler will be None if this object is being deserialized
        # if this object is deserialized, then deleting this object, or calling its
        # deallocate function will not remove the allocation.
        self.nodeList = nodeList
        self.scheduler = scheduler

    def getSchedId(self):
        return self.schedId

    def __del__(self):
        # nodeList can be if we were deserialized
        # in this case, we don't delete the job!
        if (self.nodeList is not None) and (len(self.nodeList)>0): 
            self.deallocate()

    def __getstate__(self):
        sched_save = self.scheduler
        del self.scheduler
        odict = self.__dict__.copy()
	self.scheduler = sched_save
        return odict

    def __setstate__(self, dict):
        """
        This function is implemented to keep track of deepcopies.  If deepcopy is used,
        then this function will be used, and we keep track of the fact that this is a 
        copy.

        If isCopy is true, then the destructor will not remove the allocation.
        """
        self.__dict__.update(dict)
	self.scheduler = None
        self.__isCopy = True

    def getSchedId(self):
        return self.schedId

    def run(self, args, node, inFile=None, outFile=None, errFile=None, launcherEnv=None):
        slots = 1
        op_options = ""

	cmd_args = copy.copy(args)
	# Ensure SLURM does not redirect stdin if not needed. Not doing so
	# affects interactive processes started by user scripts.
	redirArgs = []
	if inFile is None:
		redirArgs = ["--input", "none"]
	cmd_args = ["srun", "--jobid=%d"%(self.schedId), "-w", node, "-N1"]+redirArgs+cmd_args
        try:
            # NOTE: set close_fds = True as we don't want the child to inherit our FDs and then 
            # choke other things ! e.g. the SSM will not clean up a connection if close_fds is not set to True
            p = subprocess.Popen(cmd_args, stdin=inFile, stdout=outFile, stderr=errFile, close_fds=True, env=launcherEnv)
        except OSError:
                return None

        return localscheduler.VizProcess(p)

    def deallocate(self):
        # If we're a copy, then we have not much to do
        if self.__isCopy == True:
            self.schedId = None
            return

        if self.schedId is None:
            return

        # Deallocate this SLURM Job
        # Note that this will kill all the job steps associated with the job
        try:
            p = subprocess.Popen(["scancel", str(self.schedId)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
        except OSError, e:
            raise SLURMError(e.__str__)

        # Let the command finish. We ignore any reported errors and expect SLURM to do the proper cleanup.
        p.communicate()

        if self.scheduler is not None:
            self.scheduler.deallocate(self)
            self.scheduler = None

        self.schedId = None

