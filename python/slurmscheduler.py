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
import resource
import string
import launcher
import random
import sys
import time
import slurmlauncher
import re
import vsutil

class SLURMError(Exception):
    def __init__(self, msg):
        self.msg = msg
    def __str__(self):
        return self.msg

class SLURMScheduler(scheduler.Scheduler):
    def __init__(self, nodeList, params):
        if len(nodeList)==0:
            raise ValueError, "I need one or more nodes to manage, you gave me none!"
	self.allocationInfo = {}
        self.launcher = None
        # FIXME: check if "params" is a valid name for a SLURM partition
	# Also check if the partition name is valid
        if params != "":
            self.partition = ["-p",params]
        else:
            self.partition = []

        self.nodeList = nodeList

        # check if SLURM considers these to be valid node(s)
        schedNodeList = self.__getAllNodes()
        for nodeName in self.nodeList:
            if nodeName not in schedNodeList:
                if len(self.partition)==0:
                    raise ValueError, "Node '%s' is not managed by SLURM"%(nodeName)
                else:
                    raise ValueError, "Node '%s' is NOT available in SLURM partition '%s'. Please check that both the node name and the partition name match your SLURM configuration."%(nodeName, params)

    def getNodeNames(self):
        return self.nodeList

    def __del__(self):
        # if some jobs allocated by us are still running, then kill em
        # all mercilessly !
        for jobId in self.allocationInfo.keys():
            jobObj = self.allocationInfo[jobId]   
            jobObj.deallocate() # this deletes keys from allocationInfo

        # NOTE: At this point, self.allocationInfo must be an empty dictionary

    def expand(self, nodes):
        node_list = []
        num_lst = []
        for i in nodes.lstrip(nodes.split("[")[0]).lstrip("[").rstrip("]").replace(',',' ').split(' '):
            if '-' in i:
                lst = eval("range(" + i.replace('-',',').split(',')[0] + "," + str(int(i.replace('-',',').split(',')[1]) + 1) + ")")
                num_lst = num_lst + lst
            else:
                num_lst = num_lst + [int(i)]
        for i in num_lst:
            node_list.append(nodes.split("[")[0] + str(i))
        return node_list

    def condense(self, res_list):
        return string.join(res_list, ',')

    def allocate(self, userId, groupId, res_list):
        for nodeName in res_list:
            if nodeName not in self.nodeList:
                raise ValueError, "Node '%s' is not managed by this SLURM instance"%(nodeName)
        nodestr = self.condense(res_list)
        try:
            # combine stderr with stdout
            p = subprocess.Popen(["salloc"]+["--uid=%d"%(userId), "-d 4", "--no-shell", "-I"] + self.partition + [ "-w", nodestr], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            messages = p.communicate()[0]
        except OSError,e :
            raise SLURMError(repr(e))
        if(p.returncode == 1):
            raise SLURMError(messages)

        schedId = int(messages.replace("salloc: Granted job allocation ",""))
        #schedId = self.__getJobId(jobName)
        if schedId == None:
            raise ValueError, "Invalid allocation id"%(schedId)
        
        self.launcher = slurmlauncher.SLURMLauncher(schedId, res_list, self)
        # Remember that we made this allocation.
        # This will come in handy during scheduler cleanup.
	self.allocationInfo[schedId] = self.launcher
        return self.launcher

    def deallocate(self, allocObj):
        if allocObj.__class__ is not slurmlauncher.SLURMLauncher:
            raise ValueError, "Bad allocation object passed. I'm expecting a SLURMLauncher"
        # If a job corresponding to this object does not exist, then we can only fail
        schedId = allocObj.getSchedId()
	if not self.allocationInfo.has_key(schedId):
            raise ValueError, "Invalid allocation id specified"%(schedId)
        # we're no longer tracking this...
        self.allocationInfo.pop(schedId)

    def expandHosts(self, slurmOutput):
        if not ('[' in slurmOutput):
            return [slurmOutput]
        ob = re.match('(.*)\[(.*)\]', slurmOutput)
        hostPrefix = ob.groups()[0]
        hostIndices = ob.groups()[1]
        #print hostPrefix, hostIndices
        expandedHostList = []
        for hostRange in hostIndices.split(","):
            rangeParts = hostRange.split("-")
            if len(rangeParts)==1:
                expandedHostList.append('%s%s'%(hostPrefix, rangeParts[0]))
            else:
                rangeFrom = int(rangeParts[0])
                rangeTo = int(rangeParts[1])
                for i in range(rangeFrom, rangeTo+1):
                    expandedHostList.append('%s%s'%(hostPrefix, i))
        return expandedHostList

    def __flatten(self,x):
        """flatten(sequence) -> list

        Returns a single, flat list which contains all elements retrieved
        from the sequence and all recursively contained sub-sequences
        (iterables).
        
        Examples:
        >>> [1, 2, [3,4], (5,6)]
        [1, 2, [3, 4], (5, 6)]
        >>> flatten([[[1,2,3], (42,None)], [4,5], [6], 7, MyVector(8,9,10)])
        [1, 2, 3, 42, None, 4, 5, 6, 7, 8, 9, 10]"""
        
        result = []
        for el in x:
            #if isinstance(el, (list, tuple)):
            if hasattr(el, "__iter__") and not isinstance(el, basestring):
                result.extend(self.__flatten(el))
            else:
                result.append(el)
        return result
    
    def __getAllNodes(self):
        try:
            p = subprocess.Popen(["sinfo", "-h" ] + self.partition + [ "-o", "%T %N"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError, e:
            raise slurmscheduler.SLURMError(repr(e))
        if(p.returncode == 1):
            raise slurmscheduler.SLURMError(p.communicate()[1])
        jobList = p.communicate()[0].rstrip().split("\n")
        allNodes = []
        for x in jobList:
            if len(x)>0:
                allNodes = allNodes + vsutil.expandNodes(x.split(" ")[1])
        allNodes = self.__flatten(allNodes)
        return allNodes

    def getUnusableNodes(self):
        """
		Returns the nodes which are unusable at this time.
		Nodes are managed by schedulers, and may come up or go down independent of VizStack.

		We use the information about the unusable nodes to restrict ourselves from allocating
		from those.
        """
        try:
            p = subprocess.Popen(["sinfo", "-h" ] + self.partition + [ "-o", "%T %N"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError, e:
            raise slurmscheduler.SLURMError(repr(e))
        if(p.returncode == 1):
            raise slurmscheduler.SLURMError(p.communicate()[1])
        jobList = p.communicate()[0].rstrip().split("\n")
        unusableNodes = []
        for x in jobList:
            if x.split(" ")[0] in ["drained", "down","down*","dranined*"]: # FIXME: Manju what is this "*" business ??
                unusableNodes.append(vsutil.expandNodes(x.split(" ")[1]))
        unusableNodes = self.__flatten(unusableNodes)
        return unusableNodes

#cmd="/bin/date"
#a = subprocess.Popen([cmd, "-d", "+1min", "+%s"], stdout=subprocess.PIPE).communicate()[0].rstrip()
#b = subprocess.Popen([cmd, "-d", "+1440min", "+%s"], stdout=subprocess.PIPE).communicate()[0].rstrip()


