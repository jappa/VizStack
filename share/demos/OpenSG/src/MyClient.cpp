// OpenSG Tutorial Example: Hello World

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

//
// Minimalistic OpenSG cluster client program
// 
// To test it, run 
//   ./12ClusterServer -geometry 300x300+200+100 -m -w test1 &
//   ./12ClusterServer -geometry 300x300+500+100 -m -w test2 &
//   ./13ClusterClient -m -fData/tie.wrl test1 test2
//
// If you have trouble with multicasting, you can alternatively try
//   ./12ClusterServer -geometry 300x300+200+100 -w 127.0.0.1:30000 &
//   ./12ClusterServer -geometry 300x300+500+100 -w 127.0.0.1:30001 &
//   ./13ClusterClient -fData/tie.wrl 127.0.0.1:30000 127.0.0.1:30001
// This will work as long as your loopback interface can handle broadcasts.
// If that is not the case you need to use your local IP address instead
// of 127.0.0.1.
//  
// The client will open an emoty window that you can use to navigate. The
// display is shown in the server windows.
//
// This will run all three on the same machine, but you can also start the 
// servers anywhere else, as long as you can reach them via multicast.
//
// Note: This will run two VERY active OpenGL programs on one screen. Not all
// OpenGL drivers are happy with that, so if it crashes your X, it's not our
// fault! ;)


// General OpenSG configuration, needed everywhere
#include <OpenSG/OSGConfig.h>

// Methods to create simple geometry: boxes, spheres, tori etc.
#include <OpenSG/OSGSimpleGeometry.h>

// A little helper to simplify scene management and interaction
#include <OpenSG/OSGSimpleSceneManager.h>

// The cluster window that handles sort-first (screen-split) clustering
#include <OpenSG/OSGMultiDisplayWindow.h>

// Scene file handler for loading geometry files
#include <OpenSG/OSGSceneFileHandler.h>

#include <sys/time.h>
#include <time.h>

// Activate the OpenSG namespace
OSG_USING_NAMESPACE

using namespace std;
// The SimpleSceneManager to manage simple applications
SimpleSceneManager *mgr;

// forward declaration so we can have the interesting stuff upfront
int setupGLUT( int *argc, char *argv[] );

// Initialize GLUT & OpenSG and set up the scene
int main(int argc, char **argv)
{
    char     *opt;
    NodePtr   scene=NullFC;

    // OSG init
    ChangeList::setReadWriteDefault();
    osgInit(argc,argv);

    // the connection between this client and the servers
    MultiDisplayWindowPtr mwin= MultiDisplayWindow::create();

    // all changes must be enclosed in beginEditCP and endEditCP
    // otherwise the changes will not be transfered over the network.
    beginEditCP(mwin);

    // evaluate params
    for(int a=1 ; a<argc ; ++a)
    {
        if(argv[a][0] == '-')
        {
            switch(argv[a][1])
            {
                case 'm': mwin->setConnectionType("Multicast");
cout << "Connection type set to Multicast" << endl;
                          break;
                case 'p': mwin->setConnectionType("SockPipeline");
cout << "Connection type set to SockPipeline" << endl;
                          break;
                case 'i': opt = argv[a][2] ? argv[a]+2 : argv[++a];
                          if(opt != argv[argc])
                              mwin->setConnectionInterface(opt);
                          break;
                case 'a': opt = argv[a][2] ? argv[a]+2 : argv[++a];
                          if(opt != argv[argc])
                              mwin->setServiceAddress(opt);
                          break;
                case 'f': opt = argv[a][2] ? argv[a]+2 : argv[++a];
                          if(opt != argv[argc])
                              scene = SceneFileHandler::the().read(
                                  opt,0);
                          break;
                case 'x': opt = argv[a][2] ? argv[a]+2 : argv[++a];
                          if(opt != argv[argc])
                              mwin->setHServers(atoi(opt));
                          break;
                case 'y': opt = argv[a][2] ? argv[a]+2 : argv[++a];
                          if(opt != argv[argc])
                              mwin->setVServers(atoi(opt));
                          break;
                default:  std::cout << argv[0]  
                                    << " -m"
                                    << " -p"
                                    << " -i interface"
                                    << " -f file"
                                    << " -x horizontal server cnt"
                                    << " -y vertical server cnt"
                                    << endLog;
                          return 0;
            }
        }
        else
        {
            printf("%s\n",argv[a]);
            mwin->getServers().push_back(argv[a]);
        }
    }

    // dummy size for navigator
    mwin->setSize(800,600);

    // end edit of cluster window
    endEditCP(mwin);

    // create default scene
    if(scene == NullFC)
       scene = makeTorus(.5, 2, 16, 16);

    // create the SimpleSceneManager helper
    mgr = new SimpleSceneManager;

    // tell the manager what to manage
    mgr->setWindow(mwin );
    mgr->setRoot  (scene);

    // show the whole scene
    mgr->showAll();
    
    // initialize window
    mwin->init();

    struct timeval tstart;
    gettimeofday(&tstart, NULL);
    int nFrames = 0;

    while(1)
    {
	    // Simulate user mouse movements as a cheap way of turning around the model.
	    mgr->mouseButtonPress(0, 150, 150);
	    mgr->mouseMove(151,150);
	    mgr->mouseButtonRelease(0, 151, 150);
	    // redraw the cluster window
	    mgr->redraw();
	    // clear change list. If you don't clear the changelist,
	    // then the same changes will be transmitted a second time
	    // in the next frame. 
	    OSG::Thread::getCurrentChangeList()->clearAll();
            nFrames++;
	    struct timeval tend;
	    gettimeofday(&tend, NULL);
            float elapsedtime = tend.tv_sec-tstart.tv_sec;
            if(tend.tv_usec<tstart.tv_usec)
            {
                 elapsedtime = elapsedtime + 1.0;
            }
            elapsedtime = elapsedtime + (tend.tv_usec-tstart.tv_usec)*1e-6;
	 
            if(nFrames==300)
            {
	         float fps = 300.0/elapsedtime;
                 //printf("FPS = %3f elapsedtime=%f\n",fps,elapsedtime);
	         tstart = tend;
                 nFrames = 0;
            }
            //tend.tv_sec=0;
            //tend.tv_usec=20*1000;
	    //select(1, NULL, NULL, NULL, &tend);
    }
 
    return 0;
}
