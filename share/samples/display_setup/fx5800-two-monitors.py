#!/usr/bin/env python
"""
fx5800-two-monitors.py

The Quadro FX 5800 card is capable of driving
two display outputs. 

This sample Demonstrates how to setup a 5800
to drive two DFPs. We'll setup a single large
screen (2x1), and each DFP will drive a third 
of the display.

Concepts demonstrated : 

1. How to allocate a specific type of GPU
   (a Quadro FX 5800 in this case)
2. How to get a specific display device and
   use its properties
3. How to configure a 2x1 display layout.

"""

import vsapi
from pprint import pprint
import os

# Connect to the SSM
ra = vsapi.ResourceAccess()

# Create an FX 5800 GPU template. using createGPU()
# helps the API validate user parameters earlier.
reqdGPU = ra.createGPU(model="Quadro FX 5800")

# Allocate an X server, and one Quadro FX 5800 GPU
# keeping these in the same innerlist ensures that all 
# of them are allocated from the same node.
#
# Note that if your system does not have a real
# FX 5800 GPU, then the allocation will fail.
#
print "Allocating Resources..."
alloc = ra.allocate([
	[ vsapi.Server(), reqdGPU]
])

# Get all resources that got allocated
resources = alloc.getResources()
print
print "Allocated Resources are :"
pprint(resources)

# Resources will be ordered in the same way we asked for them,
# so we know what stands for which
srv = resources[0][0]
gpu = resources[0][1]

ddName = "HP LP2065"
# Create an monitor. This only gets information about the
# needed type of display device
#
# NOTE: if the system does not define this display device,
# then we will fail
dispDevice = ra.createDisplayDevice(ddName)

# Get default mode & its properties
defaultMode =  dispDevice.getDefaultMode() # get the default display mode for this device
modeAlias = defaultMode['alias'] # Unique identifier corresponding to this mode, e.g. 1600x1200_60
modeWidth = defaultMode['width'] # Width (in pixels) of this mode
modeHeight = defaultMode['height'] # Height (in pixels) of this mode
print
print "Using display device '%s', display mode '%s'."%(ddName, modeAlias)
print "Each GPU output will run at %dx%d@%sHz"%(modeWidth, modeHeight, defaultMode['refresh'])

# Screen 0 drives two monitors side by side at default resolution,
# from ports 1 and 2 of the allocated GPU
# (one DVI-I & one DisplayPort)
#
# Only one X screen is used, so the application can directly span the two displays
#
scr = vsapi.Screen(0)
gpu.setScanout(port_index=1, display_device=dispDevice, outputX=0)
gpu.setScanout(port_index=2, display_device=dispDevice, outputX=modeWidth)
scr.setGPU(gpu)
srv.addScreen(scr)

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
print "This X server is setup to control a single GPUs."
print "This GPU has a single X screen configured to drive three '%s' displays"%(ddName)
print "side by side in a 3x1 configuration"
print 
print "The overall resolution of your desktop is %dx%d."%(modeWidth*2, modeHeight)
print
print "I'm starting an SSH shell to %s for you. To access the allocated X server,"%(srvHost)
print "you will need to set the DISPLAY environment variable as follows"
print 
print " $ export DISPLAY=%s "%(scr.getDISPLAY())
print 
print "NOTE: The X server will be stopeed and the resources"
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
