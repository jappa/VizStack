#include <stdio.h>
#include <X11/Xlib.h>
#include <GL/gl.h>
#include <GL/glx.h>
#include <unistd.h>
#include <stdlib.h>

// vs-get-limits.cpp 
// Helper program to print max framebuffer size

/*
 * Create an RGB, double-buffered window.
 * Return the window and context handles.
 */
static void
make_window( Display *dpy, const char *name,
             int x, int y, int width, int height,
             Window *winRet, GLXContext *ctxRet)
{
	int attrib[] = { GLX_RGBA,
		GLX_RED_SIZE, 1,
		GLX_GREEN_SIZE, 1,
		GLX_BLUE_SIZE, 1,
		GLX_DOUBLEBUFFER,
		GLX_DEPTH_SIZE, 1,
		None };
	int scrnum;
	XSetWindowAttributes attr;
	unsigned long mask;
	Window root;
	Window win;
	GLXContext ctx;
	XVisualInfo *visinfo;

	scrnum = DefaultScreen( dpy );
	root = RootWindow( dpy, scrnum );

	visinfo = glXChooseVisual( dpy, scrnum, attrib );
	if (!visinfo) {
		printf("Error: couldn't get an RGB, Double-buffered visual\n");
		exit(1);
	}

	/* window attributes */
	attr.background_pixel = 0;
	attr.border_pixel = 0;
	attr.colormap = XCreateColormap( dpy, root, visinfo->visual, AllocNone);
	attr.event_mask = StructureNotifyMask | ExposureMask | KeyPressMask;
	mask = CWBackPixel | CWBorderPixel | CWColormap | CWEventMask;

	win = XCreateWindow( dpy, root, 0, 0, width, height,
			0, visinfo->depth, InputOutput,
			visinfo->visual, mask, &attr );

	/* set hints and properties */
	{
		XSizeHints sizehints;
		sizehints.x = x;
		sizehints.y = y;
		sizehints.width  = width;
		sizehints.height = height;
		sizehints.flags = USSize | USPosition;
		XSetNormalHints(dpy, win, &sizehints);
		XSetStandardProperties(dpy, win, name, name,
				None, (char **)NULL, 0, &sizehints);
	}

	ctx = glXCreateContext( dpy, visinfo, NULL, True );
	if (!ctx) {
		printf("Error: glXCreateContext failed\n");
		exit(1);
	}

	XFree(visinfo);

	*winRet = win;
	*ctxRet = ctx;
}

int main(int argc, char**argv)
{
	Display *dpy;
	Window win;
	GLXContext ctx;

	dpy = XOpenDisplay(NULL);
	if (!dpy) {
		printf("Error: couldn't open display\n");
		return -1;
	}

	make_window(dpy, "NV swap lock test", 0, 0, 300, 300, &win, &ctx);
	XMapWindow(dpy, win);
	glXMakeCurrent(dpy, win, ctx);

	GLint maxVal;
	glGetIntegerv(GL_MAX_TEXTURE_SIZE, &maxVal);

	FILE *fp = stdout;
	if(argc==2)
	{
		fp=fopen(argv[1], "w");
		if(!fp)
		{
			perror("Unable to write output file");
			exit(-1);
		}
	}
	fprintf(fp, "%d %d\n", maxVal,maxVal);
	return 0;
}
