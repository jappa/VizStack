#include "vsdomparser.hpp"
#include "vscommon.h"
#include <string>
#include <vector>
#include <iostream>
#include <errno.h>
#include <sys/types.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <netdb.h>
using namespace std;

bool g_standalone = false;
string g_ssmHost;
string g_ssmPort;
string g_hostName;

bool getSystemType()
{
	char myHostName[256];
	gethostname(myHostName, sizeof(myHostName));

	VSDOMParserErrorHandler errorHandler;
	// Load the display device templates
	VSDOMParser *configParser = new VSDOMParser;

	errorHandler.resetErrors();
	VSDOMDoc *config = configParser->ParseFile("/etc/vizstack/master_config.xml", errorHandler);

	// Print out warning and error messages
	vector<string> msgs;
	errorHandler.getMessages (msgs);
	for (unsigned int i = 0; i < msgs.size (); i++)
		cout << msgs[i] << endl;

	if(!config)
	{
		cerr << "ERROR: Unable to get the local configuration of this node." << endl;
		return false;
	}

	VSDOMNode rootNode = config->getRootNode();
	VSDOMNode systemNode = rootNode.getChildNode("system");
	VSDOMNode systemTypeNode = systemNode.getChildNode("type");
	string systemType = systemTypeNode.getValueAsString();

	if(systemType=="standalone")
	{
		g_standalone = true;
		g_hostName = "localhost";
	}
	else
	{

		VSDOMNode masterNode = systemNode.getChildNode("master");
		if(masterNode.isEmpty())
		{
			cerr << "ERROR: Invalid configuration. You must specify a master." << endl;
			return false;
		}
		g_ssmHost = masterNode.getValueAsString();

		VSDOMNode masterPortNode = systemNode.getChildNode( "master_port");
		if(masterPortNode.isEmpty())
		{
			cerr << "ERROR: Invalid configuration. You must specify a master port." << endl;
			return false;
		}

		g_ssmPort = masterPortNode.getValueAsString();
		if(g_ssmHost != "localhost")
		{
			int portNum = atoi(g_ssmPort.c_str());
			char buffer[100];
			sprintf(buffer, "%d",portNum);
			if((portNum<=0) or (g_ssmPort != buffer))
			{
				cerr << "ERROR: Invalid configuration. Please check the master port you have specified (" << g_ssmPort << ") for errors." << endl;
				return false;
			}
		}
		else
		if(g_ssmPort.size()>100) // prevent buffer overruns
		{
			cerr << "ERROR: Invalid configuration. The master port you have specified '%s' is too long (limit : 100 chars)." << endl;
			return false;
		}

		g_standalone = false;

		char myHostName[256];
		if(gethostname(myHostName, sizeof(myHostName))<0)
		{
			perror("ERROR: Unable to get my hostname");
			exit(-1);
		}

		if(g_ssmHost=="localhost")
			g_hostName="localhost";
		else
			g_hostName = myHostName;
	}

	return true;
}

int write_bytes(int socket, const char *buf, int nBytes)
{
	int nBytesWritten = 0;
	const char *ptr = buf;
	while(nBytesWritten != nBytes)
	{
		int ret = send(socket, ptr, nBytes - nBytesWritten, MSG_NOSIGNAL);
		if(ret==-1)
		{
			if(errno==EINTR)
				continue;
			else
			{
				perror("Unable to write data to scoket");
				return nBytesWritten;
			}
		}
		else
		{
			nBytesWritten += ret;
			ptr += ret;
		}
	}
	return nBytesWritten;
}

int read_bytes(int socket, char *buf, int nBytes)
{
	int nBytesRead = 0;
	char *ptr = buf;
	while(nBytesRead != nBytes)
	{
		int ret = recv(socket, ptr, nBytes - nBytesRead, MSG_WAITALL);
		if(ret==-1)
		{
			if(errno==EINTR)
				continue;
			else
			{
				return nBytesRead;
			}
		}
		else
		if(ret==0)
		{
			// EOF !
			break;
		}
		else
		{
			nBytesRead += ret;
			ptr += ret;
		}
	}
	return nBytesRead;
}

bool write_message(int socket, const char* data, unsigned int dataLen)
{
	char sizeStr[6];

	// FIXME: can't handle messages larger than this due to the protocol limitations
	// centralize the protocol limitations.
	if(dataLen>99999) 
	{
		fprintf(stderr,"Bad message length %d! May not exceed 99999!\n",dataLen);
		return false;
	}
	sprintf(sizeStr,"%d", dataLen);
	while(strlen(sizeStr)<5)
		strcat(sizeStr, " ");

	if(write_bytes(socket, sizeStr, 5)!=5)
	{
		fprintf(stderr,"Unable to write message header to scoket\n");
		return false;
	}

	if(write_bytes(socket, data, dataLen)!=dataLen)
	{
		fprintf(stderr,"Unable to write message data to scoket\n");
		return false;
	}

	return true;
}

char* read_message(int socket)
{
	char sizeStr[6];
	int retBytes;

	// get length first
	if((retBytes=read_bytes(socket, sizeStr, 5))!=5)
	{
		if(retBytes!=0)
			perror("Socket error - Unable to get message length");
		return 0;
	}

	int numMsgBytes = atoi(sizeStr);
	if(numMsgBytes<0)
	{
		fprintf(stderr, "Socket error: Bad message length %d\n", numMsgBytes);
		return 0;
	}

	char *message = new char[numMsgBytes+1];
	if(read_bytes(socket, message, numMsgBytes)!=numMsgBytes)
	{
		fprintf(stderr, "Socket error: Unable to read entire message\n");
		delete []message;
		return 0;
	}

	// Null terminate the string - so easy to forget these details at times :-(
	message[numMsgBytes] = 0;

	return message;
}

char *munge_encode(const char *message)
{
	// FIXME: Do thorough error logging in this function
	// failure here should be catchable !!!

	// Summary for this function is:
	// 1. we create a temporary file
	// 2. put the message as the contents of the file
	// 3. we pass that as input to munge
	// 4. we get the credential from stdout
	// 5. On error, undo stuff and return 0 !

	char tempInputFile[256];
	strcpy(tempInputFile, "/tmp/munge_encode_tmpXXXXXX");
	int fd = mkstemp(tempInputFile);
	if (fd==-1)
		return 0;

	// close the fd
	close(fd);

	FILE *fp=fopen(tempInputFile, "w");
	if(!fp)
	{
		unlink(tempInputFile);
		return 0;
	}
	if(fwrite(message, strlen(message), 1, fp)!=1)
	{
		fclose(fp);
		unlink(tempInputFile);
		return 0;
	}
	fclose(fp);

	char cmdLine[4096];
	sprintf(cmdLine, "munge --input %s",tempInputFile);
	fp = popen(cmdLine,"r");
	if(!fp)
	{
		fprintf(stderr, "ERROR Error - unable to run munge\n");
		unlink(tempInputFile);
		return 0;
	}

	string fileContent;
	char data[4096];
	while(1)
	{
		int nRead = fread(data, 1, sizeof(data), fp);

		if(nRead>0)
		{
			data[nRead]=0;
			fileContent = fileContent + data;
		}

		if (feof(fp))
		{
			break;
		}
	}
	int exitCode = pclose(fp);


	if(exitCode != 0)
	{
		fprintf(stderr, "ERROR Error - unable to get munge credential\n");
		unlink(tempInputFile);
		return false;
	}

	unlink(tempInputFile);
	return strdup(fileContent.c_str());
}

char* getServerConfig(const char *hostname, const char* xdisplay, int ssmSocket)
{
	// we do this by sending a query message to the SSM
	char message[1024];
	sprintf(message,
			"<ssm>\n"
			"	<get_serverconfig>\n"
			"		<server>\n"
			"			<hostname>%s</hostname>\n"
			"			<server_number>%s</server_number>\n"
			"		</server>\n"
			"	</get_serverconfig>\n"
			"</ssm>\n", hostname, xdisplay+1);

	if(!write_message(ssmSocket, message, strlen(message)))
	{
		fprintf(stderr, "ERROR - unable to send the query message to SSM\n");
		closeSocket(ssmSocket);
		return 0;
	}

	char *serverConfiguration = 0;
	if((serverConfiguration = read_message(ssmSocket))==0)
	{
		fprintf(stderr, "ERROR - unable to receive X configuration\n");
		closeSocket(ssmSocket);
		return 0;
	}
	return serverConfiguration;
}

char *getNodeConfig(const char *hostname, int ssmSocket)
{
	// we do this by sending a query message to the SSM
	char message[1024];
	sprintf(message,
			"<ssm>\n"
			"	<query_resource>\n"
			"		<node>\n"
			"			<hostname>%s</hostname>\n"
			"		</node>\n"
			"	</query_resource>\n"
			"</ssm>\n", hostname);

	if(!write_message(ssmSocket, message, strlen(message)))
	{
		fprintf(stderr, "ERROR - unable to send the query message to SSM\n");
		closeSocket(ssmSocket);
		return 0;
	}

	char *serverConfiguration = 0;
	if((serverConfiguration = read_message(ssmSocket))==0)
	{
		fprintf(stderr, "ERROR - unable to receive X configuration\n");
		closeSocket(ssmSocket);
		return 0;
	}
	return serverConfiguration;
}

bool getTemplates(vector<VSDOMNode>& nodes, string templateType, int ssmSocket)
{
	// we do this by sending a query template message to the SSM
	char message[1024];
	sprintf(message,
			"<ssm>\n"
			"	<get_templates>\n"
			"		<%s />\n"
			"	</get_templates>\n"
			"</ssm>\n", templateType.c_str());

	if(!write_message(ssmSocket, message, strlen(message)))
	{
		fprintf(stderr, "ERROR - unable to send the query message to SSM\n");
		closeSocket(ssmSocket);
		return false;
	}

	char *retmessage = 0;
	if((retmessage = read_message(ssmSocket))==0)
	{
		fprintf(stderr, "ERROR - unable to receive X configuration\n");
		closeSocket(ssmSocket);
		return false;
	}

	VSDOMParserErrorHandler errorHandler;
	VSDOMParser *configParser = 0;
	configParser = new VSDOMParser;
	errorHandler.resetErrors();
	VSDOMDoc *config = configParser->ParseString(retmessage, errorHandler);
	if(!config)
	{
		// Print out warning and error messages
		vector<string> msgs;
		errorHandler.getMessages (msgs);
		for (unsigned int i = 0; i < msgs.size (); i++)
			cout << msgs[i] << endl;

		fprintf(stderr, "ERROR - bad return XML from SSM.\n");
		fprintf(stderr, "Return XML was --\n");
		fprintf(stderr, "----------------------------------------------\n");
		fprintf(stderr, "%s", retmessage);
		fprintf(stderr, "\n----------------------------------------------\n");
		closeSocket(ssmSocket);
		return false;
	}

	VSDOMNode rootNode = config->getRootNode();
	VSDOMNode responseNode = rootNode.getChildNode( "response");
	int status = responseNode.getChildNode("status").getValueAsInt();
	if(status!=0)
	{
		string msg = responseNode.getChildNode("message").getValueAsString();
		fprintf(stderr, "ERROR - Failure returned from SSM : %s\n", msg.c_str());
		delete configParser;
		return false;
	}

	VSDOMNode retValNode = responseNode.getChildNode("return_value");
	nodes = retValNode.getChildNodes(templateType.c_str());
	return true;
}

int connectToSSM(string ssmHost, string ssmPort)
{
	struct hostent* hp;
	struct hostent ret;
	char buffer[1000];
	int h_errnop;
	int ssmSocket = -1;

	// If the master is on "localhost", then we use Unix Domain Sockets
	if(ssmHost == "localhost")
	{
		ssmSocket = socket(AF_UNIX, SOCK_STREAM, 0);
		if(ssmSocket < 0)
		{
			perror("ERROR - Unable to create a socket to communicate with the SSM");
			return -1;
		}

		struct sockaddr_un sa;
		sa.sun_family = AF_UNIX;
		strcpy(sa.sun_path, ssmPort.c_str()); // on Linux, the path limit seems to be 118
		if(connect(ssmSocket, (sockaddr*) &sa, sizeof(sa.sun_family)+sizeof(sa.sun_path))<0)
		{
			perror("ERROR - Unable to connect to the local SSM");
			closeSocket(ssmSocket);
			return -1;
		}
	}
	else
	{
		// resolve the SSM host first
		gethostbyname_r(ssmHost.c_str(), &ret, buffer, sizeof(buffer), &hp, &h_errnop);
		if(!hp)
		{
			perror("ERROR - unable to resolve SSM hostname");
			return -1;
		}

		ssmSocket = socket(AF_INET, SOCK_STREAM, 0);
		if(ssmSocket < 0)
		{
			perror("ERROR - Unable to create a socket to communicate with the SSM");
			return -1;
		}

		struct sockaddr_in si;
		si.sin_family = AF_INET;
		si.sin_port = htons(atoi(ssmPort.c_str()));
		memcpy((void*)&si.sin_addr.s_addr, hp->h_addr, 4); // Copying an IPv4 address => 4 bytes

		// Connect to the SSM
		if(connect(ssmSocket, (sockaddr*) &si, sizeof(si))<0)
		{
			perror("ERROR - Unable to connect to the SSM");
			closeSocket(ssmSocket);
			return -1;
		}
	}
	return ssmSocket;
}

void closeSocket(int fd)
{
	shutdown(fd, SHUT_RDWR);
	close(fd);
}

bool authenticateToSSM(string myIdentity, int ssmSocket)
{
	char *encodedCred = 0;
	if(g_ssmHost == "localhost")
		encodedCred = strdup(myIdentity.c_str());
	else
	{
		// If the SSM is not on a local host, then it uses Munge to authenticate us.
		// We need to send out a a munge encoded packet in the beginning
		// so we need to call munge next, and use that to authenticate.
		encodedCred = munge_encode(myIdentity.c_str());

		if(!encodedCred)
		{
			fprintf(stderr,"ERROR - Unable to create a munge credential\n");
			return false;
		}
	}

	if(!write_message(ssmSocket, encodedCred, strlen(encodedCred)))
	{
		fprintf(stderr,"ERROR - Unable to send my identity to SSM\n");
		free(encodedCred);
		return false;
	}

	// Free the memory
	free(encodedCred);
	encodedCred = 0;

	return true;
}

