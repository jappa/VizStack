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
// vs-identify-display.cpp
//
// Helper program to help an administrator identify where a display is
// connected.
//
// This program expects to run without a window manager
// Run this as 
// vs-identify-display -geometry WxH+X+Y
//
// E.g. vs-identify-display -geometry 640x800+0+0

#include <GL/glut.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <map>
#include <string>

using namespace std;

void *g_stroke_font = GLUT_STROKE_MONO_ROMAN;
//void *g_bitmap_font = GLUT_BITMAP_HELVETICA_18;
void *g_bitmap_font = GLUT_BITMAP_TIMES_ROMAN_24;

int g_startTime = -1;
int g_totalTime = 10;

enum infoType { INFO_X_SERVER, INFO_GPU, INFO_DEVICE, INFO_MODE, INFO_TD_COORDS, INFO_STEREO, INFO_ROTATION, INFO_XINERAMA, INFO_MAX };
map<infoType, string> g_infoMessage;

void drawStringS(const char *msg)
{
	int index=0;
	while(msg[index])
	{
		glutStrokeCharacter(g_stroke_font, msg[index]);
		index++;
	}
}
void drawStringB(const char *msg)
{
	int index=0;
	while(msg[index])
	{
		glutBitmapCharacter(g_bitmap_font, msg[index]);
		index++;
	}
}

void drawStringCenteredS(unsigned int x, unsigned int y, const char *msg)
{
	glPushMatrix();
	int sw = glutStrokeLength(g_stroke_font, (const unsigned char*) msg);
	int sh = 0;
	for(unsigned int i=0;i<strlen(msg);i++)
	{
		int h = glutStrokeWidth(g_stroke_font, msg[i]);
		sh = (h>sh)? h: sh;
	}
	glTranslatef(x-sw*0.5, y-sh*0.5, 0);
	drawStringS(msg);
	glPopMatrix();
}

void drawStringCenteredB(unsigned int x, unsigned int y, const char *msg)
{
	int sw = glutBitmapLength(g_bitmap_font, (const unsigned char*) msg);
	int sh = 0;
	for(unsigned int i=0;i<strlen(msg);i++)
	{
		int h = glutBitmapWidth(g_bitmap_font, msg[i]);
		sh = (h>sh)? h: sh;
	}
	glRasterPos2f(x-sw*0.5, y-sh*0.5);
	drawStringB(msg);
}

void drawQuad(int x1, int y1, int x2, int y2)
{
	glBegin(GL_QUADS);
		glVertex2f(x1,y1);
		glVertex2f(x2,y1);
		glVertex2f(x2,y2);
		glVertex2f(x1,y2);
	glEnd();
}

void showSingleOutput(int origX, int origY, int w, int h)
{
	// Draw a green border around the display for some projectors
	// to latch on to!
	glColor3f(0,1,0);
	int border=20;
	drawQuad(origX         ,origY+0       ,origX+w     ,origY+border);
	drawQuad(origX+w-border,origY+0       ,origX+w     ,origY+h);
	drawQuad(origX+w       ,origY+h-border,origX+0     ,origY+h);
	drawQuad(origX         ,origY+h       ,origX+border,origY+0);
	glColor3f(1,1,1);

	drawStringCenteredB(origX+(w*0.5), origY+90, g_infoMessage[INFO_ROTATION].c_str());
	drawStringCenteredB(origX+(w*0.5), origY+130, g_infoMessage[INFO_STEREO].c_str());
	drawStringCenteredB(origX+(w*0.5), origY+400, g_infoMessage[INFO_X_SERVER].c_str());
	drawStringCenteredB(origX+(w*0.5), origY+360, g_infoMessage[INFO_XINERAMA].c_str());
	drawStringCenteredB(origX+(w*0.5), origY+320, g_infoMessage[INFO_GPU].c_str());
	drawStringCenteredB(origX+(w*0.5), origY+280, g_infoMessage[INFO_MODE].c_str());
	drawStringCenteredB(origX+(w*0.5), origY+240, g_infoMessage[INFO_DEVICE].c_str());
	drawStringCenteredB(origX+(w*0.5), origY+200, g_infoMessage[INFO_TD_COORDS].c_str());

	// We keep track of time. This program will probably be run on a machine
	// without keyboard/mouse input. Most likely in an automated manner. So
	// We count down on the time. 
	if(g_startTime<0)
		g_startTime = glutGet(GLUT_ELAPSED_TIME);

	char tstr[256];
	int timeElapsed =(glutGet(GLUT_ELAPSED_TIME)-g_startTime)/1000;
	int timeRemaining = (g_totalTime-timeElapsed);
	if ((timeRemaining)<=0)
	{
		exit(0);
	}
	sprintf(tstr, "This program will exit in %d more seconds", timeRemaining);
	drawStringCenteredB(origX+(w*0.5), origY+40, tstr);
}

void draw()
{
	int w = glutGet(GLUT_WINDOW_WIDTH);
	int h = glutGet(GLUT_WINDOW_HEIGHT);
	glMatrixMode(GL_PROJECTION);
	glLoadIdentity();
	glMatrixMode(GL_MODELVIEW);
	glLoadIdentity();
	gluOrtho2D(0, w, 0, h);

	showSingleOutput(0, 0, w, h);
	glutPostRedisplay();
}

void display()
{
	glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
	draw();
	glutSwapBuffers();
}

void keyboard(unsigned char key, int x, int y)
{
	if(key==27)
	{
		exit(0);
	}
}

int main(int argc, char** argv)
{
	for (unsigned int i=0;i<INFO_MAX-1;i++) // get one line per item from STDIN
	{
		char lineBuf[80];
		g_infoMessage[(infoType)i]=fgets(lineBuf, sizeof(lineBuf), stdin);
	}
#if 0
	g_infoMessage[INFO_X_SERVER] = "Host servergfx, X server :0, Screen 0"; 
	g_infoMessage[INFO_GPU] = "GPU 0 (Quadro FX 5800), Output 0";
	g_infoMessage[INFO_DEVICE] = "Display Device: LP2065";
	g_infoMessage[INFO_MODE] = "Display Mode: 640x480_60";
	g_infoMessage[INFO_TD_COORDS] = "Position on Tiled Display : (2560,1600)";
	g_infoMessage[INFO_STEREO] = "No Stereo"; 
	g_infoMessage[INFO_ROTATION] = "No display rotation"; 
	g_infoMessage[INFO_XINERAMA] = "Xinerama is enabled on this X server"; 
#endif

	glutInit(&argc, argv);
//	glutInitWindowSize(1280,800);
//	glutInitWindowPosition(0,0);
	glutInitDisplayMode(GLUT_RGBA | GLUT_DOUBLE);
	glutCreateWindow("vs-identify-display");
	glutKeyboardFunc(keyboard);
	glutDisplayFunc(display);
//	glutFullScreen();
	glutMainLoop();
	return 0;
}

