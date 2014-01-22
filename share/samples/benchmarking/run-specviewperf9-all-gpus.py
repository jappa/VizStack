#!/usr/bin/env python
#
# run-specviewperf9-all-gpus.py
#
# This script runs SPECViewPerf on all GPUs on your
# systems in parallel !
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

if len(sys.argv)!=2:
	print >>sys.stderr, "Please pass the directory where SPECViewPerf 9 is located as an argument"
	print >>sys.stderr, "e.g. %s /home/shree/SPECViewperf9.0"%(sys.argv[0])
	print >>sys.stderr, "This directory must exist on all nodes, and each node must have sufficient"
	print >>sys.stderr, "space in /tmp for <n> copies of this directory, where <n> is the number of"
	print >>sys.stderr, "GPUs on that node."
	sys.exit(1)

spvPath = sys.argv[1]

# Connect to the SSM
ra = vsapi.ResourceAccess() 

# Get information about all available GPUs
allGPUs = ra.queryResources(vsapi.GPU())

allocList = []
for gpu in allGPUs:
	allocList.append([vsapi.Server(), gpu])

# Allocate a GPU and a Server on the same node
alloc = ra.allocate(allocList)
res = alloc.getResources()
srvList = []
gpuList = []
gpuNames = []
gpuResults = {}
print 'Running SPECViewPerf 9 in parallel on %d GPUs'%(len(allGPUs))
for srv,gpu in res:
	name = '%s/GPU-%d'%(gpu.getHostName(), gpu.getIndex())
	gpuResults[name] = []
	gpuNames.append(name)
	print '\t%s'%(name)
	srvList.append(srv)
	gpuList.append(gpu)

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

# Configure all X servers
alloc.setupViz(ra)

# Start all X server, all GPUs are reachable now
print 'Starting all X servers...'
alloc.startViz(ra)

allProcs = []
objectsToMonitor = []

# Run SPECViewPerf on all GPUs - one per server
print 'Starting Benchmark on ALL GPUs'
for srv,gpu in res:
	proc = srv.run(['/opt/vizstack/share/samples/benchmarking/helper-specviewperf9-each-gpu.sh', spvPath, '%d'%(gpu.getIndex())], outFile=subprocess.PIPE)
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
