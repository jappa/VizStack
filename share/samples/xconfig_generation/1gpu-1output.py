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
1gpu-1output.py

Demonstrates how to generate an X configuration file.

Configures an X server with a single screen. The screen
controls GPU0. From output 0, it drive an LP2065 monitor.

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

# Create & configure GPU. Index can range from 0-(n-1) where
# n is the number of GPUs on this machine.
gpu = vsapi.GPU(0)
gpu.setScanout(0, "HP LP2065") # LP2065 connected to port 0
# If you need the other output, comment out the following line
# This will configure the 
#gpu.setScanout(1, "LP2065", outputX=1600)

# Create an X screen
scr = vsapi.Screen(0)
# Assign the GPU to drive this screen.
scr.setGPU(gpu)

# Create a server, and add this screen to it
srv = vsapi.Server()
srv.addScreen(scr)

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
