
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
import xml
from xml.dom import minidom

def getChildNode(node, name):
	"""
	Returns the first child node of the passed node with the given node name.
	This will typically be used if the node has exactly one node of the
	given name.
	"""
	if node.childNodes is None:
		return None
	for n in node.childNodes:
		if n.nodeName == name:
			return n
	return None

def getChildNodes(node, name):
	"""
	Returns all child nodes of the passed node with the given node name.
	"""
	ret = []
	if node.childNodes is None:
		return ret
	for n in node.childNodes:
		if n.nodeName == name:
			ret.append(n)
	return ret

def getAllChildNodes(node):
	"""
	Return all ELEMENT_NODE children of a node
	"""
	ret = []
	if node.childNodes is None:
		return ret
	for n in node.childNodes:
		if n.nodeType == n.ELEMENT_NODE:
			ret.append(n)
	return ret

def getValue(node):
	# FIXME: find a way out of unicode-inconsistency.
	# ideally we want to support unicode.
	return node.firstChild.nodeValue.encode('iso-8859-1')

def parseString(msg):
	doc = xml.dom.minidom.parseString(msg)
	return doc.documentElement
