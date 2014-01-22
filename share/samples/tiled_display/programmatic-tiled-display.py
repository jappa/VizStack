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
programmatic-tiled-display.py

Demonstrates how to setup a Tiled Display programmatically.

By "programmatically", I mean that the Tiled Display will be 
defined completely by programming. 

In VizStack, Tiled Displays are a handler of "ResourceGroup".
ResourceGroups are VizResourceAggregates, meaning that
they can contain many VizResources.

Concepts demonstrated : 

1. How to populate a ResourceGroup with resources needed for
   a tiled display
2. How to get the XML needed for a ResourceGroup. There's no
   tool to specify a Tiled Display yet. Printing out this 
   XML is a good way to get what to paste into 
   resource_group_config.xml
3. Running programs on the TiledDisplay

NOTE: This program uses hostnames specific to the site
where the VizStack developer does programming. You _will_
need to change the hostnames, else the script will fail
with a helpful error message.

"""

import vsapi
from pprint import pprint
from copy import deepcopy
import string
import os
import sys

# Connect to the SSM
ra = vsapi.ResourceAccess()

myRG = vsapi.ResourceGroup(
	name = "customRG",
	handler = "tiled_display",
	handler_params = string.join([ 
	    "block_type='gpu'", # Only accepted value
	    "block_display_layout=[2,1]", # Each GPU will drive 2x1
	    "num_blocks=[1,2]", # and GPUs will be arranged as 1x2. These two together will give us 2x2 out of a single node
	    "display_device='HP LP2065'", # Use a HP LP2065 monitor as the display device. So no stereo :-(
	], ";"), # This actually generates a valid python code fragment, with variables separated by ';'
	resources = [
		# The above parameters need two GPUs. We will supply those from
		# the node 'slestest1', and GPUs 0 & 1 on the same node
		# Note that we don't say that we need a specific X server - VizStack
		# chooses one for us automatically
		# However, we do give out specific GPUs. This assumes that GPUs are
		# wired statically and you know what goes where !

		[ vsapi.Server(hostName="slestest1"), vsapi.GPU(0), vsapi.GPU(1) ] 

		#
		# For this tiled display, the GPU to display wiring will be
		#
		# Note : both GPUS on node 'slestest1'
		#
		# +---------------+------------------+
		# | GPU 0, Port 0 | GPU 0, Port 1    |
		# +---------------+------------------+
		# | GPU 1, Port 0 | GPU 1, Port 1    |
		# +---------------+------------------+
		#
	]
)

# Alternatively, you may try the following for "resources". This will configure
# a 2x2 display surface using two GPUs, one each from a separate node.
# Note that this configuration also uses one X server per node (not just a GPU)
#
#	resources = [
#		# We will supply two GPUs from two separate nodes.
#		# One from 'slestest1', and one from 'slestest3'
#		[ vsapi.Server(hostName="slestest1"), vsapi.GPU(0) ],
#		[ vsapi.Server(hostName="slestest3"), vsapi.GPU(0) ] 
#	]


# Allocate the above RG
print "Allocating Resources..."
try:
	alloc = ra.allocate([
		myRG	
	])
except vsapi.VizError, e:
	print >>sys.stderr
	print >>sys.stderr, "Failed to allocate resources that I need. Reason:"
	print >>sys.stderr, str(e)
	print >>sys.stderr
	print >>sys.stderr, "Please ensure that you have modified the hostnames"
	print >>sys.stderr, "in this script to suit your site. Else it may not"
	print >>sys.stderr, "work"
	print >>sys.stderr
	sys.exit(-1)

# Get all resources that got allocated
resources = alloc.getResources()

print
print "Allocated Resources are :"
pprint(resources)

# Since we only asked for a ResourceGroup, that's what the above line
# will print out. Probably makes no sense anyway!
# Probe deeper...

# Get the allocated Resource Group.
allocRG = resources[0] # We get things in the order that we pass things in !

# This gives you the real Tiled Display
myTD = allocRG.getHandlerObject()

# Now display the layout
tdim = myTD.getLayoutDimensions()
cols = tdim[0]
rows = tdim[1]
print 'Tiled Display Dimensions = %s'%(tdim)
tdLayout = myTD.getLayoutMatrix()
# This will print two screens one below the other. Each screen
# controls one GPU
pprint(tdLayout) 

# Propagate server configuration to the SSM
alloc.setupViz(ra)

print "If you need to make this a permanently defined Display Surface, then copy paste"
print "the following text into resource_group_config.xml on the master node. Then"
print "restart the SSM"
print "------------8<-----------------"
print myRG.serializeToXML()
print "------------8<-----------------"

print
print "Starting X server(s) needed for display surface..."
alloc.startViz(ra)

# Run xwininfo on each GPU to show you how things are setup
for rowNum in range(rows):
	for colNum in range(cols):
		thisScreen = tdLayout[rowNum][colNum]
		print "GPU %dx%d is %s "%(colNum, rowNum, thisScreen.getGPUs()[0])
		# Run xwininfo & wait for it to finish.
		proc = thisScreen.run(["xwininfo","-root")
		proc.wait()

# Stop the X servers
print
print "Stopping X server"
alloc.stopViz(ra)

# Deallocate resources
print "Freeing resources..."
ra.deallocate(alloc)

# Disconnect from SSM
ra.stop()
print "Done!"
