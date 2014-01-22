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

from pprint import pprint
import vsapi
import os
import time
import subprocess
import re
import sys
from glob import glob
from xml.dom import minidom
import xml
import domutil
import copy
import metascheduler
import string

def isFrameLockAvailable(resList):
	"""
	Checks if all GPUs in input list are connected to FrameLock devices or not.
	Return True if yes, False if not.

	NOTE: This cannot detect that GPUs are not connected to the same framelock chain.
	This cannot detect other case like mixing framelock devices.
	"""
	flChain = __getFrameLockChain(resList)
	# 0. Ensure that all GPUs are connected to framelock devices
	nonFrameLockGPUs = 0
	for member in flChain:
		gpuDetails = member['gpu_details']
		if gpuDetails['FrameLockDeviceConnected']!=True:
			nonFrameLockGPUs += 1
	if nonFrameLockGPUs>0:
		return False
	return True

def disableFrameLock(resList):
	"""
	Disables Frame Lock. The list of X servers to enable frame-lock on is extracted from the input list.
	The input list could contain Servers or VizResourceAggregate objects.
	"""
	flChain = __getFrameLockChain(resList)
	# 0. Ensure that all GPUs are connected to framelock devices
	nonFrameLockGPUs = 0
	for member in flChain:
		gpuDetails = member['gpu_details']
		if gpuDetails['FrameLockDeviceConnected']!=True:
			nonFrameLockGPUs += 1
	if nonFrameLockGPUs>0:
		raise vsapi.VizError(vsapi.VizError.BAD_CONFIGURATION, "%d GPUs out of %d GPUs are not connected to the frame lock device. Frame lock requires all GPUs to be connected to G-Sync cards. Perhaps you passed a wrong list?"%(len(flChain)-enableCount, len(flChain)))
	
	# 1. Ensure that framelock is already active on all GPUs
	enableCount = 0
	for member in flChain:
		gpuDetails = member['gpu_details']
		if gpuDetails['FrameLockEnable']==True:
			enableCount += 1
	if enableCount!=len(flChain):
		raise vsapi.VizError(vsapi.VizError.BAD_CONFIGURATION, "Frame lock is not enabled in %d GPUs out of %d GPUs. Probably you have passed a wrong list?"%(len(flChain)-enableCount, len(flChain)))

	# 2. Ensure that all displays are running at the same refresh rate!
	masterRefreshRate = None
	badRRList = []
	numBadPorts = 0
	totalPorts = 0
	for member in flChain:
		gpuDetails = member['gpu_details']
		for portIndex in gpuDetails['ports']:
			totalPorts += 1
			thisRR = gpuDetails['ports'][portIndex]['RefreshRate']
			if masterRefreshRate is None:
				masterRefreshRate = thisRR
			elif thisRR != masterRefreshRate:
				numBadPorts += 1
				if thisRR not in badRRList:
					badRRList.append(thisRR)
	if numBadPorts>0:
		raise vsapi.VizError(vsapi.VizError.BAD_CONFIGURATION, "Frame lock master refresh rate is %s Hz. %d output ports have a different refresh rate %s Hz. Perhaps you have included two or more framelock chains in the input?"%(masterRefreshRate, numBadPorts, badRRList))

	# 3. Disable frame lock on all GPUs
	for member in flChain:
		server = member['server']
		screen = member['screen']
		gpu_index = member['gpu_index']
		__set_nvidia_settings(server, '[gpu:%d]/FrameLockEnable'%(gpu_index), '0')

	# 4. Reset master/slave too...
	for member in flChain:
		server = member['server']
		screen = member['screen']
		gpu_index = member['gpu_index']
		__set_nvidia_settings(server, '[gpu:%d]/FrameLockMaster'%(gpu_index), '0x00000000')
		__set_nvidia_settings(server, '[gpu:%d]/FrameLockSlaves'%(gpu_index), '0x00000000')

	# Next check if framelock actually got disabled.
	# Check FrameLockSyncRate on all GPUs.
	flChain = __getFrameLockChain(resList)

	masterFLSR = None
	badFLSRList = []
	numBadGPUs = 0
	for member in flChain:
		gpuDetails = member['gpu_details']
		thisFLSR = gpuDetails['FrameLockSyncRate']
		if masterFLSR is None:
			masterFLSR = thisFLSR
		elif thisFLSR != masterFLSR:
			numBadGPUs += 1
			if thisFLSR not in badFLSR:
				badFLSR.append(thisFLSR)

	if (masterFLSR!='0') or (numBadGPUs>0):	
		raise vsapi.VizError(vsapi.VizError.BAD_CONFIGURATION, "Unable to disable lock due to unknown reasons.")
	#pprint(flChain)
	return "Disabled Frame Lock @ %s Hz on %d GPUs connected to %d display devices."%(masterRefreshRate, len(flChain), totalPorts)

def enableFrameLock(resList):
	"""
	Enable Frame Lock. The list of X servers to enable frame-lock on is extracted from the input list. Frame Lock should not be in an enabled state on any of the servers.
	The input list may contain Servers or VizResourceAggregate objects.
	"""

	flChain = __getFrameLockChain(resList)

	# Next do sanity checks

	# 0. Ensure that all GPUs are connected to framelock devices
	nonFrameLockGPUs = 0
	for member in flChain:
		gpuDetails = member['gpu_details']
		if gpuDetails['FrameLockDeviceConnected']!=True:
			nonFrameLockGPUs += 1
	if nonFrameLockGPUs>0:
		raise vsapi.VizError(vsapi.VizError.BAD_CONFIGURATION, "%d GPUs out of %d GPUs are not connected to the frame lock device. Frame lock requires all GPUs to be connected to G-Sync cards."%(len(flChain)-enableCount, len(flChain)))

	# 1. Ensure that framelock is not already active
	enableCount = 0
	for member in flChain:
		gpuDetails = member['gpu_details']
		if gpuDetails['FrameLockEnable']==True:
			enableCount += 1
	if enableCount>0:
		raise vsapi.VizError(vsapi.VizError.BAD_CONFIGURATION, "Frame lock is enabled in %d GPUs out of %d GPUs. You need to disable framelock on these before trying to enable framelock."%(enableCount, len(flChain)))

	# 2. Ensure that all displays are running at the same refresh rate!
	masterRefreshRate = None
	badRRList = []
	numBadPorts = 0
	totalPorts = 0
	for member in flChain:
		gpuDetails = member['gpu_details']
		for portIndex in gpuDetails['ports']:
			totalPorts += 1
			thisRR = gpuDetails['ports'][portIndex]['RefreshRate']
			if masterRefreshRate is None:
				masterRefreshRate = thisRR
			elif thisRR != masterRefreshRate:
				numBadPorts += 1
				if thisRR not in badRRList:
					badRRList.append(thisRR)
	if numBadPorts>0:
		raise vsapi.VizError(vsapi.VizError.BAD_CONFIGURATION, "Frame lock master refresh rate is %s Hz. %d output ports have a different refresh rate %s Hz. Framelock requires all display outputs to run at the same refresh rate."%(masterRefreshRate, numBadPorts, badRRList))


	# 3. We need to ensure that the first GPU is "master-able"???

	# 4. Ensure that all X servers have the same stereo setting
	# nVidia documentation mentions the following limitation --
	#
	# "All X Screens (driving the selected client/server display devices) must
	# have the same stereo setting. See Appendix B for instructions on how to
	# set the stereo X option."
	#
	stereoModesInUse = []
	for member in flChain:
		srvScreen = member['screen']
		try:
			scrStereoMode = srvScreen.getFBProperty('stereo')
		except:
			scrStereoMode = None
		if scrStereoMode not in stereoModesInUse:
			stereoModesInUse.append(scrStereoMode)

	if len(stereoModesInUse)>1:
		raise vsapi.VizError(vsapi.VizError.BAD_CONFIGURATION, "All X servers need to be running with the same stereo setting if you want to enable framelock on them.")
	
	
	# All sanity checks done. So time to enable frame lock...
	# 1. Setup the first available display on first GPU as master. If there are another other displays on the first GPU, set them up as slaves
	# 2. Setup all displays on all other other GPUs as slave
	# 3. Enable frame lock on all GPUs
	# 4. Toggle test signal on master

	# 1. Setup the first available display on first GPU as master. If there are another other displays on the first GPU, set them up as slaves
	masterServer = flChain[0]['server']
	masterScreen = flChain[0]['screen']
	masterGPUIndex = flChain[0]['gpu_index']
	masterGPUDetails = flChain[0]['gpu_details']
	isMaster = True
	for portIndex in gpuDetails['ports']:
		portMask = __encodeDisplay(gpuDetails['ports'][portIndex]['type'], portIndex)
		if isMaster:
			__set_nvidia_settings(masterServer, '[gpu:%d]/FrameLockMaster'%(masterGPUIndex), '0x%08x'%(portMask))
		else:
			__set_nvidia_settings(masterServer, '[gpu:%d]/FrameLockSlaves'%(masterGPUIndex), '0x%08x'%(portMask))
		isMaster = False

	# 2. Setup all displays on all other other GPUs as slave
	for member in flChain[1:]:
		slaveServer = member['server']
		slaveScreen = member['screen']
		slaveGPUIndex = member['gpu_index']
		slaveGPUDetails = member['gpu_details']
		portMask = 0
		for portIndex in slaveGPUDetails['ports']:
			portMask = portMask | __encodeDisplay(slaveGPUDetails['ports'][portIndex]['type'], portIndex)
		__set_nvidia_settings(slaveServer, '[gpu:%d]/FrameLockSlaves'%(slaveGPUIndex), '0x%08x'%(portMask))
		__set_nvidia_settings(slaveServer, '[gpu:%d]/FrameLockMaster'%(slaveGPUIndex), '0x00000000')
	
	# 3. Enable frame lock on all GPUs
	for member in flChain:
		server = member['server']
		screen = member['screen']
		gpu_index = member['gpu_index']
		__set_nvidia_settings(server, '[gpu:%d]/FrameLockEnable'%(gpu_index), '1')

	# 4. Toggle test signal on master

	# nvidia-settings needs a window manager running to toggle the test 
	# signal. So we start one...
	# FIXME: current experimentation shows this may not be necessary ??
	# We suppress all output. If running the window manager fails then a window manager is already running &
	# there will be no problems.
	sched = masterServer.getSchedulable()
	p = sched.run(["/usr/bin/env","DISPLAY=%s"%(masterServer.getDISPLAY()),"metacity"], outFile=open("/dev/null","w"), errFile=open("/dev/null","w"))
	time.sleep(2)

	__set_nvidia_settings(masterServer, '[gpu:%d]/FrameLockTestSignal'%(masterGPUIndex), '1')
	__set_nvidia_settings(masterServer, '[gpu:%d]/FrameLockTestSignal'%(masterGPUIndex), '0')

	# Kill window manager
	p.kill()

	# Next check if framelock actually got enabled.
	# Check FrameLockSyncRate on all GPUs.
	flChain = __getFrameLockChain(resList)

	masterFLSR = None
	badFLSRList = []
	numBadGPUs = 0
	for member in flChain:
		gpuDetails = member['gpu_details']
		thisFLSR = gpuDetails['FrameLockSyncRate']
		if masterFLSR is None:
			masterFLSR = thisFLSR
		elif thisFLSR != masterFLSR:
			numBadGPUs += 1
			if thisFLSR not in badFLSRList:
				badFLSRList.append(thisFLSR)
	
	if (numBadGPUs>0):
		raise vsapi.VizError(vsapi.VizError.BAD_CONFIGURATION, "Unable to setup frame lock on %d GPUs. Please ensure that all the GPUs in the passed list are chained properly via cabling."%(numBadGPUs))
	elif masterFLSR=='0':
		pprint(flChain)
		raise vsapi.VizError(vsapi.VizError.BAD_CONFIGURATION, "Unable to setup frame lock due to unknown reasons.")

	#pprint(flChain)
	return (masterRefreshRate, "Enabled Frame Lock @ %s Hz on %d GPUs connected to %d display devices"%(masterRefreshRate, len(flChain), totalPorts))

# Below, g_crt2 means CRT connected to physical port 2 on the GPU
g_crt1 = 0x00000002 # 0x00000002 - CRT-1
g_crt2 = 0x00000001 # 0x00000001 - CRT-2
g_dfp1 = 0x00020000 # 0x00040000 - DFP-1
g_dfp2 = 0x00010000 # 0x00020000 - DFP-2
# Logically ORing gives port combinations
# so -- 0x00000003 = CRT-0 and CRT-1 both connected

def __decodeMonitorMask(mask):
	result = {}
	if mask & g_crt2: result[0]={'type':'analog', 'name':'CRT-0'}
	if mask & g_dfp2: result[0]={'type':'digital', 'name':'DFP-0'}
	if mask & g_crt1: result[1]={'type':'analog', 'name':'CRT-1'}
	if mask & g_dfp1: result[1]={'type':'digital', 'name':'DFP-1'}
	return result

def __encodeDisplay(displayType, port):
	# FIXME: something wrong here. Did nvidia change lot of things from 4500 to 4600 ??
	# or are there any recent driver changes which are causing this to bork ?
	# I've inverted values for dfp1, dfp2 and crt1, crt2 to get things working on
	# QP of 5600, with driver 185.18.14
	if displayType=='analog':
		if port==0: return g_crt2
		if port==1: return g_crt1
		raise "Invalid port"
	elif displayType=='digital':
		if port==0: return g_dfp2
		if port==1: return g_dfp1
		raise "Invalid port"
	#else:
	raise "Invalid display type"

def __set_nvidia_settings(xServer, prop,val):
	sched = xServer.getSchedulable()
	cmd = ['/usr/bin/nvidia-settings', '--display=%s'%(xServer.getDISPLAY()), '-a', '%s=%s'%(prop,val)]
	#print cmd
	p = sched.run(cmd, outFile=subprocess.PIPE, errFile=subprocess.PIPE)
	p.wait()
	return p.getExitCode()

def __getGPUDetails(srv, scr, gpuIndex):
	gpuInfo = {}
	sched = srv.getSchedulable()
	cmd = ["/usr/bin/nvidia-settings","--ctrl-display=%s"%(srv.getDISPLAY()), "--display=%s"%(srv.getDISPLAY()), "-q", "[gpu:%d]/EnabledDisplays"%(gpuIndex)]
	#print cmd
	p = sched.run(cmd, outFile=subprocess.PIPE)
	p.wait()
	content =  p.getStdOut().split('\n')
	reobj = re.compile('^Attribute .*: (0x[0-9a-f]+).*$')
	l=content[1].rstrip().lstrip()
	#print l
	mobj=reobj.match(l)
	outputPortInfo = __decodeMonitorMask(int(mobj.groups(0)[0],16))
	for portNum in outputPortInfo:
		cmd = ["/usr/bin/nvidia-settings", "--ctrl-display=%s"%(srv.getDISPLAY()),"--display=%s"%(srv.getDISPLAY()),"-q","[gpu:%d]/RefreshRate3[%s]"%(gpuIndex, outputPortInfo[portNum]['name'])]
		p = sched.run(cmd, outFile=subprocess.PIPE)
		p.wait()
		content =  p.getStdOut().split('\n')
		reobj = re.compile("^Attribute 'RefreshRate3' \(.*\): ([0-9\.]+).*$")
		l=content[1].rstrip().lstrip()
		mobj=reobj.match(l)
		outputPortInfo[portNum]['RefreshRate']=mobj.groups(0)[0]
	gpuInfo['ports']=outputPortInfo

	cmd = ["/usr/bin/nvidia-settings","--ctrl-display=%s"%(srv.getDISPLAY()), "--display=%s"%(srv.getDISPLAY()), "-q", "[gpu:%d]/FrameLockAvailable"%(gpuIndex)]
	p = sched.run(cmd, outFile=subprocess.PIPE)
	p.wait()
	content =  p.getStdOut().split('\n')
	reobj = re.compile("^Attribute 'FrameLockAvailable' \(.*\): ([0-9\.]+)\..*$")
	l=content[1].rstrip().lstrip()
	mobj=reobj.match(l)
	if mobj is None:
		gpuInfo['FrameLockDeviceConnected']=False
		return gpuInfo
	else:
		gpuInfo['FrameLockDeviceConnected']=True

	gpuInfo['FrameLockAvailable']=mobj.groups(0)[0]

	cmd = ["/usr/bin/nvidia-settings","--ctrl-display=%s"%(srv.getDISPLAY()),"--display=%s"%(srv.getDISPLAY()), "-q", "FrameLockSyncRate"]
	p = sched.run(cmd, outFile=subprocess.PIPE)
	p.wait()
	content =  p.getStdOut().split('\n')
	reobj = re.compile("^Attribute 'FrameLockSyncRate' \(.*\): ([0-9\.]+)\..*$")
	l=content[1].rstrip().lstrip()
	mobj=reobj.match(l)
	gpuInfo['FrameLockSyncRate']=mobj.groups(0)[0]

	cmd = ["/usr/bin/nvidia-settings", "--ctrl-display=%s"%(srv.getDISPLAY()), "--display=%s"%(srv.getDISPLAY()), "-q", "[gpu:%d]/FrameLockEnable"%(gpuIndex)]
	p = sched.run(cmd, outFile=subprocess.PIPE)
	p.wait()
	content =  p.getStdOut().split('\n')
	reobj = re.compile("^Attribute 'FrameLockEnable' \(.*\): ([0-9\.]+)\..*$")
	l=content[1].rstrip().lstrip()
	mobj=reobj.match(l)
	gpuInfo['FrameLockEnable']=bool(int(mobj.groups(0)[0]))
	return gpuInfo

def __getFrameLockChain(resList):
	allServers = vsapi.extractObjects(vsapi.Server, resList)
	flChain = []

	# Create a frame lock chain consisting of all GPUs
	for srv in allServers:
		sched = srv.getSchedulable()
		baseGPUIndex = 0
		gpuDetails = []
		for srvScreen in srv.getScreens():
			for gi in range(baseGPUIndex, baseGPUIndex+len(srvScreen.getGPUs())):
				gpuDetails = __getGPUDetails(srv, srvScreen, gi)
				flChain.append({'server':srv, 'screen':srvScreen, 'gpu_index':gi, 'gpu_details':gpuDetails})
			baseGPUIndex += len(srvScreen.getGPUs())
	return flChain

def loadResourceGroups(sysConfig, rg_config_file=None):
	"""
	Parse the resource group configuration file & return the resource groups.
	If the resource group configuration file is missing, then we behave as if no
	resource groups have been defined.
	"""
	if rg_config_file is None:
		rg_config_file = vsapi.rgConfigFile

	resgroups = {}
	# Check if the resource group config file exists
	# A non existent file will be treated as if there were
	# no resource groups defined
	try:
		os.stat(rg_config_file)
	except:
		return resgroups
	try:
		dom = minidom.parse(rg_config_file)
	except xml.parsers.expat.ExpatError, e:
		raise vsapi.VizError(vsapi.VizError.BAD_CONFIGURATION, "Failed to parse XML file '%s'. Reason: %s"%(rg_config_file, str(e)))

	root_node = dom.getElementsByTagName("resourcegroupconfig")[0]
	rgNodes = domutil.getChildNodes(root_node,"resourceGroup")
	for node in rgNodes:
		obj = vsapi.ResourceGroup()
		try:
			obj.deserializeFromXML(node)
		except ValueError, e:
			raise vsapi.VizError(vsapi.VizError.BAD_CONFIGURATION, "FATAL: Error loading Resource Group '%s'. Reason: %s"%(obj.getName(), str(e)))

		# Normalize to paste hostnames where needed. This will make it easier to script tools!
		obj = normalizeRG(obj)

		try:
			obj.doValidate(sysConfig['templates']['display'].values())
		except ValueError, e:
			raise vsapi.VizError(vsapi.VizError.BAD_CONFIGURATION, "FATAL: Error validating Resource Group '%s'. Reason: %s"%(obj.getName(),str(e)))

		newResGrp = obj.getName()
		if resgroups.has_key(newResGrp):
			raise vsapi.VizError(vsapi.VizError.BAD_CONFIGURATION, "FATAL: Resource group '%s' defined more than once."%(newResGrp))

		resgroups[newResGrp] = obj
	return resgroups

def loadLocalConfig(
	onlyTemplates=False, master_config_file=None, node_config_file=None, rg_config_file=None, 
	systemTemplateDir = None, overrideTemplateDir = None):
	"""
	Load the local system configuration. Can load templates only, if needed.
	"""
	if master_config_file is None:
		master_config_file = vsapi.masterConfigFile
	if node_config_file is None:
		node_config_file = vsapi.nodeConfigFile
	if rg_config_file is None:
		rg_config_file = vsapi.rgConfigFile
	if systemTemplateDir is None:
		systemTemplateDir = vsapi.systemTemplateDir
	if overrideTemplateDir is None:
		overrideTemplateDir = vsapi.overrideTemplateDir
	sysConfig = {
		'templates' : { 'gpu' : {} , 'display' : {}, 'keyboard' : {}, 'mouse' : {}  }, 
		'nodes' : {},
		'resource_groups' : {}
	}

	# Load all templates...
	# NOTE: We load the templates from the global directory first.
	# Then load them from the local directory. This way, we ensure
	# that the local templates override the global ones.

	# Load GPU templates
	fileList = glob('%s/gpus/*.xml'%(systemTemplateDir))
	fileList += glob('%s/gpus/*.xml'%(overrideTemplateDir))
	for fname in fileList:
		try:
			dom = minidom.parse(fname)
		except xml.parsers.expat.ExpatError, e:
			raise vsapi.VizError(vsapi.VizError.BAD_CONFIGURATION, "Failed to parse XML file '%s'. Reason: %s"%(fname, str(e)))

		newObj = vsapi.deserializeVizResource(dom.documentElement, [vsapi.GPU])	
		sysConfig['templates']['gpu'][newObj.getType()] = newObj

	# DisplayDevice templates
	fileList = glob('%s/displays/*.xml'%(systemTemplateDir))
	fileList += glob('%s/displays/*.xml'%(overrideTemplateDir))
	for fname in fileList:
		try:
			dom = minidom.parse(fname)
		except xml.parsers.expat.ExpatError, e:
			raise vsapi.VizError(vsapi.VizError.BAD_CONFIGURATION, "Failed to parse XML file '%s'. Reason: %s"%(fname, str(e)))

		newObj = vsapi.deserializeVizResource(dom.documentElement, [vsapi.DisplayDevice])	
		sysConfig['templates']['display'][newObj.getType()] = newObj

	# Keyboard templates
	fileList = glob('%s/keyboard/*.xml'%(systemTemplateDir))
	fileList += glob('%s/keyboard/*.xml'%(overrideTemplateDir))
	for fname in fileList:
		try:
			dom = minidom.parse(fname)
		except xml.parsers.expat.ExpatError, e:
			raise vsapi.VizError(vsapi.VizError.BAD_CONFIGURATION, "Failed to parse XML file '%s'. Reason: %s"%(fname, str(e)))
		newObj = vsapi.deserializeVizResource(dom.documentElement, [vsapi.Keyboard])
		sysConfig['templates']['keyboard'][newObj.getType()] = newObj

	# Mice templates
	fileList = glob('%s/mouse/*.xml'%(systemTemplateDir))
	fileList += glob('%s/mouse/*.xml'%(overrideTemplateDir))
	for fname in fileList:
		try:
			dom = minidom.parse(fname)
		except xml.parsers.expat.ExpatError, e:
			raise vsapi.VizError(vsapi.VizError.BAD_CONFIGURATION, "Failed to parse XML file '%s'. Reason: %s"%(fname, str(e)))

		newObj = vsapi.deserializeVizResource(dom.documentElement, [vsapi.Mouse])	
		sysConfig['templates']['mouse'][newObj.getType()] = newObj

	# If we are asked for templates only, then we are done.
	if onlyTemplates:
		return sysConfig

	# Check the master config file.	
	try:
		dom = minidom.parse(vsapi.masterConfigFile)
	except xml.parsers.expat.ExpatError, e:
		raise vsapi.VizError(vsapi.VizError.BAD_CONFIGURATION, "Failed to parse XML file '%s'. Reason: %s"%(vsapi.masterConfigFile, str(e)))

	root_node = dom.getElementsByTagName("masterconfig")[0]
	system_node = domutil.getChildNode(root_node, "system")
	type_node = domutil.getChildNode(system_node, "type")
	system_type = domutil.getValue(type_node)

	if system_type=='standalone':
		raise vsapi.VizError(vsapi.VizError.BAD_CONFIGURATION, "FATAL : Standalone configurations are not managed by the SSM")

	# Read in the node configuration file. This includes the scheduler information
	try:
		dom = minidom.parse(node_config_file)
	except xml.parsers.expat.ExpatError, e:
		raise vsapi.VizError(vsapi.VizError.BAD_CONFIGURATION, "Failed to parse XML file '%s'. Reason: %s"%(node_config_file, str(e)))

	root_node = dom.getElementsByTagName("nodeconfig")[0]
	nodes_node = domutil.getChildNode(root_node,"nodes")
	nodeIdx = 0
	for node in domutil.getChildNodes(nodes_node, "node"):
		nodeName = domutil.getValue(domutil.getChildNode(node,"hostname"))
		modelName = domutil.getValue(domutil.getChildNode(node, "model"))

		newNode = vsapi.VizNode(nodeName, modelName, nodeIdx)
		nodeIdx = nodeIdx+1

		try:
			newNode.setAllocationBias(int(domutil.getValue(domutil.getChildNode(node, "weight"))))
		except:
			pass

		propsNode = domutil.getChildNode(node, "properties")
		if propsNode is not None:
			for pn in domutil.getAllChildNodes(propsNode):
				newNode.setProperty(pn.nodeName, domutil.getValue(pn))
		resList = []
		gpus = []
		for gpu in domutil.getChildNodes(node, "gpu"):
			inGPU  = vsapi.deserializeVizResource(gpu, [vsapi.GPU])
			if inGPU.getUseScanOut() is None:
				raise vsapi.VizError(vsapi.VizError.BAD_CONFIGURATION, "ERROR: useScanOut needs to be defined for every GPU")

			try:
				newGPU = copy.deepcopy(sysConfig['templates']['gpu'][inGPU.getType()])
			except KeyError, e:
				raise vsapi.VizError(vsapi.VizError.BAD_CONFIGURATION, "ERROR: No such GPU type '%s'"%(inGPU.getType()))

			# FIXME: implement a GPU.copyTemplate function that will copy the template info
			newGPU.setIndex(inGPU.getIndex())
			newGPU.setHostName(nodeName)
			newGPU.setBusId(inGPU.getBusId())
			newGPU.setUseScanOut(inGPU.getUseScanOut())
			newGPU.setAllowStereo(inGPU.getAllowStereo())
			newGPU.setShareLimit(inGPU.getShareLimit())
			if inGPU.isSharable():
				newGPU.setSharedServerIndex(inGPU.getSharedServerIndex())
			newGPU.clearScanouts()
			allSC = inGPU.getScanouts()
			if allSC is not None:
				for pi in allSC.keys():
					thisScanout = allSC[pi]
					if thisScanout is None:
						continue
					newGPU.setScanout(pi, thisScanout['display_device'], thisScanout['type'])
			gpus.append(newGPU)
		if len(gpus)==0:
			print >>sys.stderr, "WARNING: Node %s has no GPUs."%(nodeName)
		resList += gpus

		for sli in domutil.getChildNodes(node, "sli"):
			newSLI = vsapi.deserializeVizResource(sli, [vsapi.SLI])
			if (newSLI.getIndex() is None) or (newSLI.getType() is None) or (newSLI.getGPUIndex(0) is None) or (newSLI.getGPUIndex(1) is None):
				raise vsapi.VizError(vsapi.VizError.BAD_CONFIGURATION, "Incompletely specified SLI bridge for host %s"%(nodeName))

			newSLI.setHostName(nodeName)
			resList.append(newSLI)

		keyboards = []
		for kbd in domutil.getChildNodes(node,"keyboard"):
			dev_index = int(domutil.getValue(domutil.getChildNode(kbd,"index")))
			dev_type = domutil.getValue(domutil.getChildNode(kbd,"type"))
			physNode = domutil.getChildNode(kbd,"phys_addr")
			if physNode is not None:
				dev_phys = domutil.getValue(physNode)
			else:
				dev_phys = None
			keyboards.append(vsapi.Keyboard(dev_index, nodeName, dev_type, dev_phys))
		resList += keyboards

		mice = []
		for mouse in domutil.getChildNodes(node,"mouse"):
			dev_index = int(domutil.getValue(domutil.getChildNode(mouse,"index")))
			dev_type = domutil.getValue(domutil.getChildNode(mouse,"type"))
			physNode = domutil.getChildNode(mouse,"phys_addr")
			if physNode is not None:
				dev_phys = domutil.getValue(physNode)
			else:
				dev_phys = None
			mice.append(vsapi.Mouse(dev_index, nodeName, dev_type, dev_phys))
		resList += mice

		X_servers = {}
		all_servers = []
		for xs in domutil.getChildNodes(node, "x_server"):
			serverTypeNode = domutil.getChildNode(xs, "type")
			if serverTypeNode is not None:
				serverType = domutil.getValue(serverTypeNode)
			else:
				serverType = vsapi.NORMAL_SERVER
			if serverType not in vsapi.VALID_SERVER_TYPES:
				raise vsapi.VizError(vsapi.VizError.BAD_CONFIGURATION, "ERROR: Bad server type %s"%(serverType))

			rangeNode = domutil.getChildNode(xs, "range")
			fromX = int(domutil.getValue(domutil.getChildNode(rangeNode, "from")))
			toX = int(domutil.getValue(domutil.getChildNode(rangeNode, "to")))
			if toX<fromX:
				raise vsapi.VizError(vsapi.VizError.BAD_CONFIGURATION, "FATAL: Bad input. Xserver range cannot have a 'to' less than 'from'")

			for xv in range(fromX, toX+1):
				if X_servers.has_key(xv):
					raise vsapi.VizError(vsapi.VizError.BAD_CONFIGURATION, "ERROR: Bad input. Xserver %d used more than once"%(xv))

				X_servers[xv]=None
				svr = vsapi.Server(xv, nodeName, serverType)
				sharedGPUs = filter(lambda x:x.isSharable(), gpus)
				# Don't add shared servers as resources
				if xv not in map(lambda x:x.getSharedServerIndex(), sharedGPUs):
					all_servers.append(svr)
		if len(all_servers)==0:
			raise vsapi.VizError(vsapi.VizError.BAD_CONFIGURATION, "WARNING: Node %s has no X Servers."%(nodeName))
		resList += all_servers

		newNode.setResources(resList)
		sysConfig['nodes'][nodeName] = newNode

	# Process scheduler
	schedNodes = domutil.getChildNodes(root_node,"scheduler")
	if len(schedNodes)==0:
		raise vsapi.VizError(vsapi.VizError.BAD_CONFIGURATION, "FATAL: You need to specify at-least a scheduler")

	schedList = []
	for sNode in schedNodes:
		typeNode = domutil.getChildNode(sNode,"type")
		if typeNode is None:
			raise vsapi.VizError(vsapi.VizError.BAD_CONFIGRUATION, "FATAL: You need to specify a scheduler")

		# Get the scheduler specific params
		# Not specifying a parameter just results in passing an empty string
		paramNode = domutil.getChildNode(sNode,"param")
		param = ""
		if paramNode is not None:
			param=domutil.getValue(paramNode)

		nodeNodes = domutil.getChildNodes(sNode, "node")
		if len(nodeNodes)==0:
			raise vsapi.VizError(vsapi.VizError.BAD_CONFIGURATION, "FATAL: You need specify at-least one node per scheduler")

		nodeList = []
		for nodeNode in nodeNodes:
			nodeList.append(domutil.getValue(nodeNode))

		try:
			sched = metascheduler.createSchedulerType(domutil.getValue(typeNode), nodeList, param)
			schedList.append(sched)
		except ValueError, e:
			raise vsapi.VizError(vsapi.VizError.BAD_CONFIGURATION, "Error creating a scheduler : %s"%(str(e)))

	# Ensure that one node is managed by only one scheduler
	allNodeNames = []
	for sched in schedList:
		allNodeNames += sched.getNodeNames()
	allNames = {}
	for nodeName in allNodeNames:
		if allNames.has_key(nodeName):
			allNames[nodeName] += 1
		else:
			allNames[nodeName] = 1
	if len(allNames.keys())<len(allNodeNames):
		raise vsapi.VizError(vsapi.VizError.BAD_CONFIGURATION, "ERROR: One or more nodes have been mentioned more than once in the scheduler configuration. VizStack does not allow a single node to be managed by more than one scheduler at a time.")

	sysConfig['schedulerList'] = schedList

	# FIXME: check that all nodes are managed by some scheduler
	# If not, then that item will never be usable ! This is an
	# important debugging check

	# Load the resource groups
	resgroups = loadResourceGroups(sysConfig, rg_config_file)
	sysConfig['resource_groups'] = resgroups

	return sysConfig

def parseXLogFile(xServerNumber=0):
	try:
		fname = '/var/log/Xorg.%d.log'%(xServerNumber)
		f = open(fname,'r')
	except IOError, e:
		raise ValueError, "Invalid server number. Failed to open file '%s'. Reason : %s"%(fname, str(e))

	# Extract all file data
	all_lines = f.readlines()
	f.close()

	# NOTE: each of the regexps below have an extra ".*" before
	# NVIDIA. Some versions of the driver append a date value
	# in every line, and this takes care of those cases.
	#
	#Detect the starting of the EDID
	# Sample lines I've seen are
	#(--) NVIDIA(0): --- EDID for LPL (DFP-0) ---
	#
	edid_header_re = re.compile("^\(--\)[\s]+.*NVIDIA\(([0-9]+)\):[\s]+---[\s]+EDID[\s]+for[\s]+(.*)[\s]+\(([A-Z]+)\-([0-9]+)\)[\s]+---[\s]+$")

	#
	# Property lines can be
	#'(--) NVIDIA(0): 32-bit Serial Number         : 0' # Value = 0
	#'(--) NVIDIA(0): Serial Number String         : '  # NOTE: no Value!
	#
	edid_prop_re = re.compile("^\(--\)[\s]+.*NVIDIA\(([0-9]+)\):[\s]+(.*)[\s]+:[\s]+((.*)[\s]+)?$")

	# Properties end with
	edid_end_prop_re = re.compile("^\(--\)[\s]+.*NVIDIA\(([0-9]+)\):[\s]+$")

	# EDIDs have this 'Prefer first detailed timing' property.
	# If set to 'Yes', then the mode following the below line is the default mode for the
	# device
	#(--) NVIDIA(0): Detailed Timings:
	edid_detailed_timing_re = re.compile("^\(--\)[\s]+.*NVIDIA\(([0-9]+)\):[\s]+Detailed Timings:[\s]*$")

	# Each supported mode is shown as
	# '(--) NVIDIA(0):   1280 x 800  @ 60 Hz'
	edid_supported_mode_re = re.compile("^\(--\)[\s]+.*NVIDIA\(([0-9]+)\):[\s]+([0-9]+)[\s]+x[\s]+([0-9]+)[\s]+@[\s]+([0-9\.]+)[\s]+Hz[\s]*$")

	# Modes are followed by the Raw EDID bytes
	#'(--) NVIDIA(0): Raw EDID bytes:'
	edid_raw_edid_start_re = re.compile("^\(--\)[\s]+.*NVIDIA\(([0-9]+)\):[\s]+Raw EDID bytes:[\s]*$")

	# EDID data bytes are in this format
	#(--) NVIDIA(0):   00 4c 50 31 34 31 57 58  31 2d 54 4c 41 32 00 ae
	edid_data_re = re.compile("^\(--\)[\s]+.*NVIDIA\(([0-9]+)\):[\s]+"+ ("([0-9a-f]{2})[\s]+"*16)+"[\s]*$")
	edid_footer_re = re.compile("^\(--\)[\s]+.*NVIDIA\(([0-9]+)\):[\s]+---[\s]+End[\s]+of[\s]+EDID[\s]+for[\s]+(.*)[\s]+\(([A-Z]+)\-([0-9]+)\)[\s]+---[\s]+$")

	# Supported display devices can span two lines...
	#(II) Mar 10 06:40:21 NVIDIA(0): Supported display device(s): CRT-0, CRT-1, DFP-0, DFP-1,
	#(II) Mar 10 06:40:21 NVIDIA(0):     DFP-2, DFP-3
	sup_dd_re = re.compile("^\(II\)[\s]+.*NVIDIA\(([0-9]+)\):[\s]+Supported display device\(s\):(.*)$")
	ext_sup_dd_re = re.compile("^\(II\)[\s]+.*NVIDIA\(([0-9]+)\):[\s](.*)$")
	
	# Process line by line
	lineNum = -1
	maxLines = len(all_lines)

	allDisplays = []
	allScanouts = []
	while lineNum < (maxLines-1):
		lineNum += 1
		thisLine = all_lines[lineNum]

		ddcapmatch = sup_dd_re.match(thisLine)
		if ddcapmatch:
			ddcapProps = ddcapmatch.groups()
			allDevs = ddcapProps[1].lstrip().rstrip()
			if len(allDevs)>0: # Empty match means no display devices are supported
				thisGPUScanout = {}
				thisGPUScanout['GPU']=int(ddcapProps[0])
				if allDevs[-1]==',':
					lineNum += 1
					ddcapmatch = ext_sup_dd_re.match(all_lines[lineNum])
					ddcapProps = ddcapmatch.groups()
					otherDevs = ddcapProps[1].lstrip().rstrip()
					allDevs += otherDevs
				allDevs = map(lambda x:x.lstrip().rstrip(), allDevs.split(','))
				gpuScanouts = {}
				for dev in allDevs:
					parts = dev.split('-')
					port_index = int(parts[1])
					port_type = parts[0]
					try:
						gpuScanouts[port_index].append(port_type)
					except:
						gpuScanouts[port_index]=[port_type]
				thisGPUScanout['scanouts']=gpuScanouts
				allScanouts.append(thisGPUScanout)
				# Done for this line
				continue

		headerMatch = edid_header_re.match(thisLine)
		# Ignore lines till the beginning of an EDID header
		if headerMatch is None:
			continue

		thisDisplay = {}
		headerProps = headerMatch.groups()
		thisDisplay['GPU'] = int(headerProps[0])
		thisDisplay['display_device'] = headerProps[1]
		thisDisplay['port_index'] = int(headerProps[3])
		thisDisplay['output_type'] = headerProps[2]
		thisDisplay['edid_modes'] = []
		thisDisplay['edid_bytes'] = []

		# The header will be followed by a list of properties
		# that the nvidia driver decodes from the EDID
		# The end of this information is indicated with a line like
		# "(--) NVIDIA(0): "
		while lineNum < (maxLines-1):
			lineNum += 1
			thisLine = all_lines[lineNum]
			mob2 = edid_end_prop_re.match(thisLine)
			if mob2 is None:
				propMatch = edid_prop_re.match(thisLine)
				if propMatch is not None:
					#print propMatch.groups()
					propMatches = propMatch.groups()
					propName = propMatches[1].rstrip()
					thisDisplay[propName]=propMatches[3]
					
				else:
					raise ValueError, "Failed parsing line:'%s'"%(thisLine)
			else:
				break

		next_is_default = False
		# Next find all supported modes
		while lineNum < (maxLines-1):
			lineNum += 1
			thisLine = all_lines[lineNum]
			mob2 = edid_raw_edid_start_re.match(thisLine)
			if mob2 is None:
				# FIXME: we have to handle "preferred mode"s here!
				# this manifests as "prefer first detailed timing" on edids
				matchedMode = edid_supported_mode_re.match(thisLine)
				if matchedMode is not None:
					#print matchedMode.groups()
					matchedMode = matchedMode.groups()
					mode_width = int(matchedMode[1])
					mode_height = int(matchedMode[2])
					mode_refresh = matchedMode[3]
					thisDisplay['edid_modes'].append([mode_width, mode_height, mode_refresh])
					if next_is_default:
						thisDisplay['first_detailed_timing'] = [mode_width, mode_height, mode_refresh]
						next_is_default = False
				else:
					doesMatch = edid_detailed_timing_re.match(thisLine)
					if doesMatch is not None:
						next_is_default = True
			else:
				break

		# Next leach all EDID data bytes
		# till the end of EDID
		while lineNum < (maxLines-1):
			lineNum += 1
			thisLine = all_lines[lineNum]
			footerMatch = edid_footer_re.match(thisLine)
			if footerMatch is None:
				# Till we reach the footer, we may get data bytes
				edidData = edid_data_re.match(thisLine)
				if edidData is not None:
					#print edidData.groups()
					for edidByte in edidData.groups()[1:]:
						thisDisplay['edid_bytes'].append(edidByte)
			else:
				break
		hsr = thisDisplay['Valid HSync Range'].split('-')
		hsyncMin = hsr[0].lstrip().rstrip().split(' ')[0]
		hsyncMax = hsr[1].lstrip().rstrip().split(' ')[0]
		#print hsyncMin, hsyncMax

		vsr = thisDisplay['Valid VRefresh Range'].split('-')
		vrefreshMin = vsr[0].lstrip().rstrip().split(' ')[0]
		vrefreshMax = vsr[1].lstrip().rstrip().split(' ')[0]
		thisDisplay['hsync_range'] = [hsyncMin, hsyncMax]
		thisDisplay['vrefresh_range'] = [vrefreshMin, vrefreshMax]
		#print vrefreshMin, vrefreshMax

		# Create a display device object representing this display device
		thisDD = vsapi.DisplayDevice(thisDisplay['display_device'])
		thisDD.setEDIDDisplayName(thisDisplay['display_device'])
		thisDD.setHSyncRange(thisDisplay['hsync_range'])
		thisDD.setVRefreshRange(thisDisplay['vrefresh_range'])
		thisDD.setEDIDBytes(string.join(thisDisplay['edid_bytes'],""))
		for modeDesc in thisDisplay['edid_modes']:
			thisDD.addMode('edid', '%dx%d_%s'%(modeDesc[0], modeDesc[1], modeDesc[2]), modeDesc[0], modeDesc[1], modeDesc[2])
		if thisDisplay.has_key('first_detailed_timing'):
			modeDesc = thisDisplay['first_detailed_timing']
			thisDD.setDefaultMode('%dx%d_%s'%(modeDesc[0], modeDesc[1], modeDesc[2]))
		if thisDisplay['output_type']=='DFP':
			thisDD.setInput('digital')
		elif thisDisplay['output_type']=='CRT':
			thisDD.setInput('analog')
		thisDisplay['display_template'] = thisDD
		if thisDisplay.has_key('Maximum Image Size'):
			dims = map(lambda x:int(x[:-2]), map(lambda x:x.strip(), thisDisplay['Maximum Image Size'].split('x')))
			thisDD.setDimensions(dims)

		# Add this to our list of displays
		allDisplays.append(thisDisplay)

	return {'possible_scanouts': allScanouts, 'connected_displays': allDisplays}

def normalizeRG(rg):
	"""
	'Normalizes' a resource group. This basically passes through
	each reslist in the rg, and if only one resource has a hostname
	defined, then it pastes the hostname to all other resources.
	"""
	outRG = copy.deepcopy(rg)
	allRes = outRG.getResources()
	outResList = []
	for resList in allRes:
		if isinstance(resList, list):
			hostNames = []
			for res in resList:
				thisHostName = res.getHostName()
				if (thisHostName is not None) and (thisHostName not in hostNames):
					hostNames.append(thisHostName)
			#paste the hostname into all resources
			if len(hostNames)==1:
				onlyHostName = hostNames[0]
				for res in resList:
					res.setHostName(onlyHostName)
		outResList.append(resList)
	outRG.setResources(allRes)
	return outRG

def expandNodes(spec):
	"""
	Expand a nodelist, SLURM style.
	prefix[1-5,7,8] becomes prefix1 prefix2 prefix3 prefix4 prefix5 prefix7 prefix8
	viz[00-05] becomes viz00 viz01 viz03 viz04 viz05
	"""
	ob = re.match('^(.*)\[([0-9,+\-]+)\]$', spec)
	if ob is None:
		return [spec]

	nodePrefix = ob.groups()[0]
	if len(nodePrefix)==0:
		raise ValueError, "Bad node specification %s"%(spec)

	expansionSpec = ob.groups()[1]
	ranges = expansionSpec.split(",")
	nodeSuffix = []
	for thisRange in ranges:
		if len(thisRange)==0: # Empty string, error
			raise ValueError, "Bad node specification %s"%(spec)
		rangeParts = thisRange.split("-")
		if len(rangeParts)==1: # only number
			try:
				nodeSuffix.append(int(rangeParts[0]))
			except:
				raise ValueError, "Bad node specification %s"%(spec)
		elif len(rangeParts)==2:
			try:
				fromIndex = int(rangeParts[0])
				toIndex = int(rangeParts[1])
				if toIndex<fromIndex:
					raise ValueError, "Bad node specification %s"%(spec)
			except:
				raise ValueError, "Bad node specification %s"%(spec)

			for idx in range(fromIndex,toIndex+1):
				suffixStr = str(idx)
				if len(rangeParts[0])==len(rangeParts[1]):
					# In some cases, names of the nodes can have leading zeroes
					# a simple integer interpolation omits the leading 0s in this
					# case. We fix that by padding with starting zeroes !
					# Note that this may still cause problems if the nodes are 
					# numbered e.g. viz7 viz08 amd viz09. We'll live with that !
					while len(suffixStr)<len(rangeParts[1]):
						suffixStr = '0'+suffixStr
				nodeSuffix.append(suffixStr)

	return map(lambda x: nodePrefix+str(x) , nodeSuffix)

if __name__ == "__main__":
	ra = vsapi.ResourceAccess()
	alloc = ra.allocate([vsapi.ResourceGroup('desktop-right-2x2')])
	alloc.setupViz(ra)
	alloc.startViz(ra)
	refreshRate, msg =  enableFrameLock(alloc.getResources())
	print msg
	print disableFrameLock(alloc.getResources())
	#print '---- shell ----'
	#os.system('bash')
	#print '-- out of shell --'
	alloc.stopViz(ra)
	ra.stop()

	# EDID parsing based display detection testing
	# Note : uses X server 0
	displayList = getConnectedDisplays(0)
	gpuDisplays = {}
	for display in displayList:
		thisGPU = display['GPU']
		thisMonitor = display['display_device']
		try:
			gpuDisplays[thisGPU].append(thisMonitor)
		except KeyError:
			gpuDisplays[thisGPU]=[thisMonitor]
	pprint(gpuDisplays)
