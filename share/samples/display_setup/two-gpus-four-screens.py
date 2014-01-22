#!/usr/bin/env python
"""
two-gpus-four-screens.py

Demonstrates how to setup two GPUs on a node 
to drive 4 X screens, and one display device
through each screen.

Concepts demonstrated : 

1. How to use the same GPU in more than one screen.
2. How to get properties of a display device
3. How to configure multiple screens in a 2x2 logical layout

"""

import vsapi
from pprint import pprint
from copy import deepcopy # deepcopy is python function we'll use to copy GPUs
import os

# Connect to the SSM
ra = vsapi.ResourceAccess()

# Allocate an X server, and two GPUs - GPU 0 and GPU 1
# keeping these in the same innerlist ensures that all 
# of them are allocated from the same list.
print "Allocating Resources..."
alloc = ra.allocate([
	[ vsapi.Server(), vsapi.GPU(0), vsapi.GPU(1)]
])

# Get all resources that got allocated
resources = alloc.getResources()
print
print "Allocated Resources are :"
pprint(resources)

# Resources will be ordered in the same way we asked for them,
# so we know what stands for which
srv = resources[0][0]
gpu0 = resources[0][1]
gpu1 = resources[0][2]

ddName = "HP LP2065"

# Get information  corresponding to an LP2065 monitor
# NOTE: on success, we'll get a list with 1 element, and we
# use the first element
dispDevice = ra.getTemplates(vsapi.DisplayDevice(ddName))[0]

# Get default mode & its properties
defaultMode =  dispDevice.getDefaultMode() # get the default display mode for this device
modeAlias = defaultMode['alias'] # Unique identifier corresponding to this mode, e.g. 1600x1200_60
modeWidth = defaultMode['width'] # Width (in pixels) of this mode
modeHeight = defaultMode['height'] # Height (in pixels) of this mode
print
print "Using display device '%s', display mode '%s'."%(ddName, modeAlias)
print "Each GPU output will run at %dx%d@%sHz"%(modeWidth, modeHeight, defaultMode['refresh'])

# Screen 0 drives a LP2065 monitor at default resolution, from port 0 of GPU0
scr0 = vsapi.Screen(0)
scr0.setFBProperty('position',[0,0])
gpu0_0 = deepcopy(gpu0) # Make a copy of the GPU so that we can assign display devices
gpu0_0.setScanout(port_index=0, display_device=ddName)
scr0.setGPU(gpu0_0)
srv.addScreen(scr0)

# Screen 1 drives a LP2065 monitor at default resolution, from port 1 of GPU0
scr1 = vsapi.Screen(1)
scr1.setFBProperty('position',[modeWidth,0])
gpu0_1 = deepcopy(gpu0)
gpu0_1.setScanout(port_index=1, display_device=ddName)
scr1.setGPU(gpu0_1)
srv.addScreen(scr1)

# Screen 2 drives a LP2065 monitor at default resolution, from port 0 of GPU1
scr2 = vsapi.Screen(2)
scr2.setFBProperty('position',[0,modeHeight])
gpu1_0 = deepcopy(gpu1)
gpu1_0.setScanout(port_index=0, display_device=ddName)
scr2.setGPU(gpu1_0)
srv.addScreen(scr2)

# Screen 3 drives a LP2065 monitor at default resolution, from port 1 of GPU1
scr3 = vsapi.Screen(3)
scr3.setFBProperty('position',[modeWidth,modeHeight])
gpu1_1 = deepcopy(gpu1)
gpu1_1.setScanout(port_index=1, display_device=ddName)
scr3.setGPU(gpu1_1)
srv.addScreen(scr3)

# Propagate server configuration to the SSM
alloc.setupViz(ra)

# Start the server
print
print "Starting X server..."
alloc.startViz(ra)

srvDISPLAY = srv.getDISPLAY()
srvHost = srv.getHostName()
print
print "I've allocated X server '%s' at host '%s' for you"%(srvDISPLAY, srvHost)
print "This X server is setup to control 2 GPUs. Each GPU"
print "has two X screens configured on it, for a total of"
print "four X screens. The screens are laid out as below:"
print 
print "          +----------------+"
print "          | %5s +  %5s +"%(scr0.getDISPLAY(), scr1.getDISPLAY())
print "          +-------+--------+"
print "          | %5s +  %5s +"%(scr2.getDISPLAY(), scr3.getDISPLAY())
print "          +-------+--------+"
print
print "I'm starting an SSH shell to %s for you. To access the allocated X server,"%(srvHost)
print "you will need to set the DISPLAY environment variable as follows"
print 
print " $ export DISPLAY=%s # To access GPU 0, X Screen 0, Display Output 0"%(scr0.getDISPLAY())
print " $ export DISPLAY=%s # To access GPU 0, X Screen 1, Display Output 1"%(scr1.getDISPLAY())
print " $ export DISPLAY=%s # To access GPU 1, X Screen 2, Display Output 0"%(scr2.getDISPLAY())
print " $ export DISPLAY=%s # To access GPU 1, X Screen 3, Display Output 1"%(scr3.getDISPLAY())
print 
print "NOTE: The X servers will be stopeed and the resources"
print "will be cleaned up you exit from the SSH shell."
print 
print "========= SSH Session Started  ==================="
cmd = "ssh %s"%(srvHost)
os.system(cmd)
print "========= SSH Session Finished ==================="

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
