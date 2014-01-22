#!/usr/bin/env python
#
# run-cudabandwidth-app-gpus.py
#
# Sample that shows how to run a CUDA program on GPUs.
# In this case, we run the CUDA bandwidth test on all GPUs.
#
# Shows how to run an app on a bare GPU (no X server needed)
#

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
import subprocess
import copy
import select
import sys

if len(sys.argv)!=2:
	print >>sys.stderr, "Please pass the directory where the NVIDIA GPU Computing SDK is installed as an argument"
	print >>sys.stderr, "e.g. %s /home/shree/NVIDIA_GPU_Computing_SDK"%(sys.argv[0])
	print >>sys.stderr, "This directory must exist on all nodes"
	sys.exit(1)

sdkpath = sys.argv[1]

# Connect to the SSM
ra = vsapi.ResourceAccess() 

# Get information about all available GPUs
allGPUs = ra.queryResources(vsapi.GPU())

# Allocate all of them !
alloc = ra.allocate(allGPUs)
allocGPU = alloc.getResources()

gpuNames = []
gpuResults = {}
allProcs = []
objectsToMonitor = []
# Start the bandwidth test. These finish pretty fast!
print 'Running CUDA Bandwidth Test on these GPUs'
for gpu in allocGPU:
	name = '%s/GPU-%d'%(gpu.getHostName(), gpu.getIndex())
	gpuResults[name] = []
	gpuNames.append(name)
	print '\t%s (%s)'%(name, gpu.getType())
	proc = gpu.run(['/opt/vizstack/share/samples/benchmarking/helper-bandwidthTest.sh', sdkpath, '--memory=pinned'], outFile=subprocess.PIPE)
	objectsToMonitor.append(proc.getSubprocessObject().stdout)
	allProcs.append(proc)

# Leech program outputs
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
			#print '%s: %s'%(gpuNamesCopy[idx],s),

# Wait for all processes to finish
for proc in allProcs:
	proc.wait()


# Show results with formatting
print
print '============================'
print 'CUDA Bandwidth Test Results'
print '============================'
for idx in range(len(allocGPU)):
	gpu = allocGPU[idx]
	print
	print ' GPU     :',gpuNames[idx]
	for line in gpuResults[gpuNames[idx]][5:-8]: # The range removes the extra prints
		print line,
	print

# Give up the resources we are using
ra.deallocate(alloc)

# Disconnect from the SSM
ra.stop()
