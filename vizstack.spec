Summary: Software to convert one/more machines with GPUs into a sharable, multi-user, multi-session visualization resource.
Name: vizstack
Version: 1.1
Release: 4
License: GPLV2
Group: Development/Tools
URL: http://vizstack.sourceforge.net
Source0: %{name}-%{version}.tar.gz
BuildRoot: %{_tmppath}/%{name}-%{version}-%{release}-root

%description
VizStack is a software stack that turns a one or more machines with GPUs installed in them into a shared, multi-user visualization resource.  VizStack provides utilities to allocate resources (GPUs), run applications on them, and free them when they are no longer needed.  VizStack provides ways to configure and drive display devices, as well as higher level constructs like Tiled Displays. 

VizStack manages only the visualization resources (GPUs, X servers), and does not provide any utilities to do system management/setup on the nodes. VizStack can dynamically setup the visualization resources to meet any application requirement.

For ease of use, VizStack provides integrations with HP Remote Graphics Software and TurboVNC/VirtualGL, as well as popular visualization applications.

%prep
%setup -q

%build


%install
rm -rf $RPM_BUILD_ROOT
mkdir -p $RPM_BUILD_ROOT
cp -r opt usr etc lib64 $RPM_BUILD_ROOT
# Ensure the suid bit is set on the needed binaries
# For some reason I'm unable to achieve this during
# packaging
chmod +s $RPM_BUILD_ROOT/usr/X11R6/bin/vs-X
chmod +s $RPM_BUILD_ROOT/opt/vizstack/bin/vs-Xkill
chmod +s $RPM_BUILD_ROOT/opt/vizstack/bin/vs-GDMlauncher

%clean
rm -rf $RPM_BUILD_ROOT


%files
%defattr(-,root,root,-)
/opt/vizstack/python/*
/opt/vizstack/README
/opt/vizstack/COPYING
/opt/vizstack/bin/*
/opt/vizstack/sbin/*
/opt/vizstack/share/*
#/opt/vizstack/src/*
/usr/X11R6/bin/vs-X
/etc/vizstack
/etc/profile.d/vizstack.csh
/etc/profile.d/vizstack.sh
/lib64/security/pam_vizstack_rgs_setuser.so
%doc
/opt/vizstack/man/man1/

%changelog
* Wed Oct 11 2010 Shree Kumar <shreekumar@hp.com>
- New version 1.1-4
   - Enhancements
     - Added ways to control allocation of GPUs by vgl, tvnc and
       paraview scripts (SF feature request 3052964)
     - Better internal & external error logging in some cases
   - Addressed issues
     - Fixed an allocation bug where multiple node allocations would cause an
       SSM crash
     - Configuration failure with nvidia 256 series drivers (SF Bug 3058046)
     - Fixed terminal issues when viz-vgl is invoked with --shell
     - Paraview does not run with SLURM+OpenMPI(SF Bug 3046830)
     - viz-vgl --shell now picks up the user's preferred shell (SF Bug 3080926)
     - TurboVNC lock files hang around (SF Bug 3066775)
     - Error using Viz Connector (SF Bug 3060186)
     - In the profile scripts, we check for existence of environment variables
       before setting them (contributed by Klaus Reuter)
   - Packaging
     - C++ source files are not inlcuded in the RPM
     
* Wed Jul 14 2010 Shree Kumar <shreekumar@hp.com>
- Updated version number to 1.1-3
   - Few bug fixes
     - Fixed to work with SLURM 2.10 & above (Ubuntu 10.04, web download)
     - vs-manage-tiled-displays
     - Single GPU discovert issue on SLES
     - Fixed bad merge : included clip_last_block
     - Resource allocation sorting bug
     - Multiple shared servers in the same allocation
       weren't starting up right. Fixed this via a delay.
     - Updating state of multiple shared servers needed
       a uniq operation. Added that.
     - Fixed node name expansion when node names have leading zeroes.
   - Paraview script now supports shared GPUs for rendering.
     This is also the default. For dedicated GPUs, use -x.
   - Minor vsapi changes
     - include a hyphen(-) in the options for servers
       this allows usage of both - and +
   - Minor doc fixes
   - SSM can now take paths to various files. These are
     added for developer usage only.

* Mon May 17 2010 Shree Kumar <shreekumar@hp.com>
- Updated version number to 1.1-2
   - Many bug fixes
     - Fixed allocation of whole nodes, option added
       to viz-rgs, viz-tvnc and remote access tools.
   - Documentation split into admin guide, user guide
     and dev guide
   - Examples added for equalizer, SPECViewPerf and CUDA.
     These are mentioned in the dev guide.
   - Support for Bezels.

* Fri Mar 26 2010 Shree Kumar <shreekumar@hp.com>
- Updated version number to 1.1-1
   - Many bug fixes
   - Many improvements
     - Better algorithm for detecting GPUs and 
       GPU scanouts
     - GPUs now have an additional "stereo" capability.
       This allows allocation of GPUs which support 
       stereo.
     - Node specific weights to tweak order of allocation
       between nodes
     - vs-configure-system generates templates for unknown
       GPUs and displays.
     - vs-generate-xconfig can generate config file given
       X server spec. It also handles the 'EDID bytes' tag 
       properly

* Tue Feb 23 2010 Shree Kumar <shreekumar@hp.com>
- Updated version string to 1.1 for GPU sharing
   - Implemented GPU sharing. Changes touch most
     part of VizStack
   - Add option -S, -i, -x to configuration commands.
     These configure GPU sharing.
   - viz-tvnc and viz-vgl scripts allocate shared
     GPUs by default. A new option, -x is available
     to allocate exclusive GPUs.
   - File format of /etc/vizstack/node_config.xml has
     been changed. If you have an earlier version of
     VizStack installed, please run the configure
     script again; else the SSM won't start.
   - SSM uses the python logging package. Logging is 
     controlled by the file /etc/vizstack/ssm-logging.conf

* Tue Feb 23 2010 Shree Kumar <shreekumar@hp.com>
- Updated version string to 1.0-2 for new release
   - Modified "-m" option in configuration commands
     to "-r", allowing specification of a network
   - Fixed failure of configure scripts with nvidia
     r190 drivers
   - Fixed SLURM issue when uid!=gid
   - Fixed documentation, added troubleshooting section
   - Added ChangeLog section to documentation
   - Added "-v" for vs-test-gpus. Lets user check for
     errors.
   - Fixed "nvidia-settings" command not found when
     trying to enable framelock from a system without
     a graphics card. (SLURM specific)
   - viz-vgl : Starts a local client if allocated
     GPU is on the same node where the script runs.
     VGL_CLIENT and VGL_PORT can be used to point the
     script to a running vglclient.

* Thu Nov 05 2009 Sunil Shinde <sunil.shinde@hp.com>
- Bumped up the version string to 1.0-1

* Mon Oct 13 2009 Shree Kumar <shreekumar@hp.com>
- Included vizstack source in vizstack package

* Wed Sep 30 2009 Shree Kumar <shreekumar@hp.com>
- Bumped version to 0.9-1
   - added vs-test-gpus
   - improved the manual to include references to
     several tools
   - fixed an X server shutdown/startup bug

* Wed Sep 24 2009 Shree Kumar <shreekumar@hp.com>
- Bumped version to 0.9-0, to aim for a 1.0 release
   - SSM is now a daemon
   - scripts now renamed to "viz-" rather than viz_
   - New tools for managing tiled display, enumerating jobs and killing jobs
   - Dynamic reload of tiled displays
   - --server option for Paraview script
   - Manpages for many tools.
   - Reformatted & enlarged documentation in AsciiDoc.
   - Automatic framelock in scripts

* Fri Aug 28 2009 Shree Kumar <shreekumar@hp.com>
- Bumped version to 0.4-0
   - viz_ls added by Manju
   - SLI, SLI mosaic. But no support in tiled displays yet.
   - Framelock. Not integrated in scripts yet.
   - VizStack Remote Access GUI. Windows packaging implemented.

* Wed Jul 21 2009 Shree Kumar <shreekumar@hp.com>
- Bumped version to 0.3-3
  New funtionality
   - viz_rgs_multi, copied from viz_rgs. The difference is that this does not use :0
   - PAM module needed for viz_rgs_multi, needs to be enabled explicitly.
   - Not intended for release yet. A few more changes are needed before that happens.

* Wed Jul 15 2009 Shree Kumar <shreekumar@hp.com>
- Bumped version to 0.3-2
  New funtionality
   - viz_desktop
   - viz_rgs works with Tiled Displays
   - viz_vgl - use VirtualGL directly without TurboVNC
   - many fixes (including one which prevented multiple mice from being used)
   - viz_paraview works both with in sort-first & sort-last

* Tue Jul 07 2009 Shree Kumar <shreekumar@hp.com>
- Bumped version to 0.3-1
  Fixed many bugs compared to earlier release.
   - Panning domain
   - Xinerama
  Implemented
   - group_blocks
   - enhancements to viz_rgs and viz_tvnc to make
     them more usable
   - support for S series devices, not comprehensive
* Wed Jun 30 2009 Shree Kumar <shreekumar@hp.com>
- Upped version to 0.3-0.
  Many changes since earlier release
   - Integrated TurboVNC closer
   - Added support for display rotation
   - Added support for port remapping in tiled
     display. This will be useful for workstations,
     as well as for switching left & right in stereo!
   - More sample programs ?
   - panning domains supported as well.

* Wed Jun 29 2009 Shree Kumar <shreekumar@hp.com>
- Bumped up version number to 0.2-4. Significant changes
  since 0.2-2 :
   - working RGS
   - more reliable TurboVNC
   - many samples
   - keyboard/mouse detection in configuration script
   - display rotation
   - templates in /opt/vizstack/share

* Wed Jun 17 2009 Shree Kumar <shreekumar@hp.com>
- Bumped up version number to 0.2, before releasing it to C&I,
  competency center & Glenn.

* Mon Jun  8 2009 Manjunath Sripadarao <manjunath.sripadarao@hp.com>
- Added samples directory to /opt/vizstack/etc with some sample config files.

* Fri May 29 2009 Manjunath Sripadarao <manjunath.sripadarao@hp.com> - 
- Initial build.

