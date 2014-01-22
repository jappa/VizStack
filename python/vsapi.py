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
VizStack Job API

"""

import socket
import os
import subprocess
from copy import deepcopy
from xml.dom import minidom
import xml
from pprint import pprint
import re
import domutil
import slurmlauncher
import localscheduler
import sshscheduler
import string
import copy
import sys

masterConfigFile = '/etc/vizstack/master_config.xml'
nodeConfigFile = '/etc/vizstack/node_config.xml'
rgConfigFile = '/etc/vizstack/resource_group_config.xml'
systemTemplateDir = '/opt/vizstack/share/templates/'
overrideTemplateDir = '/etc/vizstack/templates/'

SSM_UNIX_SOCKET_ADDRESS = "/tmp/vs-ssm-socket"
NORMAL_SERVER = "normal"
VIRTUAL_SERVER = "virtual"

VALID_SERVER_TYPES = [NORMAL_SERVER, VIRTUAL_SERVER]

#
# On a multi-GPU system, I had observed that trying to start multiple
# X servers at the same time resulted in a crash. The node would almost
# lock up.
#
# So, vs-X now limits the rate at which X servers start. Right now, this
# is about 5 seconds (look up vs-X.cpp).
#
# Given that a job can run a single X server for every GPU (and more later),
# we need to accomodate for this delay in the job startup.
# 
X_SERVER_DELAY = 5
MAX_GPUS_PER_SYSTEM = 8
X_WAIT_TIMEOUT = ((X_SERVER_DELAY+2)*2) * MAX_GPUS_PER_SYSTEM
X_WAIT_MAX = 600

def closeSocket(s):
	"""
	We need this to avoid TIME_WAIT states
	"""
	s.shutdown(socket.SHUT_RDWR)
	s.close()

def encode_message_with_auth(authType, msg):
	if authType!='Munge':
		raise "Only Munge supported at this time"

	# create a auth packet using munge with this content
	d = subprocess.Popen('munge', stdout=subprocess.PIPE, stdin=subprocess.PIPE)
	d.stdin.write(msg)
	d.stdin.close()
	payload = d.stdout.read()
	d.stdout.close()
	return payload

def decode_message_with_auth(authType, msg):

	if authType!='Munge':
		raise "Only Munge supported at this time"

	# decode the metadata & payload into separate files
	sp = subprocess.Popen('unmunge', stdout=subprocess.PIPE, stdin=subprocess.PIPE)
	sp.stdin.write(msg)
	sp.stdin.close()
	decoded = sp.stdout.readlines()
	errcode = sp.wait()

	if errcode != 0:
		return [errcode, None, None]

	# decoding succeeded, so get the metadata
	metadata = []
	for ln in range(len(decoded)):
		if len(decoded[ln])==1:
			metadata = decoded[:ln-1]
			message = string.join(decoded[ln+1:], "")
			break

	# We now have information about who connected to us
	userInfo = parse_munge_metadata(metadata)

	# Handle failure
	if userInfo['statusCode']!=0:
		errCode = userInfo.pop('statusCode')
		message = userInfo.pop('status')
		userInfo = None
	else:
		for key in userInfo.keys():
			if key not in ['uid','gid']:
				userInfo.pop(key)
		
	return [errcode, userInfo, message]

# parse_munge_metadata
#
# Convert the munge metadata (obtained via message decoding) into
# a dictionary format that's easier to use in code.
#
def parse_munge_metadata(metadata):
	# metadata is a list of strings
	# each string is of the following format 
	# FIELD:<spaces>value
	# The fields of interest to us are STATUS, UID & GID
	ret = {}
	for kvstr in metadata:
		spindex = kvstr.find(':') 
		key = kvstr[:spindex]
		value = string.strip(kvstr[spindex+1:])

		# parse the key into components
		if key=='UID':
			parts = value.split(' ')
			ret['user']=parts[0]
			ret['uid']=int(parts[1][1:-1])
		elif key=='GID':
			parts = value.split(' ')
			ret['gid']=int(parts[1][1:-1])
		elif key=='STATUS':
			parts = value.split(' ')
			statusCode=int(parts[1][1:-1])
			ret['status']=parts[0]
			ret['statusCode']=statusCode
		else:
			ret[key]=value
	return ret

class Schedulable:

	rootNodeName = "Schedulable"

	def __clearAll(self):
		self.__launcher = None
		self.locality = None

	def __init__(self, launcher=None, locality=None):
		self.__launcher = launcher
		self.locality = locality

	def run(self, args, inFile=None, outFile=None, errFile=None, launcherEnv=None):
		proc = self.__launcher.run(args, self.locality, inFile, outFile, errFile, launcherEnv)
		return proc

	def serializeToXML(self):
		ret = "<%s>"%(Schedulable.rootNodeName)
		ret += "<locality>%s</locality>"%(self.locality)
		ret += self.__launcher.serializeToXML()
		ret += "</%s>"%(Schedulable.rootNodeName)
		return ret

	def deserializeFromXML(self, domNode):
		self.__clearAll()
		if domNode.nodeName != Schedulable.rootNodeName:
			raise ValueError, "Failed to deserialize Schedulable. Programmatic Error"

		childNodes = domutil.getAllChildNodes(domNode)
		for node in childNodes:
			if node.nodeName == "locality":
				self.locality = domutil.getValue(node)
			else:
				for className in [localscheduler.LocalReservation, slurmlauncher.SLURMLauncher, sshscheduler.SSHReservation]:
					if node.nodeName == className.rootNodeName:
						# FIXME: ensure that there is only one of these!
						newObject = className()
						newObject.deserializeFromXML(node)
						self.__launcher = newObject
						break
				# FIXME : what about bad sched input ?

		if self.locality is None:
			raise ValueError, "Bad Deserialized Object: No locality was specified"

class VizError(Exception):
	INCORRECT_VALUE = 1
	UNIMPLEMENTED = 2
	RESOURCE_BUSY = 3
	BAD_RESOURCE = 4
	BAD_CONFIGURATION = 5
	RESOURCE_UNSPECIFIED = 6
	INTERNAL_ERROR = 7
	USER_ERROR = 8
	BAD_PROTOCOL = 9
	NOT_CONNECTED = 10
	RESOURCE_UNAVAILABLE = 11
	SOCKET_ERROR = 12
	BAD_OPERATION = 13
	ACCESS_DENIED = 14
	def __init__(self, errorCode, message):
		self.errorCode = errorCode
		self.message = message

	def __str__(self):
		return self.message


#
# The "resource" classes. Resource classes encapsulate the kind of resources that 
# are managed by VizStack. These are the ones that the application deals with as 
# well.
#

#
# resClass    index    resType
#
# GPU           2      "Quadro FX 5600"
# Keyboard      0      "DefaultKeyboard"
# Mouse         0      "DefaultMouse"
# Server        0      "normal"
# Server        1      "virtual"
# SLI           0      "discrete"
# SLI           0      "quadroplex"

class VizResource:
	"""
	Base class that represents visualization resources.
	Note that the methods of this base class may be overridden in the derived classes.
	"""
	def __init__(self, resIndex=None, hostName=None, resClass=None, resType=None):
		"""
		Initialize with a class name, resouce index and hostname and type.
		These are the three essential properties of every visualization resource.
		Class is the kind of resource. E.g. gpu, X Server, keyboard, mouse, etc
		Type is an important property from a user point of view. E.g., gpus of various
		types are available(FX5800, etc). X Servers can be of multiple types too,
		"regular" and "virtual". Keyboard and mouse may also come in various varieties.

		VizResources, by default, are not shared. If you want a shared object
		(typically GPU), you neet to set sharing to True.
		"""
		self.resClass = resClass
		self.resIndex = resIndex
		self.hostName = hostName
		self.resType = resType
		self.owners = []
		self.shared = False
		self.maxShareCount = 1
		self.allocationBias = 0

	def setShareLimit(self, count):
		"""
		Set the maximum number of times this object can be shared.
		"""
		if count<1:
			raise VizError(BAD_OPERATION, "Invalid share count")
		self.maxShareCount = count

	def getShareLimit(self):
		"""
		Return the maximum number of times this object can be shared.
		"""
		return self.maxShareCount

	def setShared(self, shared):
		"""
		Change the "shared" state of this object.
		"shared" can be True/False
		"""
		if not isinstance(shared, bool):
			raise TypeError, "Expected boolean, got %s"%(shared.__class__)

		self.shared = shared

	def __checkOwner(self, owner):
		# Linux-only for now, so we check for UID
		if owner is None:
			raise TypeError, "Expecting User ID, got None"
		if not isinstance(owner, int):
			raise TypeError, "Expecting integer User ID, got %s"%(owner.__class__)
		if owner<0:
			raise TypeError, "User ID cannot be negative"

	def addOwner(self, owner):
		"""
		Add the specific owner to the list of owners of this resource.
		"""
		self.__checkOwner(owner)
		self.owners.append(owner)

	def removeOwner(self, owner):
		"""
		Remove an owner from the ownership list. Note that an object
		can be owned by a user multiple times, and this will remove only
		one instance of ownership.
		"""
		self.__checkOwner(owner)
		try:
			self.owners.remove(owner)
		except ValueError, e:
			raise VizError(VizError.ACCESS_DENIED, "That user does not own this object")

	def getOwners(self):
		"""
		Return a list of owners for this object.
		"""
		return self.owners

	def isSharable(self):
		"""
		An resource is deemed sharable if its share count is >1.
		A sharable resource can be allocated either shared or exclusive.
		"""
		return (self.maxShareCount > 1)

	def isShared(self):
		"""
		Is this object allocated for shared use ?
		"""
		return self.shared

	def isExclusive(self):
		"""
		Is this object allocated for exclusive access ?
		Unshared => exclusive
		"""
		return not self.shared

	def isFree(self):
		"""
		Is this object free (completely or partially) ?
		An object that is allocated "shared" and still has room for allocating
		out of it is considered "free"
		"""
		if self.isShared():
			maxUsers = self.maxShareCount
		else:
			maxUsers = 1

		if len(self.owners)==maxUsers:
			return False

		return True
		
	def canAllocate(self, otherObject):
		"""
		Return true if "otherObject" can be allocated out of us.
		This takes care of sharing cases
		"""
		if not self.typeSearchMatch(otherObject):
			return False

		if not self.isFree():
			return False

		if otherObject.isShared() and (not self.isSharable()):
			return False

		if self.isShared() and (not otherObject.isShared()):
			return False

		return True

	def doAllocate(self, otherObject, userInfo):
		"""
		allocate otherObject out of this object.
		Add userInfo as one of the owners.
		"""
		if not self.canAllocate(otherObject):
			raise VizError(BAD_OPERATION, "Cant allocate")
		
		self.addOwner(userInfo)

		if otherObject.isShared():
			if self.maxShareCount>1: # Sharable ?
				self.shared = True

	def deallocate(self, otherObject, userInfo):
		"""
		deallocate otherObject from this object.
		Remove userInfo from the owner list.
		"""
		self.removeOwner(userInfo)

		# reset to unshared. Note: there's no provision here to have
		# shared-only objects	
		if len(self.owners)==0:
			self.shared = False

	def getType(self):
		"""
		Return the type of this resource
		"""
		return self.resType

	def hashKey(self):
		"""
		Compute a hash key. This is used for easily searching this resource in
		a hash table.
		"""
		return "%s-%d at host %s"%(self.resClass, self.resIndex, self.hostName)

	def __str__(self):
		return '<%s-%s at host %s>'%(self.resClass, self.resIndex, self.hostName)

	def __repr__(self):
		return self.__str__()

	def isCompletelyResolvable(self):
		"""
		A resource is considered completely resolvalble if it has a hostname and index
		that are valid.
		"""
		if (self.resIndex is not None) and (self.hostName is not None):
			return True
		return False

	def getAllocationWeight(self):
		"""
		Returns a weight to be used by the allocation algorithm.
		"""
		wt = self.allocationBias

		if self.resIndex is not None:
			wt += self.resIndex

		return wt

	def getAllocationBias(self):
		return self.allocationBias

	def setAllocationBias(self, bias):
		"""
		Set a 'bias' value for allocation. This allows for fine tweaking of
		resource allocation.
		"""
		if not isinstance(bias, int):
			raise TypeError, "Expected integer weight, got %s"%(bias.__class__)
		self.allocationBias = bias

	def getAllocationDOF(self):
		"""
		Returns the "degrees of freedom" an allocator has while allocating this resource.
		The degree of freedom is a non-negative integer value, and is
		    - 0 if both hostname and index are specified
		    - 1 if only the index is specified
		    - 2 if only the hostname is specified
		    - 3 if neither hostname nor index are specified.

		The DOF value is used while allocating resources, primarily to decide the order to
		allocate resources.
		"""

		ret = 0
		if self.resIndex is not None:
			ret += 2
		if self.hostName is not None:
			ret += 1
		return (3-ret)

	def typeSearchMatch(self, otherRes):
		"""
		Method used to match two resources in a search context.
		if otherRes has specified search items that aren't in us, then we fail.
		Else we pass
		"""
		if not isinstance(otherRes, VizResource):
			raise ValueError, "%s : You're trying to compare apples(%s) to trees(%s), my friend!"%(self.resClass, self, otherRes)

		if otherRes.resClass != self.resClass:
			return False

		if otherRes.resIndex is not None:
			if self.resIndex is None:
				return False
			if self.resIndex != otherRes.resIndex:
				return False

		if otherRes.resType is not None:
			if self.resType is None:
				return False
			if self.resType != otherRes.resType:
				return False
		
		if otherRes.hostName is not None:
			if self.hostName is None:
				return False
			if self.hostName != otherRes.hostName:
				return False

		if (otherRes.isShared()) and (not self.isSharable()):
			return False

		return True

	def refersToTheSame(self, otherRes, knownApplesToOranges=False):
		"""
		Does this resource refer to the same thing as the other resource ?
		"""
		if not isinstance(otherRes, VizResource):
			raise ValueError, "%s : You're trying to compare apples(%s) to trees(%s), my friend!"%(self.resClass, self.resClass, otherRes)
		if otherRes.resClass != self.resClass:
			if knownApplesToOranges:
				return False
			raise ValueError, "%s : You're trying to compare apples(%s) and oranges(%s), my friend!"%(self.resClass, self.resClass, otherRes.resClass)

		if ( otherRes.resIndex == self.resIndex ) and (otherRes.hostName == self.hostName):
			return True

		return False

	def isSchedulable(self):
		"""
		Is this resource schedulable ?
		"""
		return False

	def getSchedulable(self):
		"""
		Return the schedulable for this resource. None is returned if there is no scheduler associated.
		"""
		return None

	def run(self, args, inFile=None, outFile=None, errFile=None, launcherEnv=None):
		"""
		Run a command on this resource.
		You may optionally specify the standard input, output and error streams for the child process. 
		These are standard python file objects.
		"""
		raise NotImplementedError, "VizResource of type %s - can't run anything on this!"%(self.resClass)

	def getHostName(self):
		"""
		Return the hostname where this resource is valid.
		"""
		return self.hostName

	def setHostName(self, newName):
		"""
		Changes the host where this resource resides.
		"""
		self.hostName = newName

	def getIndex(self):
		"""
		Return the index of this resource.
		"""
		return self.resIndex

	def setIndex(self, newIndex):
		"""
		Set the index of this resource
		"""
		self.resIndex = newIndex

	def serializeToXML(self, detailedConfig=True, addrOnly=False):
		"""
		Serialize this resource into an XML format. The base class implementation
		serializes only some of the info.
		"""
		ret = ""
		if not addrOnly:
			for owner in self.owners:
				 ret = ret + "<owner>%d</owner>"%(owner)
			ret = ret + "<maxShareCount>%d</maxShareCount>"%(self.maxShareCount)
			ret = ret + "<shared>%d</shared>"%(self.shared)
			if self.allocationBias is not None:
				ret += "<allocationBias>%s</allocationBias>"%(self.allocationBias)
		return ret

	def deserializeFromXML(self, domNode):
		"""
		Restore the state of this resource from a DOM tree
		"""
		ownerNodes = domutil.getChildNodes(domNode, "owner")
		self.owners = []
		for ownerNode in ownerNodes:
			self.addOwner(int(domutil.getValue(ownerNode)))

		node = domutil.getChildNode(domNode, "maxShareCount")
		if node is not None:
			self.maxShareCount = int(domutil.getValue(node))
		else:	
			self.maxShareCount = 1
		if self.maxShareCount < 1:
			raise ValueError, "Failed to deserialize. Invalid maxShareCount."

		node = domutil.getChildNode(domNode, "shared")
		if node is not None:
			self.shared = bool(int(domutil.getValue(node)))
		else:
			self.shared = False

		node = domutil.getChildNode(domNode, "allocationBias")
		if node is not None:
			self.allocationBias = int(domutil.getValue(node))

class Keyboard(VizResource):
	"""
	Keyboard resource class.
	"""
	rootNodeName = "keyboard"

	def __clearAll(self):
		self.resIndex = None
		self.hostName = None
		self.resType = None
		self.physAddr = None
		self.driver = None
		self.options = []

	def __init__(self, resIndex=None, hostName=None,keyboardType=None, physAddr=None):
		VizResource.__init__(self)

		self.resClass = "Keyboard"
		self.__clearAll()
		self.resIndex = resIndex
		self.hostName = hostName
		self.resType = keyboardType
		self.physAddr = physAddr

	def getPhysAddr(self):
		return self.physAddr

	def serializeToXML(self, detailedConfig = True, addrOnly=False):
		ret = "<%s>"%(Keyboard.rootNodeName)
		ret += VizResource.serializeToXML(self, detailedConfig, addrOnly)
		if self.resIndex is not None: ret = ret + "<index>%d</index>"%(self.resIndex)
		if self.hostName is not None: ret = ret + "<hostname>%s</hostname>"%(self.hostName)
		if not addrOnly:
			if self.resType is not None: ret = ret + "<type>%s</type>"%(self.resType)
			if self.driver is not None: ret = ret + "<driver>%s</driver>"%(self.driver)
			for opt in self.options:
				ret = ret + "<option><name>%s</name><value>%s</value></option>"%(opt['name'],opt['value'])
			if self.physAddr is not None: ret = ret + "<phys_addr>%s</phys_addr>"%(self.physAddr)
		ret += "</%s>"%(Keyboard.rootNodeName)
		return ret

	def deserializeFromXML(self, domNode):
		if domNode.nodeName != Keyboard.rootNodeName:
			raise ValueError, "Failed to deserialize Keyboard. Incorrect deserialization attempt."

		self.__clearAll()

		# Deserialize the base class info
		VizResource.deserializeFromXML(self, domNode)

		hostNameNode = domutil.getChildNode(domNode, "hostname")
		if hostNameNode is not None:
			self.hostName = domutil.getValue(hostNameNode)

		indexNode = domutil.getChildNode(domNode, "index")
		if indexNode is not None:
			self.resIndex = int(domutil.getValue(indexNode))

		typeNode = domutil.getChildNode(domNode, "type")
		if typeNode is not None:
			self.resType = domutil.getValue(typeNode)

		driverNode = domutil.getChildNode(domNode, "driver")
		if driverNode is not None:
			self.driver = domutil.getValue(driverNode)

		optNodes = domutil.getChildNodes(domNode, "option")
		for optNode in optNodes:
			opt = {}
			optName = domutil.getValue(domutil.getChildNode(optNode, "name"))
			optVal = domutil.getValue(domutil.getChildNode(optNode, "value"))
			opt['name']=optName
			opt['value']=optVal
			self.options.append(opt)
			self.driver = domutil.getValue(driverNode)

		physNode = domutil.getChildNode(domNode, "phys_addr")
		if physNode is not None:
			self.physAddr = domutil.getValue(physNode)

class Mouse(VizResource):
	"""
	Mouse resource class.
	"""
	rootNodeName = "mouse"

	def __clearAll(self):
		self.resIndex = None
		self.hostName = None
		self.resType = None
		self.physAddr = None
		self.driver = None
		self.options = []

	def __init__(self, resIndex=None, hostName=None,mouseType=None, physAddr=None):
		VizResource.__init__(self)
		self.resClass = "Mouse"
		self.__clearAll()
		self.resIndex = resIndex
		self.hostName = hostName
		self.resType = mouseType
		self.physAddr = physAddr

	def getPhysAddr(self):
		return self.physAddr

	def serializeToXML(self, detailedConfig = True, addrOnly=False):
		ret = "<%s>"%(Mouse.rootNodeName)
		ret += VizResource.serializeToXML(self, detailedConfig, addrOnly)
		if self.resIndex is not None: ret = ret + "<index>%d</index>"%(self.resIndex)
		if self.hostName is not None: ret = ret + "<hostname>%s</hostname>"%(self.hostName)
		if not addrOnly:
			if self.resType is not None: ret = ret + "<type>%s</type>"%(self.resType)
			if self.driver is not None: ret = ret + "<driver>%s</driver>"%(self.driver)
			for opt in self.options:
				ret = ret + "<option><name>%s</name><value>%s</value></option>"%(opt['name'],opt['value'])
			if self.physAddr is not None: ret = ret + "<phys_addr>%s</phys_addr>"%(self.physAddr)
		ret += "</%s>"%(Mouse.rootNodeName)
		return ret

	def deserializeFromXML(self, domNode):
		if domNode.nodeName != Mouse.rootNodeName:
			raise ValueError, "Failed to deserialize Keyboard. Incorrect deserialization attempt."

		self.__clearAll()

		# Deserialize the base class info
		VizResource.deserializeFromXML(self, domNode)

		hostNameNode = domutil.getChildNode(domNode, "hostname")
		if hostNameNode is not None:
			self.hostName = domutil.getValue(hostNameNode)

		indexNode = domutil.getChildNode(domNode, "index")
		if indexNode is not None:
			self.resIndex = int(domutil.getValue(indexNode))

		typeNode = domutil.getChildNode(domNode, "type")
		if typeNode is not None:
			self.resType = domutil.getValue(typeNode)

		driverNode = domutil.getChildNode(domNode, "driver")
		if driverNode is not None:
			self.driver = domutil.getValue(driverNode)

		optNodes = domutil.getChildNodes(domNode, "option")
		for optNode in optNodes:
			opt = {}
			optName = domutil.getValue(domutil.getChildNode(optNode, "name"))
			optVal = domutil.getValue(domutil.getChildNode(optNode, "value"))
			opt['name']=optName
			opt['value']=optVal
			self.options.append(opt)
			self.driver = domutil.getValue(driverNode)

		physNode = domutil.getChildNode(domNode, "phys_addr")
		if physNode is not None:
			self.physAddr = domutil.getValue(physNode)

# Resource Aggregates

# resClass       index    resType
#
# ResourceGroup    ?      "TiledDisplay"
# Node             ?      "Proliant DL160 G5"


class VizResourceAggregate(VizResource):
	"""
	Aggregate of Viz Resources. This has the same root properties - resClass, resIndex and resType
	Additionally, it implements a getResources().

	Calling some functions on the aggregates is considered an Error -
	e.g., getAllocationDOF()
	"""
	def getResources(self):
		"""
		Get the list of resources that are included in this resource aggregate.
		"""
		raise UnimplementedError, "getResources() needs to be implemented in the derived class"

	def setResources(self, resources):
		"""
		Sets the list of resources inside this aggregate to 'resources'
		"""
		raise UnimplementedError, "setResources() needs to be implemented in the derived class"

	def getAllocationDOF(self):
		"""
		This inherited method from VizResource must not be called by anyone. This method
		implementation exists to fail any such attempt.
		"""
		raise "getAllocationDOF must not be called for this class"

class DisplayDevice(VizResource):
	rootNodeName = "display"

	def __str__(self):
		return self.__repr__()

	def __repr__(self):
		ret = "<Display Device '"
		if self.resType is None:
			ret = ret + "<undefined>"
		else:
			ret = ret + "%s"%(self.resType)
		ret += "' at index "
		if self.resIndex is None:
			ret = ret + "<undefined>"
		else:
			ret = ret + "%d"%(self.resIndex)
		ret = ret + " at host "
		if self.hostName is None:
			ret = ret + "<undefined>"
		else:
			ret = ret + "%s"%(self.hostName)

		ret = ret + " >"
		return ret

	def __clearAll(self):
		self.resIndex = None
		self.resType = None
		self.hostName = None

		self.input = None
		self.edid = None
		self.edidBytes = None
		self.edid_name = None
		self.hsync_min = None
		self.hsync_max = None
		self.vrefresh_min = None
		self.vrefresh_max = None
		self.default_mode = None
		self.modes = []

		self.dimensions = None # Dimensions of the display. Two element [w,h]
		self.bezel = None # Bezel - four elements [left, right, bottom, top]

	def getDimensions(self):
		"""
		Get the physical dimensions of this display device (width, height)	
		in millimeters
		"""
		return self.dimensions

	def setDimensions(self, dimensions):
		"""
		Set the physical dimensions of this display device (width, height)
		in millimeters
		"""
		if dimensions is None:
			self.dimensions = None
			return

		if not isinstance(dimensions, list):
			raise TypeError, "Expect a list"

		if len(dimensions)!=2:
			raise ValueError, "Expect a two element list. Got %s"%(dimensions)

		for dim in dimensions:
			if isinstance(dim, int) or isinstance(dim, float) or isinstance(dim, long):
				if dim<0:
					raise ValueError, "Dimension(%s) cannot be negative"%(dim)
			else:
				raise TypeError, "Dimension(%s) has be a number"%(dim)

		self.dimensions = dimensions

	def getEDIDDisplayName(self):
		"""
		Return the name by which the display identifies itself in the EDID
		Returns None of the display has no EDID.
		"""
		return self.edid_name

	def getBezel(self):
		return self.bezel

	def setBezel(self, bezel):
		if bezel is None:
			self.bezel = None
			return

		if not isinstance(bezel, list):
			raise TypeError, "Expect a list"

		if len(bezel)!=4:
			raise ValueError, "Expect a four element list. Got %s"%(bezel)

		for val in bezel:
			if isinstance(val, int) or isinstance(val, float) or isinstance(val, long):
				if val<0:
					raise ValueError, "Bezel dimension(%s) cannot be negative"%(val)
			else:
				raise TypeError, "Bezel dimension(%s) has be a number"%(val)

		self.bezel = bezel

	def getInput(self):
		return self.input

	def setEDIDDisplayName(self, name):
		self.edid_name = name

	def setEDIDBytes(self, value):
		self.edidBytes = value

	def getEDIDBytes(self):
		return self.edidBytes

	def setHSyncRange(self, value):
		self.hsync_min = value[0]
		self.hsync_max = value[1]

	def setVRefreshRange(self, value):
		self.vrefresh_min = value[0]
		self.vrefresh_max = value[1]

	def getHSyncRange(self):
		return [self.hsync_min, self.hsync_max]

	def getVRefreshRange(self):
		return [self.vrefresh_min, self.vrefresh_max]

	def getAllModes(self):
		return deepcopy(self.modes)

	def isValid(self):
		if self.resType is None:
			return False
		if len(self.modes)==0:
			return False
		if self.default_mode is None:
			return False
		return True

	def getModeByAlias(self, alias):
		"""
		Returns the mode that is supported by this Display Device, 
		and known by the specified alias.
		"""
		for thisMode in self.modes:
			if alias == thisMode['alias']:
				return thisMode

		raise ValueError, "Did not find a mode matching '%s'"%(alias)

	def getDefaultMode(self):
		"""
		Returns the "default" mode for this display device.

		
		"""

		if self.default_mode is None:
			# If this _ever_ shows up, then we have a bug !
			raise ValueError, "No default mode has been assigned for this device"

		# Search for the default mode and return it.
		for thisMode in self.modes:
			if self.default_mode == thisMode['alias']:
				return thisMode

		raise ValueError, "Did not find a matching default mode. A default mode is assigned, but not defined for the display device."

	def findBestMatchingMode(self, searchParams):
		"""
		Find the mode that best matches the search parameters.

		searchParams may be a 2 or 3 item list. The following two inputs are supported:
		[ width, height ] => search for a mode with this width or height
		[ width, height, refresh_rate ] => search for a mode with specified width, height and refresh rate

		This function goes through the list of modes supported by this device,
		and chooses a single mode.

		1. If the refresh rate is not specified in the input, then the
		   mode matching the width & height and having the maximum refresh
		   rate is chosen. 

		2. If the refresh rate is specified, then the mode which matches
		   all three parameters is returned.

		Note that this function returns the information for the chosen mode as a dictionary. 
		Raises ValueError if no matching mode can be found.
		"""

		if not isinstance(searchParams, list):
			raise TypeError, "findBestMatchingMode: Expected list of [width,height[,refresh]], got a %s"%(searchParams.__class__)
		if len(searchParams)<2 or len(searchParams)>3:
			raise ValueError, "findBestMatchingMode: search mode must adhere to format [width,height[,refresh]]. You passed: %s"%(searchParams)

		bestRefreshRate = 0
		bestMatchingMode = None
		float_tolerance = 0.0001
		for thisMode in self.modes:
			if thisMode['width']!=searchParams[0] or thisMode['height']!=searchParams[1]:
				continue
			if len(searchParams)==3:
				if float(thisMode['refresh']-searchParams[3])<=float_tolerance:
					return thisMode['alias']
			if float(thisMode['refresh'])>bestRefreshRate:
				bestMatchingMode = thisMode
				bestRefreshRate = float(thisMode['refresh'])

		if bestMatchingMode is None:
			raise ValueError, "Can't find a matching mode"

		return bestMatchingMode
				
	def __init__(self, model=None):
		VizResource.__init__(self)
		self.__clearAll()
		self.resClass = DisplayDevice.rootNodeName
		self.resType = model

	def serializeToXML(self, detailedConfig=True, addrOnly=False):
		ret = "<%s>"%(DisplayDevice.rootNodeName)
		if self.resType is not None:
			ret += "<model>%s</model>"%(self.resType)
		if self.input is not None:
			ret += "<input>%s</input>"%(self.input)
		if self.edid is not None:
			ret += "<edid>%s</edid>"%(self.edid)
		if self.edidBytes is not None:
			ret += "<edidBytes>%s</edidBytes>"%(self.edidBytes)
		if self.edid_name is not None:
			ret += "<edid_name>%s</edid_name>"%(self.edid_name)
		if (self.hsync_min is not None) or (self.hsync_max is not None):
			ret += "<hsync>"
			if self.hsync_min is not None:
				ret += "<min>%s</min>"%(self.hsync_min)
			if self.hsync_max is not None:
				ret += "<max>%s</max>"%(self.hsync_max)
			ret += "</hsync>"
		if (self.vrefresh_min is not None) or (self.vrefresh_max is not None):
			ret += "<vrefresh>"
			if self.vrefresh_min is not None:
				ret += "<min>%s</min>"%(self.vrefresh_min)
			if self.vrefresh_max is not None:
				ret += "<max>%s</max>"%(self.vrefresh_max)
			ret += "</vrefresh>"
		if self.dimensions is not None:
			ret += "<dimensions>"
			ret += "<width>%f</width>"%(self.dimensions[0])
			ret += "<height>%f</height>"%(self.dimensions[1])
			if self.bezel is not None:
				ret += "<bezel>"
				ret += "<left>%f</left>"%(self.bezel['left'])
				ret += "<right>%f</right>"%(self.bezel['right'])
				ret += "<bottom>%f</bottom>"%(self.bezel['bottom'])
				ret += "<top>%f</top>"%(self.bezel['top'])
				ret += "</bezel>"
			ret += "</dimensions>"
		if self.default_mode is not None:
			ret += "<default_mode>%s</default_mode>"%(self.default_mode)
		for thisMode in self.modes:
			ret += "<mode>"
			ret += "<type>%s</type>"%(thisMode['type'])
			ret += "<alias>%s</alias>"%(thisMode['alias'])
			ret += "<width>%d</width>"%(thisMode['width'])
			ret += "<height>%d</height>"%(thisMode['height'])
			ret += "<refresh>%s</refresh>"%(thisMode['refresh'])
			if thisMode['value'] is not None:
				ret += "<value>%s</value>"%(thisMode['value'])
			# Serialize the bezel info for this mode. Note that
			# values not provided in the config file can end up
			# defined here as a result of computation
			if thisMode.has_key('bezel'):
				ret += "<bezel>"
				for bpos in ['left','right','bottom','top']:
					if thisMode['bezel'].has_key(bpos):
						ret += "<%s>%d</%s>"%(bpos, thisMode['bezel'][bpos], bpos)
				ret += "</bezel>"
			ret += "</mode>"

		ret += "</%s>"%(DisplayDevice.rootNodeName)

		return ret

	def addMode(self, modeType, modeAlias, modeWidth, modeHeight, modeRefresh, modeValue=None):
		# Parameter validation
		# mode width must be a multiple of 8
		if (modeWidth%8)!=0:
			raise ValueError, "Display mode width(%d) must be a multiple of 8"%(modeWidth)

		if self.modes is None:
			self.modes = []
		thisMode = {}
		thisMode['type'] = modeType
		thisMode['alias'] = modeAlias
		thisMode['width'] = modeWidth
		thisMode['height'] = modeHeight
		thisMode['refresh'] = modeRefresh
		thisMode['value'] = modeValue
		self.modes.append(thisMode)

	def setInput(self, inputType):
		if inputType not in GPU.ScanTypes:
			raise ValueError, "Incorrect inputType '%s'. Expected one of %s"%(inputType, GPU.ScanTypes)
		self.input = inputType

	def setDefaultMode(self, mode):
		self.default_mode = mode

	def getEDIDFileName(self):
		return self.edid

	def setEDIDFileName(self, fname):
		self.edid = fname

	def deserializeFromXML(self, domNode):
		self.__clearAll()
		if domNode.nodeName != DisplayDevice.rootNodeName:
			raise ValueError, "Failed to deserialize DisplayDevice. Incorrect deserialization attempt."

		# FIXME: do validation in the code below!
		tNode = domutil.getChildNode(domNode, 'model')
		if tNode is not None:
			self.resType = domutil.getValue(tNode)
		tNode = domutil.getChildNode(domNode, 'input')
		if tNode is not None:
			self.input = domutil.getValue(tNode)
		tNode = domutil.getChildNode(domNode, 'edid')
		if tNode is not None:
			self.edid = domutil.getValue(tNode)
		tNode = domutil.getChildNode(domNode, 'edidBytes')
		if tNode is not None:
			self.edidBytes = domutil.getValue(tNode)
		tNode = domutil.getChildNode(domNode, 'edid_name')
		if tNode is not None:
			self.edid_name = domutil.getValue(tNode)
		tNode = domutil.getChildNode(domNode, 'hsync')
		if tNode is not None:
			minNode = domutil.getChildNode(tNode, 'min')
			self.hsync_min = domutil.getValue(minNode)
			maxNode = domutil.getChildNode(tNode, 'max')
			self.hsync_max = domutil.getValue(maxNode)
		tNode = domutil.getChildNode(domNode, 'vrefresh')
		if tNode is not None:
			minNode = domutil.getChildNode(tNode, 'min')
			self.vrefresh_min = domutil.getValue(minNode)
			maxNode = domutil.getChildNode(tNode, 'max')
			self.vrefresh_max = domutil.getValue(maxNode)
		tNode = domutil.getChildNode(domNode, 'dimensions')
		if tNode is not None:
			widthNode = domutil.getChildNode(tNode, 'width')
			heightNode = domutil.getChildNode(tNode, 'height')
			self.dimensions = [ float(domutil.getValue(widthNode)), float(domutil.getValue(heightNode))]
			tNode = domutil.getChildNode(tNode, "bezel")
			if tNode is not None:
				leftNode = domutil.getChildNode(tNode, 'left')
				rightNode = domutil.getChildNode(tNode, 'right')
				bottomNode = domutil.getChildNode(tNode, 'bottom')
				topNode = domutil.getChildNode(tNode, 'top')
				self.bezel = {'left': float(domutil.getValue(leftNode)), 'right':float(domutil.getValue(rightNode)),'bottom':float(domutil.getValue(bottomNode)), 'top':float(domutil.getValue(topNode))}
		tNode = domutil.getChildNode(domNode, 'default_mode')
		if tNode is not None:
			self.default_mode = domutil.getValue(tNode)
		vModes = domutil.getChildNodes(domNode, 'mode')
		for modeNode in vModes:
			thisMode = {}
			tNode = domutil.getChildNode(modeNode, 'type')
			thisMode['type'] = domutil.getValue(tNode)
			tNode = domutil.getChildNode(modeNode, 'width')
			thisMode['width'] = int(domutil.getValue(tNode))
			tNode = domutil.getChildNode(modeNode, 'height')
			thisMode['height'] = int(domutil.getValue(tNode))
			tNode = domutil.getChildNode(modeNode, 'refresh')
			thisMode['refresh'] = domutil.getValue(tNode)
			tNode = domutil.getChildNode(modeNode, 'value')
			if tNode is not None:
				thisMode['value'] = domutil.getValue(tNode)
			else:
				thisMode['value'] = None

			# Compute the bezel
			thisMode['bezel'] = {'left':0, 'right':0, 'bottom':0, 'top':0}
			# If dimensions and bezel both are specified, then we can compute
			# the bezel size in pixels, given the resolution
			# more than half a pixel sends the bezel over the the higher value
			if (self.dimensions is not None) and (self.bezel is not None):
				hDPMM = thisMode['width']/self.dimensions[0] # dots per mm
				vDPMM = thisMode['height']/self.dimensions[1] # dots per mm
				for bpos in ['left','right']:
					if self.bezel[bpos] is not None:
						thisMode['bezel'][bpos] = int((hDPMM*self.bezel[bpos])+0.5) 
				for bpos in ['bottom','top']:
					if self.bezel[bpos] is not None:
						thisMode['bezel'][bpos] = int((vDPMM*self.bezel[bpos])+0.5)

			# Override with any bezel values given
			tNode = domutil.getChildNode(modeNode, 'bezel')
			if tNode is not None:
				for bpos in ['left','right', 'bottom','top']:
					bpNode = domutil.getChildNode(tNode, bpos)
					if bpNode is not None:
						thisMode['bezel'][bpos] = int(domutil.getValue(bpNode))
				
			# We replicate this mode multiple times
			for tNode in domutil.getChildNodes(modeNode, 'alias'):
				thisMode['alias'] = domutil.getValue(tNode)
				self.modes.append(deepcopy(thisMode))

		# FIXME: validation needed here. What if two or more modes
		# have the same resolution and refresh rate. Should we allow
		# this ? should we ignore this ?
		# We need to disallow usage of the same "alias" multiple
		# times. We need to enforce default - if we find modes.

class GPU(VizResource):
	"""
	GPU resource class
	"""

	rootNodeName = "gpu"

	ScanTypes = ["digital", "analog"]

	def __clearAll(self):
		self.resIndex = None 
		self.busID = None
		self.resType = None
		self.hostName = None
		self.scanout = { }
		self.schedulable = None

		# GPUs, by default, don't have a preference about using a scanout
		self.useScanOut = None
		self.allowNoScanOut = True # GPUs support 'noscanout', unless mentioned otherwise
		self.allowStereo = None

		# properties from the GPU template
		# resType => model
		self.vendor = None
		self.scanoutCaps = None
		self.max_width = None
		self.max_height = None

		# Optional resource access for validation
		self.ra = None

		# Not shared by default
		self.sharedServer = Server()
		self.sharedServer.setShared(True)
		self.sharedServerIndex = None

	def __str__(self):
		return self.__repr__()

	def __repr__(self):
		ret = "<GPU-"
		if self.resIndex is None:
			ret = ret + "<location undefined>"
		else:
			ret = ret + "%d"%(self.resIndex)
		ret = ret + " at host "
		if self.hostName is None:
			ret = ret + "<undefined>"
		else:
			ret = ret + "%s"%(self.hostName)

		ret = ret + " model "
		if self.resType is None:
			ret = ret + "<undefined>"
		else:
			ret = ret + "%s"%(self.resType)

		ret = ret + " bus location "
		if self.busID is None:
			ret = ret + "<undefined>"
		else:
			ret = ret + "%s"%(self.busID)

		if self.isSharable():
			ret = ret + " sharable maxCount=%d"%(self.maxShareCount)

		if self.isShared():
			ret = ret + " shared"

		if self.getAllowStereo():
			ret = ret + " stereo"
		ret = ret + " >"
		return ret

	def setBusId(self, busID):
		self.busID = busID

	def getBusId(self):
		return self.busID

	def isSchedulable(self):
		return True

	def run(self, args, inFile=None, outFile=None, errFile=None, launcherEnv=None):
		if self.schedulable is None:
			raise VizError(VizError.INVALID_OPERATION, "Cannot run() on a GPU which is not scheduled!")
		cmd_args = copy.copy(args)
		cmd_args = ["/usr/bin/env", "GPU_INDEX=%d"%(self.resIndex)]+cmd_args
		return self.schedulable.run(cmd_args, inFile, outFile, errFile, launcherEnv)

	def doAllocate(self, otherObject, userInfo):
		"""
		On allocation, we need to add the owner of the
		allocation as an owner of the X server
		"""
		VizResource.doAllocate(self, otherObject, userInfo)
		self.sharedServer.addOwner(userInfo)
		#print 'Post addition, owners for shared GPU %s are : %s. Added owner=%s'%(self.hashKey(), self.sharedServer.getOwners(), userInfo)

	def deallocate(self, otherObject, userInfo):
		"""
		On deallocation, we need to remove the owner of the
		allocation from the list of owners of the X server
		"""
		#print 'Pre removal, owners for shared GPU %s are : %s. Removed owner = %s'%(self.hashKey(), self.sharedServer.getOwners(), userInfo)
		self.sharedServer.removeOwner(userInfo)
		VizResource.deallocate(self, otherObject, userInfo)

	def setShareLimit(self, shareCount):
		VizResource.setShareLimit(self, shareCount)
		self.sharedServer.setShareLimit(shareCount)

	def getSharedServer(self):
		return self.sharedServer

	def getSharedServerIndex(self):
		return self.sharedServerIndex

	def setSharedServerIndex(self, serverIndex):
		"""
		Set the index of the shared server associated with this GPU.
		"""
		self.sharedServerIndex = serverIndex
		self.sharedServer.setShared(True)
		self.sharedServer.setHostName(self.getHostName())
		self.sharedServer.setShareLimit(self.getShareLimit())
		self.sharedServer.setIndex(self.sharedServerIndex)

	def __init__(self, resIndex=None, hostName = None, model=None, busID=None, useScanOut=None, isShared=False):
		VizResource.__init__(self)
		self.resClass = "GPU"
		self.__clearAll()

		if (busID is not None) and (not isinstance(busID, str)):
			raise TypeError, "Expected string busID"

		if (hostName is not None) and (not isinstance(hostName, str)):
			raise TypeError, "Expected string hostName"

		if (resIndex is not None) and (not isinstance(resIndex, int)):
			raise TypeError, "Expected integer resIndex"

		if (model is not None) and (not isinstance(model, str)):
			raise TypeError, "Expected string model"

		if (useScanOut is not None) and (not isinstance(useScanOut, bool)):
			raise TypeError, "Expected boolean useScanOut"

		self.resIndex = resIndex # The index of the GPU
		self.busID = busID       # The PCI BusID
		self.resType = model         # Model Name of the GPU - e.g. Quadro FX 5800
		self.hostName = hostName   # Hostname on which this GPU exists.
		self.useScanOut = useScanOut
		self.setShared(isShared)

	def typeSearchMatch(self, otherRes):
		"""
		Method used to match two resources in a search context.
		if otherRes has specified search items that aren't in us, then we fail.
		Else we pass

		NOTE: this overrides the base class (i.e. VizResource) to allow for
		people to either ask for scanout(1), or not ask for it(0), or say "I don't
		care about scanout"(None)

		"""
		if not VizResource.typeSearchMatch(self, otherRes):
			return False

		if otherRes.useScanOut is not None:
			# if useScanOut == 1, then the GPU needs to have scanouts capabilityto
			# be considered matching
			if (otherRes.useScanOut==1) and (self.scanoutCaps is not None) and (self.useScanOut==1):
				return True
			# if useScanOut == 0, then the GPU must _not_ have scanout capability to
			# be considered matching
			elif (otherRes.useScanOut==0) and ((self.scanoutCaps is None) or (self.useScanOut==0)):
				return True
			# to treat scanout or no scanout as "don't care", set it to
			# None (i.e. the default value)
			return False

		if otherRes.allowStereo is not None:
			# If stereo is required, and we don't have it, then we fail.
			if (self.allowStereo==False) and (otherRes.allowStereo==True):
				return False

		return True

	def setUseScanOut(self, useScanOut):
		"""
		Change scanout usage settings

		FIXME: change the name of this function ??
		"""
		if (useScanOut is not None) and (not isinstance(useScanOut, bool)):
			raise TypeError, "Expected boolean useScanOut"

		self.useScanOut = useScanOut

	def getUseScanOut(self):
		"""
		Returns if this GPU is scanout capable
		"""
		return self.useScanOut

	def setType(self, model):
		"""
		Set the type, i.e. the model of the GPU.
		"""
		if (model is not None) and (not isinstance(model, str)):
			raise TypeError, "Expected string model"

		self.resType = model

	def getType(self):
		return self.resType

	def setResourceAccess(self, resourceAccessObj):
		if resourceAccessObj is not None:
			if not isinstance(resourceAccessObj, ResourceAccess):
				raise TypeError, "Expected ResourceAccess object. Got '%s'"%(resourceAccessObj.__class__)

		self.ra = resourceAccessObj

	def setSchedulable(self, schedulable):
		# FIXME : do type checking on the schedulable object before letting it through
		# if type(schedulable) is

		self.schedulable = schedulable

	def getSchedulable(self):
		return self.schedulable

	def addScanoutCap(self, port_index, output_type):
		if self.scanoutCaps is None:
			self.scanoutCaps = {}
		if not self.scanoutCaps.has_key(port_index):
			self.scanoutCaps[port_index] = []

		if output_type not in GPU.ScanTypes:
			raise ValueError, "Unexpected scanout type '%s'. Expected one of %s"%(output_type, GPU.ScanTypes)

		self.scanoutCaps[port_index].append(output_type)

	def getScanoutCaps(self):
		return self.scanoutCaps

	def setScanoutCaps(self, caps):
		self.scanoutCaps = copy.deepcopy(caps)

	def setMaxFBWidth(self, value):
		self.max_width = value

	def getMaxFBWidth(self):
		return self.max_width

	def getMaxFBHeight(self):
		return self.max_height

	def setMaxFBHeight(self, value):
		self.max_height = value

	def getVendor(self):
		return self.vendor

	def setVendor(self, value):
		self.vendor = value
	
	def serializeToXML(self, detailedConfig = True, addrOnly=False):
		"""
		NOTE: detailedConfig triggers serialization of schedulable information.
		"""
		ret = "<%s>"%(GPU.rootNodeName)
		ret += VizResource.serializeToXML(self, detailedConfig, addrOnly)

		if self.hostName is not None:
			ret = ret + "<hostname>%s</hostname>"%(self.hostName)

		if self.resIndex is not None:
			ret = ret + "<index>%d</index>"%(self.resIndex)

		if not addrOnly:
			if self.sharedServerIndex is not None:
				ret = ret + "<sharedServerIndex>%d</sharedServerIndex>"%(self.sharedServerIndex)
				# Add configuration of the shared server, if present
				if self.sharedServer is not None:
					ret = ret + self.sharedServer.serializeToXML()

			if self.resType is not None:
				ret = ret + "<model>%s</model>"%(self.resType)

			if self.busID is not None:
				ret = ret + "<busID>%s</busID>"%(self.busID)

			if self.useScanOut is not None:
				ret = ret + "<useScanOut>%d</useScanOut>"%(self.useScanOut)

			if self.allowNoScanOut is not None:
				ret = ret + "<allowNoScanOut>%d</allowNoScanOut>"%(self.allowNoScanOut)

			if self.allowStereo is not None:
				ret = ret + "<allowStereo>%d</allowStereo>"%(self.allowStereo)

			# serialize scanouts
			scanoutKeys = self.scanout.keys()
			scanoutKeys.sort()
			for scanout_index in scanoutKeys:
				scanout = self.scanout[scanout_index]
				ret = ret + "<scanout>"
				ret = ret + "<port_index>%d</port_index>"%(scanout_index)
				if scanout.has_key('type'):
					ret = ret + "<type>%s</type>"%(scanout["type"])
				if isinstance(scanout["display_device"],str):
					ddType = scanout["display_device"]
				else:
					ddType = scanout["display_device"].getType()
				ret = ret + "<display_device>%s</display_device>"%(ddType)
				if scanout.has_key("mode"):
					ret = ret + "<mode>%s</mode>"%(scanout["mode"])
				areaDesc =""
				if scanout.has_key("area_x"): areaDesc = areaDesc + "<x>%d</x>"%(scanout["area_x"])
				if scanout.has_key("area_y"): areaDesc = areaDesc + "<y>%d</y>"%(scanout["area_y"])
				if scanout.has_key("area_width"): areaDesc = areaDesc + "<width>%d</width>"%(scanout["area_width"])
				if scanout.has_key("area_height"): areaDesc = areaDesc + "<height>%d</height>"%(scanout["area_height"])
				if len(areaDesc)>0:
					ret = ret + "<area>%s</area>"%(areaDesc)
				ret = ret + "</scanout>"

			if detailedConfig:
				# serialize any scheduler information
				if self.schedulable:
					ret = ret + self.schedulable.serializeToXML()
		
			# serialize other template properties
			if self.vendor is not None:
				ret += "<vendor>%s</vendor>"%(self.vendor)
			if self.scanoutCaps is not None:
				for idx in self.scanoutCaps:
					ret += "<scanout_caps>"
					ret += "<index>%d</index>"%(idx)
					for st in self.scanoutCaps[idx]:
						ret += "<type>%s</type>"%(st)
					ret += "</scanout_caps>"
			if (self.max_width is not None) or (self.max_height is not None):
				ret += "<limits>"
				if self.max_width is not None:
					ret += "<max_width>%d</max_width>"%(self.max_width)
				if self.max_height is not None:
					ret += "<max_height>%d</max_height>"%(self.max_height)
				ret += "</limits>"

		ret = ret + "</%s>"%(GPU.rootNodeName)
		return ret

	def getAllowNoScanOut(self):
		return self.allowNoScanOut

	def setAllowNoScanOut(self, value):
		self.allowNoScanOut = value

	def getAllowStereo(self):
		return self.allowStereo

	def setAllowStereo(self, value):
		if value is not None and not isinstance(value, bool):
			raise TypeError, "Expected None or boolean. Got '%s'"%(value)
		self.allowStereo = value

	def deserializeFromXML(self, domNode):
		"""
		Deserialize from XML, essentially recreating the whole object again.
		"""
		self.__clearAll()

		if domNode.nodeName != GPU.rootNodeName:
			raise ValueError, "Faild deserialize GPU. Programmatic error."

		# Deserialize the base class info
		VizResource.deserializeFromXML(self, domNode)

		hostnameNode = domutil.getChildNode(domNode, "hostname")
		if hostnameNode is not None:
			self.hostName = domutil.getValue(hostnameNode)

		indexNode = domutil.getChildNode(domNode, "index")
		if indexNode is not None:
			self.resIndex = int(domutil.getValue(indexNode))

		busIdNode = domutil.getChildNode(domNode, "busID")
		if busIdNode is not None:
			self.busID = domutil.getValue(busIdNode)

		modelNode = domutil.getChildNode(domNode, "model")
		if modelNode is not None:
			self.resType = domutil.getValue(modelNode)

		scanOutNode = domutil.getChildNode(domNode, "useScanOut")
		if scanOutNode != None:
			self.useScanOut = bool(int(domutil.getValue(scanOutNode)))

		scanOutNode = domutil.getChildNode(domNode, "allowNoScanOut")
		if scanOutNode != None:
			self.allowNoScanOut = bool(int(domutil.getValue(scanOutNode)))

		stereoNode = domutil.getChildNode(domNode, "allowStereo")
		if stereoNode != None:
			self.allowStereo = bool(int(domutil.getValue(stereoNode)))

		# Create the shared X server here if it exists.
		sharedServerNode = domutil.getChildNode(domNode, Server.rootNodeName)
		if sharedServerNode is not None:
			self.sharedServer.deserializeFromXML(sharedServerNode)
			self.sharedServer.setShareLimit(self.getShareLimit())

		# Get the shared server index
		indexNode = domutil.getChildNode(domNode, "sharedServerIndex")
		if indexNode is not None:
			self.setSharedServerIndex(int(domutil.getValue(indexNode)))
		elif self.sharedServer is not None:
			self.sharedServerIndex = self.sharedServer.getIndex()

		# deserialize scanout caps before scanouts. This will
		# help us validate the scanouts
		vNodes = domutil.getChildNodes(domNode, "scanout_caps")
		for tNode in vNodes:
			thisScanoutCap = []
			scanIndex = int(domutil.getValue(domutil.getChildNode(tNode, "index")))
			for typeNode in domutil.getChildNodes(tNode, "type"):
				thisScanoutCap.append(domutil.getValue(typeNode))
			if self.scanoutCaps is None:
				self.scanoutCaps = {}
			self.scanoutCaps[scanIndex] = thisScanoutCap

		# deserialize scanouts
		scanoutNodes = domutil.getChildNodes(domNode, "scanout")
		for sNode in scanoutNodes:
			thisScanout = {}
			portIndexNode = domutil.getChildNode(sNode, "port_index")
			if portIndexNode is None:
				raise ValueError, "Failed to deserialize : Scanout needs a port index"
			try:
				portIndex = int(domutil.getValue(portIndexNode))
				if (portIndex<0):
					raise ValueError, "Bad value of port index. This can't be negative."
				if (self.scanoutCaps is not None) and (portIndex>len(self.scanoutCaps)):
					raise ValueError, "Port index(%d) has to be less than the number of scanouts supported(%d)"%(portIndex, len(self.scanoutCaps))
			except ValueError:
				raise ValueError, "Failed to deserialize : Bad value for port index"

			# this is optional since it can be picked up from the display device.
			portTypeNode = domutil.getChildNode(sNode, "type")
			if portTypeNode is not None:
				portType = domutil.getValue(portTypeNode)
				thisScanout['type'] = portType
				if portType not in GPU.ScanTypes:
					raise ValueError, "Failed to deserialize. Bad value for type of scanout type. Valid values are %s, specified value was:%s"%(repr(GPU.ScanTypes), portType)

			# mode is optional too since it can be picked up from the display device.
			modeNode = domutil.getChildNode(sNode, "mode")
			if modeNode is not None:
				mode = domutil.getValue(modeNode)
				if len(mode)==0:
					raise ValueError, "Failed to deserialize. Empty mode node has been specified."
				thisScanout['mode'] = mode

			displayDeviceNode = domutil.getChildNode(sNode, "display_device")
			if displayDeviceNode is None:
				raise ValueError, "Failed to deserialize. No display device specified"
			else:
				thisScanout['display_device'] = domutil.getValue(displayDeviceNode)

			areaNode = domutil.getChildNode(sNode, "area")
			if areaNode is not None:
				try:
					xNode = domutil.getChildNode(areaNode, "x")
					if xNode is not None:
						thisScanout['area_x'] = int(domutil.getValue(xNode))
					yNode = domutil.getChildNode(areaNode, "y")
					if yNode is not None:
						thisScanout['area_y'] = int(domutil.getValue(yNode))
					widthNode = domutil.getChildNode(areaNode, "width")
					if widthNode is not None:
						thisScanout['area_width'] = int(domutil.getValue(widthNode))
					heightNode = domutil.getChildNode(areaNode, "height")
					if heightNode is not None:
						thisScanout['area_height'] = int(domutil.getValue(heightNode))
				except ValueError:
					raise ValueError, "Failed to deserialize. Bad value for area parameters : x or y or width or height"

			# FIXME : where will we validate the display device information
			self.scanout[portIndex] = thisScanout

		# Deserialize any scheduler info next
		schedulableNode = domutil.getChildNode(domNode, Schedulable.rootNodeName)
		if schedulableNode is not None:
			self.schedulable = Schedulable()
			self.schedulable.deserializeFromXML(schedulableNode)
		else:
			self.schedulable = None

		# Deserialize detailed config
		# FIXME: do validation for fields below !
		tNode = domutil.getChildNode(domNode, "vendor")
		if tNode is not None:
			self.vendor = domutil.getValue(tNode)

		limitNode = domutil.getChildNode(domNode, "limits")
		if limitNode is not None:
			self.max_width = int(domutil.getValue(domutil.getChildNode(limitNode, "max_width")))
			self.max_height = int(domutil.getValue(domutil.getChildNode(limitNode, "max_height")))

	def getScanouts(self):
		ret = {}
		for pi in self.scanout.keys():
			ret[pi]=self.scanout[pi]
		return ret

	def clearScanouts(self):
		"""
		Clear all scanouts defined for this GPU
		"""
		self.scanout.clear()

	def clearScanout(self, port_index):
		self.scanout.pop(port_index)

	def setScanout(self, port_index, display_device, scan_type=None, mode=None, outputX=0, outputY=0, outputWidth=None, outputHeight=None):
		"""
		Sets a scanout on this GPU.
		"""
		#
		# Validate Input
		#
		if port_index<0:
			raise ValueError, "Port index specified is %d . This cannot be negative."%(port_index)

		# Check if we're allowed to configure scanouts
		if (self.useScanOut is not None) and (self.useScanOut==False):
			# FIXME: change the type of exception.
			raise ValueError, "You're not allowed to configure scanouts on this GPU."

		# Check the port index. If we have the GPU information with us, use that to validate
		if (self.scanoutCaps is not None) and (port_index>=len(self.scanoutCaps)):
			raise ValueError, "Port index specified is %d. This needs to be less than %d."%(port_index, len(self.scanoutCaps))

		if outputX is None:
			raise ValueError, "Expect integer for outputX, Can't pass None"
		else:
			if not isinstance(outputX, int):
				raise TypeError, "Expected integer for output X position"
			if outputX<0:
				raise ValueError, "Expected non-negative integer for output X position"
			if (self.max_width is not None) and (outputX>self.max_width): # FIXME: add the minimum dimension check here
				raise ValueError, "Output position X %d is too high. Max allowed for this GPU is %d"%(outputX, self.max_width)

		if outputY is None:
			raise ValueError, "Expect integer for outputY, Can't pass None"
		else:
			if not isinstance(outputY, int):
				raise TypeError, "Expected integer for output Y position"
			if outputY<0:
				raise ValueError, "Expected non-negative integer for output Y position"
			if (self.max_height is not None) and (outputY>self.max_height): # FIXME: add the minimum dimension check here
				raise ValueError, "Output position Y %d is too high. Max allowed for this GPU is %d"%(outputY, self.max_height)

		# Check that the scan type. None will take defaults of the display device.
		if (scan_type is not None):
			if (scan_type not in GPU.ScanTypes):
				raise ValueError, "Incorrect scan type specified, '%s'."%(scan_type)
			if (self.scanoutCaps is not None) and (scan_type not in self.scanoutCaps[port_index]):
				raise ValueError, "For port %d, the valid scanout types are %s. You passed: %s"%(port_index, self.scanoutCaps[port_index], scan_type)

		validDD = None
		if isinstance(display_device, DisplayDevice):
			if not display_device.isValid():
				raise ValueError, "You need to pass a valid DisplayDevice object"
			validDD = display_device
		elif isinstance(display_device, str):
			if self.ra is not None:
				try:
					validDD = self.ra.getTemplates(DisplayDevice(display_device))[0]
				except VizError, e:
					raise ValueError, "Invalid display device '%s'. Reason:%s"%(display_device, str(e))
		else:
			raise ValueError, "Display device must be a string value or a DisplayDevice object."

		if (mode is not None) and (type(mode) is not str):
			raise ValueError, "Mode must be a string value."

		if validDD is not None:
			try:
				if mode is None:
					modeDetails = validDD.getDefaultMode()
				else:
					modeDetails = validDD.getModeByAlias(mode)
			except ValueError, e:
				raise ValueError, "Improper mode '%s' for device '%s'. Reason : %s"%(mode, validDD.getType(), str(e))

			if outputWidth is not None:
				if outputWidth < modeDetails['width']:
					raise ValueError, "Output width(%d) needs to be atleast as wide (%d) as the mode you have chosen."%(outputWidth, modeDetails['width']) 
			if outputHeight is not None:
				if outputHeight < modeDetails['height']:
					raise ValueError, "Output height(%d) needs to be atleast as tall (%d) as the mode you have chosen."%(outputHeight, modeDetails['height']) 
		else:
			modeDetails = None

		tempOutputWidth = None
		if outputWidth is not None:
			if not isinstance(outputWidth, int):
				raise TypeError, "Expected integer for output width"
			if outputWidth<=0: # FIXME: Put a minimum bound here!
				raise ValueError, "Expected positive integer for output width"
			if (self.max_width is not None) and (outputWidth>self.max_width):
				raise ValueError, "Output width %d is too high. Max allowed for this GPU is %d"%(outputWidth, self.max_width)
			tempOutputWidth = outputWidth
		else:
			if modeDetails:
				tempOutputWidth = modeDetails['width']

		tempOutputHeight = None
		if outputHeight is not None:
			if not isinstance(outputHeight, int):
				raise TypeError, "Expected integer for output height"
			if outputHeight<=0: # FIXME: Put a minimum bound here!
				raise ValueError, "Expected positive integer for output width"
			if (self.max_height is not None) and (outputHeight>self.max_height):
				raise ValueError, "Output height %d is too high. Max allowed for this GPU is %d"%(outputHeight, self.max_height)
			tempOutputHeight = outputHeight
		else:
			if modeDetails:
				tempOutputHeight = modeDetails['height']

		if (self.max_width is not None):
			if (tempOutputWidth is not None) and ((outputX+tempOutputWidth)>self.max_width):
				raise ValueError, "This GPU supports a framebuffer of width %d pixels. For the settings you are trying, you'll need a GPU which supports a framebuffer width of at-least %d pixels"%(self.max_height, tempOutputHeight+self.max_width)

		if (self.max_height is not None):
			if (tempOutputHeight is not None) and ((outputY+tempOutputHeight)>self.max_height):
				raise ValueError, "This GPU supports a framebuffer of width %d pixels. For the settings you are trying, you'll need a GPU which supports a framebuffer width of at-least %d pixels"%(self.max_height, tempOutputHeight+self.max_height)

		# Assemble all this into a friendly neighbourhood dictionary !
		dict = {}
		dict['port_index'] = port_index
		if scan_type is not None:
			dict['type'] = scan_type
		if mode is not None:
			dict['mode'] = mode
		dict['display_device'] = display_device
		dict['area_x']=outputX
		dict['area_y']=outputY
		if outputWidth is not None: dict['area_width']=outputWidth
		if outputHeight is not None: dict['area_height']=outputHeight

		# And add it to us...
		self.scanout[port_index] = dict

	def getHostName(self):
		return self.hostName

	def getAllocationWeight(self):
		"""
		Returns a weight to be used by the allocation algorithm.
		"""
		totalWeight = VizResource.getAllocationWeight(self)

		if (self.useScanOut is not None) and (self.useScanOut==1):
			# Every scanout that this is capable of adds 100 to 
			# the weight
			if self.scanoutCaps is not None:
				for sc in self.scanoutCaps.keys():
					totalWeight += 100
			
			# add 100 for every connected display device
			for scanoutIndex in self.scanout.keys():
				totalWeight += 100

		# A shared GPU decrements the weight by number of users that can 
		# additionally access the GPU. This ensures that shared GPUs are chosen
		# earlier if needed.
		if self.isShared():
			totalWeight = totalWeight - (self.getShareLimit()-len(self.getOwners()))

		return totalWeight

class SLI(VizResource):

	rootNodeName = "sli"
	validModes = [ "auto", "SFR", "AFR", "AA", "mosaic" ]
	validTypes = [ "discrete", "quadroplex" ]
	def __clearAll(self):
		self.resIndex = None
		self.hostName = None
		self.resType = None # Choices are "discrete" & "quadroplex"
		self.gpu0 = None
		self.gpu1 = None
		self.mode = None

	def __init__(self, resIndex=None, hostName = None, sliType=None, gpu0=None, gpu1=None):
		VizResource.__init__(self)
		self.resClass = "SLI"
		self.__clearAll()
		self.resIndex = resIndex
		self.hostName = hostName
		self.setType(sliType)
		self.gpu0 = gpu0
		self.gpu1 = gpu1

	def getGPUIndex(self, index):
		"""
		Return the indexth GPU connected to the SLI. Index can be 0 or 1
		"""
		if not isinstance(index, int):
			raise TypeError, "Expected int"
		if index==0:
			return self.gpu0
		elif index==1:
			return self.gpu1

		raise ValueError, "Bad index %s"%(index)

	def setType(self, sliType):
		"""
		Set the type of SLI connector. 
		"""
		if (sliType is not None):
			if (not isinstance(sliType, str)):
				raise TypeError, "Expected string type"
			if sliType not in SLI.validTypes:
				raise ValueError, "Valid values are 'discrete' and 'quadroplex'"
		self.resType = sliType

	def getType(self):
		return self.resType

	def getGPUs(self):
		if (self.gpu0 is not None) and (self.gpu1 is not None):
			return [ GPU(self.gpu0, self.hostName), GPU(self.gpu1, self.hostName) ]
		raise VizError(VizError.RESOURCE_UNSPECIFIED, "One or more GPUs for this SLI object are not defined.")

	def setMode(self, mode):
		if mode not in SLI.validModes:
			raise ValueError, "Invalid value for mode '%s'. Expecting one of %s."%(mode, validModes)
		if (self.resType is not None) and (mode == "mosaic") and (self.resType != "quadroplex"):
			raise ValueError, "SLI mosaic mode is available only on QuadroPlex"
		self.mode = mode

	def getMode(self):
		return self.mode

	def serializeToXML(self, detailedConfig = True, addrOnly=False):
		"""
		"""
		ret = "<%s>"%(SLI.rootNodeName)
		ret += VizResource.serializeToXML(self, detailedConfig, addrOnly)

		if self.hostName is not None:
			ret = ret + "<hostname>%s</hostname>"%(self.hostName)

		if self.resIndex is not None:
			ret = ret + "<index>%d</index>"%(self.resIndex)

		if not addrOnly:
			if self.resType != None:
				ret = ret + "<type>%s</type>"%(self.resType)

			if detailedConfig == True:
				if self.gpu0 is not None:
					ret = ret + "<gpu0>%d</gpu0>"%(self.gpu0)
				if self.gpu1 is not None:
					ret = ret + "<gpu1>%d</gpu1>"%(self.gpu1)

			if self.mode is not None:
				ret = ret + "<mode>%s</mode>"%(self.mode)

		ret += "</%s>"%(SLI.rootNodeName)
		return ret

	def deserializeFromXML(self, domNode):
		"""
		Deserialize from XML, essentially recreating the whole object again.
		"""
		self.__clearAll()

		if domNode.nodeName != SLI.rootNodeName:
			raise ValueError, "Faild to deserialize SLI. Programmatic error."

		# Deserialize the base class info
		VizResource.deserializeFromXML(self, domNode)

		hostnameNode = domutil.getChildNode(domNode, "hostname")
		if hostnameNode is not None:
			self.hostName = domutil.getValue(hostnameNode)

		indexNode = domutil.getChildNode(domNode, "index")
		if indexNode is not None:
			self.resIndex = int(domutil.getValue(indexNode))

		sliTypeNode = domutil.getChildNode(domNode, "type")
		if sliTypeNode is not None:
			self.setType(domutil.getValue(sliTypeNode))

		gpu0Node = domutil.getChildNode(domNode, "gpu0")
		if gpu0Node is not None:
			self.gpu0 = int(domutil.getValue(gpu0Node))

		gpu1Node = domutil.getChildNode(domNode, "gpu1")
		if gpu1Node is not None:
			self.gpu1 = int(domutil.getValue(gpu1Node))

		sliModeNode = domutil.getChildNode(domNode, "mode")
		if sliModeNode is not None:
			self.setMode(domutil.getValue(sliModeNode))

class Screen:
	"""
	Screen class enapsulates a single screen of an X server - i.e. a framebuffer.
	"""

	rootNodeName = "framebuffer"
	stereoModes = { 
		"none" : "No Stereo",
		"active" : "Active Stereo using Shutter Glasses",
		"passive" : "Passive Stereo",
		"SeeReal_stereo_dfp" : "Auto-Stereoscopic SeeReal DFP (suitable for Tridelity SV displays)",
		"Sharp3D_stereo_dfp" : "Auto-Stereoscopic Sharp DFP"
	}
	rotationModes = {
	    "none" : "No Rotation",
	    "portrait" : "Portrait Mode (90 degrees to the left)",
	    "inverted_portrait" : "Inverted Portrait Mode (90 degrees to the right)",
	    "inverted_landscape" : "Inverted Landscape (180 degrees)" # 180 degree
	}
	def __clearAll(self):
		self.screenNumber = None
		self.server = None
		self.gpus = []
		self.properties = {}
		self.isXineramaScreen = False
		self.gpuCombiner = None

	def __str__(self):
		return '<Screen %d>'%(self.screenNumber)

	def __init__(self, screenNumber=None, server=None):
		self.__clearAll()

		if (server is not None) and (type(server) is not Server):
			raise VizError(VizError.INCORRECT_VALUE, "Improper object passed as a server")
		if (type(screenNumber) is not int) and (screenNumber is not None):
			raise VizError(VizError.INCORRECT_VALUE, "Screen number must be an integer or None")
			
		self.screenNumber = screenNumber
		self.server = server
		self.gpus = []
		self.properties = {}

	def setGPUCombiner(self, combiner):
		if not isinstance(combiner, SLI):
			raise TypeError, "Expecting a SLI object, got %s"%(combiner.__class__)

		self.gpuCombiner = combiner

	def getGPUCombiner(self):
		return self.gpuCombiner
		
	def createXineramaScreen(self, server, width, height, stereoMode):
		"""
		Create a Xinerama screen with specified attributes. 
		The xinerama screen will be immutable - and act as an aid to
		applications.
		"""
		self.__clearAll()
		self.server = server
		self.screenNumber = 0 # That's all you get with Xinerama
		self.isXineramaScreen = True
		self.properties['position'] = [0,0]
		self.properties['resolution'] = [width, height]
		self.properties['stereo'] = stereoMode

	def getServer(self):
		"""
		Return the Server which this screen is associated with.
		"""
		return self.server

	def getDISPLAY(self):
		"""
		Return the DISPLAY environment variable that can be used to
		address this screen. Note that the DISPLAY is valid only on the
		host where the corresponding X server is running.
		"""
		if self.screenNumber is None:
			raise VizError(VizError.BAD_CONFIGURATION, "This screen isn't valid.")
		if self.server is None:
			raise VizError(VizError.BAD_CONFIGURATION, "This screen deosn't have an associated Server")
		srvNum = self.server.getIndex()

		if self.isXineramaScreen == False: # Xinerama screens need no GPUs
			if len(self.gpus)==0:
				raise VizError(VizError.BAD_CONFIGURATION, "This screen deosn't have any GPUs associated with it")

		scrNum = self.screenNumber
		return ":%d.%d"%(srvNum, scrNum)

	def setServer(self, server):
		"""
		Sets the Server for this screen. Meant for internal use.
		"""
		if self.isXineramaScreen:
			raise VizError(VizError.BAD_OPERATION, "Can't change the server on a Xinerama screen")
		if (self.server is not None) and (not isinstance(self.server, Server)):
			raise TypeError, "Expect an object of type Server, got %s"%(server.__class__)
		self.server = server

	def getSchedulable(self):
		if self.isXineramaScreen==False:
			if len(self.gpus) == 0:
				return None
			return self.gpus[0].getSchedulable()
		else:
			return self.server.getSchedulable()

	def run(self, args, inFile=None, outFile=None, errFile=None, launcherEnv=None):
		if self.screenNumber is None:
			raise VizError(VizError.INVALID_OPERATION, "Cannot run() on a screen which is not valid!")
		if self.server is None:
			raise VizError(VizError.INVALID_OPERATION, "Cannot run() on a screen which is not attached to an X server")
		if self.server.getSchedulable() is None:
			raise VizError(VizError.INVALID_OPERATION, "The X server containing this screen is not schedulable. Cannot run command")
		if not self.server.isCompletelyResolvable():
			raise ValueError, "Incomplete X server passed %s"%(s.hashKey())
		cmd_args = copy.copy(args)
		cmd_args = ["/usr/bin/env", "DISPLAY=%s"%(self.getDISPLAY())]+cmd_args
		return self.getSchedulable().run(cmd_args, inFile, outFile, errFile, launcherEnv)

	def setGPU(self, gpu):
		"""
		Set the GPU driving this screen. The screen copies the GPU. Any changes made to
		the GPU object after this call will not reflect on the screen.
		"""
		if self.isXineramaScreen:
			raise VizError(VizError.BAD_OPERATION, "Can't change the GPU on a Xinerama screen")
		if gpu is None:
			raise ValueError, "I need a GPU, won't accept None"
		if not isinstance(gpu, GPU):
			raise VizError(VizError.INCORRECT_VALUE, "Improper object passed as a GPU")
		
		# Keep a copy of the GPU with us
		# Why copy ?? The same GPU can get assigned to multiple screens, so we need to do
		# this; else user applications will run into scripting errors.
		self.gpus = [deepcopy(gpu)]

	def setGPUs(self, gpu_list):
		"""
		Set multiple GPUs to drive this screen. This could be the case with SLI modes
		OR with the QuadroPlex-specific SLI Mosaic Mode
		"""
		if self.isXineramaScreen:
			raise VizError(VizError.BAD_OPERATION, "Can't change the GPU on a Xinerama screen")
		if not isinstance(gpu_list, list):
			raise ValueError, "Expect a list of GPUs as my argument!"
		for ob in gpu_list:
			if not isinstance(ob, GPU):
				raise ValueError, "Improper object passed as a GPU"
		if len(gpu_list)>2:
			raise ValueError, "Cannot accept more than two GPUs"

		self.gpus = deepcopy(gpu_list)

	def getGPUs(self):
		"""
		Return a copy of the GPUs being used by this screen.
		"""
		if self.isXineramaScreen:
			raise VizError(VizError.BAD_OPERATION, "Can't get GPU from a Xinerama screen")
		# NOTE: we use deepcopy below. This copies everything properly. The 
		# copied scheduler object knows that it is not the original, so cleanup
		# issues are avoided.
		return deepcopy(self.gpus)

	def getUsedResources(self):
		ret = deepcopy(self.gpus)
		if self.gpuCombiner is not None:
			ret.append(deepcopy(self.gpuCombiner))
		return ret

	def setFBProperty(self, name, value):
		"""
		Set various frame buffer properties. 
		Resolution, stereo state are example properties.
		"""
		if self.isXineramaScreen:
			raise VizError(VizError.BAD_OPERATION, "Can't change properties on a Xinerama screen")
		if name == "resolution":
			if (len(value)!=2 or (type(value[0]) is not int)  or (type(value[1]) is not int)):
				raise ValueError, "Invalid value for resolution. It must be a 2-tuple."
			# FIXME: Again, current generation nvidia validation here
			# NOTE: 304x200 is the minimum size of the virtual framebuffer.
			if (value[0]<304) or (value[0]>8192) or (value[1]<200) or (value[1]>8192):
				raise ValueError, "Out of range values specified for resolution. The minimum supported is 304x200."
			#if (value[0]%8) != 0:
			#	raise ValueError, "Width (%d) of the framebuffer must be a multiple of 8"%(value[0])
		elif name == "position":
			if (len(value)!=2 or (type(value[0]) is not int)  or (type(value[1]) is not int)):
				raise ValueError, "Invalid value for position. It must be a 2-tuple."
			if (value[0]<0) or (value[1]<0):
				raise ValueError, "Out of range values specified for position. No negative values allowed."
		elif name == "stereo":
			if value not in Screen.stereoModes.keys():
				raise ValueError, "Unsupported type of stereo mode '%s'"%(value)
		elif name == "rotate":
			if value not in Screen.rotationModes.keys():
				raise ValueError, "Unsupported type of rotation mode '%s'"%(value)
		else:
			raise ValueError, "Unknown property : %s"%(name)
				

		self.properties[name] = value

	def getFBProperty(self, name):
		"""
		Get a framebuffer property corresponding to this screen.
		Examples are 'resolution' and 'stereo'.

		NOTE: the 'resolution' property is influenced by the setting
		of the 'rotate' option. This is provided for application
		convenience.
		"""
		if name == "resolution":
			try:
				res = self.properties[name]
				prop = self.getFBProperty('rotate')
				if (prop is None) or (prop=="none"):
					return res
				elif prop=="portrait": # 90 degree left
					return [res[1], res[0]]
				elif prop=="inverted_portrait": #90 degree right 
					return [res[1], res[0]] # FIXME: should we return a negative value here ??
				elif prop=="inverted_landscape": # 180 degree
					return res # FIXME: should we return a negative value here ??
				else:
					raise ValueError, "Bad rotation setting in screen"
			except:
				pass

		return self.properties[name]

	def setScreenNumber(self, screenNumber):
		"""
		Ser the X screen number corresponding to this screen.
		"""
		if (screenNumber is not None):
			if (not isinstance(screenNumber, int)):
				raise TypeError, "Screen Number must be an integer"
			if (screenNumber < 0):
				raise ValueError, "Screen number must be non-negative. You passed %d"%(screenNumber)

		self.screenNumber = screenNumber

	def getScreenNumber(self):
		"""
		Get the X screen number corresponding to this screen.
		"""
		return self.screenNumber

	def serializeToXML(self):
		ret = "<%s>"%(Screen.rootNodeName)

		if self.isXineramaScreen:
			raise VizError(VizError.BAD_OPERATION, "Can't serialize a Xinerama screen")

		if self.screenNumber is not None:
			ret = ret +"<index>%d</index>"%(self.screenNumber)

		if len(self.properties)>0:
			ret = ret + "<properties>"
		if self.properties.has_key("position"):
			position = self.properties["position"]
			ret = ret + "<x>%d</x>"%(position[0])
			ret = ret + "<y>%d</y>"%(position[1])
		if self.properties.has_key("resolution"):
			resolution = self.properties["resolution"]
			ret = ret + "<width>%d</width>"%(resolution[0])
			ret = ret + "<height>%d</height>"%(resolution[1])
		if self.properties.has_key("stereo"):
			ret = ret + "<stereo>%s</stereo>"%(self.properties['stereo'])
		if self.properties.has_key("rotate"):
			ret = ret + "<rotate>%s</rotate>"%(self.properties['rotate'])
		if len(self.properties)>0:
			ret = ret + "</properties>"

		if self.gpuCombiner is not None:
			ret = ret + "<gpu_combiner>"
			ret = ret + self.gpuCombiner.serializeToXML(False)
			ret = ret + "</gpu_combiner>"

		for gpu in self.gpus:
			ret = ret + gpu.serializeToXML(False) # serialize the mimimum amount of GPU config possible

		ret = ret + "</%s>"%(Screen.rootNodeName)
		return ret

	def deserializeFromXML(self, domNode):
		if domNode.nodeName != Screen.rootNodeName:
			raise ValueError, "Failed to deserialize Screen. Incorrect deserialization attempt"

		self.__clearAll()

		indexNode = domutil.getChildNode(domNode, "index")
		if indexNode is None:
			raise ValueError, "Failed to deserialize Screen. Improper screen specification: screen number is mandatory"
		else:
			self.screenNumber = int(domutil.getValue(indexNode))

		propertiesNode = domutil.getChildNode(domNode, "properties")
		if propertiesNode:
			w = h = None
			widthNode = domutil.getChildNode(propertiesNode, "width")
			if widthNode is not None:
				try:
					w = int(domutil.getValue(widthNode))
					if (w<0) or (w>8192):
						raise ValueError, "Out of bounds value for framebuffer width"
				except ValueError, e:
					raise ValueError, "Invalid value for properties/width. Reason:%s"%(str(e))

			heightNode = domutil.getChildNode(propertiesNode, "height")
			if heightNode is not None:
				try:
					h = int(domutil.getValue(heightNode))
					if (h<0) or (h>8192):
						raise ValueError, "Out of bounds value for framebuffer height"
				except ValueError, e:
					raise ValueError, "Invalid value for properties/height. Reason:%s"%(str(e))

			if (w is not None) and (h is not None):
				self.setFBProperty("resolution",[w,h])
			elif (w is not None) or (h is not None):
				raise ValueError, "You need to specify width and height both OR keep both of them unspecified"

			# Get X & Y
			x = y = None
			xNode = domutil.getChildNode(propertiesNode, "x")
			if xNode is not None:
				try:
					x = int(domutil.getValue(xNode))
					if (x<0):
						raise ValueError, "x component of position can't be negative"
				except ValueError, e:
					raise ValueError, "Invalid value for properties/x. Reason:%s"%(str(e))

			yNode = domutil.getChildNode(propertiesNode, "y")
			if yNode is not None:
				try:
					y = int(domutil.getValue(yNode))
					if (y<0):
						raise ValueError, "y component of position can't be negative"
				except ValueError, e:
					raise ValueError, "Invalid value for properties/y. Reason:%s"%(str(e))

			if (x is not None) and (y is not None):
				self.setFBProperty("position",[x,y])
			elif (x is not None) or (y is not None):
				raise ValueError, "You need to specify x and y both OR keep both of them unspecified"

			# Get the stereo value
			stereoNode = domutil.getChildNode(propertiesNode, "stereo")
			if stereoNode is not None:
				smode = domutil.getValue(stereoNode)
				if smode not in Screen.stereoModes.keys():
					raise ValueError, "Invalid stereo mode specified '%s'. Valid values are %s"%(smode, Screen.stereoModes.keys())
				self.setFBProperty("stereo", smode)

			# Get the rotation value
			rotNode = domutil.getChildNode(propertiesNode, "rotate")
			if rotNode is not None:
				rot = domutil.getValue(rotNode)
				if rot not in Screen.rotationModes.keys():
					raise ValueError, "Invalid rotation mode specified '%s'. Valid values are %s"%(smode, Screen.rotationModes.keys())
				self.setFBProperty("rotate", rot)

		combinerNodes = domutil.getChildNodes(domNode, "gpu_combiner")
		if len(combinerNodes)==1:
			childNodes = domutil.getChildNodes(combinerNodes[0], SLI.rootNodeName)
			if len(childNodes)==0:
				raise ValueError, "No combiners specified."
			elif len(childNodes)>1:
				raise ValueError, "More than one combiners specified. Only one is allowed"
			newSLI = SLI()
			newSLI.deserializeFromXML(childNodes[0])
			self.setGPUCombiner(newSLI)
		elif len(combinerNodes)>1:
			raise ValueError, "Only one GPU combiner allowed"

		gpuNodes = domutil.getChildNodes(domNode, "gpu")
		if len(gpuNodes)==0:
			raise ValueError, "Failed to deserialize Screen. Improper configuration - No GPUs are present"
		for gpuNode in gpuNodes:
			newGPU = GPU()
			newGPU.deserializeFromXML(gpuNode)
			self.gpus.append(newGPU)

class Server(VizResource):
	"""
	Server class encapsulates a single X server
	"""

	rootNodeName = "server"
	all_x_extension_section_options = ['Composite']
	
	def getSchedulable(self):
		if not self.hasValidRuntimeConfig():
			return None
		return self.screens[0].getSchedulable()

	def __clearAll(self):
		self.resIndex = None
		self.modules = []
		self.keyboard = None
		self.mouse = None
		self.screens = {}
		self.combineFBs = False
		self.hostName = None
		self.resType = NORMAL_SERVER
		self.x_extension_section_option = {}
		self.serverArgs = {}

	def setConfig(self, srv):
		self.modules = srv.modules
		self.keyboard = srv.keyboard
		self.mouse = srv.mouse
		self.screens = srv.screens
		self.combineFBs = srv.combineFBs
		self.x_extension_section_option = srv.x_extension_section_option
		self.serverArgs = srv.serverArgs

	def setXExtensionSectionOption(self, optName, optVal):
		"""
		Set an Option to the X server configuration file's "Extension" Section.
		Each option has a name and a value, e.g. if you want to disable the
		composite extension, then you need to pass in

		    optName = "Composite", and optVal = "Disable"

		This will add the following line(s) to the X configuration file in this
		X server's "Extensions" section:
		
		    Option "Composite" "Disable"

		"""
		if not isinstance(optName, str):
			raise TypeError, "Expected string for optName, got '%s'"%(optName.__class__)
		if not isinstance(optVal, str):
			raise TypeError, "Expected string for optVal, got '%s'"%(optVal.__class__)
		if len(optName)==0:
			raise ValueError, "Option name must not be an empty string"
		if len(optVal)==0:
			raise ValueError, "Option value must not be an empty string"

		if optName not in Server.all_x_extension_section_options:
			raise ValueError, "Unrecognized option '%s'. Possible values are %s"%(optName, Server.all_x_extension_section_options)

		self.x_extension_section_option[optName] = optVal

	def unsetXExtensionSectionOption(self, optName):
		if not isinstance(optName, str):
			raise TypeError, "Expected string for optName, got '%s'"%(optName.__class__)
		if len(optName)==0:
			raise ValueError, "Option name must not be an empty string"
		try:
			self.x_extension_section_option.pop(optName)
		except IndexError, e:
			raise ValueError, "No such option exists '%s'"%(optName)
		return

	def __str__(self):
		return self.__repr__()

	def __repr__(self):
		return "< X Server :%s at host %s type %s >"%(self.resIndex, self.hostName, self.resType)

	def combineScreens(self, combineThem=True):
		if not isinstance(combineThem, bool):
			raise TypeError, "Expected boolean value"

		self.combineFBs = combineThem

	def referenceIsComplete(self):
		"""
		The reference is deemed complete if there is a hostanme and resIndex
		"""
		if self.resIndex is None: return False
		if type(self.resIndex) is not int: return False
		if self.hostName is None: return False
		if type(self.hostName) is not str: return False
		if len(self.hostName)==0: return False
		return True

	def __init__(self, resIndex=None, hostName = None, serverType = NORMAL_SERVER):
		VizResource.__init__(self)
		self.resClass = "Server"
		self.__clearAll()
		if serverType not in VALID_SERVER_TYPES:
			raise ValueError, "Invalid server type has been specified %s"%(serverType)
		self.resIndex = resIndex
		self.hostName = hostName
		self.resType = serverType

		self.clearConfig()

	def clearConfig(self):
		self.modules = []
		self.keyboard = None
		self.mouse = None
		self.screens = {}
		self.combineFBs = False
		self.x_extension_section_option = {}
		self.serverArgs = {}
		# By default, we configure servers to disable the Composite extension.
		# Applications which need this extension can enable this explicitly
		self.setXExtensionSectionOption('Composite','Disable')

		# Disable power-save and screen saver
		self.setArg('-dpms')
		self.setArg('-s', 'off')
		# Disable TCP access by default.
		self.setArg('-nolisten', 'tcp')

	def setArg(self, argName, argVal=None):
		"""
		Add a command line argument to the X server.
		If argVal=None, then there are no parameters to the option
		"""
		self.serverArgs[argName] = argVal

	def unsetArg(self, argName):
		"""
		Remove a command line argument
		"""
		self.serverArgs.pop(argName)

	def setKeyboard(self, kbd):
		if kbd is not None:
			if not isinstance(kbd, Keyboard):
				raise TypeError, "Expected Keyboard object, got %s object"%(kbd.__class)
		self.keyboard = kbd

	def setMouse(self, mouse):
		if mouse is not None:
			if not isinstance(mouse, Mouse):
				raise TypeError, "Expected Mouse object, got %s object"%(kbd.__class)
		self.mouse = mouse

	def addScreen(self, newScreen):
		"""
		FIXME: this needs to be renamed to 'setScreen'
		Add a Screen to this X server.
		The screen needs to be completely valid.
		"""
		if self.resType != NORMAL_SERVER:
			raise VizError(VizError.BAD_CONFIGURATION, "You are allowed to add screens to only normal servers")
		if not isinstance(newScreen,Screen):
			raise VizError(VizError.INVALID_VALUE, "Improper object passed as a screen")
		if len(newScreen.getGPUs())==0:
			raise VizError(VizError.BAD_CONFIGURATION, "Passed screen has no GPUs.")
		# FIXME: validate the screen for completeness
		# FIXME: Should we validate that adding this screen does not
		# break any configuration rules ?
		newScreen.setServer(self)
		self.screens[newScreen.getScreenNumber()] = newScreen

	def getScreen(self, screenNumber):
		"""
		Return a specific screen from this X server
		"""
		return self.screens[screenNumber]

	def run(self, args, inFile=None, outFile=None, errFile=None, launcherEnv=None):
		if not self.screens.has_key(0):
			raise VizError(VizError.BAD_CONFIGURATION, "No Screens on this X server. Cannot run anything on it!")

		# Let screen number 0 do the running
		return self.getScreen(0).run(args,inFile,outFile,errFile,launcherEnv)
			
	def getScreens(self):
		"""
		Return a list of all screens
		"""
		ret = []
		screenNumbers = self.screens.keys()
		screenNumbers.sort()
		for n in screenNumbers:
			ret.append(self.screens[n])
		return ret

	def getCombinedScreen(self):
		if self.combineFBs == False:
			raise VizError(VizError.BAD_CONFIGURATION, "This server isn't setup to combine screens")
		newScreen = Screen()
		#
		# Go over all our screens and find the min and max
		#
		allScreens = self.getScreens()
		maxX = 0
		maxY = 0
		overallStereo = None
		singleStereoMode = True
		for scr in allScreens:
			sx = 0
			sy = 0
			# Ignore if the position is not defined. This will not give good results,
			# but GIGO applies here :-(
			try:
				[sx, sy] = scr.getFBProperty('position')
			except:
				pass
			dim = scr.getFBProperty('resolution')
			sx += dim[0]
			sy += dim[0]
			if sx>maxX: maxX=sx
			if sy>maxY: maxY=sy

			scrStereo = None
			try:
				scrStereo = scr.getFBProperty('stereo')
			except:
				pass

			if overallStereo is None:
				overallStereo = scrStereo

			if scrStereo != overallStereo:
				singleStereoMode = False

		if not singleStereoMode:
			overallStereo = None

		newScreen.createXineramaScreen(self, maxX, maxY, overallStereo)
		return newScreen
		
	def hasValidRuntimeConfig(self):
		if len(self.screens)>0:
			return True
		return False

	def getDISPLAY(self):
		#if not self.hasValidRuntimeConfig():
		#	raise VizError(VizError.BAD_CONFIGURATION, "This server isn't valid.")
		srvNum = self.getIndex()
		return ":%d"%(srvNum)

	def addModule(self, moduleName):
		if type(moduleName) is not str:
			raise VizError(VizError.INVALID_VALUE, "Module name must be a string")
		if len(moduleName)==0:
			raise VizError(VizError.INVALID_VALUE, "Module name must not be empty")

		# add this as a module, if it's not added already.
		if not moduleName in self.modules:
			self.modules.append(moduleName)

	def start(self, allocId=None, suppressOutput=True, suppressErrors=True):
		"""
		Start this X server
		"""
		if not self.referenceIsComplete():
			raise VizError(VizError.INCORRECT_VALUE, "%s is not a proper reference to a startable X server"%(str(self)))
		if not self.hasValidRuntimeConfig():
			raise VizError(VizError.BAD_CONFIGURATION, "%s cannot be started since it has not been configured properly"%(str(self)))
	
		sched = self.getSchedulable()
		if sched is None:
			raise VizError(VizError.RESOURCE_UNSPECIFIED, "Unable to get the scheduler details for this %s. Unable to start X server."%(str(self)))

		# If we came all the way, then invoke the scheduler !
		if suppressOutput:
			outFile = open("/dev/null","w")
		else:
			outFile = None
		if suppressErrors:
			errFile = open("/dev/null","w")
		else:
			errFile = None

		cmd = ["/opt/vizstack/bin/start-x-server",":%d"%(self.getIndex()),"-logverbose", "6"]
		if allocId is not None:
			cmd = cmd + [" --allocId", "%d"%(allocId)]
		return sched.run(cmd, outFile=outFile, errFile=errFile)

	def stop(self):
		"""
		Stop this X server
		"""
		if not self.referenceIsComplete():
			raise VizError(VizError.INCORRECT_VALUE, "%s is not a proper reference to a startable X server"%(str(self)))
		if not self.hasValidRuntimeConfig():
			raise VizError(VizError.BAD_CONFIGURATION, "%s cannot be started since it has not been configured properly"%(str(self)))
		if self.isShared():
			raise VizError(VizError.BAD_CONFIGURATION, "%s is a shared server. It cannot be stopped directly using this method."%(str(self)))
	
		sched = self.getSchedulable()
		if sched is None:
			raise VizError(VizError.RESOURCE_UNSPECIFIED, "Unable to get the scheduler details for this %s. Unable to start X server."%(str(self)))

		# If we came all the way, then invoke the scheduler !
		return sched.run(["/opt/vizstack/bin/vs-Xkill",":%d"%(self.getIndex())])

	def serializeToXML(self, detailedConfig = True, addrOnly=False):
		ret = "<%s>"%(Server.rootNodeName)
		ret = ret + VizResource.serializeToXML(self, detailedConfig, addrOnly)
		if self.hostName is not None: ret = ret + "<hostname>%s</hostname>"%(self.hostName)
		if self.resIndex is not None: ret = ret + "<server_number>%d</server_number>"%(self.resIndex)

		if not addrOnly:
			if self.resType is not None: ret = ret + "<server_type>%s</server_type>"%(self.resType)

			if detailedConfig:
				for arg in self.serverArgs:
					ret = ret + "<x_cmdline_arg>"
					ret = ret + "<name>%s</name>"%(arg)
					if self.serverArgs[arg] is not None:
						ret = ret + "<value>%s</value>"%(self.serverArgs[arg])
					ret = ret + "</x_cmdline_arg>"
				for name in self.modules: ret = ret + "<x_module>%s</x_module>"%(name)
				for optName in self.x_extension_section_option: ret = ret + "<x_extension_section_option><name>%s</name><value>%s</value></x_extension_section_option>"%(optName, self.x_extension_section_option[optName])
				if self.keyboard is not None: ret = ret + self.keyboard.serializeToXML(detailedConfig=False)
				if self.mouse is not None: ret = ret + self.mouse.serializeToXML(detailedConfig=False)

				# serialize each screen
				screenNumbers = self.screens.keys()
				screenNumbers.sort()
				for n in screenNumbers:
					screen = self.screens[n]
					ret = ret + screen.serializeToXML()

			# If asked to combine the framebuffers, then do so!
			if self.combineFBs == True:
				ret = ret + "<combine_framebuffers>1</combine_framebuffers>";

		ret = ret + "</%s>"%(Server.rootNodeName)
		return ret

	def deserializeFromXML(self, domNode):
		self.__clearAll()

		if domNode.nodeName != Server.rootNodeName:
			raise ValueError, "Failed to deserialize Server. This should not happen. Node name=%s, expected %s!"%(domNode.nodeName, Server.rootNodeName)

		VizResource.deserializeFromXML(self, domNode)

		hostNameNode = domutil.getChildNode(domNode, "hostname")
		if hostNameNode is not None:
			self.hostName = domutil.getValue(hostNameNode)

		resIndexNode = domutil.getChildNode(domNode, "server_number")
		if resIndexNode is not None:
			self.resIndex = int(domutil.getValue(resIndexNode))

		resTypeNode = domutil.getChildNode(domNode, "server_type")
		if resTypeNode is not None:
			resType = domutil.getValue(resTypeNode)
			if resType not in VALID_SERVER_TYPES:
				raise ValueError, "Invalid server type '%s'"%(resType)
			self.resType = resType

		for cmdArgNode in domutil.getChildNodes(domNode, "x_cmdline_arg"):
			argName = domutil.getValue(domutil.getChildNode(cmdArgNode,'name'))
			argValNode = domutil.getChildNode(cmdArgNode,'value')
			if argValNode is not None:
				argVal = domutil.getValue(argValNode)
			else:
				argVal = None
			self.setArg(argName, argVal)

		for moduleNode in domutil.getChildNodes(domNode, "x_module"):
			self.modules.append(domutil.getValue(moduleNode))

		for extoptNode in domutil.getChildNodes(domNode, "x_extension_section_option"):
			optName = domutil.getValue(domutil.getChildNode(extoptNode, "name"))
			optVal = domutil.getValue(domutil.getChildNode(extoptNode, "value"))
			self.setXExtensionSectionOption(optName, optVal)

		kbdNode = domutil.getChildNode(domNode, "keyboard")
		if kbdNode is not None:
			self.keyboard = deserializeVizResource(kbdNode,[Keyboard])

		mouseNode = domutil.getChildNode(domNode, "mouse")
		if mouseNode is not None:
			self.mouse = deserializeVizResource(mouseNode,[Mouse])

		for screenNode in domutil.getChildNodes(domNode, Screen.rootNodeName):
			scr = Screen()
			scr.deserializeFromXML(screenNode)
			scr.setServer(self)
			self.addScreen(scr)

		combineFBNode = domutil.getChildNode(domNode, "combine_framebuffers")
		if combineFBNode is not None:
			self.combineFBs = bool(domutil.getValue(combineFBNode))

	def getAllocationWeight(self):
		"""
		Returns a weight to be used by the allocation algorithm.
		"""
		wt = VizResource.getAllocationWeight(self)

		if self.resIndex == 0:
			# using a weight of 10000 protects nodes which are RGS capable!
			# GPUs from those will naturally get selected at the end
			wt += 10000

		return wt

class ResourceGroup(VizResourceAggregate):
	"""
	The ResourceGroup class. Provides a generalized way to setup and use a group of resources.
	This is accomplished by the resType(actually a handler) and 'handler_params'
	"""
	rootNodeName = "resourceGroup"

	def __clearAll(self):
		self.name = None
		self.resIndex = None # These two are not useful here, but kept to keep code from breaking
		self.hostName = None # 
		self.resType = None
		self.handler_params = None
		self.resources = []
		self.validateAgainst = None
		self.description = None # A string which describes the resource group

	def getDescription(self):
		"""
		Get the description of the resource group. This is a string
		which gives info about the resource group to the users.
		"""
		if self.description is None:
			return  ""
		return self.description

	def setDescription(self, desc):
		"""
		Set the description of the resource group. This is a string
		which gives info about the resource group to the users.
		"""
		if not isinstance(desc, str):
			raise TypeError, "Expected string"
		self.description = desc
	
	def typeSearchMatch(self, otherRes):
		if not VizResource.typeSearchMatch(self, otherRes):
			return False

		if (otherRes.name is not None) and (self.name != otherRes.name):
			return False

		return True
		
	def getName():
		return self.name

	def __init__(self, name=None, handler=None, handler_params=None, resources=[]):
		"""
		Constructor. Create a resource group, with specific parameters.
		"""
		VizResource.__init__(self)
		if not isinstance(resources, list):
			raise TypeError, "Expected list of resources. Got '%s'"%(resources.__class__)
		self.__clearAll()
		self.resClass = "ResourceGroup"
		self.name = name
		self.resType = handler
		self.handler_params = handler_params
		self.resources = resources
		self.handlerObj = self.__createHandlerObj()

	def __createHandlerObj(self):
		"""
		Internal function to create a handler object if the input is right.
		"""
		if (self.resType is not None) and (self.handler_params is not None):
			handlerObj = TiledDisplay(self)
		else:
			handlerObj = None
		return handlerObj

	def getName(self):
		"""
		Returns the name of this resource group.
		"""
		return self.name

	def getResources(self):
		"""
		Return a list of all resources that is included in this Resource Group.
		"""
		return self.resources

	def getParams(self):
		"""
		Get the parameters of this resource group
		"""
		return self.handler_params

	def setParams(self, params):
		"""
		Set the parameters of this resource group. 
		Note that this method does not validate the parameters.
		"""
		self.handler_params = params

	def setResources(self, resources):
		"""
		Set the list of resources that will be part of this resource group.
		"""
		if not isinstance(resources, list):
			raise TypeError, "Expected list of resources. Got '%s'"%(resources.__class__)
		self.resources = resources

	def serializeToXML(self, detailedConfig=True, addrOnly=False):
		# Validate before serializing
		self.doValidate(self.validateAgainst)

		ret = "<%s>"%(ResourceGroup.rootNodeName)
		if self.name is not None:
			ret += "<name>%s</name>"%(self.name)
		if self.resType is not None:
			ret += "<handler>%s</handler>"%(self.resType)
		if self.description is not None:
			ret += "<description>%s</description>"%(self.description)
		if self.handler_params is not None:
			ret += "<handler_params>%s</handler_params>"%(self.handler_params)
		if len(self.resources)>0:
			ret += "<resources>"
			for innerList in self.resources:
				ret += "<reslist>"
				for res in innerList:
					ret += "<res>%s</res>"%(res.serializeToXML())
				ret += "</reslist>"
			ret += "</resources>"
		ret += "</%s>"%(ResourceGroup.rootNodeName)
		return ret

	def deserializeFromXML(self, domNode):
		self.__clearAll()
		if domNode.nodeName != ResourceGroup.rootNodeName:
			raise ValueError, "Failed to deserialize Resource Group. This should not happen. Node name=%s, expected %s!"%(domNode.nodeName, ResourceGRoup.rootNodeName)

		nameNode = domutil.getChildNode(domNode,"name")
		if nameNode is not None:
			name = domutil.getValue(nameNode)
			if len(name)==0:
				raise ValueError, "Resource Group name should not be empty"
		else:
			name = None

		handlerNode = domutil.getChildNode(domNode, "handler")
		if handlerNode is None:
			handler = None
		else:
			handler = domutil.getValue(handlerNode)
			if len(handler)==0:
				raise ValueError, "Resource Group handler should not be empty"

		descNode = domutil.getChildNode(domNode, "description")
		if descNode is not None:
			self.description = domutil.getValue(descNode)

		handlerParamsNode = domutil.getChildNode(domNode, "handler_params")
		if handlerParamsNode is None:
			handler_params = None
		else:
			handler_params = domutil.getValue(handlerParamsNode)

		resourcesNode = domutil.getChildNode(domNode, "resources")
		resources = []
		if resourcesNode is not None:
			resListNodes = domutil.getChildNodes(resourcesNode, "reslist")
			if len(resListNodes)==0:
				raise ValueError, "Resource Group needs to have one or more resource lists"
			for resListNode in resListNodes:	
				resNodes = domutil.getChildNodes(resListNode, "res")
				if len(resNodes)==0:
					raise ValueError, "Resource Group's resource lists must have one or more resources"

				innerResources = []
				for node in resNodes:
					for innerRes in domutil.getAllChildNodes(node):
						obj = deserializeVizResource(innerRes)
						innerResources.append(obj)
				resources.append(innerResources)

		self.name = name
		self.resType = handler
		self.handler_params = handler_params
		self.resources = resources
		self.handlerObj = self.__createHandlerObj()

	def getHandlerObject(self):
		"""
		Return the handler object corresponding to this resource group.
		The handler object is valid only after allocation.

		The handler object typically provides meaningful ways to access the 
		contents of the resource group. E.g., only type of handler is 
		TiledDisplay, which helps you create a rectangular tiled display in a
		variety of ways. Custom handlers can be defined as well.
		"""
		return self.handlerObj

	def doValidate(self, templateResList):
		"""
		Validate this resource group, all parameters, etc.
		"""
		self.validateAgainst = templateResList
		if self.name is not None:
			if not isinstance(self.name, str):
				raise ValueError, "Name has to be a string"
			if len(self.name)==0:
				raise ValueError, "Name shouldn't be empty"

		# If no handler is defined, that's not too bad!
		if self.resType == None:
			return

		if self.resType != "tiled_display":
			raise ValueError, "No handler corresponds to '%s'"%(self.resType)

		# Validate from a handler point-of-view as well
		if self.handlerObj is None:
			# If no object exists, create a temporary one if needed.
			tempObj = self.__createHandlerObj()
			if tempObj:
				tempObj.doValidate(self.validateAgainst)
		else:
			self.handlerObj.doValidate(self.validateAgainst)

	def setupXServers(self, templateInfo=None):
		"""
		Setup the X servers needed for this Resource Group.  Note that
		this function does not propagate the settings to the SSM.
		"""
		if self.resType != "tiled_display":
			raise ValueError, "No handler corresponds to Resource Group handler '%s'"%(self.resType)

		# Invoke the same on the handler
		self.handlerObj.setupXServers(templateInfo)
		
class ResourceGroupHandler:
	def __init__(self, rgObj):
		pass

	def doValidate(self, templateResList):
		raise NotImplementedError, "doValidate has to be implemented"

	def setupXServers(self, templateInfo=None):
		raise NotImplementedError, "setupXServers was not implemented"

class TiledDisplay(ResourceGroupHandler):
	__validBlockTypes = ["gpu", "quadroplex"]
	__validBezelModes = ["all", "disable", "desktop"]
	def __init__(self, rgObj):
		self.stereo_mode = None
		self.num_blocks = None
		self.block_display_layout = None
		self.display_device = None
		self.display_mode = None
		self.tile_resolution = None
		self.block_type = None
		self.rgObj = rgObj
		self.params = rgObj.getParams()
		self.layoutMatrix = None
		self.validateAgainst = None
		self.combine_displays = None # Enable OR disable Xinerama
		self.group_blocks = None # For Xinerama per node
		self.remap_display_outputs = None 
		self.bezels = None
		self.framelock = False # Disable framelock by default
		self.clip_last_block = None # No clipping for the last block
		self.rotate = None

		self.matchedDD = None
		self.matchedMode = None

		# let python parse the parameters for us !
		paramsDict = {}
		try:
			# split to lines & remove leading and trailing newlines
			params = map(lambda x:x.lstrip().rstrip(), self.params.split('\n'))
			allParams = ""
			for line in params:
				hashPos=line.find('#') # remove comments, this also means that a hash can't come inside a string.
				if hashPos!=-1:
					line = line[:hashPos-1]
				allParams += (line+'\n')
			if allParams.find("(")!=-1:
				raise ValueError, "Function call bracket is not allowed in the parameter specification for security reasons."
			exec(allParams, paramsDict)
		except Exception, e:
			raise ValueError, "Bad Syntax in parameter specification for Tiled Display.\nParams='%s'.\nError : %s"%(self.params, str(e))
		#pprint(paramsDict)
		if paramsDict.has_key('num_blocks'): self.num_blocks = paramsDict['num_blocks']
		if paramsDict.has_key('block_display_layout'): self.block_display_layout = paramsDict['block_display_layout']
		if paramsDict.has_key('block_type'): self.block_type = paramsDict['block_type']
		if paramsDict.has_key('display_device'): self.display_device = paramsDict['display_device']
		if paramsDict.has_key('display_mode'): self.display_mode = paramsDict['display_mode']
		if paramsDict.has_key('tile_resolution'): self.tile_resolution = paramsDict['tile_resolution']
		if paramsDict.has_key('stereo_mode'): self.stereo_mode = paramsDict['stereo_mode']
		if paramsDict.has_key('combine_displays'):
			self.combine_displays = paramsDict['combine_displays']
		else:
			self.combine_displays = False
		if paramsDict.has_key('group_blocks'):
			self.group_blocks = paramsDict['group_blocks']
		else:
			if self.combine_displays: # If nothing is specified, then we take this to be the same as num_blocks
				self.group_blocks = self.num_blocks
		if paramsDict.has_key('remap_display_outputs'): self.remap_display_outputs = paramsDict['remap_display_outputs']
		if paramsDict.has_key('rotate'): self.rotate = paramsDict['rotate']
		if paramsDict.has_key('bezels'): self.bezels = paramsDict['bezels']
		if (self.bezels is not None) and (self.bezels not in TiledDisplay.__validBezelModes):
			raise ValueError, "Bad value for Bezel Mode(%s). Valid values are None, 'all', 'disable' and 'desktop'"%(self.bezels)
		if paramsDict.has_key('framelock'): self.framelock = paramsDict['framelock']
		if paramsDict.has_key('clip_last_block'): self.clip_last_block = paramsDict['clip_last_block']
	def getParam(self, paramName):
		if paramName == 'num_blocks':
			return self.num_blocks
		elif paramName == 'block_display_layout':
			return self.block_display_layout
		elif paramName == 'block_type':
			return self.block_type
		elif paramName == 'display_device':
			return self.display_device
		elif paramName == 'display_mode':
			return self.display_mode
		elif paramName == 'tile_resolution':
			return self.tile_resolution
		elif paramName == 'combine_displays':
			return self.combine_displays
		elif paramName == 'group_blocks':
			return self.group_blocks
		elif paramName == 'remap_display_outputs':
			return self.remap_display_outputs
		elif paramName == 'rotate':
			return self.rotate
		elif paramName == 'stereo_mode':
			return self.stereo_mode
		elif paramName == 'bezels':
			return self.bezels
		elif paramName == 'framelock':
			return self.framelock
		elif paramName == 'clip_last_block':
			return self.clip_last_block
		else:
			raise ValueError, "Unknown parameter '%s'"%(paramName)

	def setParam(self, paramName, paramValue):
		if paramName == 'num_blocks':
			self.num_blocks = paramValue
		elif paramName == 'block_display_layout':
			self.block_display_layout = paramValue
		elif paramName == 'block_type':
			self.block_type = paramValue
		elif paramName == 'display_device':
			self.display_device = paramValue
		elif paramName == 'display_mode':
			self.display_mode = paramValue
		elif paramName == 'tile_resolution':
			self.tile_resolution = paramValue
		elif paramName == 'combine_displays':
			self.combine_displays = paramValue
		elif paramName == 'group_blocks':
			self.group_blocks = paramValue
		elif paramName == 'remap_display_outputs':
			self.remap_display_outputs = paramValue
		elif paramName == 'rotate':
			self.rotate = paramValue
		elif paramName == 'stereo_mode':
			self.stereo_mode = paramValue
		elif paramName == 'bezels':
			self.bezels = paramValue
		elif paramName == 'framelock':
			self.bezels = paramValue
		elif paramName == 'clip_last_block':
			self.clip_last_block = paramValue
		else:
			raise ValueError, "Unknown parameter '%s'"%(paramName)

	def doValidate(self, templateResList):
		self.validateAgainst = templateResList

		if not isinstance(self.combine_displays, bool):
			raise ValueError, "combine_displays needs to be a boolean value. One of 'True' or 'False' (note: case must match as well)"

		if (self.rotate is not None):
			if self.rotate not in Screen.rotationModes.keys():
				raise ValueError, "rotate needs be one of %s. You've specified %s"%(Screen.rotationModes.keys(), self.rotate)
		if (self.block_type is None):
			raise ValueError, "Block type has to be specified"
		if not isinstance(self.block_type,str):
			raise ValueError, "Block type has to be a string value"
		if self.block_type not in TiledDisplay.__validBlockTypes:
			raise ValueError, "Block type has to be one of these values : %s"%(TiledDisplay.__validBlockTypes)

		if self.num_blocks is None:
			raise ValueError, "Dimensions of blocks must be specified."
		if not isinstance(self.num_blocks, list):
			raise ValueError, "Dimensions of blocks must be a list"
		if len(self.num_blocks) != 2:
			raise ValueError, "Dimensions of blocks must be two-element"
		if not (isinstance(self.num_blocks[0],int) and isinstance(self.num_blocks[1],int)):
			raise ValueError, "Dimensions of blocks must be integers"
		if self.num_blocks[0]<=0 or self.num_blocks[1]<=0:
			raise ValueError, "Dimensions of blocks must be positive integers"

		if self.group_blocks is not None:
			if not isinstance(self.group_blocks, list):
				raise ValueError, "group_blocks must be a list"
			if len(self.group_blocks) != 2:
				raise ValueError, "group_blocks must be two-element"
			if not (isinstance(self.group_blocks[0],int) and isinstance(self.group_blocks[1],int)):
				raise ValueError, "group_blocks must consist of two integers"
			if (self.group_blocks[0]<=0) or (self.group_blocks[1]<=0):
				raise ValueError, "group_blocks must have only positive integers"
			if ((self.num_blocks[0] % self.group_blocks[0]) != 0) or ((self.num_blocks[1] % self.group_blocks[1]) != 0):
				raise ValueError, "num_blocks (%s) must be divisible by group_blocks(%s)"%(self.num_blocks, self.group_blocks)
			if (self.block_type == "quadroplex") and ((self.num_blocks[0] * self.num_blocks[1])!=1):
				raise ValueError, "For QuadroPlex blocks, the only valid value for group_block is [1,1]" 

		if self.block_display_layout is None:
			raise ValueError, "Display Layout of the Block must be specified"
		if not isinstance(self.block_display_layout, list):		
			raise ValueError, "Display Layout must be a list"
		if len(self.block_display_layout)!=2:
			raise ValueError, "Display Layout must be a list of two positive integers"
		if not (isinstance(self.block_display_layout[0], int) and isinstance(self.block_display_layout[1],int)):
			raise ValueError, "Display Layout must be a list of two positive integers"
		if (self.block_display_layout[0]<=0) or (self.block_display_layout[1]<=0):
			raise ValueError, "Display Layout must be a list of two positive integers"
		if self.block_type == "gpu":
			numDisplays = self.block_display_layout[0]*self.block_display_layout[1] 
			if (numDisplays<1) or (numDisplays>2):
				raise ValueError, "For GPU blocks, display layout must be [1,1], [1,2], [2,1]. Value %s is not valid."%(self.block_display_layout)
		else: # quadroplex
			numDisplays = self.block_display_layout[0]*self.block_display_layout[1]
			if (numDisplays<2) or (numDisplays>4):
				raise ValueError, "For QuadroPlex blocks, display layout must be [1,2], [1,3], [1,4], [2,2] (or reverse of these values). Value %s is not valid."%(self.block_display_layout)

		# Stereo check	
		if self.stereo_mode is not None:
			if self.stereo_mode not in Screen.stereoModes.keys():
				raise ValueError, "Stereo mode must be one of %s"%(Screen.stereoModes.keys())
			# 1x2 and 2x1 layouts are not allowed for passive stereo since it takes uses
			# up both display outputs
			if self.stereo_mode == "passive":
				if self.block_display_layout[0]!=1 or self.block_display_layout[1]!=1:
					raise ValueError, "With passive stereo, block display layout must be [1,1]. No other value is allowed"

				if self.block_type == "quadroplex":
					raise ValueError, "Passive stereo is not compatible with quadroplex blocks. QuadroPlex blocks use the SLI mosaic mode, which is not compatible with passive stereo. If you want to use passive stereo with GPUs inside a QuadroPlex, then please set the block_type to 'gpu'"

		# Check display output remapping
		if self.remap_display_outputs is not None:
			if not isinstance(self.remap_display_outputs, list):		
				raise ValueError, "Remapped Display Output (remap_display_outputs) must be a list"
			if (self.stereo_mode == "passive") and (len(self.remap_display_outputs)!=2):
				raise ValueError, "If passive stereo is enabled, then remap_display_outputs must have exactly two port values"
			if self.block_type == "gpu":
				if len(self.remap_display_outputs)!=(self.block_display_layout[0]*self.block_display_layout[1]):
					raise ValueError, "Remapped Display Output (remap_display_outputs) have have as many elements as the display outputs driven per GPU."
			else: # quadroplex
				maxOutputsPerGPU = (self.block_display_layout[0]*self.block_display_layout[1]+1)/2
				if len(self.remap_display_outputs)!=maxOutputsPerGPU:
					raise ValueError, "Incorrect value for remap_display_outputs."
			repeatUsage = {}
			for po in self.remap_display_outputs:
				if not isinstance(po, int):
					raise ValueError, "Expect int for port number, got '%s'"(po)
				if (po<0):
					raise ValueError, "Port number can't be negative. You passed:%d"%(po)
				repeatUsage[po]=None
			if len(repeatUsage) != len(self.remap_display_outputs):
				raise ValueError, "One or more port numbers specified more than once."

		if self.framelock not in [True, False]:
			raise ValueError, "Bad value for framelock(%s). Must be one of True/False"%(self.framelock)

		if self.clip_last_block is not None:
			clb = self.clip_last_block
			if (not isinstance(clb, list)):
				raise TypeError, "Expecting a two element list for 'clip_last_block'. Got %s"%(clb)
			if len(clb)!=2:
				raise ValueError, "Expecting a two element list for 'clip_last_block'. Got %s"%(clb)
			if (clb[0] is not None) and (not isinstance(clb[0], int)):
				raise ValueError, "The first element of 'clip_last_block' must be an integer or None. Got %s"%(clb[0])
			if (clb[1] is not None) and (not isinstance(clb[1], int)):
				raise ValueError, "The second element of 'clip_last_block' must be an integer or None. Got %s"%(clb[1])
			if ((clb[0] is not None) and (clb[0]<1)) or ((clb[1] is not None) and (clb[1]<1)):
				raise ValueError, "The elements of 'clip_last_block' may not be less than 1. The used value was %s"%(clb)
			if ((clb[0] is not None) and (clb[0]>self.block_display_layout[0])) or ((clb[1] is not None) and (clb[1]>self.block_display_layout[1])):
				raise ValueError, "The elements of 'clip_last_block'(%s) may not greater than 'block_display_layout'(%s)"%(clb, self.block_display_layout)
			
		# check that the required number of GPUs are present in rgObj's allocation
		# if combine_displays is true, then additionally we'll require that each reqlist has the same
		# number of GPUs,
		resources = self.rgObj.getResources()
		total_gpus = 0
		each_reslist_ngpus = []
		for innerRes in resources:
			# we must have one X server
			server = extractObjects(Server, innerRes)
			if len(server)<1:
				raise ValueError, "Each reslist must have atleast one X server"
			if server[0].getType() not in [None, NORMAL_SERVER]:
				raise ValueError, "Each reslist must have one normal X server"
			kbd = extractObjects(Keyboard, innerRes)
			if len(kbd)>1:
				raise ValueError, "Each reslist can have maximum of one keyboard"
			mouse = extractObjects(Mouse, innerRes)
			if len(mouse)>1:
				raise ValueError, "Each reslist can have maximum of one mouse"
		
			# accumulate the number of GPUs
			# FIXME: we need to validate all the GPUs and X servers too. What if there are double references due to manual entry ??
			gpu_list = extractObjects(GPU, innerRes)
			if len(gpu_list)==0:
				raise ValueError, "Each reslist must have at-least one GPU."

			if (self.block_type == "quadroplex"):
				if len(gpu_list)!=2:
					raise ValueError, "Each reslist must have exactly two GPU."
				sliList = extractObjects(SLI, innerRes)
				if len(sliList)!=1:
					raise ValueError, "Each reslist must have exactly one SLI."
				# FIXME: can we check the type of SLI connector & whether the GPUs passed are its GPUs
			each_reslist_ngpus.append(len(gpu_list))
			total_gpus += len(gpu_list)
		expected_gpus = self.num_blocks[0]*self.num_blocks[1]
		if self.block_type == "quadroplex":
			expected_gpus = expected_gpus*2
		if total_gpus != expected_gpus:
			raise ValueError, "Invalid Configuration. All reslists together must have exactly %d GPUs, but you have specified %d GPUs."%(expected_gpus, total_gpus)

		if self.combine_displays==True:
			for gc in each_reslist_ngpus[1:]:
				if gc != each_reslist_ngpus[0]:
					raise ValueError, "All reslists must have the same number of GPUs when you want the displays to be combined using xinerama (i.e. when combine_displays = True)"
			if each_reslist_ngpus[0] != (self.group_blocks[0]*self.group_blocks[1]):
				raise ValueError, "Number of GPUs in reslist must be the same as that needed for a full block. Found %d, expected %d"%(each_reslist_ngpus[0], (self.group_blocks[0]*self.group_blocks[1]))

		# Check display device
		if self.display_device is None:
			raise ValueError, "Display Device must be specified"
		if not isinstance(self.display_device, str):
			raise ValueError, "Display Device must be a string"
		if len(self.display_device)==0:
			raise ValueError, "Display Device must not be empty"

		# If we have nothing to validate against, then this is all we can do.
		if self.validateAgainst is None:
			return

		# Find a matching display device. 
		if isinstance(self.validateAgainst, ResourceAccess):
			try:
				candidateList = self.validateAgainst.getTemplates(DisplayDevice(self.display_device))
			except VizError, e:
				raise ValueError, "Invalid display device '%s'"%(self.display_device)
		else:
			candidateList = self.validateAgainst

		matchingMonitors = filter(lambda x:x.getType()==self.display_device, candidateList)
		if len(matchingMonitors)==0:
			raise ValueError, "Invalid display device '%s'"%(self.display_device)
		if len(matchingMonitors)>1:
			raise ValueError, "More than one matching monitors found matching '%s'. Something is really wrong!"%(self.display_device)
		self.matchedDD = matchingMonitors[0]

		if self.display_mode is not None:
			if isinstance(self.display_mode, str):
				if len(self.display_mode)==0:
					raise ValueError, "Display mode must not be empty"
				self.matchedMode = self.matchedDD.getModeByAlias(self.display_mode)
			elif isinstance(self.display_mode, list):
				try:
					self.matchedMode = self.matchedDD.findBestMatchingMode(self.display_mode)
				except ValueError, e:
					raise ValueError, "Couldn't determine a mode matching display_mode=%s. Reason: %s"%(self.display_mode, str(e))
				except TypeError, e:
					raise ValueError, "Couldn't determine a mode matching display_mode=%s. Reason: %s"%(self.display_node, str(e))
			else:
				raise ValueError, "Display mode must be a string"
		else:
			self.matchedMode = self.matchedDD.getDefaultMode()
		# Check that display mode is at-least as large as the tile_resolution 
		# If it's more than that, then we'll happily pan :-)
		if self.tile_resolution is not None:
			if (self.tile_resolution[0]<self.matchedMode['width']) or (self.tile_resolution[1]<self.matchedMode['height']):
				raise ValueError, "Specified tile resolution %s must be atleast as large as the display output %s"%(self.tile_resolution, [self.matchedMode['width'],self.matchedMode['height']])

	def setupXServers(self, templateInfo=None):
		"""
		Setup the X servers. Doesn't propagate the settings to the SSM.

		Optionally, you may pass a list of templates (display devices, ..) that will be 
		used for validation. This parameter is currently only used internally.
		"""
		# create the X servers necessary
		# if the layout is 2x1 or 1x2, then we use TwinView, not Two X screens.
		# We avoid Xinerama because of the poor performance we have observed with it
		Xservers = []
		Xscreens = []
		resources = self.rgObj.getResources()

		if templateInfo is not None:
			self.validateAgainst = templateInfo
	
		# validate & find any needed mode and devices	
		self.doValidate(self.validateAgainst)
		usedMode = copy.deepcopy(self.matchedMode)
		tile_resolution = [self.matchedMode['width'], self.matchedMode['height']]

		display_mode = self.matchedMode['alias']
			
		# compute the framebuffer size for each GPU
		fbWidth = tile_resolution[0]*self.block_display_layout[0]
		fbHeight = tile_resolution[1]*self.block_display_layout[1]

		blockDesc = { 
			'screen' : None, # The framebuffer to use for drawing to this block
			'rect_area' : None,# Coordinates, (x1,y1,x2,y2). rectangular => (0,0) is the origin and corresponds to top left. All values in pixels. 
			'gl_area' : None,# # Coordinates, (x1,y1,x2,y1). x1, x2 vary from 0 to 1, and so do x2, y2. Y increases from top to bottom, GL style
			'gpus' : [],
			'server' : None, # which server controls this block
			'posInServer' : None, # col, row position of the GPU in the server - for the purpose of group_blocks!
			'sli' : [], # SLI object for QuadroPlex
		}

		# create a block layout with which to populate all the blocks
		blockLayout = []
		blockLayoutRow = []
		for i in range(self.num_blocks[0]):
			blockLayoutRow.append(copy.deepcopy(blockDesc))
		for i in range(self.num_blocks[1]):
			blockLayout.append(copy.deepcopy(blockLayoutRow))

		rotateNormal = (self.rotate not in ['portrait', 'inverted_portrait'])
				
		# populate the blocks with the servers, gpus, kbd and mouse
		blockIndex = 0
		for innerRes in resources:
			server = extractObjects(Server, innerRes)[0] # Take the first X server
			kbd = extractObjects(Keyboard, innerRes)
			if len(kbd) == 1:
				server.setKeyboard(kbd[0])
			mouse = extractObjects(Mouse, innerRes)
			if len(mouse) == 1: 
				server.setMouse(mouse[0])
			# len(servers) can't be > 0 as we check for it earlier
			gpu_list = extractObjects(GPU, innerRes)
			# Reset all scanouts - we will define them next ourselves.
			for gpu in gpu_list:
				gpu.clearScanouts()

			if self.block_type == "gpu":
				gpuIndex = 0
				screenNumber = 0
				for gpu in gpu_list:
					colInBlock = blockIndex % self.num_blocks[0]
					rowInBlock = blockIndex / self.num_blocks[0]
					bl = blockLayout[rowInBlock][colInBlock]
					bl['server'] = server
					bl['screen'] = Screen(screenNumber)
					bl['gpus'] = [gpu]
					if self.group_blocks is not None:
						colInServer = gpuIndex % self.group_blocks[0]
						rowInServer = (gpuIndex-colInServer) / self.group_blocks[0]
					else:
						colInServer = 0
						rowInServer = 0
					bl['posInServer'] = [colInServer, rowInServer]

					# increment for next iteration
					screenNumber += 1
					gpuIndex += 1
					blockIndex += 1
			else:
				colInBlock = blockIndex % self.num_blocks[0]
				rowInBlock = blockIndex / self.num_blocks[0]
				bl = blockLayout[rowInBlock][colInBlock]

				bl['server'] = server
				bl['posInServer'] = [0, 0]
				bl['screen'] = Screen(0)
				bl['gpus'] = gpu_list
				bl['sli'] = extractObjects(SLI, innerRes)[0]


		# Compute a mapping of display outputs
		if self.remap_display_outputs is not None:
			map_do = self.remap_display_outputs
		else:
			if self.stereo_mode != "passive":
				map_do = range(self.block_display_layout[0]*self.block_display_layout[1])
			else:
				map_do = range(2) # FIXME: Hardcoded to 2, since that's the max scanouts a single GPU can drive at once!

		isSingleOutputBlock = ((self.block_display_layout[0]*self.block_display_layout[1])==1)

		# Force all bezels if needed. This is the default, since most applications cannot
		# handle irregular bezels!
		if self.bezels in [None, 'all']:
			forceBezel = True
		else:
			forceBezel = False

		if self.bezels == 'desktop':
			desktopBezel = True
		else:
			desktopBezel = False

		# Clear bezels if asked to
		if self.bezels == 'disable':
			for side in ['left','right','bottom','top']:
				usedMode['bezel'][side] = 0

		#print 
		#print 
		#forceBezel = True
		#print 'forceBezel = ',forceBezel
		#print 'num_blocks = ',self.num_blocks
		#print 'block_display_layout = ',self.block_display_layout

		if self.rotate=='portrait':
			leftEdge = 'top'
			rightEdge = 'bottom'
			topEdge = 'right'
			bottomEdge = 'left'
		elif self.rotate=='inverted_portrait':
			leftEdge = 'bottom'
			rightEdge = 'top'
			topEdge = 'left'
			bottomEdge = 'right'
		elif self.rotate=='inverted_landscape':
			leftEdge = 'right'
			rightEdge = 'left'
			topEdge = 'bottom'
			bottomEdge = 'top'
		else:
			# Normal
			leftEdge = 'left'
			rightEdge = 'right'
			topEdge = 'top'
			bottomEdge = 'bottom'

		# Get the clip value for the last block
		clb = self.clip_last_block
		# No value specified implies no clipping
		if clb is None:
			clb = self.block_display_layout
		# If one of the values is None, then it is assumed to mean "no clipping is needed in this direction" 
		if clb[0] is None:
			clb[0] = self.block_display_layout[0]
		if clb[1] is None:
			clb[1] = self.block_display_layout[1]
		#print 'clip_last_block = ', clb
		# Now, walk the blockLayout matrix 
		# Populate the screens with the GPUs
		# and compute coordinates
		curY = 0
		lastRow = self.num_blocks[1]-1
		lastCol = self.num_blocks[0]-1
		for row in range(self.num_blocks[1]):
			curX = 0 
			for col in range(self.num_blocks[0]):
				bl = blockLayout[row][col]
				if self.block_type=="gpu":
					gpu = bl['gpus'][0]

					fbHeight = 0
					lastSubRow = self.block_display_layout[1]-1
					lastSubCol = self.block_display_layout[0]-1

					# Clip if last col
					if col==lastSubCol:
						if (lastSubCol+1) > clb[0]:
							lastSubCol = clb[0]-1

					# Clip if last row
					if row==lastSubRow:
						if (lastSubRow+1) > clb[1]:
							lastSubRow = clb[1]-1

					fbHeight = 0
					originY = 0
					oY = []

					fbWidth = 0
					originX = 0	
					oX = []

					# landscape(normal) or inverted_landscape
					if topEdge in ['top','bottom']:
						for subRow in range(lastSubRow+1):
							originY = fbHeight
							# Unrotated tiled display; 
							# Bezels on top and bottom only if not on the respective edge
							includeBezel = []
							if (not ((row==0) and (subRow==0))) or forceBezel:
								#print 'Including Top Bezel'
								includeBezel.append(topEdge)
							if (not ((row==lastRow) and (subRow==lastSubRow))) or forceBezel:
								#print 'Including Bottom Bezel'
								includeBezel.append(bottomEdge)

							for bezel in includeBezel:
								if bezel=='top':
									fbHeight += usedMode['bezel']['top']
									originY += usedMode['bezel']['top']
									if desktopBezel:
										fbHeight += usedMode['bezel']['bottom']
										originY += usedMode['bezel']['bottom']
								if (bezel=='bottom') and (not desktopBezel):
									fbHeight += usedMode['bezel']['bottom']

							oY.append(originY)
							#print 'added %d to oY'%(originY)
							fbHeight += tile_resolution[1]

						for subCol in range(lastSubCol+1):
							originX = fbWidth
							# Unrotated tiled display; 
							# Bezels on left and right only if not on the respective edge
							includeBezel = []
							if (not ((col==0) and (subCol==0))) or forceBezel: # left bezel only if not the first
								includeBezel.append(leftEdge)
							if (not ((col==lastCol) and (subCol==lastSubCol))) or forceBezel:
								includeBezel.append(rightEdge)
							for bezel in includeBezel:
								if bezel=='left':
									#print 'Including Left Bezel'
									fbWidth += usedMode['bezel']['left']
									originX += usedMode['bezel']['left']
									if desktopBezel:
										fbWidth += usedMode['bezel']['right']
										originX += usedMode['bezel']['right']
								if (bezel=='right') and (not desktopBezel):
									#print 'Including Right Bezel'
									fbWidth += usedMode['bezel']['right']
							oX.append(originX)
							#print 'added %d to oX'%(originX)
							fbWidth += tile_resolution[0]
					else:
						# portrait or inverted_portrait

						for subRow in range(lastSubCol+1):
							originX = fbWidth
							includeBezel = []
							if (not ((row==0) and (subRow==0))) or forceBezel:
								includeBezel.append(topEdge)

							if (not ((row==lastRow) and (subRow==lastSubRow))) or forceBezel:
								includeBezel.append(bottomEdge)

							for bezel in includeBezel:
								if bezel=='left':
									fbWidth += usedMode['bezel']['left']
									originX += usedMode['bezel']['left']
									if desktopBezel:
										fbWidth += usedMode['bezel']['right']
										originX += usedMode['bezel']['right']
								if (bezel=='right') and (not desktopBezel):
									fbWidth += usedMode['bezel']['right']

							oX.append(originX)
							fbWidth += tile_resolution[0]

						for subCol in range(lastSubRow+1):
							originY = fbHeight
							includeBezel = []
							if (not ((col==0) and (subCol==0))) or forceBezel: # left bezel only if not the first
								includeBezel.append(leftEdge)
							if (not ((col==lastCol) and (subCol==lastSubCol))) or forceBezel:
								includeBezel.append(rightEdge)

							for bezel in includeBezel:
								if bezel=='top':
									fbHeight += usedMode['bezel']['top']
									originY += usedMode['bezel']['top']
									if desktopBezel:
										fbHeight += usedMode['bezel']['bottom']
										originY += usedMode['bezel']['bottom']
								if (bezel=='bottom') and (not desktopBezel):
									fbHeight += usedMode['bezel']['bottom']
							oY.append(originY)
							fbHeight += tile_resolution[1]

					#print 'oX = ',
					#pprint(oX)
					#print 'oY = ',
					#pprint(oY)
					scanoutIndex = 0
					for subRow in range(lastSubRow+1):
						for subCol in range(lastSubCol+1):
							# Create the scanout needed
							gpu.setScanout(
								port_index = map_do[scanoutIndex], 
								display_device = self.display_device,
								mode = display_mode,
								outputX = oX[subCol],
								outputY = oY[subRow])
							scanoutIndex += 1

					# Passive stereo needs a second scanout as well
					if self.stereo_mode == "passive":
						gpu.setScanout(
							port_index = map_do[1], 
							display_device = self.display_device,
							mode = display_mode,
							outputX = originX,
							outputY = originY)
					#pprint(gpu.getScanouts())
				else: # quadroplex block
					# we have two GPUs here
					# Setup SLI mosaic
					sli = extractObjects(SLI, innerRes)[0]
					sli.setMode("mosaic")
					bl['screen'].setGPUCombiner(sli)

					fbHeight = 0
					# Compute each framebuffer; clipping is handled by
					# usage of lastSubRow and lastSubCol
					si = -1
					numScanouts = (lastSubRow+1) * (lastSubCol+1)
					for qpRow in range(lastSubRow+1):
						originY = fbHeight
						fbHeight += tile_resolution[1]
						if ((row>0) or (qpRow>0)) or forceBezel: # first row
							fbHeight += usedMode['bezel']['top']
							originY += usedMode['bezel']['top']
							if desktopBezel:
								fbHeight += usedMode['bezel']['bottom']
								originY += usedMode['bezel']['bottom']
						if ((row<(self.num_blocks[1]-1)) or (qpRow<lastSubRow)) or forceBezel: # not last row
							if not desktopBezel:
								fbHeight += usedMode['bezel']['bottom']
					
						fbWidth = 0
						for qpCol in range(lastSubCol+1):
							si += 1
							originX = fbWidth
							fbWidth += tile_resolution[0]
							if ((col>0) or (qpCol>0)) or forceBezel: # first col
								fbWidth += usedMode['bezel']['left']
								originX += usedMode['bezel']['left']
								if desktopBezel:
									fbWidth += usedMode['bezel']['right']
									originX += usedMode['bezel']['right']
							if ((col<(self.num_blocks[0]-1)) or (qpCol<lastSubCol)) or forceBezel: # not last col ?
								if not desktopBezel:
									fbWidth += usedMode['bezel']['right']
							# determine GPU index and Port Index
							if (numScanouts == 2):
								gi = si
								pi = 0
							else:
								pi = si%2
								gi = si/2
							# and set the scanout
							bl['gpus'][gi].setScanout(
								port_index = map_do[pi],
								display_device = self.display_device,
								mode = display_mode,
								outputX = originX,
								outputY = originY)

				# end processing for this block
				bl['screen'].setFBProperty('resolution', [fbWidth, fbHeight])
				#pprint(bl['screen'].getFBProperty('resolution'))
				bl['screen'].setGPUs(bl['gpus'])
				if rotateNormal:
					bl['rect_area'] = [curX, curY, curX + fbWidth, curY+fbHeight]
				else:
					bl['rect_area'] = [curX, curY, curX + fbHeight, curY+fbWidth]
				if rotateNormal:
					curX += fbWidth
				else:
					curX += fbHeight
			# End processing for a single row by incrementing our Y
			if rotateNormal:
				curY += fbHeight # height will be constant if not rotated, so we can do this
			else:
				curY += fbWidth # width will be constant if not rotated, so we can do this

		# Make another pass in terms of blocks(as in 'X server')
		if self.group_blocks is not None:
			numRowsPerServer = self.num_blocks[1]/self.group_blocks[1]
			numColsPerServer = self.num_blocks[0]/self.group_blocks[0]
			for serverRow in range(numRowsPerServer):
				for serverCol in range(numColsPerServer):
					originCol = serverCol*self.group_blocks[0]
					originRow = serverRow*self.group_blocks[1]
					bl = blockLayout[originRow][originCol]
					originArea = bl['rect_area']
					for subRow in range(self.group_blocks[1]):
						for subCol in range(self.group_blocks[0]):
							screen = blockLayout[originRow+subRow][originCol+subCol]['screen']
							subArea = blockLayout[originRow+subRow][originCol+subCol]['rect_area']
							screen.setFBProperty('position', [ subArea[0]-originArea[0], subArea[1]-originArea[1] ])
							#pprint(screen.getFBProperty('resolution'))

		# Last steps
		for row in range(self.num_blocks[1]):
			for col in range(self.num_blocks[0]):
				screen = blockLayout[row][col]['screen']
				server = blockLayout[row][col]['server']
				# Handle stereo
				if self.stereo_mode is not None:
					screen.setFBProperty('stereo', self.stereo_mode)
				# Setup rotation & stereo
				if self.rotate is not None:
					screen.setFBProperty('rotate', self.rotate)

				server.addScreen(screen)
				# Enforce Xinerama
				if self.combine_displays:
					server.combineScreens(True)

		self.actualLayoutMatrix = blockLayout

		if self.combine_displays:
			numRowsPerServer = self.num_blocks[1]/self.group_blocks[1]
			numColsPerServer = self.num_blocks[0]/self.group_blocks[0]
			blockLayoutXinerama = []
			blockLayoutRow = []
			for i in range(numColsPerServer):
				blockLayoutRow.append(copy.deepcopy(blockDesc))
			for i in range(numRowsPerServer):
				blockLayoutXinerama.append(copy.deepcopy(blockLayoutRow))

			for serverRow in range(numRowsPerServer):
				for serverCol in range(numColsPerServer):
					originCol = serverCol*self.group_blocks[0]
					originRow = serverRow*self.group_blocks[1]
					bl = blockLayout[originRow][originCol]
					blx = blockLayoutXinerama[serverRow][serverCol]
					blx['screen']=bl['server'].getCombinedScreen()
					blx['server']=bl['server']
					blx['gpus']=[]
					blx['sli']=[]
					# compute a bounding box - couldn't this be computed using the combined screen
					maxX = 0
					maxY = 0
					minX = 10000000
					minY = 10000000
					for subRow in range(self.group_blocks[1]):
						for subCol in range(self.group_blocks[0]):
							screen = blockLayout[originRow+subRow][originCol+subCol]['screen']
							subArea = blockLayout[originRow+subRow][originCol+subCol]['rect_area']
							x1 = subArea[0]
							y1 = subArea[1]
							x2 = subArea[2]
							y2 = subArea[3]
							maxX = max(x1,x2,maxX)
							maxY = max(y1,y2,maxY)
							minX = min(x1,x2,minX)
							minY = min(y1,y2,minY)
							blx['gpus'] += blockLayout[originRow+subRow][originCol+subCol]['gpus']
							blx['sli'] += blockLayout[originRow+subRow][originCol+subCol]['sli']
					blx['rect_area']=[minX, minY, maxX, maxY]
			self.effectiveLayoutMatrix = blockLayoutXinerama
			computeGLAreaFor = [self.actualLayoutMatrix, self.effectiveLayoutMatrix]
		else:
			# retain the layout matrix
			self.effectiveLayoutMatrix = blockLayout
			computeGLAreaFor = [self.actualLayoutMatrix]

		for layout in computeGLAreaFor:
			# Compute the gl_area values
			lastBlock = layout[-1][-1]
			maxRectX = lastBlock['rect_area'][2]
			maxRectY = lastBlock['rect_area'][3]
			for row in range(len(layout)):
				for col in range(len(layout[0])):
					bl = layout[row][col]
					x1 = bl['rect_area'][0]/float(maxRectX)
					y1 = 1.0-bl['rect_area'][1]/float(maxRectY)
					x2 = bl['rect_area'][2]/float(maxRectX)
					y2 = 1.0-bl['rect_area'][3]/float(maxRectY)
					bl['gl_area'] = [x1,y2,x2,y1]

		#pprint(self.effectiveLayoutMatrix)

	def getActualLayoutMatrix(self):
		"""
		Get the "actual" layout matrix. This reflects the way in which the tiled
		display is laid out, without accounting for xinerama (if any)
		"""
		return self.actualLayoutMatrix

	def getLayoutMatrix(self):
		"""
		Get the effective layout matrix. If xinerama is in use, you get t
		"""
		return self.effectiveLayoutMatrix

	def getLayoutDimensions(self):
		return [len(self.effectiveLayoutMatrix[0]), len(self.effectiveLayoutMatrix)]

		
def deserializeVizResource(domNode, classList=[GPU, SLI, Server, Keyboard, Mouse]):
	"""
	Convenience function to deserialize VizResource subclasses.
	"""
	#print 'Decoding :', domNode.toxml()
	# check if this dom corresponds to any viz resource class
	for className in classList:
		if domNode.nodeName == className.rootNodeName:
				newObject = className()
				newObject.deserializeFromXML(domNode)
				return newObject
	raise ValueError, "Could not deserialize VizResource : Unrecognized object '%s'"%(domNode.nodeName)


def findMatchingObjects(classTemplate, searchOb, objectList):
	if not isinstance(objectList, list):
		objectList = [ objectList ]
	obList = extractObjects(classTemplate, objectList)
	retList = []
	for ob in obList:
		if ob.typeSearchMatch(searchOb):
			retList.append(ob)
	return retList

def extractObjects(classTemplate, objectList):
	"""
	Convenience function to extract objects matching
	a given class from a list
	"""
	ret = []
	for item in objectList:
		if isinstance(item, list):
			itemList = item
		elif isinstance(item, VizResourceAggregate):
			itemList = item.getResources()
		elif isinstance(item, VizResource):
			itemList = [item]
		else:
			raise TypeError, "Bad object in input list"

		for innerItem in itemList:
			if isinstance(innerItem, list):
				resList = innerItem
			else:
				resList = [innerItem]
			for res in resList:
				if isinstance(res, classTemplate):
					ret.append(res)
	return ret

class Allocation:
	"""
	Class encapsulating a set of resources as an allocation.
	"""

	def __init__(self, id, resList):
		self.isValid = True
		self.id = id
		self.resources = resList
		self.xprocs = []

	def __del__(self):
		pass

	def getId(self):
		return self.id

	def getResources(self):
		return self.resources

	def getServers(self):
		"""
		Return a list of all servers in this allocation
		"""
		allServers = []
		for innerList in self.resources:
			if isinstance(innerList, list):
				if isinstance(innerList[0], VizResourceAggregate):
					resList = innerList[0].getResources()
					realRes = []
					for item in resList:
						if isinstance(item, list):
							realRes += item
						else:
							realRes.append(item)
				else:
					realRes = innerList
			else:
				realRes = [innerList]

			allServers += extractObjects(Server, realRes)

		allSharedGPUs = extractObjects(GPU, self.resources)
		allSharedGPUs = filter(lambda x:x.isShared(), allSharedGPUs)
		allServers += map(lambda x:x.getSharedServer(), allSharedGPUs)

		return allServers

	def setupViz(self, resourceAccess):
		"""
		Setup the visualization environment for this allocation.
		This typically sets up the Resource Groups with valid resType(handlers).
		The primary usage of this is to setup display surfaces, but could
		be extended using the handler mechanism.
		"""

		if not isinstance(resourceAccess, ResourceAccess):
			raise ValueError, "Bad type for argument resourceAccess '%s'. Expected ResourceAccess."%(allocObj.__class__)

		# Ensure that all resource group X servers are setup properly
		for item in self.resources:
			if isinstance(item, ResourceGroup):
				item.setupXServers(resourceAccess)
		
		# Make a list of _all_servers in this allocation !
		allServers = self.getServers()

		# Eliminate duplicates due to shared GPUs - the UpdateServerConfig
		# message will not tolerate multiple instances of the same X server.
		uniqServers = {}
		for thisServer in allServers:
			if not uniqServers.has_key(thisServer.hashKey()):
				uniqServers[thisServer.hashKey()] = thisServer
		uniqServers = uniqServers.values()

		# We can do setup only on the 'normal' servers
		serverList = filter(lambda x: x.getType()==NORMAL_SERVER, uniqServers)

		# Update the configuration of these on the SSM
		resourceAccess.updateServerConfig(self.getId(), serverList)
		
				
	def startViz(self, resourceAccess, timeout=X_WAIT_TIMEOUT, suppressMessages=True):
		if not isinstance(resourceAccess, ResourceAccess):
			raise ValueError, "Bad type for argument resourceAccess '%s'. Expected ResourceAccess."%(allocObj.__class__)

		# Make a list of _all_servers in this allocation !
		allServers = self.getServers()

		# We can start X servers on 'normal' servers
		serverList = filter(lambda x: x.getType()==NORMAL_SERVER, allServers)

		if len(serverList)==0:
			raise VizError(VizError.BAD_CONFIGURATION, "This allocation has no usable X servers")

		# We can do something only if the servers are setup completely
		serversToStart = filter(lambda x: x.hasValidRuntimeConfig(), serverList)

		if len(serversToStart)<len(serverList):
			# Commenting out this warning - since it interferes with GUIs 
			#print 'WARNING: %d servers were not setup with a valid runtime configuration. Skipping them'%(len(serverList)-len(serversToStart))
			pass

		if len(serversToStart)==0:
			raise VizError(VizError.BAD_CONFIGURATION, "There are no servers with a valid configuration to start")

		# Start the X servers !
		for srv in serversToStart:
			if srv.isShared():
				p = srv.start(self.id, suppressOutput=suppressMessages, suppressErrors=suppressMessages)
			else:
				p = srv.start(suppressOutput=suppressMessages, suppressErrors=suppressMessages)
			self.xprocs.append(p)

		# Wait for them to start
		try:
			resourceAccess.waitXState(self, 1, timeout, serversToStart)
		except Exception, e: # FIXME: Exception OR BaseException ?? Seems to have a dependency on Python Version
			# If there's a problem, then they all have to GO!
			# Kill all X servers !!!
			try:
				self.stopViz(resourceAccess)
			except VizError, e2:
				pass
			raise e

	def __emptyXprocs(self):
		for proc in self.xprocs:
			try:
				proc.kill()
			except OSError, e:
				pass
		self.xprocs = []

	def stopViz(self, resourceAccess, timeout = X_WAIT_TIMEOUT):
		if not isinstance(resourceAccess, ResourceAccess):
			raise ValueError, "Bad type for argument resourceAccess '%s'. Expected ResourceAccess."%(allocObj.__class__)

		#print 'Stopping X servers for allocation %d'%(self.getId())
		resourceAccess.stopXServers(self)

		# Wait for them to stop
		try:
			resourceAccess.waitXState(self, 0, timeout)
		except VizError, e: 
			self.__emptyXprocs()
			raise e

		self.__emptyXprocs()

def sendMessageOnSocket(sock, message):
	dataLen = '%d'%(len(message))
	dataLen = dataLen + ' '*(5-len(dataLen)) # NOTE: the '5' is a dependency from vs-ssm.py

	sock.send(dataLen)
	sock.send(message)

def readMessageFromSocket(sock):
	try:
		dataLenStr = sock.recv(5)
		if len(dataLenStr)==0:
			raise VizError(VizError.NOT_CONNECTED, "Socket Disconnected")
		if len(dataLenStr)!=5:
			raise VizError(VizError.BAD_PROTOCOL, "Message length should be indicated in 5 bytes, not '%s'"%(dataLenStr))

		try:
			dataLen = int(dataLenStr)
			if dataLen<=0:
				raise VizError(VizError.BAD_PROTOCOL, "Message length = %d is invalid"%(dataLen))
		except ValueError, e:
			raise VizError(VizError.BAD_PROTOCOL, "Message length = %s is invalid"%(dataLenStr))
		
		# FIXME: is the below loop necessary ? it's a blocking socket afterall, right ?
		payload =''
		while len(payload)<dataLen:
			data = sock.recv(dataLen-len(payload))
			if len(data)==0:
				break
			payload = payload + data

		if len(payload)!=dataLen:
			raise VizError(VizError.BAD_PROTOCOL, "Incomplete message. Expected message of length %s, got message of lenght %d"%(dataLenStr, len(payload)))
	except socket.error, e:
		raise VizError(VizError.SOCKET_ERROR, str(e))

	return payload

def getMasterParameters(filepath = masterConfigFile):
	try:
		dom = minidom.parse(filepath)
	except xml.parsers.expat.ExpatError, e:
		raise ValueError, str(e)
	rootNode = dom.documentElement
	systemNode = domutil.getChildNode(rootNode, 'system')
	if systemNode is None:
		raise VizError(VizError.BAD_CONFIGURATION, "Incorrect Master Configuration (%s). Need to have a valid system specification."%(filepath))
	typeNode = domutil.getChildNode(systemNode, 'type')
	if typeNode is None:
		raise VizError(VizError.BAD_CONFIGURATION, "Incorrect Master Configuration File (%s). Need to have a valid system specification."%(filepath))
	systemType = domutil.getValue(typeNode)
	if systemType == "standalone":
		raise VizError(VizError.BAD_CONFIGURATION, "Accessing resources is not possible on a standalone system; bad Master Configuration File(%s)"%(filepath))
	masterNode = domutil.getChildNode(systemNode, "master")
	if masterNode is None:
		raise VizError(VizError.BAD_CONFIGURATION, "Master Node is not specified in Master Configuration File(%s)"%(filepath))
	master = domutil.getValue(masterNode)
	if len(master)==0:
		raise VizError(VizError.BAD_CONFIGURATION, "Master Node cannot be empty in Master Configuration File(%s)"%(filepath))
	portNode = domutil.getChildNode(systemNode, "master_port")
	if portNode is None:
		raise VizError(VizError.BAD_CONFIGURATION, "Master Port is not specified in Master Configuration File(%s)"%(filepath))
	masterPortStr = domutil.getValue(portNode)
	if len(masterPortStr)==0:
		raise VizError(VizError.BAD_CONFIGURATION, "Master Port cannot be empty in Master Configuration File(%s)"%(filepath))
	try:
		if master != "localhost":
			masterPort = int(masterPortStr)
			if (masterPort<=0) or (masterPort>65535):
				raise ValueError, "Master Port must be a valid TCP port number"
		else:
			if not (masterPortStr.startswith("/tmp/")):
				raise ValueError, "Master Port (unix socket name) must begin with /tmp/"
			masterPort = masterPortStr
	except ValueError, e:
		raise VizError(VizError.BAD_CONFIGURATION, "Bad port number value in Master Configuration File(%s). Reason: %s"%(filepath, str(e)))

	authNode = domutil.getChildNode(systemNode, "master_auth")
	if authNode is None:
		raise VizError(VizError.BAD_CONFIGURATION, "Authorization method for communication to Master is not specified in Master Configuration File(%s)"%(filepath))
	masterAuth = domutil.getValue(authNode)
	if len(masterAuth)==0:
		raise VizError(VizError.BAD_CONFIGURATION, "Authorization method for communication to Master cannot be empty in Master Configuration File(%s)"%(filepath))
	if masterAuth not in ['None','Munge']:
		raise VizError(VizError.BAD_CONFIGURATION, "Improper Authorization method specified for communication to Master in Master Configuration File(%s)"%(filepath))
		
	return [master, masterPort, masterAuth]

class ResourceAccess:
	"""
	The main class for gaining access to resources.

	Usage of this class is needed for allocation/cleanup and interacting with resources.
	"""

	def __fini__(self):
		# Finish handler for disconnecting from SSM.
		# Not necessary at all - given that the socket will automatically disconnect
		# anyway !
		self.__endConnection()

	def __init__(self, cleanupOnDisconnect=True):
		"""
		If cleanupOnDisconnect is True, then all allocations made on this connection
		are freed up when the connection to the SSM is either closed OR lost. The cleanup
		is done on the SSM side.

		This flag is provided as a convenience to user scripts.  

		Resource cleanup in user scripts tends to become complicated, especially 
		when scripts are either terminated or fail (could be during development or due to
		runtime conditions). This flag helps in such cases. By shifting 
		the burden of the cleanup to the server side, we guarantee proper cleanup 
		on script termination. This way, user scripts do not lead to an unusable system.
		"""
		self.sock = None
		if cleanupOnDisconnect is None:
			raise ValueError, "Bad value for cleanupOnDisconnect"
		if not isinstance(cleanupOnDisconnect, bool):
			raise ValueError, "cleanupOnDisconnect must be a boolean"

		self.cleanupOnDisconnect = cleanupOnDisconnect

		[self.masterHost, self.masterPort, self.masterAuth] = getMasterParameters()
		self.start()

	def start(self, host=None, port=None):
		"""
		Connect to the SSM. Practically, every useful client will need to do this.
		"""
		if host is None:
			host = self.masterHost
		if port is None:
			port = self.masterPort

		payload = '<client><cleanupOnDisconnect>%d</cleanupOnDisconnect></client>'%(self.cleanupOnDisconnect)

		# Connect using the right socket type, depending on the host
		try:
			if host == "localhost":
				sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
				sock.connect(SSM_UNIX_SOCKET_ADDRESS)
			else:
				sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
				sock.connect((host,int(port)))
		except socket.error, e:
			raise VizError(VizError.NOT_CONNECTED, "Failed to connect to SSM. Please ensure that it is running. Reason: %s"%(str(e)))

		if host != "localhost":
			# If we use TCP sockets, then we'll have to authenticate
			payload = encode_message_with_auth(self.masterAuth, payload)

		self.sock = sock

		# Cleanup if sending the message failed
		try:
			sendMessageOnSocket(sock, payload)
		except Exception, e:
			self.__endConnection()
			raise e

	def __endConnection(self):
		if self.sock is not None:
			try:
				closeSocket(self.sock)
			except socket.error, e:
				pass
		self.sock = None

	def stop(self):
		"""
		Disconnect from the SSM
		"""
		self.__endConnection()

	def __sendAndRecvMessage(self, message):
		"""
		Internal use function.

		Send message and receive response from the SSM, all in one step.
		Returns [statusCode, statusMessage, dom] where dom is the XML tree representing the response
		All errors are handled. Including this function has made the code so readable !
		"""
		try:
			sendMessageOnSocket(self.sock, message)
			msg = readMessageFromSocket(self.sock)
			dom = None
			try:
				dom = xml.dom.minidom.parseString(msg)
			except xml.parsers.expat.ExpatError, e:
				# bad return XML point to deep problems
				raise VizError(VizError.INTERNAL_ERROR, "Improperly formed return XML from SSM.\n XML Error : %s \nReturned XML:%s\n"%(str(e),msg))
			doc = dom.documentElement
			responseNode = domutil.getChildNode(doc, "response")
			if responseNode is None:
				raise VizError(VizError.BAD_PROTOCOL, "Incorrect XML response from SSM - missing response node")
			statusNode = domutil.getChildNode(responseNode, "status")
			if statusNode is None:
				raise VizError(VizError.BAD_PROTOCOL, "Incorrect XML response from SSM - missing status node")
			statusValue = domutil.getValue(statusNode)
			if len(statusValue)==0:
				raise VizError(VizError.BAD_PROTOCOL, "Incorrect XML response from SSM - status is empty")
			try:
				statusCode = int(statusValue)
			except ValueError, e:
				raise VizError(VizError.BAD_PROTOCOL, "Incorrect XML response from SSM - bad status value. Reason %s"%(str(e)))
			messageNode = domutil.getChildNode(responseNode, "message")
			if messageNode is None:
				statusMessage = ""
			else:
				statusMessage = domutil.getValue(messageNode)
		except VizError, e:
			print "************** DISCONNECTING CLIENT ******************" 
			self.__endConnection()
			print "VizError :  %s"%(repr(e))
			raise 

		return [statusCode, statusMessage, dom]
	def attach(self, allocId):
		"""
		attach(allocId)

		Attach to an  existing allocation. Only the user to whom the allocation belongs
		(or root) can attach to the allocation.

		Return value :

		On successful allocation, an allocation object is returned that contains all the resources
		allocated to this allocation ID.

		On failure, a VizError exception is thrown.
		"""
		if self.sock is None:
			raise VizError(VizError.NOT_CONNECTED, "Not connected to SSM")

		if not isinstance(allocId, int):
			raise TypeError, "You need to pass an integer as allocId"

		if allocId<0:
			raise ValueError, "allocId needs to be positive"

		message = "<ssm><attach><allocId>%d</allocId></attach></ssm>"%(allocId)

		statusCode, statusMessage, dom = self.__sendAndRecvMessage(message)

		if statusCode!=0:
			raise VizError(VizError.USER_ERROR, statusMessage)

		return self.__decodeAllocation(dom)
	
	def allocate(self, reqResList, chooseNodeList=[], appName=None):
		"""
		allocate(reqResList, chooseNodeList)
		
		Allocate resources. reqResList is a list of resource requirements, with each element being a required
		resource.

		An appName can be given to an allocation. This can help users identify an allocation more
		naturally.

		Resources are chosen from chooseNodeList. If chooseNodeList is empty, then all nodes are 
		candidates.

		The viz resources that may be allocated by this call are
		  - X servers
		  - GPUs
		  - Input devices : Keyboard, mice
		  - Resource Groups - these are aggregates of the above resources. If you pass an object with resources inside it, then the SSM will allocate the resources you need & ignore the name.  If no resources are specified but you pass a resource group name known to the SSM, then the SSM will allocate that. 
		  - VizNodes. You may allocate complete nodes by passing just the nodename. You may allocate resources inside nodes by adding them to nodes. If a name s not specified for the node, then it is assumed that the best fit node will be chosen.
		
		Returned Value : 
		
		On successful allocation, an allocation object is returned. This allocation object encapsulates the allocated resource as  list.
		Each element of this list corresponds to the requirement in the same position in the reqResList.
		On failure, a VizError exception is thrown.
		"""
		if appName is None:
			appName = sys.argv[0]
			# remove any path prefix
			exeName = appName.rfind('/')
			if exeName != -1:
				appName = appName[exeName+1:]
		if self.sock is None:
			raise VizError(VizError.NOT_CONNECTED, "Not connected to SSM")

		if not isinstance(chooseNodeList, list):
			raise TypeError, "You need to pass a list for possible nodes to choose from"
		nodeSpec = ""
		for nodeName in chooseNodeList:
			if not isinstance(nodeName, str):
				raise TypeError, "Each item in the list of nodes must be a string"
			else:
				nodeSpec += "<search_node>%s</search_node>"%(nodeName)

		message = """<ssm><allocate>"""
		if appName is not None:
			message += "<appName>%s</appName>"%(appName)
		for req in reqResList:
			message = message+ "<resdesc>"
			if type(req) is list:
				message = message + "<list>"
				for req2 in req:
					if isinstance(req2, VizResourceAggregate):
						raise ValueError, "allocate() does not all VizResourceAggregate objects inside lists"
					elif isinstance(req2, VizResource):
						message = message + "%s"%(req2.serializeToXML())
					else:
						raise ValueError, "allocate() accepts only aggregation of VizResource objects, or single VizResourceAggregate objects."
				message = message + "</list>"
			elif isinstance(req, VizResource):
				message = message+ "%s"%(req.serializeToXML())
			elif isinstance(req, VizResourceAggregate):
				message = message+ "%s"%(req.serializeToXML())
			else:
				raise ValueError, "allocate() does not accept this object %s"%(repr(req))
			message = message+ "</resdesc>"

		message += nodeSpec
		message = message + "</allocate></ssm>"

		statusCode, statusMessage, dom = self.__sendAndRecvMessage(message)

		if statusCode!=0:
			raise VizError(VizError.USER_ERROR, statusMessage)

		return self.__decodeAllocation(dom)

	def __decodeAllocation(self, dom):
		# If we came here, then the allocation was successful
		# create an Allocation object by deserializing the allocation
		allocationNode = dom.getElementsByTagName("allocation")[0]
		resourceNodes = domutil.getChildNodes(allocationNode, "resource")
		allocRes = [] # the objects that we allocate representing the resources
		for resNode in resourceNodes:
			valueNode = domutil.getChildNode(resNode, "value")
			allValueChildren = domutil.getAllChildNodes(valueNode)
			if len(allValueChildren)!=1:
				raise VizError(VizError.INTERNAL_ERROR, "Incorrect return XML from the SSM in decodeAllocation")
			
			vc = allValueChildren[0]
			if vc.nodeName == "list":
				innerRes = []
				allResNodes = domutil.getAllChildNodes(vc)
				for node in allResNodes:
					# create a factory to create objects corresponding to this
					# XML
					decodedObj = deserializeVizResource(node, [GPU, SLI, Server, Keyboard, Mouse, ResourceGroup, VizNode])
					if isinstance(decodedObj, VizResourceAggregate):
						raise VizError(VizError.INTERNAL_ERROR, "Incorrect return XML from the SSM in decodeAllocation")
					innerRes.append(decodedObj)
			else:
				decodedObj = deserializeVizResource(vc, [GPU, Server, SLI, Keyboard, Mouse, ResourceGroup, VizNode])
				#
				# Setup the X servers for ResourceGroups. The user can tweak
				# things after the call to allocate
				#
				if isinstance(decodedObj, ResourceGroup):
					# FIXME: If something fails here, then do we know who is to blame. The caller !?
					decodedObj.setupXServers(self)
				innerRes = decodedObj
			allocRes.append(innerRes)

		allocId = int(domutil.getValue(dom.getElementsByTagName("allocId")[0]))
		allocObj = Allocation(allocId, allocRes)

		# Set validation information on the created GPUs.
		# This will help reduce user mistakes.
		# FIXME: is this the earliest time we can do this ??
		allocGPUs = extractObjects(GPU, allocRes)
		for gpu in allocGPUs:
			gpu.setResourceAccess(self)

		# Nothing succeeds like success !
		return allocObj

	def getAllocationList(self, allocId=None):
		"""
		"""
		if self.sock is None:
			raise VizError(VizError.NOT_CONNECTED, "Not connected to SSM")
		if allocId is None:
			allocStr = ""
		else:
			allocStr = "<allocId>%d</allocId>"%(allocId)

		message = """
		<ssm>
			<query_allocation>%s</query_allocation>
		</ssm>
		"""%(allocStr)

		statusCode, statusMessage, dom = self.__sendAndRecvMessage(message)
		if statusCode!=0:
			raise VizError(VizError.USER_ERROR, statusMessage)

		returnedMatches = [] 
		rvNode = dom.getElementsByTagName("return_value")[0] # FIXME: replace this with "ssm/response/return_value"
		for allocNode in rvNode.childNodes:
			if allocNode.nodeType != allocNode.ELEMENT_NODE:
				continue
			if allocNode.nodeName == "allocation":
				allocIdNode = domutil.getChildNode(allocNode, "allocId")
				userNameNode = domutil.getChildNode(allocNode, "userName")
				resourceNode = domutil.getChildNode(allocNode, "resources")
				startTimeNode = domutil.getChildNode(allocNode, "startTime")
				appNameNode = domutil.getChildNode(allocNode, "appName")
				resourceList = []
				for resNode in resourceNode.childNodes:
					if resNode.nodeType != resNode.ELEMENT_NODE:
						continue
					newResource = deserializeVizResource(resNode)
					resourceList.append(newResource)

				returnedMatches.append({
					'allocId':int(domutil.getValue(allocIdNode)),
					'user':domutil.getValue(userNameNode), 
					'resources':resourceList, 
					'startTime': int(domutil.getValue(startTimeNode)),
					'appName': domutil.getValue(appNameNode)
				})

		return returnedMatches

	def queryResources(self, what=None):
		"""
		"""
		if self.sock is None:
			raise VizError(VizError.NOT_CONNECTED, "Not connected to SSM")
		query = ""
		if what is not None:
			if not isinstance(what, VizResource):
				raise TypeError, "Expecting a VizResource"
			else:
				query = what.serializeToXML()
		message = """
		<ssm>
			<query_resource>%s</query_resource>
		</ssm>
		"""%(query)

		statusCode, statusMessage, dom = self.__sendAndRecvMessage(message)
		if statusCode!=0:
			raise VizError(VizError.USER_ERROR, statusMessage)

		returnedMatches = [] 
		rvNode = dom.getElementsByTagName("return_value")[0] # FIXME: replace this with "ssm/response/return_value"
		for resNode in rvNode.childNodes:
			if resNode.nodeType != resNode.ELEMENT_NODE:
				continue

			decodedObj = deserializeVizResource(resNode, [GPU, Server, SLI, Keyboard, Mouse, ResourceGroup, VizNode])
			returnedMatches.append(decodedObj)

		return returnedMatches

	def getServerConfig(self, searchServer):
		if self.sock is None:
			raise VizError(VizError.NOT_CONNECTED, "Not connected to SSM")
		if not isinstance(searchServer,Server):
			raise ValueError, "I expect the searchServer to be a Server"

		message = """
		<ssm>
			<get_serverconfig>
			%s
			</get_serverconfig>
		</ssm>
		"""%(searchServer.serializeToXML())

		statusCode, statusMessage, dom = self.__sendAndRecvMessage(message)
		if statusCode!=0:
			raise VizError(VizError.USER_ERROR, statusMessage)

		rvNode = dom.getElementsByTagName("return_value")[0] # FIXME: replace this with "ssm/response/return_value"
		srvNode = domutil.getChildNode(rvNode, Server.rootNodeName)
		decodedObj = deserializeVizResource(srvNode, [Server])

		return decodedObj

	def getTemplates(self, searchOb=None):
		if self.sock is None:
			raise VizError(VizError.NOT_CONNECTED, "Not connected to SSM")

		if searchOb is None:
			searchExpr = ""
		elif isinstance(searchOb, GPU) or isinstance(searchOb, DisplayDevice):
			searchExpr = searchOb.serializeToXML()
		else:
			raise ValueError, "Expected GPU or DisplayDevice or None as search object"
		
		message = "<ssm><get_templates>%s</get_templates></ssm>"%(searchExpr)

		statusCode, statusMessage, dom = self.__sendAndRecvMessage(message)
		if statusCode!=0:
			raise VizError(VizError.USER_ERROR, statusMessage)

		rvNode = dom.getElementsByTagName("return_value")[0] # FIXME: replace this with "ssm/response/return_value"
		allTemplateNodes = domutil.getAllChildNodes(rvNode)
		retObs = []
		for tNode in allTemplateNodes:
			try:
				newOb = deserializeVizResource(tNode, [GPU, DisplayDevice, Keyboard, Mouse])
			except ValueError, e:
				raise VizError(VizError.INTERNAL_ERROR, "Incorrect return XML from the SSM during getTemplates")
			retObs.append(newOb)

		return retObs

	def createGPU(self, resIndex=None, hostName=None, model=None):
		"""
		Create a GPU. Using this function may provide better validation compared to other methods.

		FIXME: should we enhance this to fail if there are no instances of
		the specified GPU model ?
		"""
		if self.sock is None:
			raise VizError(VizError.NOT_CONNECTED, "Not connected to SSM")
		gpuTemplate = GPU(resIndex, hostName, model)

		# If a complete address is specified, then we'll get all the details NOW !
		if gpuTemplate.isCompletelyResolvable():
			gpuTemplate = self.queryResources(gpuTemplate)
		elif model is not None:
			gpuTemplate = self.getTemplates(gpuTemplate)[0]

		gpuTemplate.setResourceAccess(self) # Let the GPU do validation using us later

		return gpuTemplate

	def createDisplayDevice(self, displayDeviceType):
		"""
		Create a Display device of given type. This function will fail
		if this kind of display device is not defined in the system.
		"""
		if self.sock is None:
			raise VizError(VizError.NOT_CONNECTED, "Not connected to SSM")

		if not isinstance(displayDeviceType, str):
			raise TypeError, "Expected type of display device as a string"
		if len(displayDeviceType)==0:
			raise ValueError, "You've passed an empty string. Pass a display device type"

		return self.getTemplates(DisplayDevice(displayDeviceType))[0]
		

	def updateServerConfig(self, allocId, serverList):
		if self.sock is None:
			raise VizError(VizError.NOT_CONNECTED, "Not connected to SSM")
		if type(allocId) is not int:
			raise ValueError, "Allocation ID needs to be an integer"
		if type(serverList) is not list:
			raise ValueError, "I expect serverList to be a server"
		newServerConfig = ""
		for s in serverList:
			if not isinstance(s,Server):
				raise ValueError, "All elements of serverList need to be objects of class Server"
			if not s.isCompletelyResolvable():
				raise ValueError, "Incomplete X server passed %s"%(s.hashKey())
			newServerConfig = newServerConfig + s.serializeToXML()

		message = """
		<ssm>
			<update_serverconfig>
				<allocId>%d</allocId>
				%s
			</update_serverconfig>
		</ssm>
		"""%(allocId, newServerConfig)

		statusCode, statusMessage, dom = self.__sendAndRecvMessage(message)
		if statusCode!=0:
			raise VizError(VizError.USER_ERROR, statusMessage)

		# Success !
		return

	def waitXState(self, allocObj, state, timeout=X_WAIT_TIMEOUT, serverList=None):
		"""
		Wait till specified serves on an allocation reach required 'state'.
		Timeout is specified in seconds. Pass None for an infinite timeout.
		"""
		if self.sock is None:
			raise VizError(VizError.NOT_CONNECTED, "Not connected to SSM")
		if not isinstance(allocObj, Allocation):
			raise ValueError, "You need to pass an Allocation object to deallocate"

		if (type(state) is not int) or (state<0) or (state>1):
			raise ValueError, "State needs to be an integer (0 or 1)"
		if timeout is not None:
			if (type(timeout) is not int) or (timeout<0) or (timeout>X_WAIT_MAX):
				raise ValueError, "Timeout needs to be an integer between 0 and %d (secs)"%(X_WAIT_MAX)

		waitServers = ""
		if serverList is not None:
			if type(serverList) is not list:
				raise ValueError, "I expect serverList to be a server"
			for s in serverList:
				if not isinstance(s,Server):
					raise ValueError, "All elements of serverList need to be objects of class Server"
				waitServers = waitServers + s.serializeToXML()
		if timeout is not None:
			timeoutStr = "<timeout>%d</timeout>"%(timeout)
		else:
			timeoutStr = ""
		message = """
		<ssm>
			<wait_x_state>
				<allocId>%d</allocId>
				<newState>%d</newState>
				%s
				%s
			</wait_x_state>
		</ssm>
		"""%(allocObj.getId(), state, timeoutStr, waitServers)

		statusCode, statusMessage, dom = self.__sendAndRecvMessage(message)
		if statusCode!=0:
			raise VizError(VizError.USER_ERROR, statusMessage)

		# Success !
		return

	def stopXServers(self, allocObj, serverList=None):
		if self.sock is None:
			raise VizError(VizError.NOT_CONNECTED, "Not connected to SSM")
		if not isinstance(allocObj, Allocation):
			raise ValueError, "You need to pass an Allocation object to deallocate"

		stopServers = ""
		if serverList is not None:
			if type(serverList) is not list:
				raise ValueError, "I expect serverList to be a server"
			for s in serverList:
				if not isinstance(s,Server):
					raise ValueError, "All elements of serverList need to be objects of class Server"
				stopServers = stopServers + s.serializeToXML()

		message = """
		<ssm>
			<stop_x_server>
				<allocId>%d</allocId>
				%s
			</stop_x_server>
		</ssm>
		"""%(allocObj.getId(), stopServers)

		statusCode, statusMessage, dom = self.__sendAndRecvMessage(message)
		if statusCode!=0:
			raise VizError(VizError.USER_ERROR, statusMessage)

		# Success !
		return

	def deallocate(self, allocation):
		"""
		Free up an allocation. You may pass in an allocation object, or an allocation ID
		"""
		if self.sock is None:
			raise VizError(VizError.NOT_CONNECTED, "Not connected to SSM")
		if isinstance(allocation, Allocation):
			# get the ID corresponding to this allocation
			resId = allocation.getId()
		elif isinstance(allocation, int):
			resId = allocation
		else:
			raise TypeError, "You need to pass an Allocation object or an allocation ID to deallocate"

		message = "<ssm><deallocate><allocId>%d</allocId></deallocate></ssm>"%(resId)

		statusCode, statusMessage, dom = self.__sendAndRecvMessage(message)
		if statusCode!=0:
			raise VizError(VizError.USER_ERROR, statusMessage)

		# Success !
		return

	def refreshResourceGroups(self):
		"""
		This is an administrative message. Will succeed only root sends it.

		Sending this message causes the SSM to reload the resource group information.
		Typically, this message would be used after creating/deleting a Tiled Display.
		"""
		if self.sock is None:
			raise VizError(VizError.NOT_CONNECTED, "Not connected to SSM")

		message = "<ssm><refresh_resource_groups /></ssm>"

		statusCode, statusMessage, dom = self.__sendAndRecvMessage(message)
		if statusCode!=0:
			raise VizError(VizError.BAD_CONFIGURATION, statusMessage)

		# Success !
		return

class VizNode(VizResourceAggregate):
	rootNodeName = "node"
	ALL_PROPERTIES = ['remote_hostname', 'fast_network']

	def __clearAll(self):
		self.resIndex = None
		self.hostName = None
		self.model = None
		self.properties = {}
		self.resources = []

	def __init__(self, hostName=None, model=None, idx = None):
		self.resClass = "VizNode"
		self.__clearAll()
		VizResource.__init__(self)
		self.resIndex = idx
		self.hostName = hostName
		self.resType = model

	def getAllocationDOF(self):
		# Ignore index of node

		return 3

	def getAllocationWeight(self):
		"""
		Returns our bias as the weight. No preference is given directly to the 
		node based on its index.
		NOTE: However, the allocation algorithm does choose the node with the 
		lower index, if all else is the same.
		"""
		return self.allocationBias

	def setProperty(self, propName, propVal):
		if propName not in VizNode.ALL_PROPERTIES:
			raise ValueError, "Invalid property name '%s'"%(propName)
		self.properties[propName] = propVal

	def getProperty(self, propName):
		if propName not in VizNode.ALL_PROPERTIES:
			raise ValueError, "Invalid property name '%s'"%(propName)
		return self.properties[propName]

	def addResource(self, res):
		if not isinstance(res, VizResource):
			raise TypeError, "Expecting a VizResource. Got %s"%(res.__class__)
		if self.hostName is not None:
			otherHostName = res.getHostName()
			if otherHostName is None: # If the resource doesn't have a hostname, we add it. It now belongs to us, right ?
				res.setHostName(self.hostName)
			else:
				if otherHostName != self.hostName: # We don't allow conflicts
					raise ValueError, "The Viz Resource you've passed is on node '%s'. It needs to be on node '%s'"%(res.getHostName(), self.hostName)
		else:
			self.hostName = res.getHostName() # this may either keep it None or change it to something else

		# Note: we keep the res itself, not a copy. This make us vulnerable to changes in the original
		# FIXME: what do we do to combat this problem ?
		self.resources.append(res)

	def getGPUs(self):
		return extractObjects(GPU, self.resources)

	def getKeyboards(self):
		return extractObjects(Keyboard, self.resources)

	def getMice(self):
		return extractObjects(Mouse, self.resources)

	def getServers(self):
		return extractObjects(Server, self.resources)

	def getSLIs(self):
		return extractObjects(SLI, self.resources)

	def getResources(self):
		return self.resources

	def setResources(self, resources):
		#
		# FIXME FIXME FIXME: I need to fix this list of list story sometime. Better late than never?
		#
		allRes = extractObjects(VizResource, resources) # resources may be a list of lists, and we need to flatten that !
		self.resources = []
		# Iterate over the list, adding each item. This helps validate
		for res in allRes:
			self.addResource(res)

	def serializeToXML(self, detailedConfig=True, addrOnly=False):
		ret = "<%s>"%(VizNode.rootNodeName)
		if self.resIndex is not None:
			ret += "<index>%d</index>"%(self.resIndex)
		if self.hostName is not None:
			ret += "<hostname>%s</hostname>"%(self.hostName)
		if self.resType is not None:
			ret += "<model>%s</model>"%(self.resType)
		if self.allocationBias is not None:
			ret += "<weight>%s</weight>"%(self.allocationBias)
		if len(self.properties)>0:
			ret += "<properties>"
			for propName in self.properties:
				#FIXME : should we quote these things as names may have double hashes ??
				ret += "<%s>%s</%s>"%(propName, self.properties[propName], propName)
			ret += "</properties>"
		# We serialize in a particular order
		for gpu in self.getGPUs():
			ret += gpu.serializeToXML()
		for kbd in self.getKeyboards():
			ret += kbd.serializeToXML()
		for mouse in self.getMice():
			ret += mouse.serializeToXML()
		for srv in self.getServers():
			ret += srv.serializeToXML()
		for sli in self.getSLIs():
			ret += sli.serializeToXML()

		ret += "</%s>"%(VizNode.rootNodeName)
		return ret

	def deserializeFromXML(self, domNode):
		self.__clearAll()
		if domNode.nodeName != VizNode.rootNodeName:
			raise ValueError, "Failed to deserialize VizNode. Node name=%s, expected %s!"%(domNode.nodeName, VizNode.rootNodeName)

		for xmlNode in domutil.getAllChildNodes(domNode):
			if xmlNode.nodeName == "index":
				self.resIndex = int(domutil.getValue(xmlNode))
			elif xmlNode.nodeName == "weight":
				self.allocationBias = int(domutil.getValue(xmlNode))
			elif xmlNode.nodeName == "hostname":
				self.hostName = domutil.getValue(xmlNode)
			elif xmlNode.nodeName == "model":
				self.resType = domutil.getValue(xmlNode)
			elif xmlNode.nodeName == "properties":
				propNodes = domutil.getAllChildNodes(xmlNode)
				for pn in propNodes:
					self.setProperty(pn.nodeName, domutil.getValue(pn))
			else:
				newResource = deserializeVizResource(xmlNode)
				self.addResource(newResource)

def sanitisedEnv():
	"""
	Return a modified environment. Currently, this ensures that
	VirtualGL's librrfaker.so LD_PRELOAD does not affect
	applications
	"""
	safeEnv = deepcopy(os.environ)
	if safeEnv.has_key('LD_PRELOAD'):
		val = safeEnv['LD_PRELOAD']
		sanitisedPreload = ""
		reg = re.compile("^.*\/librrfaker\.so$")
		for item in val.split(":"):
			if item != "librrfaker.so":
				item = reg.sub("", item)
			else:
				item = ""
			if len(item)>0:
				sanitisedPreload += item + ":"
				
		safeEnv['LD_PRELOAD'] = sanitisedPreload
	return safeEnv

