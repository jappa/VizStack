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

# Makefile to build the OpenSG samples in this directory.
# Expects OpenSG to be installed, and GLUT (freeglut-devel) too
#
# Builds binaries into the ../bin directory. Ready for packaging.
#
ALL: ../bin/ClusterServer ../bin/ClusterClient ../bin/ClusterServerX ../bin/MyClient ../bin/SortLastClusterClient

clean:
	rm ../bin/ClusterServer ../bin/ClusterClient ../bin/ClusterServerX ../bin/MyClient ../bin/SortLastClusterClient

../bin/ClusterServer: 12ClusterServer.cpp
	g++ -o ../bin/ClusterServer 12ClusterServer.cpp `osg-config --libs Base System GLUT`

../bin/ClusterClient: 13ClusterClient.cpp
	g++ -o ../bin/ClusterClient 13ClusterClient.cpp `osg-config --libs Base System GLUT`

../bin/ClusterServerX: 12ClusterServerX.cpp
	g++ -o ../bin/ClusterServerX 12ClusterServerX.cpp `osg-config --libs Base System X`

../bin/MyClient: MyClient.cpp
	g++ -o ../bin/MyClient MyClient.cpp `osg-config --libs Base System`

../bin/SortLastClusterClient: 28SortLastClusterClient.cpp
	g++ -o ../bin/SortLastClusterClient 28SortLastClusterClient.cpp `osg-config --libs Base System GLUT`
