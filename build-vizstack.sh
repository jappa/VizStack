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

#
# Developer/Release build control:
#
# If you want a release build, set the RELEASE environment variable to
# something non-empty. Then execute this script.
# The packages will be named
#   vizstack-major.minor-release e.g. vizstack-1.1-3
#   vizrt-major.minor-release e.g. vizrt-1.1-3
#
# If you want a regular developer build, then just execute this script.
# The packages will be named 
#   vizstack-major.minor-svnVER e.g. vizstack-1.1-svn123
#   vizrt-major.minor-svnVER e.g. vizrt-1.1-svn123
#
# This change was contributed by: Simon Fowler
# 

VIZSTACK_SPEC=vizstack.spec
VIZRT_SPEC=vizrt.spec

SVN_REVISION=""
if test -z $RELEASE; 
then
    if test -d .svn;
    then
        # Get the SVN version number, suffix it with svn
        SVN_REVISION=svn`svn info |grep 'Revision:' |cut -d ' ' -f 2`

        # Create temporary spec files with the replaced version number 
        VIZSTACK_SPEC=vizstack.spec.in
        VIZRT_SPEC=vizrt.spec.in
        sed -e "s/Release: \(.*$\)/Release: $SVN_REVISION/" vizstack.spec >$VIZSTACK_SPEC
        sed -e "s/Release: \(.*$\)/Release: $SVN_REVISION/" vizrt.spec >$VIZRT_SPEC
    fi
fi

VV=`grep ^Version: $VIZSTACK_SPEC | sed -e "s/Version: //"`
VR=`grep ^Release: $VIZSTACK_SPEC | sed -e "s/Release: //"`
VIZSTACK_VERSION=$VV
VIZSTACK_VERSION_COMPLETE=$VV-$VR

VV=`grep ^Version: $VIZRT_SPEC | sed -e "s/Version: //"`
VR=`grep ^Release: $VIZRT_SPEC | sed -e "s/Release: //"`
VIZRT_VERSION=$VV
VIZRT_VERSION_COMPLETE=$VV-$VR

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
rm -Rf /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}
mkdir -p /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/opt/vizstack
mkdir -p /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/opt/vizstack/share
mkdir -p /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/opt/vizstack/share/doc
#mkdir -p /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/opt/vizstack/src
mkdir -p /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/usr/X11R6/bin
mkdir -p /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/etc/vizstack
mkdir -p /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/etc/vizstack/templates
mkdir -p /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/etc/vizstack/templates/displays
mkdir -p /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/etc/vizstack/templates/gpus
mkdir -p /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/etc/vizstack/templates/keyboard
mkdir -p /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/etc/vizstack/templates/mouse
mkdir -p /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/etc/profile.d
mkdir -p /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/lib64/security
mkdir -p /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/opt/vizstack/man/man1

# Copy scripts, python files, template, src files to the directory structure
#   Scripts
cp -r bin /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/opt/vizstack

#   Admin scripts, SSM
cp -r sbin /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/opt/vizstack

#   Python Modules
cp -r python /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/opt/vizstack

# Sources
#cp -r src/{*.c,*.cpp,*.hpp,*.py,SConstruct,*.txt} /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/opt/vizstack/src

# README
cp -r doc/README /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/opt/vizstack/share/doc
cp -r doc/README /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/opt/vizstack/
cp -r COPYING /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/opt/vizstack/

#   Template files, XML schema and Samples
cp -r share/samples /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/opt/vizstack/share
cp -r share/schema /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/opt/vizstack/share
cp -r share/templates /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/opt/vizstack/share

# gdm.conf template
mv /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/opt/vizstack/share/templates/gdm.conf.template /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/etc/vizstack/templates

#   Environment setup fileds
cp -r etc/profile.d /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/etc

# Logging control
cp -r etc/ssm-logging.conf /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/etc/vizstack

# Build the source code
cd src
scons
if [ "$?" -ne "0" ]
then
	echo "========================================="
	echo "FATAL: Code build failed - cannot proceed"
	echo "========================================="
	exit -1
fi
cd -

# Build the manpages
# We don't check failure yet
cd doc/manpages
make 
cd -

# Build the manual & html docs
cd doc/manual
make
make html
cd -
cp doc/manual/admin_guide.pdf /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/opt/vizstack/share/doc/admin_guide.pdf
cp doc/manual/user_guide.pdf /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/opt/vizstack/share/doc/user_guide.pdf
cp doc/manual/dev_guide.pdf /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/opt/vizstack/share/doc/dev_guide.pdf

cp doc/manual/user_guide.pdf /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/opt/vizstack/share/doc/user_guide.pdf
# Admin guide html lacks images, since they are in SVG format, so not including this for now.
#cp doc/manual/admin_guide.html /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/opt/vizstack/share/doc/admin_guide.html
cp doc/manual/user_guide.html /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/opt/vizstack/share/doc/user_guide.html
cp doc/manual/dev_guide.html /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/opt/vizstack/share/doc/dev_guide.html

cp -r doc/manual/images /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/opt/vizstack/share/doc/

# Copy the built binaries
cp src/vs-X /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/usr/X11R6/bin
cp src/vs-generate-xconfig /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/opt/vizstack/bin
cp src/vs-Xkill /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/opt/vizstack/bin
cp src/vs-GDMlauncher /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/opt/vizstack/bin
cp src/vs-aew /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/opt/vizstack/bin
cp src/vs-Xv /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/opt/vizstack/bin
cp src/vs-get-limits /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/opt/vizstack/bin
cp src/pam_vizstack_rgs_setuser.so /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/lib64/security
cp src/vs-wait-x /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/opt/vizstack/bin

# Generate the man pages if asciidoc has been installed
cp doc/manpages/*.1 /tmp/vizstack-tmp/vizstack-${VIZSTACK_VERSION}/opt/vizstack/man/man1

# Vizconn stuff
rm -Rf /tmp/vizrt-tmp/vizrt-${VIZRT_VERSION}
mkdir -p /tmp/vizrt-tmp/vizrt-${VIZRT_VERSION}/opt/vizrt/bin

# Copy vizconn stuff to the staging dir
cp vizconn/remotevizconnector /tmp/vizrt-tmp/vizrt-${VIZRT_VERSION}/opt/vizrt/bin
cp vizconn/sshconnector.py /tmp/vizrt-tmp/vizrt-${VIZRT_VERSION}/opt/vizrt/bin

# Remove subversion information from the packaging tree
find /tmp/vizstack-tmp -type d -name ".svn" | xargs rm -rf
find /tmp/vizstack-tmp -type f -name "*~" | xargs rm -f
find /tmp/vizstack-tmp -type f -name ".scons*" | xargs rm -f

# Remove subversion information from the packaging tree
find /tmp/vizrt-tmp -type d -name ".svn" | xargs rm -rf
find /tmp/vizrt-tmp -type f -name "*~" | xargs rm -f

# Last steps to build the RPM
cp $VIZSTACK_SPEC ${RPM_PATH}/SPECS/vizstack.spec
pushd /tmp/vizstack-tmp
tar -zcvf vizstack-${VIZSTACK_VERSION}.tar.gz vizstack-${VIZSTACK_VERSION}
cp vizstack-${VIZSTACK_VERSION}.tar.gz ${RPM_PATH}/SOURCES
rpmbuild -ba ${RPM_PATH}/SPECS/vizstack.spec
if [ "$?" -ne "0" ]
then
	echo "================================"
	echo "FATAL: VizStack RPM Build failed"
	echo "================================"
	exit -1
fi
popd

# Build the vizrt rpm also
cp $VIZRT_SPEC ${RPM_PATH}/SPECS/vizrt.spec
pushd /tmp/vizrt-tmp
tar -zcvf vizrt-${VIZRT_VERSION}.tar.gz vizrt-${VIZRT_VERSION}
cp vizrt-${VIZRT_VERSION}.tar.gz ${RPM_PATH}/SOURCES
rpmbuild -ba ${RPM_PATH}/SPECS/vizrt.spec
if [ "$?" -ne "0" ]
then
	echo "============================="
	echo "FATAL: vizrt RPM Build failed"
	echo "============================="
	exit -1
fi
popd

VSRPM=vizstack-${VIZSTACK_VERSION_COMPLETE}.`uname -m`.rpm
VSRTRPM=vizrt-${VIZRT_VERSION_COMPLETE}.noarch.rpm
if test "$DISTRO" == "debian"; then
	echo "Converting RPM to DEB. DEB packages will be in the current directory"
	fakeroot alien -k $RPM_PATH/RPMS/`uname -m`/$VSRPM
	fakeroot alien -k $RPM_PATH/RPMS/noarch/$VSRTRPM
else
	echo "Copying generated RPMS to the current directory"
	cp $RPM_PATH/RPMS/`uname -m`/$VSRPM .
	cp $RPM_PATH/RPMS/noarch/$VSRTRPM .
fi

# Cleanup any temporary SPEC files
if test -z $RELEASE; 
then
	echo "Cleaning up..."
	rm $VIZSTACK_SPEC
	rm $VIZRT_SPEC
fi
