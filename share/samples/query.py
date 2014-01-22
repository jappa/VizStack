#!/usr/bin/env python
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
query.py : Sample to illustrate querying VizStack for resource related information.

This programs shows how you can find all kinds of information about the VizStack 
managed system
  - what display devices are defined in the system
  - what GPUs are defined in the system
  - what resources are available
  - which nodes have what resources
  - how many resource allocations are active in the system
  - which allocations are using what resources

Note that VizStack has the following kind of resources : GPU, Server, Keyboard, 
Mouse, and SLI (not at this time).
"""

import vsapi
from pprint import pprint

#
# Most programs that use the vsapi will connect to the SSM.
# An SSM connection is needed for allocating, configuring 
# and deallocating resources. 
#
# A connection to the SSM is also required to query the SSM
# about resources in the system (which is the purpose of this
# sample program)
#
ra = vsapi.ResourceAccess()

# First, lets see what DisplayDevices are defined in
# this system.
displayDevices = ra.getTemplates(vsapi.DisplayDevice())
# Print out information about each
for device in displayDevices:
	print "Display Device : %s"%(device.getType())

	defaultMode = device.getDefaultMode()
	print "Preferred Mode : %s"%(defaultMode['alias'])
	print "The following modes supported are supported with this display device :"

	allModes = device.getAllModes()
	for mode in allModes:
		# FIXME: we need to add a "stereo" attribute here
		# NOTE: Refresh Rate is a "string" value
		print "    Mode Name: %s"%(mode['alias'])
		print "         Resolution = %dx%d pixels, Refresh Rate = %s Hz"%(mode['width'], mode['height'], mode['refresh'])
		bezel_left = mode['bezel']['left']
		bezel_right = mode['bezel']['right']
		bezel_bottom = mode['bezel']['bottom']
		bezel_top = mode['bezel']['top']
		if bezel_left+bezel_right+bezel_bottom+bezel_top>0:
			print "         Bezels :",
			for bpos in ['left','right','bottom','top']:
				if mode['bezel'][bpos]>0:
					print "%s %d px "%(bpos, mode['bezel'][bpos]),
			print
	print

# Next, lets get a list of GPU resources available
gpuList = ra.queryResources(vsapi.GPU())
print "Total Number of GPU resources present : %d"%(len(gpuList))
# Compute how many of which type are present
gpuTypeInfo = {}
for gpu in gpuList:
	gpuType = gpu.getType()
	try:
		gpuTypeInfo[gpuType] += 1
	except KeyError:
		gpuTypeInfo[gpuType] = 1

# and print it out...
for gpuType in gpuTypeInfo.keys():
	print "GPU type '%s', instances present = %d"%(gpuType, gpuTypeInfo[gpuType])

