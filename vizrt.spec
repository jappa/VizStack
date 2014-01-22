Summary: VizStack Remote Access Tools
Name: vizrt
Version: 1.1
Release: 3
License: GPLV2
Group: Applications/Internet
URL: http://vizstack.sourceforge.net
BuildArch: noarch
Source0: %{name}-%{version}.tar.gz
BuildRoot: %{_tmppath}/%{name}-%{version}-%{release}-root
Requires: wxPython paramiko

%description

%prep
%setup -q

%build

%install
rm -rf $RPM_BUILD_ROOT
mkdir -p $RPM_BUILD_ROOT
cp -r opt $RPM_BUILD_ROOT

%clean
rm -rf $RPM_BUILD_ROOT

%files
%defattr(-,root,root,-)
/opt/vizrt/bin/*
%doc


%changelog
* Wed Jun 7 2010 Shree Kumar <shreekumar@hp.com>
- Bumped up version string to 1.1-3, keeping in sync with VizStack.

* Mon May 17 2010 Shree Kumar <shreekumar@hp.com>
- Bumped up version string to 1.1-2, Changes being
  - Added GPL license page
  - Added an option to allocate an exclusive node

* Fri Mar 26 2010 Shree Kumar <shreekumar@hp.com>
- Bumped up version string to 1.1-1, keeping in sync with VizStack
  main RPM.

* Tue Feb 23 2010 Shree Kumar <shreekumar@hp.com>
- Bumped up the version string to 1.1, for GPU sharing release

* Tue Feb 23 2010 Shree Kumar <shreekumar@hp.com>
- Bumped up the version string to 1.0-2, for new release

* Thu Nov 05 2009 Sunil Shinde <sunil.shinde@hp.com>
- Bumped up the version string to 1.0-1
* Thu Sep 17 2009 manjunath.sripadarao <manjunath.sripadarao@hp.com> - 
- Initial build.

