
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

# Initialization file for vizstack

# Make sure scripts can find the python library
if ( $?PYTHONPATH ) then   # test for the existence of PYTHONPATH
    setenv PYTHONPATH "${PYTHONPATH}:/opt/vizstack/python"
else
    setenv PYTHONPATH /opt/vizstack/python
endif

# Make sure scripts are usable from the command line
if ( $?PATH ) then
    setenv PATH "${PATH}:/opt/vizstack/bin"
else
    setenv PATH /opt/vizstack/bin
endif

# Ensure manpages are usable
if ( $?MANPATH ) then
    setenv MANPATH "${MANPATH}:/opt/vizstack/man"
else
    setenv MANPATH /opt/vizstack/man
endif

