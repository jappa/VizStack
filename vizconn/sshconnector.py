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

import paramiko
import socket
import os
from xml.dom import minidom
import sys
import time

class ConnectorError(Exception):
	def __init__(self, msg):
		self.msg = msg
	def __str__(self):
		return self.msg
	def getErrorMessage(self):
		return self.msg

class Connector:
	"""
	Base class which describes the behaviours that a Connector
	needs to implement
	"""
	def __init__(self, hostname, username, password=None):
		"""
		hostname and username are mandatory.
		password could be a text string, a function callback (username as parameter),
		or None.
		"""
		pass

	def StartDialog(self, binaryPath, expectedHeader):
		"""
		Starts a "dialog" by executing the executable in "binaryPath".
		The executable should print out the the expectedHeader at the beginning, else
		you get a failure.
		"""
		raise NotImplementedError, "StartDialog needs to be implemented in the derived class"

	def Write(self, data):
		"""
		Write data to the remote processes's stdin. Valid only after StartDialog succeeds.
		"""
		raise NotImplementedError, "Write needs to be implemented in the derived class"

	def ReadXML(self):
		"""
		Read a complete DOM tree from the destination.
		Function returns when either a complete XML has been extracted OR on EOF.
		"""
		raise NotImplementedError, "ReadXML needs to be implemented in the derived class"

	def Close(self):
		"""
		Close the connection, killing application and disconnecting.
		"""
		raise NotImplementedError, "Close needs to be implemented in the derived class"


class SSHConnector(Connector):
	"""
	Implementation of the Connector interface using SSH
	"""
	def __init__(self, hostname, username, password=None, callbackdata=None):
		self.hostname = hostname
		try:
			sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
			sock.connect((hostname, 22))
		except socket.error, e:
			raise ConnectorError("Failed to connect to host %s. Reason:%s"%(hostname, str(e)))

		self.sock = sock

		t = paramiko.Transport(sock)
		self.transport = t
		try:
			t.start_client()
		except paramiko.SSHException:
			raise ConnectorError("SSH negotiation to host '%s' failed."%(hostname))

# Skipping key validation. This does not work on Windows. The burden of detecting security
# issues is too much for this small tool. So we skip it.
#
#		try:
#			keys = paramiko.util.load_host_keys(os.path.expanduser('~/.ssh/known_hosts'))
#		except IOError:
#			try:
#				keys = paramiko.util.load_host_keys(os.path.expanduser('~/.ssh/known_keys'))
#			except IOError:
#				raise ConnectorError("Unable to open host keys file")
#
#			# Check server's host key
#			key = t.get_remote_server_key()
#			if not keys.has_key(hostname):
#				raise ConnectorError("Unknown host key")
#			elif not keys[hostname].has_key(key.get_name()):
#				raise ConnectorError("Unknown host key")
#			elif keys[hostname][key.get_name()] != key:
#				raise ConnectorError("Host key has changed")

		self.__agent_auth(t, username)
		if not t.is_authenticated():
			# Try with DSA key, if it exists
			dsa_key_path = os.path.expanduser('~/.ssh/id_dsa')
			try:
				open(dsa_key_path,'r')
			except IOError, e:
				pass
			else:
				try:
					try:
						key = paramiko.DSSKey.from_private_key_file(dsa_key_path)
					except paramiko.PasswordRequiredException:
						textPassPhrase = password("Connecting as user %s\nEnter passphrase for your public DSA key(~/.ssh/id_dsa.pub)"%(username), callbackdata)
						if textPassPhrase is None:
							raise ConnectorError("Failed to connect")
						key = paramiko.DSSKey.from_private_key_file(dsa_key_path, textPassPhrase)
					except paramiko.SSHException:
						pass
					t.auth_publickey(username, key)
				except paramiko.AuthenticationException, e:
					pass
				except paramiko.SSHException, e:
					# This can happen due to incomplete implementation in Paramiko. We ignore such errors...
					#
					# SSHException: Unable to parse key file: Unknown ber encoding type 135 (robey is lazy)
					pass

			# Try pasword authentication if DSA key auth failed/didn't happen
			if not t.is_authenticated():
				# Do password authentication
				if password is None:
					raise ConnectorError("Authentication failed.")
				elif callable(password):
					textPassword = password("Enter password for user %s"%(username), callbackdata)
					if textPassword is None:
						raise ConnectorError("Failed to connect")
				else:
					textPassword = password
				try:
					t.auth_password(username, textPassword)
				except paramiko.AuthenticationException, e:
					raise ConnectorError("Authentication failed. Invalid username/password")

		self.channel = None

	def Close(self):
		if self.channel:
			self.channel.close()
			self.channel = None
		if self.transport:
			self.transport.close()
			self.transport = None
		if self.sock:
			self.sock.close()
			self.sock = None

	def StartDialog(self, binaryPath, expectedHeader):
		try:
			self.channel = self.transport.open_channel('session')
		except Exception, e:
			raise ConnectorError("Failed to open SSH channel. Reason : %s"%(str(e)))

		try:
			self.channel.exec_command(binaryPath)
		except Exception, e:
			raise ConnectorError("Internal error while trying to execute remote command on '%s'"%(self.hostname))
		header = self.__readRaw(len(expectedHeader))
		if header != expectedHeader:
			# 1000 bytes of error ought to be enough to diagnose the problem...
			errors = self.channel.recv_stderr(1000)
			if len(errors)==0:
				raise ConnectorError("Header mismatch from application. Please check application path")
			# return appropriate error indicator
			if(errors.find('command not found')!=-1) or (errors.find('No such file or directory')!=-1):
				raise ConnectorError("Application is not installed on remote machine.")
			else:
				raise ConnectorError("Unknown error: '%s'"%(errors))
	def Write(self, data):
		index=0
		while index<len(data):
			try:
				nBytes = self.channel.send(data[index:])
			except socket.timeout, e:
				continue
			if nBytes==0:
				break
			index = index+nBytes
		# if the two are not equal below, then a write error happened
		return index==len(data)

	def ReadXML(self):
		total_data = ''
		dom = None
		# Keep trying to get a full XML tree
		# what a painless way to get around parsing issues :-)
		while dom is None:
			data=self.channel.recv(1) # heh-extra safety !
			if len(data)==0:
				#print 'EOF'
				break
			total_data = total_data+data
			try:
				dom = minidom.parseString(total_data)
			except:
				dom = None
		#print 'response = "%s"'%(total_data)
		return dom

	def __readRaw(self, nBytes=0):
		data = ''
		if nBytes==0:
			data = self.channel.recv(0)
		else:
			data = self.channel.recv(nBytes)
		return data

	def __agent_auth(self,transport, username):
		agent = paramiko.Agent()
		agent_keys = agent.get_keys()
		if len(agent_keys)==0:
			return

		for key in agent_keys:
			try:
				transport.auth_publickey(username, key)
				return
			except paramiko.SSHException:
				pass

	def __fini__(self):
		self.Close()


if __name__ == "__main__":
	import wx

	def getPassword(username):
		dlg = wx.TextEntryDialog(None, "Enter password for user %s"%(username),"User Authentication", style=wx.OK|wx.CANCEL|wx.TE_PASSWORD)
		if dlg.ShowModal()==wx.ID_OK:
			return dlg.GetValue()
		return None

	app = wx.App(0)
	try:
		c = SSHConnector('15.146.228.89', "root", getPassword)
	except ConnectorError, e:
		dlg = wx.MessageDialog(None, e.getErrorMessage(), "Error", style=wx.OK|wx.ICON_EXCLAMATION)
		dlg.ShowModal()
		app.Destroy()
		sys.exit(-1)
	c.StartDialog("/opt/vizstack/bin/vizconn/rgshelper","rgshelper")
	print c.ReadXML().toprettyxml()
	c.Close()
