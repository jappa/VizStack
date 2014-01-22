
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

class Launcher:
    def __init__(self, sched):
        self.sched = sched
        self.jobNumId = {}
        self.jobNum = -1
    
    """
    Runs a particular command using the scheduler supported by the unerlying implementation.
    cmd - The command that needs to be supplied, this is a string.
    node - What node to run it on, if there are multiple nodes.
    stdout - This can be a filename to which the output is dumped. Default is None and the output is dumped to stdout.
    stderr - This can be a filename to which the errors are dumped. Default is None and the errors are dumped to stderr.
    stdin - This can be a filename from which the input is read. Default is None and the input is accepted from stdin.
    On a successful run this returns a number, this can be used with the other functiosn in the class to get more information about the job. This need not be the job number given by the underlying implementation.
    """
    def run(self, cmd, node, stdout=None, stderr=None, stdin=None):
        return None

    """
    Using this one can access the job ID given by the underlying implementation.
    If there is a valid id associated it returns the ID or None if there is no such job.
    """
    def getId(self, jobNum):
        return None

    """
    Takes the job number returned by run as input and waits until the job either completes or fails.
    t - Amount of time to wait, default for now is 900 secs. This might change in the future.
    Returns nothing.
    """
    def wait(self, jobNum, t=None):
        return None

    """
    Kills the job. Takes the job number returned by run as input.
    """
    def kill(self, jobNum):
        return None

    """
    Kills all the jobs.
    """
    def killall(self):
        return None

