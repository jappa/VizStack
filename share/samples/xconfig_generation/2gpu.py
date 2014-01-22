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
2gpu.py

Demonstrates how to generate an X configuration file.

Configures an X server with two screens. Each screen
controls one GPU. Each GPU drives an LP2065 monitor from output 0.

This script creates the XML corresponding to the X server
configuration & writes it to a temporary file.

This temporary file is passed an input to vs-generate-xconfig.
This tool generates the X configuration file corresponding to
the configuration.

Concepts demonstrated:
1. This script shows one use of vsapi without connecting to SSM.
2. How to get configuration XML corresponding to an X server.
3. Generate X configuration file for X server using VizStack
   tools.

"""
import vsapi
import os
import tempfile
import sys

# Create & configure the first GPU on the system. 
gpu0 = vsapi.GPU(0)
gpu0.setScanout(0, "HP LP2065") # LP2065 connected to port 0
# If you need the other output, comment out the following line
# This will configure the 
#gpu0.setScanout(1, "LP2065", outputX=1600)

# Create & configure the second GPU on the system. 
gpu1 = vsapi.GPU(1)
gpu1.setScanout(0, "HP LP2065") # LP2065 connected to port 0
# If you need the other output, comment out the following line
# This will configure the 
#gpu1.setScanout(1, "LP2065", outputX=1600)

# Create an X screen, and assign the first GPU
# to drive this screen
scr0 = vsapi.Screen(0)
scr0.setFBProperty('position',[0,0])
scr0.setGPU(gpu0)

# Create another X screen, and assign the second GPU
# to drive this screen
scr1 = vsapi.Screen(1)
scr1.setFBProperty('position',[0,1200]) # Screen 1 below screen 0
scr1.setGPU(gpu1)

# Create a server, and all screens to it
srv = vsapi.Server()
srv.addScreen(scr0)
srv.addScreen(scr1)
#Uncomment the following line to enable Xinerama
#srv.combineScreens(True)

# Get the XML corresponding to this server configuration
configXML = srv.serializeToXML()

# Populate XML into a temporary file
(fd, tempFile) = tempfile.mkstemp()
os.write(fd, configXML)
os.close(fd)

# Invoke configuration file generator with this input
# This will print out the X configuration file
ret = os.system("/opt/vizstack/bin/vs-generate-xconfig --input=%s"%(tempFile))
if ret!=0:
	print >>sys.stderr, "Failed to generate X configuration file."

# Remove our temporary file
os.unlink(tempFile)

# Done!
sys.exit(ret)
