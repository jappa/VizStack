#!/bin/bash

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


VV=`grep ^Version: vizstack-opensg-demos.spec | sed -e "s/Version: //"`
VR=`grep ^Release: vizstack-opensg-demos.spec | sed -e "s/Release: //"`
DEMO_VERSION=$VV
DEMO_VERSION_COMPLETE=$VV-$VR

if test -f /etc/SuSE-release ;
then
    DISTRO=suse
    RPM_PATH=/usr/src/packages
fi
if test -f /etc/redhat-release;
then
    if grep Fedora /etc/redhat-release
    then
        echo "Fedora"
        DISTRO=fedora
        RPM_PATH=~/rpmbuild
    else
        echo "RedHat EL"
        DISTRO=redhat
        RPM_PATH=/usr/src/redhat
    fi
fi
if test -f /etc/debian_version;
then
    DISTRO=debian
    #RPM_PATH=/usr/src/rpm
    RPM_PATH=~/rpmbuild
fi

# Build the target directory structure we need
# Trying to confirm to FHS 2.3
rm -Rf /tmp/vizstack-opensg-demos-tmp/vizstack-opensg-demos-${DEMO_VERSION}
mkdir -p /tmp/vizstack-opensg-demos-tmp/vizstack-opensg-demos-${DEMO_VERSION}/opt/vizstack/share/demos

# Copy OpenSG demos
cp -r OpenSG /tmp/vizstack-opensg-demos-tmp/vizstack-opensg-demos-${DEMO_VERSION}/opt/vizstack/share/demos

# Build the source code, resulting in a populated bin directory
make -C /tmp/vizstack-opensg-demos-tmp/vizstack-opensg-demos-${DEMO_VERSION}/opt/vizstack/share/demos/OpenSG/src
if [ "$?" -ne "0" ]
then
	echo "============================="
	echo "FATAL: Code build failed"
	echo "============================="
	exit 1
fi

# Remove subversion information from the packaging tree
find /tmp/vizstack-opensg-demos-tmp -type d -name ".svn" | xargs rm -rf

# Last steps to build the RPM
cp vizstack-opensg-demos.spec ${RPM_PATH}/SPECS
pushd /tmp/vizstack-opensg-demos-tmp
tar -zcvf vizstack-opensg-demos-${DEMO_VERSION}.tar.gz vizstack-opensg-demos-${DEMO_VERSION}
cp vizstack-opensg-demos-${DEMO_VERSION}.tar.gz ${RPM_PATH}/SOURCES
rpmbuild -ba ${RPM_PATH}/SPECS/vizstack-opensg-demos.spec
popd

THISRPM=vizstack-opensg-demos-${DEMO_VERSION_COMPLETE}.`uname -m`.rpm
if test "$DISTRO" == "debian"; then
	echo "Converting RPM to DEB. DEB packages will be in the current directory"
	fakeroot alien $RPM_PATH/RPMS/`uname -m`/$THISRPM
else
	echo "Copying generated RPMS to the current directory"
	cp $RPM_PATH/RPMS/`uname -m`/$THISRPM .
fi
