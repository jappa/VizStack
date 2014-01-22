#ifndef __VS_COMMON_INCLUDED__
#define __VS_COMMON_INCLUDED__

#include <string>

extern bool g_standalone;
extern std::string g_ssmHost;
extern std::string g_ssmPort;
extern std::string g_hostName;

bool getSystemType();
int write_bytes(int socket, const char *buf, int nBytes);
int read_bytes(int socket, char *buf, int nBytes);
bool write_message(int socket, const char* data, unsigned int dataLen);
char* read_message(int socket);
char *munge_encode(const char *message);
char* getServerConfig(const char *hostname, const char* xdisplay, int ssmSocket);
int connectToSSM(std::string ssmHost, std::string ssmPort);
void closeSocket(int fd);
bool getTemplates(std::vector<VSDOMNode>& nodes, std::string templateType, int ssmSocket);
bool authenticateToSSM(std::string myIdentity, int ssmSocket);
char *getNodeConfig(const char *hostname, int ssmSocket);

#define CODE_SIGCHLD '0'
#define CODE_SIGUSR1  '1'
#define CODE_SIGHUP   '2'
#define CODE_SIGTERM  '3'
#define CODE_SIGINT   '4'

#define RETRY_ON_EINTR(ret, x)  { \
	while(1) { \
		ret = x; \
		if(ret == -1) { \
			if(errno==EINTR) \
				 continue; \
		} \
		else \
			break; \
	} \
}

#endif
