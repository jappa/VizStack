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


import process
import launcher
import slurmscheduler
import slurmlauncher
import subprocess
import time
import os

class SLURMProcess(process.Process):
    	def __init__(self, proc):
		self.proc = proc
		self.retCode = None
		self.savedStdOut = None
		self.savedStdErr = None

	def __del__(self):
		if self.proc is not None:
			self.kill()

	def wait(self):
		self.savedStdOut, self.savedStdErr = self.proc.communicate() # To avoid the wait below from blocking
		self.proc.wait()
		self.retCode = self.proc.returncode
		self.proc = None

	def getStdOut(self):
		return self.savedStdOut

	def getStdErr(self):
		return self.savedStdErr

	def getExitCode(self):
		return self.retCode

	def kill(self, signal=15): # Default to SIGTERM(15), and not SIGKILL(9)
		if self.proc is None:
			return
		try:
			os.kill(self.proc.pid, signal)
		except OSError, e:
			pass
		self.wait()
