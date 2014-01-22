#!/usr/bin/env python
"""
laptop.py

Used by Shree to setup his laptop !

HP Pavillion DV2117 TX (based on DV 2000). 
Equipped with a GeForce Go 7200.
"""

import vsapi
from pprint import pprint
import os

# Connect to the SSM
ra = vsapi.ResourceAccess()

# Allocate an X server, and one GPU
# keeping these in the same innerlist ensures that all 
# of them are allocated from the same node.
#
print "Allocating Resources..."
alloc = ra.allocate([
	[ vsapi.Server(0), vsapi.GPU(), vsapi.Keyboard(), vsapi.Mouse()]
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
kbd = resources[0][2]
mouse = resources[0][3]

ddName = "HP DV2000"
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

# Screen 0 drives the inbuilt LCD of my laptop
#
scr = vsapi.Screen(0)
gpu.setScanout(port_index=0, display_device=dispDevice)
scr.setGPU(gpu)
srv.addScreen(scr)
srv.setKeyboard(kbd) # The X server on my laptop lets me use the built-in
srv.setMouse(mouse)  # keyboard and mouse even if I set these to None!

# Propagate server configuration to the SSM
alloc.setupViz(ra)

# Start X Server
alloc.startViz(ra)

desktop = scr.run(["gnome-session"])
desktop.wait()

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
