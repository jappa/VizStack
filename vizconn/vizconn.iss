[Files]
Source: dist\*; DestDir: {app}
[Setup]
AppCopyright=Hewlett-Packard
AppName=VizStack Remote Access
AppVerName=VizStack Remote Access v1.1-2
RestartIfNeededByRun=false
PrivilegesRequired=none
InternalCompressLevel=ultra64
SolidCompression=true
ShowLanguageDialog=no
DefaultGroupName=VizStack Remote Access
OutputDir=.
DefaultDirName={pf}\VizStack Remote Access
LicenseFile=..\COPYING
[Icons]
Name: {group}\Viz Connector for HP RGS Receiver; Filename: {app}\remotevizconnector.exe; WorkingDir: {app}; Parameters: --rgs; Comment: Start a remote desktop session using HP RGS software
Name: {group}\Viz Connector for TurboVNC; Filename: {app}\remotevizconnector.exe; WorkingDir: {app}; Parameters: --tvnc; Comment: Start a remote desktop session using TurboVNC/VirtualGL
