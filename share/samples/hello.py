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

import vsapi

# Connect to the SSM
ra = vsapi.ResourceAccess() 

# Allocate a GPU and a Server on the same node
alloc = ra.allocate([ [vsapi.GPU(), vsapi.Server()] ])
res = alloc.getResources()
gpu = res[0][0]
srv = res[0][1]

screen = vsapi.Screen(0)

# Setup the X screen
if gpu.getAllowNoScanOut():
	gpu.clearScanouts()
	screen.setFBProperty('resolution', [1280,1024])
else:
	if len(gpu.getScanouts())==0:
		sc = gpu.getScanoutCaps()
		gpu.setScanout(0, 'HP LP2065', sc[0][0])

# X screen controls the allocated GPU
screen.setGPU(gpu)

# Configure the screen on our allocated server
srv.addScreen(screen)

# Configure X server - this propagates the X server
# configuration to the SSM
alloc.setupViz(ra)

# Start X server
alloc.startViz(ra)

# Run glxinfo on the server
proc = srv.run(['glxinfo'])
proc.wait()

# Stop the X servers
alloc.stopViz(ra)

# Give up the resources we are using
ra.deallocate(alloc)

# Disconnect from the SSM
ra.stop()
