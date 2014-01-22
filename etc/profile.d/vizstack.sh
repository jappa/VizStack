
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

# Initialization for vizstack

# Make sure scripts can find the python library
if [[ -z $PYTHONPATH ]] # test for existence of PYTHONPATH 
then
    export PYTHONPATH=/opt/vizstack/python
else
    export PYTHONPATH="${PYTHONPATH}:/opt/vizstack/python"
fi

# Make sure scripts are usable from the command line
if [[ -z $PATH ]]
then
    export PATH=/opt/vizstack/bin
else
    export PATH="${PATH}:/opt/vizstack/bin"
fi

# Ensure manpages are usable
if [[ -z $MANPATH ]]
then
    export MANPATH=/opt/vizstack/man
else
    export MANPATH="${MANPATH}:/opt/vizstack/man"
fi
