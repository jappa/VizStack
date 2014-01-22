// OpenSG Tutorial Example: Cluster Server
//
// This is a full functional OpenSG cluster server. In OpenSG
// the terms server and client are used similar to X11. The
// application is the client. Instances that are used for 
// rendering are called server.
//
// See the ClusterClient.cpp for an example of how to use them.

#include <iostream>

#define OSG_WITH_GLUT // Shree added for glut usage!

// GLUT is used for window handling
#include <OpenSG/OSGGLUT.h>
// General OpenSG configuration, needed everywhere
#include <OpenSG/OSGConfig.h>
// The Cluster server definition
#include <OpenSG/OSGClusterServer.h>
// The GLUT-OpenSG connection class
#include <OpenSG/OSGGLUTWindow.h>
// Render action definition. 
#include <OpenSG/OSGRenderAction.h>

OSG_USING_NAMESPACE

// local glut window
GLUTWindowPtr   window;
// render action
RenderAction   *ract;
// pointer the the cluster server instance
ClusterServer  *server;

// forward declaration so we can have the interesting stuff upfront
void display();
void update();
void reshape( int width, int height );

// Initialize GLUT & OpenSG and start the cluster server
int main(int argc,char **argv)
{
    int             winid;
    char           *name          ="ClusterServer";
    char           *connectionType="StreamSock";
    bool            fullscreen     =true;
    std::string     address        ="";
    char           *opt;

    // initialize Glut
    glutInit(&argc, argv);
    glutInitDisplayMode( GLUT_RGB | 
                         GLUT_DEPTH | 
                         GLUT_DOUBLE);

    // evaluate params
    for(int a=1 ; a<argc ; ++a)
    {
        if(argv[a][0] == '-')
        {
            switch(argv[a][1])
            {
                case 'm': connectionType="Multicast";
                          break;
                case 'p': connectionType="SockPipeline";
                          break;
                case 'w': fullscreen=false;
                          break;
                case 'a': address = argv[a][2] ? argv[a]+2 : argv[++a];
                          if(address == argv[argc])
                          { 
                              SLOG << "address missing" << endLog;
                              return 0;
                          }
                          std::cout << address << endLog;
                          break;
                default:  std::cout << argv[0] 
                                    << "-m "
                                    << "-p "
                                    << "-w "
                                    << "-a address "
                                    << endLog;
                          return 0;
            }
        }
        else
        {
            name=argv[a];
        }
    }
    try
    {
        ChangeList::setReadWriteDefault();

        // init OpenSG
        osgInit(argc, argv);

        winid = glutCreateWindow(name);
        if(fullscreen)
            glutFullScreen();
        glutDisplayFunc(display);
        glutIdleFunc(update);
        glutReshapeFunc(reshape);
        glutSetCursor(GLUT_CURSOR_NONE);

        glEnable( GL_LIGHTING );
        glEnable( GL_LIGHT0 );
        glEnable( GL_NORMALIZE );

        // create the render action
        ract=RenderAction::create();

        // setup the OpenSG Glut window
        window     = GLUTWindow::create();
        window->setId(winid);
        window->init();

        // create the cluster server
        server     = new ClusterServer(window,name,connectionType,address);
        // start the server
        server->start();

	// We resize the window here. 
	// Reason : if this program is run on an X server without a
	// window manager, then the GLUT resize function never gets
	// called. The side effect is that the program doesn't display
	// anything. We explicitly set the size to work around this 
	// problem. This size can be passed either from the command
	// line OR implicitly by fullscreen.
	//
	int width = glutGet(GLUT_WINDOW_WIDTH);
	int height = glutGet(GLUT_WINDOW_HEIGHT);
	window->resize( width, height);

	glutPostRedisplay();
        // enter glut main loop
        glutMainLoop();
    }
    catch(OSG_STDEXCEPTION_NAMESPACE::exception &e)
    {
        SLOG << e.what() << endLog;
        delete server;
        osgExit(); 
    }
    return 0;
}

/* render loop */
void display()
{
    try
    {
        // receive scenegraph and do rendering
        server->render(ract);
        // clear changelist 
        OSG::Thread::getCurrentChangeList()->clearAll();
    } 
    catch(OSG_STDEXCEPTION_NAMESPACE::exception &e)
    {
        SLOG << e.what() << endLog;
        // try to restart server
        server->stop();
        // start server, wait for client to connect
        server->start();
    }
}

void update(void)
{
    glutPostRedisplay();
}

/* window reshape */
void reshape( int width, int height )
{
    // set new window size
	window->resize( width, height );
}
