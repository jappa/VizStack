REM VizStack - A Framework to manage visualization resources

REM Copyright (C) 2009-2010 Hewlett-Packard
REM 
REM This program is free software; you can redistribute it and/or
REM modify it under the terms of the GNU General Public License
REM as published by the Free Software Foundation; either version 2
REM of the License, or (at your option) any later version.
REM 
REM This program is distributed in the hope that it will be useful,
REM but WITHOUT ANY WARRANTY; without even the implied warranty of
REM MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
REM GNU General Public License for more details.
REM 
REM You should have received a copy of the GNU General Public License
REM along with this program; if not, write to the Free Software
REM Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

rmdir /S /Q build
rmdir /S /Q dist
python setup.py py2exe
"C:\Program Files\Inno Setup 5\iscc.exe" vizconn.iss
move setup.exe VizStackRemoteAccessSetup-1.1-3.exe

