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

import slurmscheduler
import localscheduler
import sshscheduler
import vsapi
import time
import sys
import weakref
import os
import copy
from pprint import pprint

def uniqList(list):
	alreadySeen = {}
	for s in list:
		alreadySeen[s] = None
	return alreadySeen.keys()

def createSchedulerType(schedType, nodeList, params):
	if schedType=="slurm":
		return slurmscheduler.SLURMScheduler(nodeList, params)
	elif schedType=="local":
		return localscheduler.LocalScheduler(nodeList, params)
	elif schedType=="ssh":
		return sshscheduler.SSHScheduler(nodeList, params)

	raise ValueError, "Unknown scheduler type '%s'"%(schedType)

class Allocation:
	def __clearAll(self):
		self.allocatedResources = None
		self.launcherList = None
		self.user = None

	def __init__(self, launcherList, allocatedResources, user):
		"""
		launcher => the real allocation from the scheduler. This encapsulates all resources included in
		the allocation.
		allocatedResources => the resources allocated for this.
		"""
		self.launcherList = launcherList
		self.allocatedResources = allocatedResources
		self.user = user

	def getUser(self):
		return self.user

	def __del__(self):
		"""
		Destructor : do nothing. If the user wants, s/he will call deallocate. Else the 
		SSM takes care if cleanup on disconnect is detected.
		"""
		pass

	def deallocate(self):
		"""
		This is called when the allocation needs to be removed from the scheduler.

		Free the resources that this allocation has.
		"""
		# if we're already freed, then no need to do anything
		if self.allocatedResources is None:
			return

		if self.launcherList is not None: # FIXME: this is None sometimes. Why ??
			# Deallocate the resources 
			for launcher in self.launcherList:
				launcher.deallocate()

		# Clear all internal variables to indicate that we are'nt valid
		self.__clearAll()

	def getResources(self):
		"""
		Get the list of resources associated with this allocation.
		"""
		return self.allocatedResources

class Metascheduler:
	def __init__(self, allNodes, schedList):
		self.allocations = []

		vizResourceList = []
		nodeWeightWhenFree = {}
		nodeMap = {}
		for node in allNodes:
			nodeWeightWhenFree[node.getHostName()] = 0
			vizResourceList = vizResourceList + node.getResources()
			nodeMap[node.getHostName()] = node

		# we keep a hash table to let us easily get to the object by name
		# we keep references to the original objects. The allocation
		# state is thus kept in one set of objects, which are in maintained
		# in the caller of the metascheduler
		infoTable = {}
		for res in vizResourceList:
			infoTable[res.hashKey()] = res
			nodeWeightWhenFree[res.getHostName()] += res.getAllocationWeight()

		self.infoTable = infoTable
		self.schedList = schedList
		self.nodeMap = nodeMap
		self.nodeWeightWhenFree = nodeWeightWhenFree

	"""
	Allocate the list of requested resources. 
	Nodes are picked only from the includeNodeList. If includeNodeList is empty,
	then all nodes are candidates

	The requested resources must be VizResource objects, or inherited classes
	"""
	def allocate(self, requestedResources, userInfo, includeNodeList):
		# validate input argument
		if not isinstance(requestedResources, list):
			raise ValueError, "Bad value: allocate only deals with lists"

		if len(requestedResources)==0:
			raise ValueError, "Nothing to do!"

		for item in requestedResources:
			if isinstance(item, list):
				allRes = item
			else:
				allRes = [item]
			for res in allRes:
				if isinstance(res, vsapi.VizResourceAggregate):
					if len(allRes)>1:
						raise ValueError, "Bad Resource Request: Only a Aggregate VizResource is allowed as a subrequest"%(repr(res))
				elif isinstance(res, vsapi.VizResource):
					#if not res.isCompletelyResolvable():
					#	raise ValueError, "Bad Resource Request '%s': Only completely resolvable objects can be allocated"%(repr(res))
					pass
				else:
					raise ValueError, "Bad Value: Only VizResource objects, VizResourceAggregate objects or derived objects are accepted"
	

		allAreAvailable = True
		nodesToAlloc = {}

		# requestedResources is a list of requests
		# Each item in the list may be
		#  - a VizResourceAggregate
		#  - a list of VizResources
		#  - a VizResource

		# Expand the request into final items
		# This is done by expanding the VizResourceAggregate objects
		# in the requested list
		indexOfExpandedInFinal = [] # says how to map results back
		expandedResourceList = []
		for possibleRes in requestedResources:
			if isinstance(possibleRes, list):
				indexOfExpandedInFinal.append(len(expandedResourceList))
				expandedResourceList.append(possibleRes)
			elif isinstance(possibleRes, vsapi.VizNode): # and (len(possibleRes.getResources())==0):
				# Append node as is
				indexOfExpandedInFinal.append(len(expandedResourceList))
				expandedResourceList.append(possibleRes)
			elif isinstance(possibleRes, vsapi.VizResourceAggregate):
				sti = len(expandedResourceList)
				realRes = possibleRes.getResources() # this may be a list of items or lists
				indexOfExpandedInFinal.append(range(sti, sti+len(realRes)))
				for resList in realRes:
					expandedResourceList.append(resList)
			elif isinstance(possibleRes, vsapi.VizResource):
				indexOfExpandedInFinal.append(len(expandedResourceList))
				expandedResourceList.append([possibleRes])

		# expandedResourceList is a list of lists of objects of type VizResource
		#
		# Process the list, checking for errors and generating information that
		# will be useful later
		#
		resReqByDOF = { 0:[], 1:[], 2:[], 3:[] }
		fixedResources = {}
		for i in range(len(expandedResourceList)):
			innerList = expandedResourceList[i]
			if not isinstance(innerList, list):
				innerList = [innerList]
			# make a unique list of non-null hostnames
			hnList = map(lambda x:x.getHostName(),filter(lambda x:x.getHostName()!=None, innerList))
			uniqHostList = uniqList(hnList)

			dofItems = { 0:0, 1:0, 2:0, 3:0 }
			numItems = len(innerList)
			for res in innerList:
				nd = res.getAllocationDOF()
				dofItems[nd]+=1

			# Error case : More than 1 host name, and 
			# not all items are dof=0
			if len(uniqHostList)>1 and dofItems[0]!=numItems:
				raise ValueError, "Invalid resource request. If resources in a request list are on multiple hosts, then they must all be completely resolvable(i.e. fixed in both index and hostname)."

			# If 1 host name, then paste it to all items
			if len(uniqHostList)==1:
				for res in innerList:
					res.setHostName(uniqHostList[0])

			# The DOF value for this group will be the highest DOF
			# of the modified resources at this point
			max_dof = 0
			for res in innerList:
				nd = res.getAllocationDOF()
				if nd>max_dof: max_dof = nd
				if isinstance(res, vsapi.VizNode):
					continue
				if res.isCompletelyResolvable():
					hk = res.hashKey()
					if not fixedResources.has_key(hk):
						fixedResources[hk]={'count':1, 'ref':res, 'share_count':0}
					else:
						# increment usage count
						fixedResources[hk]['count']+=1
					# Increment share count
					if res.isShared():
						fixedResources[hk]['share_count']+=1


			# save the information for this requirement by DOF
			resReqByDOF[max_dof].append({
				'reqIndex' : i,
				'requirement' : expandedResourceList[i]
			})

		resourcesUsedMultipleTimes = filter(lambda x:fixedResources[x]['count']>1, fixedResources.keys())
		if len(resourcesUsedMultipleTimes)>0:
			msg = ""
			for res in resourcesUsedMultipleTimes:
				if fixedResources[res]['count']!=fixedResources[res]['share_count']:
					msg += "%s used %d times %d times shared,"%(res, fixedResources[res]['count'], fixedResources[res]['share_count'])
			if len(msg)>0:
				raise ValueError, "Invalid resource request. One or more resources have been requested more than once OR has been requested both shared and unshared, %s. Reason: %s"%(res, msg)
		errorMessage = ""

		unusableNodes = []
		for sched in self.schedList:
			unusableNodes += sched.getUnusableNodes()

		#
		# Verify that all completely resolvable resources that are requested are indeed free
		# This is a necessary requirement.
		#
		for resKey in fixedResources:
			if not self.infoTable.has_key(resKey):
				raise vsapi.VizError(vsapi.VizError.BAD_RESOURCE, "Pre-allocation: I dont manage the resource : %s. So can't allocate that"%(resKey))
			# if the resource is on a node which is not usable, then we can't satisfy this request.
			if self.infoTable[resKey].getHostName() in unusableNodes:
				raise vsapi.VizError(vsapi.VizError.RESOURCE_UNAVAILABLE, "%s is not available at this time."%(resKey))

			if not self.infoTable[resKey].isFree():
				raise vsapi.VizError(vsapi.VizError.RESOURCE_BUSY, "Resource %s is already being used. It can't be allocated for you at this time."%(resKey))

			if not self.infoTable[resKey].typeSearchMatch(fixedResources[resKey]['ref']):
				raise vsapi.VizError(vsapi.VizError.USER_ERROR, "Requested %s has a different type compared to the available resource. So this requirement cannot be fulfilled"%(resKey))

			# if the resource is on a node which is not in the search list, then we can't satisfy this request.
			if (len(includeNodeList)>0) and (self.infoTable[resKey].getHostName() not in includeNodeList):
				raise vsapi.VizError(vsapi.VizError.RESOURCE_UNAVAILABLE, "%s is not in the include list to choose from. So the request can't be satisfied."%(resKey))

			# XXX: The next two checks can be enforced by using "canAllocate()"
			# However, that will reduce the verbosity of the error messages

			# check if user is asking for exclusive access on a resource which is already shared, then we have to fail
			if fixedResources[resKey]['ref'].isExclusive() and self.infoTable[resKey].isShared():
				raise vsapi.VizError(vsapi.VizError.RESOURCE_BUSY, "Resource %s has already been allocated for shared access. It can't be allocated for you in exclusive mode at this time."%(resKey))

			# check if user is asking for shared access on a resource which is already exclusively allocated, then we have to fail
			if fixedResources[resKey]['ref'].isShared() and (not self.infoTable[resKey].isSharable()):
				raise vsapi.VizError(vsapi.VizError.RESOURCE_BUSY, "Resource %s is not sharable and hence cannot be allocated for shared access."%(resKey))
	
		# FIXME: we could check if this request can ever be satisfied. Implement this later
		
		#
		# Create a hash of free resources. We'll allocate out of these
		# hash is indexed by host name
		#
		freeResources = {}
		for resKey in self.infoTable:
			ob = self.infoTable[resKey]
			obNodeName = ob.getHostName()
			# Skip resources on unusable nodes
			if obNodeName in unusableNodes:
				continue
			# Skip resources not in the include list
			if (len(includeNodeList)>0) and (obNodeName not in includeNodeList):
				continue
			if not freeResources.has_key(obNodeName):
				freeResources[obNodeName] = {}
			if self.infoTable[resKey].isFree():
				# Create a copy of the free resources. If we fail allocation,
				# then our internal table will still be consistent!
				freeResources[obNodeName][resKey] = copy.deepcopy(ob)

		# create an empty list for all allocations.
		# this has 1 spot for every requirement
		# we'll populate this as we do the allocation
		allocatedResources = [None]*len(expandedResourceList)

		# allocate all DOF=0 items
		# Note that this not make them unavailable yet
		for reqDesc in resReqByDOF[0]:
			reqIndex = reqDesc['reqIndex']
			allocatedRes = reqDesc['requirement']
			allocatedResources[reqIndex] = allocatedRes

		# remove all fixed (i.e. DOF=0) VizResources 
		# from the availability pool.
		# however, we keep them in the lists at the some position
		# we'll skip over them while allocating, so there will be no problems
		for dof in resReqByDOF:
			for reqDesc in resReqByDOF[dof]:
				resToAlloc = reqDesc['requirement']
				if isinstance(resToAlloc, list):
					for res in resToAlloc:
						if res.getAllocationDOF()==0:
							resKey = res.hashKey()
							resHost = res.getHostName()
							# Allocate out of the existing item
							freeResources[resHost][resKey].doAllocate(res, userInfo['uid'])
							if not freeResources[resHost][resKey].isFree():
								freeResources[resHost].pop(resKey)
				else:
					res = resToAlloc
					if res.getAllocationDOF()==0:
						resKey = res.hashKey()
						resHost = res.getHostName()
						# Allocate out of the existing item
						freeResources[resHost][resKey].doAllocate(res, userInfo['uid'])
						if not freeResources[resHost][resKey].isFree():
							freeResources[resHost].pop(resKey)
				
		#
		# The real allocation logic starts from here ...
		#
		# We have resReqByDOF 
		#    0 => all fixed resources
		#    1 => list of list of VizResource with only index specified
		#    2 => list of list of VizResource, all with hostnames. Zero or more with index value specified.
		#    3 => list of list of VizResource with neither index nor hostname specified
		#
		# There may be VizResource objects with DOF=0 in any lists 1,2,or 3. We'll skip
		# them all the time since we've effectively taken them in the beginning.
		#
		# We can skip 0. It has all fixed resources; and we've effectively taken them
		# 
		# Our algorithm will look like the following --
		#
		# Step 1
		#
		#  - Get all VizResource lists for DOF = 1. These resources have only indices
		#    Sort them by number of resources in each list, with the maximum 
		#    coming first. This is the "requirement list"
		#  - Create another list of available resources per node, copying freeResources
		#    This is the "availability list", and will have max number of items 
		#    equal to number of nodes
		#  - Create a per node list of DOF=2 requirements
		#
		# Step 2
		#
		#  - For each requirement in "requirement list":
		#    - Sort availability list, least resources on top
		#    - For each node in "availability list"
		#      - If this requirement can be matched by resources on this node
		#        - Allocate this if this does not cause any DOF=2 (hostname) requirements 
		#          to break. Update the available resources and break
		#    - If no match, then error out
		#
		# Step 3
		#
		#  - Create a requirement list for DOF=2, again more requirements on top.
		#  - For each DOF=2 requirement,
		#    - check in availabilty for this node. If we have enough resources (count matching 
		#      resource type numbers, then allocate it. If ues, update availabiliy and break
		#    - Getting a no here must not result in an assertion !? Since we have 
		#      explicitly checked that earlier
		#    - FIXME: are no failures possible here at all ?? Logical debate is needed!
		#
		# Step 4
		#
		#  - Create a requirement list for DOF=3, sort maximal first
		#  - For each DOF=3 requirement,
		#    - Sort availability list to order minimal resources on top.
		#    - for each availability
		#      - check if requirement matches availability
		#        - if yes, allocate em and break. Update availability list
		#    - if no match, error out
		#
		#  - We're done if we come here !!!


		#
		# Step 1
		#

		# create a list, with each element saying what resources are free on a particular node
		# note that availResources has references to the objects
		availResources = []
		for node in freeResources:
			freeRes  = []
			for resKey in freeResources[node]:
				freeRes.append(freeResources[node][resKey])
			availResources.append([node, freeRes])

		# sort with maximal number of resources per requirement coming first
		reqDescList = resReqByDOF[1]
		self.__sortReqList(reqDescList)

		# create a per-node list of DOF=2 requirements
		dof2ReqsByNode = {}
		for resReq in resReqByDOF[2]:
			for res in resReq['requirement']:
				if res.getAllocationDOF() == 2:
					nodeName = res.getHostName()
					if not dof2ReqsByNode.has_key(nodeName):
						dof2ReqsByNode[nodeName] = []
					dof2ReqsByNode[nodeName].append(res)

		#
		# Step 2
		#

		for reqDesc in reqDescList:
			# our greedy strategy - sort resources so that minimal number of resources
			# are on top
			self.__sortAvailResources(availResources)

			didSatisfy = False
			resRequired = reqDesc['requirement']
			resFinalSelected, resToBeAllocated, resTBAIndexMap = self.__classifyRes(reqDesc['requirement'])
			for nodeAvail in availResources:
				nodeName = nodeAvail[0]
				nodeFreeRes = nodeAvail[1]
				# Note: adding the nodeName to all these reqs makes all reqs fully resolved
				# they're all DOF=1 (index is specified). Adding hostname makes them DOF=0
				reqWithThisHostName = self.__copyWithThisNodeName(resToBeAllocated, nodeName)
				allocThese, remainingAvail = self.__resourceMatchDOF0(reqWithThisHostName, nodeFreeRes, userInfo['uid'])
				if allocThese is None:
					continue

				if dof2ReqsByNode.has_key(nodeName):
					satisfied, remaining = self.__resourceMatchDOF2(dof2ReqsByNode[nodeName], remainingAvail, userInfo['uid'])
					if satisfied is None:
						continue

				# we've satisfied this requirement here
				didSatisfy = True

				# put the allocated resources into their place
				for idx in range(len(allocThese)):
					resFinalSelected[resTBAIndexMap[idx]] = allocThese[idx]

				# update the available items on the node
				nodeAvail[1] = remainingAvail

				# And we are done meeting this requirement
				break

			# if we don't have a match, then we're done
			if didSatisfy == False:
				raise vsapi.VizError(vsapi.VizError.USER_ERROR, "Not enough resources to satisfy the request")
		
			# put the allocated resources in their final place
			allocatedResources[reqDesc['reqIndex']] = resFinalSelected



		#
		# Step 3
		#

		# Get DOF=2 requirements
		# Our error checking in the beginning ensures that, each DOF=2 requirement will have the same hostname
		# and the index will not be specified in any (except in the fixed)
		reqDescList = resReqByDOF[2]
		self.__sortReqList(reqDescList)

		availResourcesByNodeName = {}
		for ar in availResources:
			availResourcesByNodeName[ar[0]]=ar[1]

		for reqDesc in reqDescList:
			didSatisfy = False
			resRequired = reqDesc['requirement']
			resFinalSelected, resToBeAllocated, resTBAIndexMap = self.__classifyRes(reqDesc['requirement'])

			# determine the node name to allocate on
			# the names on all resources will be the same, so pick the first one
			# also, note that the length of resToBeAllocated must be atleast one - else we goofed up elsewhere above!
			if len(resToBeAllocated)==0:
				raise vsapi.VizError(vsapi.VizError.INTERNAL_ERROR, "No resources TBA at DOF=2, but still resource requirement got classified as DOF=2 !")
			nodeName = resToBeAllocated[0].getHostName() 
			# Check whether this nodename is valid ? FIXME: should I do this test earlier ??
			if not availResourcesByNodeName.has_key(nodeName):
				raise vsapi.VizError(vsapi.VizError.USER_ERROR, "Can't allocate resources. Node name '%s' is not available for allocation"%(nodeName))
			nodeFreeRes = availResourcesByNodeName[nodeName]

			# Sort free list by weight; this ensures that matching items with lower weight will 
			# be picked up first
			nodeFreeRes.sort(lambda x,y:x.getAllocationWeight()-y.getAllocationWeight())
		
			allocThese, remainingAvail = self.__resourceMatchDOF2(resToBeAllocated, nodeFreeRes, userInfo['uid'])
			if allocThese is None:
				# This shouldn't happen at all. If it does, it's a bug in our algorithm
				raise vsapi.VizError(vsapi.VizError.INTERNAL_ERROR, "Couldn't allocate a DOF=2 requirement. Please check your resource list")

			# Got the resources...

			# put the allocated resources into their place
			for idx in range(len(allocThese)):
				resFinalSelected[resTBAIndexMap[idx]] = allocThese[idx]

			# update the available items on the node
			availResourcesByNodeName[nodeName] = remainingAvail

			# put the allocated resources in their final place
			allocatedResources[reqDesc['reqIndex']] = resFinalSelected
		
		# convert the available resources back to the list representation
		availResources = []
		for nodeName in availResourcesByNodeName:
			ar = availResourcesByNodeName[nodeName]
			if len(ar)>0:
				availResources.append([nodeName, ar])

		#
		# Step 4
		#

		# Get DOF=3 requirementss.
		reqDescList = resReqByDOF[3]
		# sort with maximal number of resources per requirement coming first
		self.__sortReqList(reqDescList)

		for reqDesc in reqDescList:
			# our greedy strategy - sort resources so that minimal number of resources
			# are on top
			self.__sortAvailResources(availResources)

			didSatisfy = False
			resRequired = reqDesc['requirement']
			if not isinstance(resRequired, vsapi.VizNode): # List of resource
				resFinalSelected, resToBeAllocated, resTBAIndexMap = self.__classifyRes(reqDesc['requirement'])
					
				for nodeAvail in availResources:
					nodeName = nodeAvail[0]
					nodeFreeRes = nodeAvail[1]
					# Note: adding the nodeName to all these reqs converts these DOF=3 requests turn into DOF=2
					reqWithThisHostName = self.__copyWithThisNodeName(resToBeAllocated, nodeName)
					allocThese, remainingAvail = self.__resourceMatchDOF2(reqWithThisHostName, nodeFreeRes, userInfo['uid'])
					if allocThese is None:
						continue

					# Got the resources...
					didSatisfy = True

					# put the allocated resources into their place
					for idx in range(len(allocThese)):
						resFinalSelected[resTBAIndexMap[idx]] = allocThese[idx]

					# update the available items on the node
					nodeAvail[1] = remainingAvail

					# And we are done meeting this requirement
					break
			else:
				# Whole node needs to be matched
				for nodeAvail in availResources:
					nodeName = nodeAvail[0]
					nodeFreeRes = nodeAvail[1]
					availResourceWeight = sum(map(lambda x: x.getAllocationWeight(), nodeFreeRes))

					# Skip this node if the whole node is not available
					if self.nodeWeightWhenFree[nodeName] != availResourceWeight:
						continue

					matchRes = resRequired.getResources()

					# Use all the resources
					resFinalSelected = copy.deepcopy(nodeFreeRes)

					if len(matchRes)>0:
						# We need to match specific resource requirements...
						unmatchedRes = copy.copy(nodeFreeRes)
						matchSuccess = False
						for res in matchRes:
							# Search in all the unmatched ones. This is an
							# inefficient algorithm which may not work correctly
							# given all kinds of complex match requirements.
							# I retain this since it is simple and work for
							# typical requirements!
							# FIXME: if somebody complains, fix this! Fixing this
							# really well will need lots of work I think
							matchSuccess = False
							for potentialMatch in unmatchedRes:
								if potentialMatch.typeSearchMatch(res):
									matchSuccess = True
									unmatchedRes.remove(potentialMatch)
									break
							if not matchSuccess:
								# No matches
								break
						if matchSuccess:
							didSatisfy = True
					else:
						# We've satisfied reqs
						didSatisfy = True

					if didSatisfy:
						# Remove all resources from the avail list, since we've allocated them
						nodeAvail[1] = []
						break
					
			if didSatisfy == False:
				# we can't satisfy the user request
				raise vsapi.VizError(vsapi.VizError.USER_ERROR, "Not able to satisfy the request with the available resources (DOF=3)")

			# put the allocated resources in their final place
			allocatedResources[reqDesc['reqIndex']] = resFinalSelected

		# till the whole code works, this is what we'll keep for success!
		#allocatedResources = expandedResourceList

		#print '---------------------------------------------'
		#print 'Requested Resource by DOF'
		#print '---------------------------------------------'
		#pprint(resReqByDOF)
		#print '---------------------------------------------'
		#print 'The allocated resources for this request were'
		#print '---------------------------------------------'
		#pprint(allocatedResources)
		#print '---------------------------------------------'
		#print 'Resources remaining at the end'
		#print '---------------------------------------------'
		#pprint(availResources)
		#print '---------------------------------------------'

		# Mark the resource
		for innerList in allocatedResources:
			if not isinstance(innerList, list):
				innerList = [innerList]
			for res in innerList:
				if not res.isCompletelyResolvable():
					raise ValueError, "Programming Error. You allocated %s which is not completely resolvable"%(res)

				searchKey = res.hashKey()
				if not self.infoTable.has_key(searchKey):
					raise vsapi.VizError(vsapi.VizError.BAD_RESOURCE, "I dont manage the resource : %s. So can't allocate that"%(searchKey))
	
				if not self.infoTable[searchKey].isFree():
					raise vsapi.VizError(vsapi.VizError.RESOURCE_BUSY, "Programming Error - allocated resource (%s) is not free ? This is not supposed to happen! Allocator bug most likely"%(searchKey))

				# Append this to the node list only if it is schedulable.
				if res.isSchedulable():
					nodesToAlloc[res.getHostName()] = None

		# convert dictionary to list
	   	nodesToAlloc = nodesToAlloc.keys()

		# these nodes may be managed by one or more schedulers
		# so we'll have to partition this 
		node2launcher = {}
		launcherList = []
		for sched in self.schedList:
			thisSchedNodes = sched.getNodeNames()
			matchNodes = []
			for nodeName in nodesToAlloc:
				if nodeName in thisSchedNodes:
					matchNodes.append(nodeName)
			# call the scheduler only if there is a need to allocate any
			# scheduled resources
			if len(matchNodes)>0:
				thisLauncher = sched.allocate(userInfo['uid'], userInfo['gid'], matchNodes)
				launcherList.append(thisLauncher)
				for nodeName in matchNodes:
					node2launcher[nodeName] = thisLauncher

		# This is where we put back what we allocated into
		# something that corresponds to the original request
		#
		# The key thing here is to convert lists back to resource groups
		finalResources = []
		for itemIndex in range(len(requestedResources)):
			if isinstance(requestedResources[itemIndex], list):
				wasAggregate = False
				wasList = True
				resListList = [ allocatedResources[indexOfExpandedInFinal[itemIndex]] ] # list of VizResources
			elif isinstance(requestedResources[itemIndex], vsapi.VizNode): # and (len(requestedResources[itemIndex].getResources())==0): # Whole node alloc
				wasAggregate = True
				wasList = False
				resListList = [ allocatedResources[indexOfExpandedInFinal[itemIndex]] ]
			elif isinstance(requestedResources[itemIndex], vsapi.VizResourceAggregate):
				wasAggregate = True
				wasList = False
				resListList = map(lambda x:allocatedResources[x], indexOfExpandedInFinal[itemIndex]) # list of lists OR VizResources
			else:
				wasAggregate = False
				wasList = False
				resList = allocatedResources[itemIndex]
				resListList = [ allocatedResources[indexOfExpandedInFinal[itemIndex]] ] # single VizResource

			subAlloc = []
			for innerList in resListList:
				subSubAlloc = []
				if not isinstance(innerList, list):
					innerList = [innerList]
				for ob in innerList:
					subSubSubAlloc = []
					if isinstance(ob, list):
						resList = ob
					else:
						resList = [ob]

					for res in resList:
						# mark this resource as being in use
						searchKey = res.hashKey()
						self.infoTable[searchKey].doAllocate(res, userInfo['uid'])

						# make a copy of the original object corresponding to this resource
						# XXX: this will make the object have "instantaneous" shared info that
						# is not dynamically allocated
						newRes = copy.deepcopy(self.infoTable[searchKey])

						# Create a schedulable only if the new item is a schedulable one
						if newRes.isSchedulable():
							newRes.setSchedulable(vsapi.Schedulable(node2launcher[newRes.getHostName()], newRes.getHostName()))
	
						subSubSubAlloc.append(newRes)

					if not isinstance(ob, list):
						subSubSubAlloc = subSubSubAlloc[0]
					subSubAlloc.append(subSubSubAlloc)
				subAlloc.append(subSubAlloc)

			if wasList:
				finalResources.append(subAlloc[0])
			elif wasAggregate:
				allocItem = copy.deepcopy(requestedResources[itemIndex]) #duplicate the aggregate group object
				allocItem.setResources(subAlloc)
				finalResources.append(allocItem)
			else:
				finalResources.append(subAlloc[0][0])

		newAlloc = Allocation(launcherList, finalResources, userInfo['uid'])

		self.allocations.append(newAlloc)
		return newAlloc

	def __classifyRes(self, resRequired):
		resFinalSelected = []
		resToBeAllocated = []
		resTBAIndexMap = []
		for res in resRequired:
			thisDOF = res.getAllocationDOF()
			if thisDOF == 0:
				resFinalSelected.append(res)
			else:
				# the final location of this resource will be this index
				resTBAIndexMap.append(len(resFinalSelected))
				# create the space for it
				resFinalSelected.append(None)
				resToBeAllocated.append(res)
		return [resFinalSelected, resToBeAllocated, resTBAIndexMap]

	def __copyWithThisNodeName(self, resList, nodeName):
		out = []
		for res in resList:
			newRes = copy.deepcopy(res)
			newRes.setHostName(nodeName)
			out.append(newRes)
		return out

	def __resourceMatchDOF2(self, reqList, availList, userInfo):
		"""
		Match a list of VizResources (reqList) to available resources on a node(avail).
		The hostnames of all resources in reqList must match the hostname of availList.
		NOTE: One or more items in reqList may have index specified.
		"""

		# separate the DOF=0 from the DOF=2
		resFinalAllocated, resToBeMatched, resTBMIndexMap = self.__classifyRes(reqList)

		# match DOF=0
		dof0only = filter(lambda x: x is not None,resFinalAllocated)
		dof0match, remaining = self.__resourceMatchDOF0(dof0only, availList, userInfo)

		# if we can't match the DOF=0, then we've failed
		if dof0match == None:
			return [None, None]

		# NOTE: remaining is already a copy of availList, not a reference, so any
		# failures in the rest of the function will not impact the original list

		# NOTE: dof0match will be the same as dof0only on success
		#
		# 'remaining' will contain the resources that we can now use to satisfy
		# resToBeMatched, which has resources with indices unspecified
		#
		# our algorithm for this will be --
		#  - for each type of resource (GPU, Server) in 'remaining'
		#    - create a list in the order that we want to allocate them
		#      - e.g. Servers will be sorted from highest number to lowest number
		#      - GPUs may be sorted later with alternating slot numbers
		#  - for each res in resToBeMatched
		#    - see if this type's list has any items. If so, select that as the match
		#    - on failure, we cant do the allocation - as simple as that !
		# 

		# classify resources by type
		availRes = {}
		allResClasses = [vsapi.GPU, vsapi.Server, vsapi.Keyboard, vsapi.Mouse, vsapi.SLI]
		for resClass in allResClasses:
			availRes[resClass.rootNodeName] = []
		for res in remaining:
			for resClass in allResClasses:
				if isinstance(res, resClass):
					availRes[resClass.rootNodeName].append(res)
					break

		matchedRes = []
		for res in resToBeMatched:
			match = None
			for resClass in allResClasses:
				if isinstance(res, resClass):
					ar = availRes[resClass.rootNodeName]
					if len(ar)==0:
						return [None, None] # Not possible to match request with available resources

					# look in the available resources of this type
					# the first one fulfilling the type match will be allocated
					for mi in range(len(ar)):
						possibleMatch = ar[mi]
						if possibleMatch.canAllocate(res):
							match = res
							res.setHostName(possibleMatch.getHostName())
							res.setIndex(possibleMatch.getIndex())
							possibleMatch.doAllocate(res, userInfo)
							# post allocation, if the object is not free then remove it from the
							# free list
							if not possibleMatch.isFree():
								ar.pop(mi)
							break
					if match is None: # Not possible to match request with available resources
						return [None, None]
						
			if match is None:
				raise vsapi.VizError(vsapi.VizError.INTERNAL_ERROR, "You aren't handling this class of resources.")

			matchedRes.append(match)

		# remap allocation into final places
		for idx in range(len(matchedRes)):
			res = matchedRes[idx]
			newIndex = resTBMIndexMap[idx]
			resFinalAllocated[newIndex] = res
	
		# all leftover items are free
		allFree = []
		for resClass in allResClasses:
			allFree = allFree + availRes[resClass.rootNodeName]

		return [resFinalAllocated, allFree]

	def __resourceMatchDOF0(self, reqList, availList, userInfo):
		"""
		Match a list of VizResource requirements (req) to available resources on a node(avail).
		All resources are fully specified. So this is just a dual loop
		Returns [matched, remaining] if all reqs were in avail
		else returns [None, availList]
		"""
		matched = []
		# make a complete copy of the available objects. In case
		# of failures, we will just return the original list
		remaining = copy.deepcopy(availList) 
		for req in reqList:
			foundIt = False
			for avail in remaining:
				if avail.refersToTheSame(req, True) and avail.canAllocate(req):
					req.setHostName(avail.getHostName())
					req.setIndex(avail.getIndex())
					matched.append(req)
					avail.doAllocate(req, userInfo)
					# remove from availability list only if it is not free as a result of allocation
					if not avail.isFree(): 
						remaining.remove(avail)
					foundIt = True
					break
			# If one item fails matching, then it's failure overall
			if foundIt == False:
				return [None, availList]

		return [matched, remaining]

	def __sortAvailResources(self, resList):
		# each element of list is [name, <list of resources>]
		# sort with minimal number of resources coming first
		nodeWeight2 = {}
		for nodeEntry in resList:
			nodeName = nodeEntry[0]
			nodeResources = nodeEntry[1]
			resWeight = {}
			totalWeight = 0
			# compute weight of each resource and the total weight of
			# this node's resources
			for res in nodeResources:
				wt = res.getAllocationWeight()
				resWeight[res.hashKey()] = wt
				totalWeight += wt
				#print "Res '%s' weight %d"%(res.hashKey(), wt)
			# Sort resources of this node in order
			nodeResources.sort(lambda x,y : resWeight[x.hashKey()]-resWeight[y.hashKey()])
			nodeWeight2[nodeName] = totalWeight

		def sortFunc(x,y):
			nodeName1 = x[0]
			nodeName2 = y[0]
			node1 = self.nodeMap[nodeName1]
			node2 = self.nodeMap[nodeName2]
			# Return the node with the lower weight first
			wt1 = node1.getAllocationWeight()-node2.getAllocationWeight()
			if wt1 != 0:
				return wt1

			# Return the node whose resources have a lower weight next
			wt2 = nodeWeight2[nodeName1]-nodeWeight2[nodeName2]
			if wt2 != 0:
				return wt2

			# Return the node with lower index if all else fails. This
			# gives a consistent & predictable order of allocation.
			return node1.getIndex()-node2.getIndex()
			
		# Sort nodes with lower weights coming first
		resList.sort(sortFunc)


	def __sortReqList(self, reqDescList):
		# each element of list is dictionary { 'reqIndex':n, 'requirement' : list of VizResource objects }
		# sort with maximum requirements coming first
		# FIXME: this does not consider that the lists may have DOF=0 items. they'll get counted
		# too, effectively reducing the value of our greedy strategy
		def ordinalLength(x):
			if x is list:
				return len(x)
			else:
				return 1
		reqDescList.sort(lambda x,y: ordinalLength(y['requirement'])-ordinalLength(x['requirement']))

	"""
	Free an allocation created by us.
	This marks the resources as "free" in our internal table.
	Also calls the allocation objects deallocate method.
	"""
	def deallocate(self, allocObj):
		foundAlloc = None
		for i in range(len(self.allocations)):
			if self.allocations[i] is allocObj:
				foundAlloc = allocObj

		if foundAlloc is None:
			raise KeyError, "The requested allocation with id=%d does not exist"%(allocObj.getID())

		# if we came till here, then all is fine.

		# get resources that were allocated, and mark them as free
		allocatedResources = allocObj.getResources()
		for item in allocatedResources:
			if isinstance(item, list):
				realResList = item
			elif isinstance(item, vsapi.VizResourceAggregate):
				realResList = item.getResources()
			else:
				realResList = [item]

			for itemRes in realResList:
				if isinstance(itemRes,list):
					resList = itemRes
				else:
					resList = [itemRes]
				for res in resList:
					# update availability of this resource
					searchKey = res.hashKey()
					self.infoTable[searchKey].deallocate(res, allocObj.getUser())

		# deallocate the object - this frees up the scheduler, etc
		allocObj.deallocate()
