#!/usr/bin/env python

import vsapi
from pprint import pprint
import os

ra = vsapi.ResourceAccess()

sli = vsapi.SLI(0, gpu0=0, gpu1=1)
input = [[vsapi.Server()]+[sli]+sli.getGPUs()]
pprint(input)
alloc = ra.allocate(input)
res = alloc.getResources()
srv = res[0][0]
sli = res[0][1]
gpu0 = res[0][2]
gpu1 = res[0][3]

pprint(res)

scr = vsapi.Screen(0)
gpu0.setScanout(port_index= 0, display_device="HP LP2065", outputX=0, outputY=0)
gpu1.setScanout(port_index= 0, display_device="HP LP2065", outputX=1600, outputY=0)
scr.setGPUs([gpu0, gpu1])
sli.setMode("mosaic")
scr.setGPUCombiner(sli)
srv.addScreen(scr)

alloc.setupViz(ra)

alloc.startViz(ra)
print "Ready. Starting shell"
os.system("bash")
print "Shell done. Cleaning up..."
alloc.stopViz(ra)
ra.stop()

