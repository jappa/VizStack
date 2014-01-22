#!/usr/bin/env python
#
# run-specviewperf9-one-gpu.py
#
# This script runs multiple instances of SPECViewPerf on one GPU
# of your system. These instances are run in parallel.
# The intent of this script is to show you the impact of
# running multiple users together.
#
#
# Results are reported at the end; with periodic status
# too

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
import sys
from pprint import pprint
import subprocess
import select
import copy

if len(sys.argv)!=3:
	print >>sys.stderr, "Please pass the directory where SPECViewPerf 9 is located as the first argument"
	print >>sys.stderr, "Please pass the number of instances to run as second argument"
	print >>sys.stderr, ""
	print >>sys.stderr, "e.g. %s /home/shree/SPECViewperf9.0 2"%(sys.argv[0])
	print >>sys.stderr, ""
	print >>sys.stderr, "This directory must exist on all nodes, and each node must have sufficient"
	print >>sys.stderr, "space in /tmp for <n> copies of this directory, where <n> is the number of"
	print >>sys.stderr, "GPUs on that node."
	sys.exit(1)

spvPath = sys.argv[1]
nCopies = int(sys.argv[2])

# Connect to the SSM
ra = vsapi.ResourceAccess() 

# Allocate a GPU and a Server on the same node
alloc = ra.allocate([ [vsapi.Server(), vsapi.GPU()] ])
res = alloc.getResources()
srv = res[0][0]
gpu = res[0][1]
scrList = []
gpuList = []
gpuNames = []
gpuResults = {}
print 'Running %d copies of SPECViewPerf 9 on a single GPU'%(nCopies)
for screenIndex in range(nCopies):
	name = '%s/GPU-%d/Instance %d'%(gpu.getHostName(), gpu.getIndex(),screenIndex)
	gpuResults[name] = []
	gpuNames.append(name)
	print '\t%s'%(name)

	screen = vsapi.Screen(screenIndex)

	# Configure an independent screen for each benchamrk
	# may not work on GeForce cards.
	gpu.clearScanouts()
	screen.setFBProperty('resolution', [1280,1024])

	# X screen controls the allocated GPU
	screen.setGPU(gpu)

	# Configure the screen on our allocated server
	srv.addScreen(screen)

	gpuList.append(gpu)
	scrList.append(screen)

# Configure all X servers
alloc.setupViz(ra)

# Start all X server, all GPUs are reachable now
print 'Starting X server...'
alloc.startViz(ra)

allProcs = []
objectsToMonitor = []

# Run SPECViewPerf on all GPUs - one per server
print 'Starting %d copies of Benchmark on GPU'%(nCopies)
for screenIndex in range(nCopies):
	scr = scrList[screenIndex]
	proc = scr.run(['/opt/vizstack/share/samples/benchmarking/helper-specviewperf9-each-gpu.sh', spvPath, str(screenIndex)], outFile=subprocess.PIPE)
	objectsToMonitor.append(proc.getSubprocessObject().stdout)
	allProcs.append(proc)

# Dump information about the progress on each GPU
# This way, user is sure that something is happening!
# Record results as they come in
gpuNamesCopy = copy.deepcopy(gpuNames)
while len(objectsToMonitor)>0:
	fileToRead, unused1, unused2 = select.select(objectsToMonitor, [], [])
	for f in fileToRead:
		s = f.readline()
		idx = objectsToMonitor.index(f)
		if len(s)==0:
			objectsToMonitor.pop(idx)
			gpuNamesCopy.pop(idx)
		else:
			gpuResults[gpuNamesCopy[idx]].append(s)
			print '%s: %s'%(gpuNamesCopy[idx],s),

# Wait for all processes to finish
for proc in allProcs:
	proc.wait()

# Show a summary of the results
print
print
print '============================'
print 'SPECViewPerf9 Results'
print '============================'
for idx in range(len(gpuList)):
	gpu = gpuList[idx]
	print
	print 'GPU  : ',gpuNames[idx]
	print 'Type : ',gpu.getType()
	print 'BusID: ',gpu.getBusId()
	print
	for line in gpuResults[gpuNames[idx]][-9:]:
		print line,
	print

# Stop the X servers
print 'Stopping all X servers...'
alloc.stopViz(ra)

# Give up the resources we are using
ra.deallocate(alloc)

# Disconnect from the SSM
ra.stop()
