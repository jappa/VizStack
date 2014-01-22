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
Object returned by the run call to launcher. This is self contained
and can be used to wait on the underlying process or kill it.
"""
class Process:
    def __init__(self):
        pass

    """
    If this object gets deleted then the underlying job gets killed
    """
    def __del__(self):
	pass
      
    """
    Wait for certain time t on the process. If t is None, wait forever or until the process quits.
    If t is some value in secs, return after the given amount of time or earlier if the process exits.
    """
    def wait(self, t=None):
        raise "Attempt to call method of unimplemented abstract class!"

    """
    Kill the process
    """
    def kill(self):
        raise "Attempt to call method of unimplemented abstract class!"
