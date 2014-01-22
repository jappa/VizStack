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
Script to demonstrate usage of RGS with an 
auto-stereoscopic monitor.

Here is the scenario :

1. You have a few nodes with two GPUs.

2. All these nodes are setup as follows :
    - the second GPU is connected to a Tridelity 
      auto-stereoscopic monitor over a DVI extender
    - the first GPU needs to be used for running 
      a remote desktop using HP RGS.

3. The application will run on the HP RGS desktop,
   and show stereoscopic output on the tridelity monitor.

4. The user will use the Tridelity desktop with the
   RGS desktop side by side.

"""

import vsapi
import viz_rgs

searchNodeList = ['node1','node5','node6']

ra = vaspi.ResourceAccess()

alloc = ra.allocate([
	   [vsapi.Server(), vsapi.GPU(0), vsapi.GPU(1)] # Allocate a server, GPU0 and GPU1 all on the same node
        ], searchNodeList)                              # with the restriction that the node is in this list

allocResources = alloc.getResources()
xServer = allocResources[0]
rgsGPU = allocResources[1]
autoStereoGPU = allocResources[2]

rgsScreen = vsapi.Screen(0)
rgsScreen.setFBProperties('resolution', [1280,1024])
rgsScreen.setGPU(rgsGPU)

autoStereoScreen = vsapi.Screen(1)
autoStereoGPU.setScanout(
	port_index = 0,
	display_device = "XYZ") # Name of the display device here !
autoStereoScreen.setFBProperties('stereo',"SeeReal_stereo_dfp")
autoStereoScreen.setGPU(autoStereoGPU)

xServer.addScreen(rgsScreen)
xServer.addScreen(autoStereoGPU)

# Enable RGS on this X server. This will remote screen #0
viz_rgs.setupRGS(xServer)

# Propagate X server settings to SSM
alloc.setupViz(ra)

# Start RGS via GDM. This does the job of startViz,
# including waiting for the availability of this X server
rgsProc = viz_rgs.startGDM(xServer, alloc, ra)

if rgsProc is None:
	print >>sys.stderr, "Failed to start RGS"
	sys.exit(-1)

# Get information about the node where the X server is running
tvncNode = ra.queryResources(vsapi.VizNode(xServer.getHostName()))[0]
try:
	externalName = tvncNode.getProperty('remote_hostname')
except KeyError, e:
	print >>sys.stderr, "Failed to get the remote access hostname. Will use local hostname."
	externalName = xServer.getHostName()
	if externalName == "localhost": # Localhost needs to be expanded for single node case
		externalName = socket.gethostname()
userConnectsTo = externalName
print "==============================================================="
print "A desktop has been started for you at '%s' "%(userConnectsTo)
print "==============================================================="

# Wait till the user logs out (detected by waiting on X server to disconnect)
# "None" for timeout results in an infinite wait.
try:
	ra.waitXState(alloc, 0, None, [xServer])
except KeyboardInterrupt, e:
	pass # follow through to kill stuff anyway
except vsapi.VizError, e:
	print "Waiting for X: exception %s"%(str(e))
	pass

# Kill RGS since the GDM will be still active and may try to 
# restart the X server
rgsProc.kill()
# Stop the real X server - this is not needed actually
alloc.stopViz(ra)

# Deallocate resources. We do this quickly to prevent GDM from keeping running!
ra.deallocate(alloc)

# Disconnect from the SSM - we're done!
ra.stop()
