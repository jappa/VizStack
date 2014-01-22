/*
 * VizStack - A Framework to manage visualization resources

 * Copyright (C) 2009-2010 Hewlett-Packard
 * 
 * This program is free software; you can redistribute it and/or
 * modify it under the terms of the GNU General Public License
 * as published by the Free Software Foundation; either version 2
 * of the License, or (at your option) any later version.
 * 
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 * 
 * You should have received a copy of the GNU General Public License
 * along with this program; if not, write to the Free Software
 * Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
 */

#ifndef __VS_DOM_PARSER_INCLUDED__
#define __VS_DOM_PARSER_INCLUDED__

#ifdef DOM_USE_XERCES
	// Xerces includes
	#include <xercesc/util/PlatformUtils.hpp>
	#include <xercesc/parsers/AbstractDOMParser.hpp>
	#include <xercesc/framework/Wrapper4InputSource.hpp>
	#include <xercesc/dom/DOMImplementation.hpp>
	#include <xercesc/dom/DOMImplementationLS.hpp>
	#include <xercesc/dom/DOMImplementationRegistry.hpp>
	#include <xercesc/dom/DOMBuilder.hpp>
	#include <xercesc/dom/DOMException.hpp>
	#include <xercesc/dom/DOMDocument.hpp>
	#include <xercesc/dom/DOMNodeList.hpp>
	#include <xercesc/dom/DOMError.hpp>
	#include <xercesc/dom/DOMLocator.hpp>
	#include <xercesc/dom/DOMNamedNodeMap.hpp>
	#include <xercesc/dom/DOMAttr.hpp>
	#include <xercesc/dom/DOMErrorHandler.hpp>
	#include <xercesc/util/XMLString.hpp>
	XERCES_CPP_NAMESPACE_USE
#endif

#ifdef DOM_USE_LIBXML
	#include <libxml/parser.h>
	#include <libxml/tree.h>
#endif

#include <vector>
#include <string>

class VSDOMNode;
class VSDOMDoc;
class VSDOMParser;

#ifdef DOM_USE_XERCES
class VSDOMParserErrorHandler : public DOMErrorHandler
#else
class VSDOMParserErrorHandler
#endif
{
	public:
		VSDOMParserErrorHandler ();
		~VSDOMParserErrorHandler ();

		bool haveMessages () const;
		bool haveErrors () const;
		void getMessages(std::vector<std::string>& msg) const;
#ifdef DOM_USE_XERCES
		// -----------------------------------------------------------------------
		//  Implementation of the DOM ErrorHandler interface
		// -----------------------------------------------------------------------
		bool handleError (const DOMError & domError);
#endif
		void resetErrors ();

	private:
		std::vector<std::string> m_messages;
		unsigned int m_nErrors;
		unsigned int m_nWarnings;
};

class VSDOMParser
{
#ifdef DOM_USE_XERCES
	DOMBuilder *m_parser;
#endif
	public:
		static bool Initialize();
		static void Finalize();

		VSDOMParser();
		~VSDOMParser();

		VSDOMDoc* ParseString(const char* source, VSDOMParserErrorHandler& errorHandler);
		VSDOMDoc* ParseFile(const char* filename, VSDOMParserErrorHandler& errorHandler);
};

class VSDOMNode
{
#ifdef DOM_USE_XERCES
	DOMNode *m_node;
#endif

#ifdef DOM_USE_LIBXML
	xmlNodePtr m_node;
	xmlDocPtr m_doc; // we need this for xmlElemDump
#endif
	public:
		VSDOMNode() { m_node = 0; }
#ifdef DOM_USE_XERCES
		VSDOMNode(DOMNode *node) { m_node = node; }
#endif
#ifdef DOM_USE_LIBXML
		VSDOMNode(xmlNodePtr node, xmlDocPtr doc) { m_node = node; m_doc=doc; }
#endif
		std::vector<VSDOMNode> getChildNodes(std::string nodeName);
		VSDOMNode getChildNode(std::string nodeName);
		std::string getNodeName();
		std::string getValueAsString();
		unsigned int getValueAsInt();
		float getValueAsFloat();
		bool writeXML(const char* fileName, VSDOMParserErrorHandler &errorHandler);
		bool isEmpty() { return (m_node==0); }
};

class VSDOMDoc
{
#ifdef DOM_USE_XERCES
	DOMDocument *m_doc;
#endif

#ifdef DOM_USE_LIBXML
	xmlDocPtr  m_doc;
#endif
	public:
		~VSDOMDoc();
#ifdef DOM_USE_XERCES
		VSDOMDoc(DOMDocument *doc) { m_doc = doc; }
#endif
#ifdef DOM_USE_LIBXML
		VSDOMDoc(xmlDocPtr doc) { m_doc = doc; }
#endif
		VSDOMNode getRootNode();
};

bool writeXML(VSDOMNode* node, const char* fileName, VSDOMParserErrorHandler &errorHandler);

#endif
