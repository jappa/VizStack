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

import subprocess
import os
import time
import sys
import pickle
import stat


class Scheduler:
    # Returns the scheduler object
    def __init__(self):
        self.res = []
        self.sched_res = {}
        self.schedId = None
        self.launcher = None

    # Calls the kill on all objects of class Launcher and calls deallocate
    def __del__(self):
        self.schedId = None
        self.launcher = None

    # Returns the id corresponding to the allocation from the underlying implementation
    # None if there is no allocation
    """
    Get the allocation id from the underlying implementation.
    Returns None if the allocation does not exist.
    """
    def getId(self):
        return self.schedId

    # Return the list of nodes. None of the initialization has not happened yet
    """
    Returns the list of nodes with a particular state. The state is specific to
    the underlying implementation. Returns None if no nodes match the specification.
    """
    def getNodes(self, state=None):
        return nodes

    # Allocate the resource for the job. This returns in the corresponding launcher object
    """
    Allocates a list of nodes. Returns None if none of them could be allocated.
    Throws a SLURMError object.
    """
    def allocate(self, node_list):
        return self.launcher

    """
    Deallocates the job session. If there are any active jobs running calls a kill on them too.
    Returns nothing.
    """
    # Calls the Launcher killall method and then deallocates the session
    def deallocate(self):
        return success
    """
    Returns True if a particular node is up. or else returns False.
    """
    # Node state can be UP or DOWN
    def isNodeUp(self, node):
        return state
