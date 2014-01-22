
This file contains instructions to build VizStack.

First things:
-------------
VizStack contains the following type of code
  - C/C++
  - Python

VizStack's C/C++ code is compiled using the SCons (http://www.scons.org)
build tool. So, you need to install that first.

VizStack's C/C++ code depends on the following libraries:
  - XML2
  - Linux PAM
  - X11 headers
  - OpenGL header files

So, you need to install these to ensure successful compilation.

VizStack's documentation is written using AsciiDoc.
The documentation is in the 'doc/manual' and 'doc/manpages'
directory.
  
To generate the documentation, you need to install the asciidoc
package, docbook and FOP. The developers have had most success w.r.t
building documentation on Ubuntu.

The VizStack build process can create RPM and DEB packages.
It uses rpm, fakeroot and alien packages to create the DEB package,
so you need to install them on Ubuntu/Debian.

Howto Build:
------------

The build-vizstack scripts in the root directory does the 
following steps:
 - Build the documentation
    - User Guide
    - Administrator Guide
    - Developer Guide
    - manpages
 - Build the source code
 - Build a native package. RPM and DEB packages are generated.

To build, just type

$ bash build-vizstack.sh

This will give you packages named after the svn version, i.e.
a developer build.  Note that this the version numbers on the
documentation will not carry the SVN revision number.

To create a release, set the RELEASE environment variable to
something non-empty

$ export RELEASE=1
$ bash build-vizstack.sh

On certain Linux distros, you need to be root to build this
package
  - RHEL
  - FC 11 and below
  - Ubuntu 8.1 and below

On the following distros, you don't need to be root
  - Ubuntu 9.10
  - FC 12

You will find the resulting RPM or DEB package generated in the
current directory.

Notes for specific distros are given below:
-------------------------------------------
 
SLES 11 :
---------

Install the scons RPM from http://www.scons.org/

You'll need to install some packages from the SDK DVD.

1. pam-devel
2. xorg-x11-devel and its dependent packages 
   I used the command 

   rpm -i `ls xorg-x11-*-devel-7* | grep -v unstable` libuuid-devel-2.16-6.5.3.x86_64.rpm 

   after mounting the SDK DVD. If you have a better method, do let me know!

3. libmxl2-devel and dependent packages. I had to run

   rpm -i libxml2-devel-2.7.6-0.1.11.x86_64.rpm zlib-devel-1.2.3-106.34.x86_64.rpm readline-devel-5.2-147.6.25.x86_64.rpm 

   from the SDK DVD

Ubuntu 9.10 :
-------------

The default CD install can make it difficult to compile the sources. 
Post install, you may not even have the compiler.

You need to install the right packages. I needed to do the following
on Ubuntu 9.10:

 0. sudo apt-get install scons
 1. sudo apt-get install libpam-dev
 2. sudo apt-get install g++
 3. sudo apt-get install libxml2-dev
 4. sudo apt-get install xorg-dev
 5. sudo apt-get install x11proto-gl-dev
 6. sudo apt-get install --reinstall mesa-common-dev
 7. sudo apt-get install nvidia-glx-185-dev
    (libgl1-mesa-dev might work too?)
 8. sudo apt-get install asciidoc   # I have 8.4.4-1 and docs build fine with this
 9. sudo apt-get install fop
10. sudo apt-get install docbook

Compiling dependencies from source:
-----------------------------------

Some platforms don't provide packages for dependencies used by VizStack. e.g., SLURM and Munge 
packages are not available for SLES.  These may be needed for multi-node deployment. 
So, you will need to build these manually.

1. MUNGE on SLES: For 'configure' to succeed, you need to install
     - libopenssl-devel
     - zlib-devel (dependency of libopenssl-devel)
   These packages are available on the SLES SDK DVD.

   After extracting the munge source code, use the following steps :
    # ./configure --prefix=/
    # make
    # make install

2. SLURM on SLES: Run configure with prefix set to /usr.
