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
//
// vs-generate-xconfig.cpp
//
// X configuration file generator for VizStack
//

// Xerces includes
#include "vsdomparser.hpp"
#include "vscommon.h"
#include <string.h>
#include <stdlib.h>
#include <algorithm>
#include <fstream>
#include <iostream>

#include <map>
#include <vector>
#include <string>

using namespace std;

#include <glob.h>
#include <assert.h>

// Some default values
#define MIN_HSYNC "30.0"
#define MAX_HSYNC "130.0"
#define MIN_VREFRESH "50.0"
#define MAX_VREFRESH "150.0"

bool g_debugPrints=false;

int g_ssmSocket=-1;

vector<string> g_templatedir;

void Glob(std::string pathspec, std::vector<std::string>& matchingEntries)
{
        glob_t globbuf;

        if(glob(pathspec.c_str(), GLOB_TILDE, NULL, &globbuf)<0)
        {
        }

        for(unsigned int i=0;i<globbuf.gl_pathc;i++)
        {
                matchingEntries.push_back(globbuf.gl_pathv[i]);
        }
	globfree(&globbuf);
}

#define VALUE_UNSPECIFIED 0xffffffff

struct FBGPUScanout
{
	unsigned int x, y;
	unsigned int width, height;
	unsigned int portIndex;
	string type;
	string mode;
	string device;
};

struct FBGPUConfig
{
	unsigned int gpuIndex;
	vector<FBGPUScanout> scanout;
};

enum StereoMode { STEREO_NONE, ACTIVE_STEREO, PASSIVE_STEREO, STEREO_SEEREAL_DFP, STEREO_SHARP3D_DFP} ;
enum RotationType { ROTATE_NONE, ROTATE_PORTRAIT, ROTATE_INVERTED_PORTRAIT, ROTATE_INVERTED_LANDSCAPE };
enum SLIMode { SLI_AUTO, SLI_SFR, SLI_AFR, SLI_AA, SLI_MOSAIC} ;

struct SLI
{
	int index;
	bool isQuadroPlex;
	SLIMode mode;
	unsigned int gpu0, gpu1;
	unsigned int usageCount;

	SLI() { usageCount = 0; }
};

struct Framebuffer
{
	unsigned int index;
	unsigned int width, height, bpp;
	unsigned int posX, posY;
	StereoMode stereoMode;
	RotationType rotation;
	vector<SLI> sliBridge;
	vector<FBGPUConfig> gpuConfig;
};

struct DisplayMode
{
	string alias;
	unsigned int width;
	unsigned int height;
	float refreshRate;
	string value;
	string type;
};

#define EDID_BLOCK_SIZE 128
#define MAX_EDID_BLOCKS 20 // I don't know how many of these can exist; but this is good for validation

struct DisplayTemplate
{
	string name; // name of the device model - e.g., "HP LP2065"
	string input; // Default input type - analog or digital.
	bool hasEdid; // Does this display have an EDID ?
	string edidFile; // It yes, it's probably in this file.
	unsigned char edidBytes[EDID_BLOCK_SIZE*MAX_EDID_BLOCKS]; // If the filename is empty, then it's in this file
	unsigned int numEdidBytes; // and these many bytes are valid
	string hsyncRange[2], vrefreshRange[2];
	vector<DisplayMode> displayModes;
	string defaultDisplayMode;
};

struct OptVal
{
	string name;
	string value;
};

struct Keyboard
{
	int index; // this is the "index"th keyboard
	string type; // could be "DefaultKeyboard", etc
	string driver; // X driver to use for this keyboard
	string physAddr;
	vector<OptVal> optval; // options and values
	unsigned int usageCount;

	Keyboard() { usageCount = 0; }
};

struct Mouse
{
	int index; // this is the "index"th mouse
	string type; // could be "DefaultMouse", "ScrollMouse", etc
	string driver; // X driver to use for this mouse
	string physAddr;
	vector<OptVal> optval;
	unsigned int usageCount;
	Mouse() { usageCount = 0; }
};

struct IODevice
{
	string name; // name of device
	string templateFile; // name of the device template
	string type; // type of device
	string driver; // which driver to use
	vector<OptVal> optval; // options and values
};

struct GPUInfo // tracks usage of important GPU resources
{
	string busID;
	string modelName;
	string vendorName;
	bool allowScanOut;
	bool allowNoScanOut;
	unsigned int usageCount;
	vector < vector<string> > portOutputCaps;
	vector < unsigned int > portUsageCount;
	vector <FBGPUScanout> portScanout;
	unsigned int maxFramebufferWidth; // max width of framebuffer supported
	unsigned int maxFramebufferHeight;// max height of framebuffer supported
};

struct KernelDevice
{
	string name;
	string physicalAddress;
	string handler;
	bool isKeyboard;
};

bool getKernelDevices(vector<KernelDevice>& allDevs)
{
	allDevs.clear();

	FILE* fp=fopen("/proc/bus/input/devices","r");
	if(!fp)
	{
		return false;
	}

	KernelDevice currentDev;
	while(!feof(fp))
	{
		char lbuf[4096];
		char *line = fgets(lbuf, sizeof(lbuf), fp);
		if(line==0)
		{
			break;
		}

		if(strlen(line)==1)
		{
			// Empty line indicates end of info about this device
			if(g_debugPrints)
			{
				printf("keyboard=%d\n",currentDev.isKeyboard);
				printf("device='%s'\n",currentDev.physicalAddress.c_str());
				printf("handler='%s'\n",currentDev.handler.c_str());
				printf("\n");
			}
			// add all devices to the list, except "PC Speaker" !
			// Note that this will include the iLO virtual keyboard and mouse
			// on iLo enabled machines.
			if (currentDev.name != "PC Speaker")
				allDevs.push_back(currentDev);
		}
		else
		{
			// remove the trailing newline first
			int lastChar = strlen(line)-1;
			if(line[lastChar]=='\n')
				line[lastChar]=0;

			if(line[0]=='N')
			{
				// Line will be like
				//N: Name="PC Speaker"
				// or
				//N: Name="AT Translated Set 2 keyboard" 
				// we'll skip till the first double quote
				char *p=strchr(line,'"'); 
				// remote the ending double quote
				p[strlen(p)-1]=0;
				currentDev.name = p;
			}
			if(line[0]=='P')
			{
				// Line will be "P: Phys=isa0061/input0"
				char *p=strchr(line, '='); // skip till '='
				currentDev.physicalAddress = p+1;
			}
			if(line[0]=='H')
			{
				// Line will be "H: Handlers=mouse2 event7" for mice
				// or           "H: Handlers=kbd event0" for keyboards
				char *p=strchr(line, '='); // skip till '='
				p++;
				if(strncmp(p,"kbd",3)==0)
				{
					currentDev.isKeyboard = true;
				}
				else
				{
					currentDev.isKeyboard = false;
				}
				char *p2 = strchr(p,' ');
				p2++;
				if(currentDev.isKeyboard)
				{
					// Remove trailing whitespace. I've seen one.
					while(isspace(p2[strlen(p2)-1]))
						p2[strlen(p2)-1]=0;
					char handler[256];
					sprintf(handler,"/dev/input/%s",p2);
					currentDev.handler = handler;
				}
				else
				{
					*p2=0;
					// Remove trailing whitespace. I've seen one.
					while(isspace(p[strlen(p)-1]))
						p[strlen(p)-1]=0;
					char handler[256];
					sprintf(handler,"/dev/input/%s",p);
					currentDev.handler = handler;
				}
			}
		}
	}
	return true;
}

int getDisplay(const vector<DisplayTemplate>& validDisplayTemplates, string displayDevice, DisplayTemplate& dt)
{
	for(unsigned int i=0;i<validDisplayTemplates.size();i++)
	{
		if(validDisplayTemplates[i].name == displayDevice)
		{
			dt = validDisplayTemplates[i];
			return i;
		}
	}
	return -1;
}

bool setDisplay(vector<DisplayTemplate>& validDisplayTemplates, DisplayTemplate& dt)
{
	for(unsigned int i=0;i<validDisplayTemplates.size();i++)
	{
		if(validDisplayTemplates[i].name == dt.name)
		{
			validDisplayTemplates[i] =  dt;
			return true;
		}
	}
	validDisplayTemplates.push_back(dt);
	return false;
}

bool findDisplayMode(DisplayTemplate& dt, string mode, DisplayMode& dm)
{
	for(unsigned int i=0;i<dt.displayModes.size();i++)
	{
		if(dt.displayModes[i].alias==mode)
		{
			dm = dt.displayModes[i];
			return true;
		}
	}
	return false;
}

bool findDevice(const vector<IODevice>& ioDevices, string deviceName, IODevice& dev)
{
	for(unsigned int i=0;i<ioDevices.size();i++)
	{
		if(ioDevices[i].name == deviceName)
		{
			dev = ioDevices[i];
			return true;
		}
	}
	return false;
}


string convertScanoutType(const string& scanoutType)
{
	 // convert  input types to tokens that the nvidia driver understands
	if (scanoutType == "digital")
	{
		return "DFP";
	}
	else
	if (scanoutType == "analog")
	{
		return "CRT";
	}

	fprintf(stderr, "ERROR: Unknown type of display output signal specified '%s'. The valid values are 'analog' and 'digital'\n", scanoutType.c_str());
	exit(-1);
}

void generateXConfig(
	FILE* outFile,
	bool combineFB,
	vector<Framebuffer>& framebuffers,
	vector<GPUInfo>& gpuInfo,
	vector<string>& modulesToLoad,
	vector<OptVal>& extensionSectionOptions,
	vector<Keyboard>& usedKeyboards,
	vector<Mouse>& usedMice,
	const vector<DisplayTemplate>& validDisplayTemplates,
	vector<SLI>& usedSLIBridge)
{
	bool useStereo = false;

	fprintf(outFile, "Section \"Module\"\n");
	fprintf(outFile, "\tLoad \"dbe\"\n");
	fprintf(outFile, "\tLoad \"extmod\"\n");
	fprintf(outFile, "\tLoad \"type1\"\n");
	fprintf(outFile, "\tLoad \"freetype\"\n");
	fprintf(outFile, "\tLoad \"glx\"\n");
	for(unsigned int i=0;i<modulesToLoad.size();i++)
	{
		fprintf(outFile, "\tLoad \"%s\"\n",modulesToLoad[i].c_str());
	}
	fprintf(outFile, "EndSection\n");

	// create a device section for all framebuffers
	// This is needed to handle the case where the same device gets used in multiple framebuffers.
	// Doing this generically (and always) avoids any special casing we may need to do.

	//
	// FIXME: I've found what could be an issue with nvidia drivers.
	// If there is one scanout being driven by a GPU, I could configure one virtual X screen
	// If both scanouts were being driven, then no virtual screens could be driven.
	// If no scanouts were driven, then I could run upto 6 virtual X screens.
	//
	// I may need to enforce this check till it goes away.
	//
	for(unsigned int i=0;i<framebuffers.size();i++)
	{
		unsigned int fbIndex = framebuffers[i].index;
		unsigned int gpuIndex = framebuffers[i].gpuConfig[0].gpuIndex;

		GPUInfo &thisGPU = gpuInfo[gpuIndex];

		fprintf(outFile, "Section \"Device\"\n");
		fprintf(outFile, "\tIdentifier \"gpu-screen%d\"\n",fbIndex);
		fprintf(outFile, "\tDriver \"nvidia\"\n");
		fprintf(outFile, "\tVendorName \"%s\"\n", thisGPU.vendorName.c_str());
		fprintf(outFile, "\tBoardName \"%s\"\n", thisGPU.modelName.c_str());
		if (thisGPU.busID.size()>0)
		{
			fprintf(outFile, "\tBusID \"%s\"\n", thisGPU.busID.c_str());
		}
		fprintf(outFile, "\tOption \"ProbeAllGpus\" \"False\"\n");

		// TODO: I've found bugs with versions of drivers when using this.
		// If you use two screens per GPU, then the driver just throws up
		// problems. If you use one screen per GPU, then things seem fine
		// Behaviour seen in nvidia driver 177.70.35
		// I used an ML370 with two QP 2200 D2s for this. I configure
		// 8 dummy LP3065 devices. A 4 screen configuration works if the 
		// "screen" value is not specified.  If the "Screen" value is specified
		// then the server comes up with 1 screen.
		// An 8 screen configuration does not work at all.
		//
		// Conclusion : don't use "Screen" if the GPU is not used to drive
		// multiple screens.
		//
		if (thisGPU.usageCount>1)
		{
			fprintf(outFile, "\tScreen %d\n",fbIndex);
		}

		// Include ConnectedMonitor, CustomEDID and RefreshRate directives here
		//
		// FIXME: possible nvidia driver bug. Why is this done ??
		// the nvidia driver doesn't work if there are multiple screen
		// sections refering to the same device with conflicting values of thes
		// properties. This is probably a bug in the nvidia driver.
		//
		// So we consolidate the value of all these properties and push them into
		// the device section. This results in a duplication of these values in
		// multiple device sections, but that's not a problem.
		string connectedMonitor;
		string customEDIDs;
		string modeValidation;
		string horizSyncRange, vertRefreshRange;

		for(unsigned int j=0;j<thisGPU.portScanout.size();j++)
		{
			// ignore this port if it is not being used
			if(thisGPU.portUsageCount[j]==0)
				continue;

			FBGPUScanout &scanout = thisGPU.portScanout[j];

			// get the template for this display
			DisplayTemplate dt;
			if(getDisplay(validDisplayTemplates, scanout.device, dt)<0)
			{
				// This simply cannot happen !
				// the display device is supposed to be validated first -- so we shouldn't land in this situation
				// ever !
				std::cerr << "Unknown display device '" << scanout.device <<"'" << std::endl;
				return;
			}

			DisplayMode dm;
			if(!findDisplayMode(dt, scanout.mode, dm))
			{
				cerr << "Unknown display mode '" << scanout.mode <<"'" << endl;
				return; // XXX: Can't happen since tis was supposed to be validated earlier
			}

			// Add this display device to the usage list
			char dd[256];
			string scanoutType = convertScanoutType(scanout.type); // convert signal type to those understood by the nVidia driver
			sprintf(dd, "%s-%d", scanoutType.c_str(), scanout.portIndex);
			if(j==0)
				connectedMonitor = dd;
			else
				connectedMonitor = connectedMonitor + "," + dd;

			// If digital output & refresh rate is greater than 60 Hz, then
			// we need to use
			// Option "ModeValidation" "AllowNon60HzDFPModes"
			if((dm.refreshRate>60.0) && (scanout.type=="digital"))
			{
				modeValidation += dd;
				modeValidation = ":";
				modeValidation = " AllowNon60HzDFPModes;";
			}

			// If an EDID file is specified for the device, then use it
			if(dt.edidFile.size()!=0)
			{
				string edid;
				edid = dd;
				edid = edid + ":" ;
				edid = edid + dt.edidFile;

				if(j==0)
				{
					customEDIDs = edid;
				}
				else
				{
					customEDIDs = customEDIDs + ";" +edid;
				}
			}
			else
			{
				// Add the monitor parameters information
				char range[256];
				sprintf(range, "%s: %s-%s", dd, dt.hsyncRange[0].c_str(), dt.hsyncRange[1].c_str());
				if(j==0)
					horizSyncRange = range;
				else
					horizSyncRange = horizSyncRange + "; " + range;

				if(dt.vrefreshRange[0]!=dt.vrefreshRange[1])
					sprintf(range, "%s: %s-%s", dd, dt.vrefreshRange[0].c_str(), dt.vrefreshRange[1].c_str());
				else
					sprintf(range, "%s: %s", dd, dt.vrefreshRange[0].c_str());

				if(j==0)
					vertRefreshRange = range;
				else
					vertRefreshRange = vertRefreshRange + "; " + range;
			}
		}

		// Some drivers seem to have problems parsing this :-(
		// FIXME: this is currently handled by having a generic, all-encompassing monitor
		if(horizSyncRange.size()>0)
			fprintf(outFile, "\tOption \"HorizSync\" \"%s\"\n", horizSyncRange.c_str());
		if(vertRefreshRange.size()>0)
			fprintf(outFile, "\tOption \"VertRefresh\" \"%s\"\n", vertRefreshRange.c_str());

		// FIXME: The ConnectedMonitor override is necessary only if there is no direct connection.
		// If there is a direct connection, then there is no need to use it. Also, not using this
		// may be a good way to validate if what was connected is indeed what was detected !
		if(connectedMonitor.size()>0)
			fprintf(outFile, "\tOption \"ConnectedMonitor\" \"%s\"\n",connectedMonitor.c_str());

		// If an EDID file is specified for the device, then use it
		if(customEDIDs.size()>0)
			fprintf(outFile, "\tOption \"CustomEDID\" \"%s\"\n", customEDIDs.c_str());

		// Apply any mode validation relaxations!
		if(modeValidation.size()>0)
			fprintf(outFile, "\tOptin \"ModeValidation\" \"%s\"\n", modeValidation.c_str());
		fprintf(outFile, "EndSection\n");
	}

	map<string , string> usedModeLines; // dictionary to keep a mapping of modeline names to modeline params

	// create a screen section for each framebuffer
	for(unsigned int i=0;i<framebuffers.size();i++)
	{
		Framebuffer &fb = framebuffers[i];
		fprintf(outFile, "Section \"Screen\"\n");
		fprintf(outFile, "\tIdentifier \"screen%d\"\n", fb.index);
		fprintf(outFile, "\tMonitor    \"combinedMonitor\"\n");
		fprintf(outFile, "\tDevice \"gpu-screen%d\"\n", fb.index);

		switch(fb.stereoMode)
		{
			default:
				assert("Unhandled stereo mode!");
			case STEREO_NONE:
				break;
			case ACTIVE_STEREO:
				fprintf(outFile, "\tOption \"Stereo\" \"3\"\n");
				// FIXME: detect that we're actually using a DFP and then add the below line.
				fprintf(outFile, "\tOption \"AllowDFPStereo\" \"True\"\n"); // nVidia Driver by default does not allow Active Stereo on DFPs. We need to add this to make it possible. DVI projectors like Sony's probably need this.
				useStereo = true;
				break;
			case PASSIVE_STEREO:
				fprintf(outFile, "\tOption \"Stereo\" \"4\"\n");
				useStereo = true;
				break;
			case STEREO_SEEREAL_DFP:
				fprintf(outFile, "\tOption \"Stereo\" \"5\"\n");
				useStereo = true;
				break;
			case STEREO_SHARP3D_DFP:
				fprintf(outFile, "\tOption \"Stereo\" \"6\"\n");
				useStereo = true;
				break;
		}

		bool sliMosaicMode = false;
		if (fb.sliBridge.size()==1)
		{
			const char *sliMode=0;
			switch(fb.sliBridge[0].mode)
			{
				default:
					assert("Invalid SLI mode");
				case SLI_AUTO:
					sliMode = "auto";
					break;
				case SLI_SFR:
					sliMode = "SFR";
					break;
				case SLI_AFR:
					sliMode = "AFR";
					break;
				case SLI_AA:
					sliMode = "AA";
					break;
				case SLI_MOSAIC:
					sliMode = "mosaic";
					sliMosaicMode = true;
					break;
			}
			fprintf(outFile, "\tOption \"SLI\" \"%s\"\n", sliMode);
		}

		// Handle display rotation
		// FIXME: Rotation is incompatible with overlays. Handle this later.
		switch(fb.rotation)
		{
			default:
				assert("Unhandled rotation mode!");
			case ROTATE_NONE:
				break;
			case ROTATE_PORTRAIT:
				fprintf(outFile, "\tOption \"Rotate\" \"left\"\n");
				break;
			case ROTATE_INVERTED_PORTRAIT:
				fprintf(outFile, "\tOption \"Rotate\" \"right\"\n");
				break;
			case ROTATE_INVERTED_LANDSCAPE:
				fprintf(outFile, "\tOption \"Rotate\" \"inverted\"\n");
				break;
		}

		// 1 GPU and no scanout ? Present a virtual frambuffer
		if(fb.gpuConfig[0].scanout.size()==0)
		{
			fprintf(outFile, "\tOption \"UseDisplayDevice\" \"None\"\n");
			fprintf(outFile, "\tSubSection \"Display\"\n");
			fprintf(outFile, "\t\tDepth %d\n",fb.bpp);
			fprintf(outFile, "\t\tVirtual %d %d\n",fb.width,fb.height);
			fprintf(outFile, "\tEndSubSection\n");
		}
		else
		{
			string useDisplayDevice;
			string metamodes;

			for(int k=0;k<fb.gpuConfig.size();k++)
			{
				FBGPUConfig& gpuConfig = fb.gpuConfig[k];

				// If more than one scanouts, then we need TwinView
				// but only if SLI is not enabled
				if((gpuConfig.scanout.size()>1) && (fb.sliBridge.size()==0))
				{
					fprintf(outFile, "\tOption \"TwinView\"\n"); 
				}
				for(unsigned int j=0;j<gpuConfig.scanout.size();j++)
				{
					FBGPUScanout &scanout = gpuConfig.scanout[j];

					// get the template for this display
					DisplayTemplate dt;
					if(getDisplay(validDisplayTemplates, scanout.device, dt)<0)
					{
						// This simply cannot happen !
						// the display device is supposed to be validated first -- so we shouldn't land in this situation
						// ever !
						std::cerr << "Unknown display device '" << scanout.device <<"'" << std::endl;
						return;
					}

					DisplayMode dm;
					if(!findDisplayMode(dt, scanout.mode, dm))
					{
						cerr << "Unknown display mode '" << scanout.mode <<"'" << endl;
						return; // XXX: Can't happen since tis was supposed to be validated earlier
					}

					// Add this display device to the usage list
					char dd[256];
					string scanoutType = convertScanoutType(scanout.type); // convert signal type to those understood by the nVidia driver
					sprintf(dd, "%s-%d", scanoutType.c_str(), scanout.portIndex);

					if(k==0) // add to "useDisplayDevice" only for the first GPU
					{
						if(useDisplayDevice.size()==0)
							useDisplayDevice = dd;
						else
							useDisplayDevice = useDisplayDevice + "," + dd;
					}

					string usedMode;
					if(dm.type=="modeline")
					{
						usedMode = dt.name + "_" + dm.alias;
						usedModeLines[usedMode] = dm.value; // add this as a modeline
					}
					else
					{
						// NOTE: nvidia specific mapping of width,height,refreshrate to
						// WidthxHeight_Refresh
						// NOTE: EDIDs don't have provisions for fractional refresh rates, so we convert
						// to integer
						char mappedMode[4096];
						sprintf(mappedMode,"%dx%d_%d", dm.width, dm.height, (int)dm.refreshRate);
						usedMode = mappedMode;
					}

					// Add the metamode for this scanout
					char mm[256];
					char panningDomain[256];
//					if((scanout.width==dm.width) && (scanout.height==dm.height))
//						strcpy(panningDomain,"");
//					else
					sprintf(panningDomain, "@%dx%d ", scanout.width, scanout.height);
					if(!sliMosaicMode)
					{
						sprintf(mm, "%s: %s %s+%d+%d", dd, usedMode.c_str(), panningDomain, scanout.x, scanout.y);
					}
					else
					{
						// Don't include the device when generating metamodes for SLI mosaic mode.
						sprintf(mm, "%s %s +%d+%d", usedMode.c_str(), panningDomain, scanout.x, scanout.y);
					}
					if(metamodes.size()==0)
						metamodes = mm ;
					else
						metamodes = metamodes + "," + mm;

				}
			}

			if(useDisplayDevice.size()>0)
				fprintf(outFile, "\tOption \"UseDisplayDevice\" \"%s\"\n",useDisplayDevice.c_str());

			fprintf(outFile, "\tOption \"MetaModes\" \"%s\"\n", metamodes.c_str());

			fprintf(outFile, "\tSubSection \"Display\"\n");
			fprintf(outFile, "\t\tDepth %d\n",fb.bpp);
			// NOTE: Use the "virtual" directive here. The MetaModes will
			// take care of configuring the display devices. Using Virtual
			// ensures that we can pan around a mode much larger than the
			// display mode. 
			fprintf(outFile, "\t\tVirtual %d %d\n",fb.width,fb.height);
			fprintf(outFile, "\tEndSubSection\n");

			// DESIGN DECISION: Don't include all validated modes in the mode pool
			// this will enforce the rule that modes don't get changed at runtime.
			// Note that the user can still potentially use NV-CONTROL to change
			// all these properties, but we are just trying to do the best we can
			// for an out-of-the-box setup. Letting the user switch modes will have
			// all sorts of problems, including disabling framelock when the mode
			// switch happens.
			fprintf(outFile, "\tOption \"IncludeImplicitMetaModes\" \"False\"\n");

			// DESIGN DECISION: When TwinView is enabled, ensure that the the nvidia
			// driver does not convey Xinerama information to the X server. We don't
			// use directives like LeftOf, RightOf, etc to convey positioning information
			// to the nvidia driver, instead relying on rectangular coordinates. 
			// This helps use get a "spanning" configuration without much trouble,
			// and additional configuration needed. Not disabling this confuses window
			// managers like MetaCity.
			//
			// If the user wants separate screens, they can always configure things that
			// way.
			if((fb.gpuConfig[0].scanout.size()>1)&&(fb.sliBridge.size()==1))
			{
				fprintf(outFile, "\tOption \"NoTwinViewXineramaInfo\" \"True\"\n");
			}
		}
		fprintf(outFile, "EndSection\n");
	}

	// include IO device definitions
	if(usedKeyboards.size()==0)
	{
		Keyboard kbd;
		kbd.type = "NullKeyboard";
		kbd.driver = "void";
		usedKeyboards.push_back(kbd);
	}

	if(usedMice.size()==0)
	{
		Mouse mouse;
		mouse.type = "NullMouse";
		mouse.driver = "void";
		usedMice.push_back(mouse);
	}

	for(unsigned int i=0;i<usedKeyboards.size();i++)
	{
		Keyboard &thisKbd = usedKeyboards[i];
		fprintf(outFile, "Section \"InputDevice\"\n");
		fprintf(outFile, "\tIdentifier \"%s_%d\"\n", thisKbd.type.c_str(),i);
		fprintf(outFile, "\tDriver \"%s\"\n",thisKbd.driver.c_str());
		for(unsigned int j=0;j<thisKbd.optval.size();j++)
		{
			OptVal &ov = thisKbd.optval[j];
			fprintf(outFile, "\tOption \"%s\" \"%s\"\n", ov.name.c_str(), ov.value.c_str());
		}
		if(i>0)
		{
			fprintf(outFile, "\tOption \"SendCoreEvents\" \"True\"\n");
		}
		fprintf(outFile, "EndSection\n");
	}

	for(unsigned int i=0;i<usedMice.size();i++)
	{
		Mouse &thisMouse = usedMice[i];
		fprintf(outFile, "Section \"InputDevice\"\n");
		fprintf(outFile, "\tIdentifier \"%s_%d\"\n", thisMouse.type.c_str(),i);
		fprintf(outFile, "\tDriver \"%s\"\n",thisMouse.driver.c_str());
		for(unsigned int j=0;j<thisMouse.optval.size();j++)
		{
			OptVal &ov = thisMouse.optval[j];
			fprintf(outFile, "\tOption \"%s\" \"%s\"\n", ov.name.c_str(), ov.value.c_str());
		}
		if(i>0)
		{
			fprintf(outFile, "\tOption \"SendCoreEvents\" \"True\"\n");
		}
		fprintf(outFile, "EndSection\n");
	}

	fprintf(outFile, "Section \"Monitor\"\n");
	fprintf(outFile, "\tIdentifier \"combinedMonitor\"\n");
	fprintf(outFile, "\tHorizSync %s - %s\n", MIN_HSYNC, MAX_HSYNC);
	fprintf(outFile, "\tVertRefresh %s - %s\n", MIN_VREFRESH, MAX_VREFRESH);
	// add all referenced modelines here
	for(map<string, string>::iterator pModeLine = usedModeLines.begin(); pModeLine!=usedModeLines.end(); pModeLine++)
	{
		fprintf(outFile, "\tModeLine \"%s\" %s\n", pModeLine->first.c_str(), pModeLine->second.c_str());
	}
	fprintf(outFile, "EndSection\n");

	fprintf(outFile, "Section \"Extensions\"\n");
	for(unsigned int i=0;i<extensionSectionOptions.size();i++)
	{
		OptVal &ov=extensionSectionOptions[i];
		fprintf(outFile, "\tOption \"%s\" \"%s\"\n", ov.name.c_str(), ov.value.c_str());
	}
	fprintf(outFile, "EndSection\n");

	// Finally, create the ServerLayout containing everything
	fprintf(outFile, "Section \"ServerLayout\"\n");
	fprintf(outFile, "\tIdentifier \"DefaultLayout\"\n");
	for(unsigned int i=0;i<framebuffers.size();i++)
	{
		unsigned int fbIndex = framebuffers[i].index;
		fprintf(outFile, "\tScreen %d \"screen%d\"", fbIndex, fbIndex);
		// FIXME: we treat unspecification of one or both values as unspecification.
		if((framebuffers[i].posX != VALUE_UNSPECIFIED) && (framebuffers[i].posY != VALUE_UNSPECIFIED))
			fprintf(outFile, " %d %d", framebuffers[i].posX, framebuffers[i].posY);
		fprintf(outFile, "\n");
	}
	fprintf(outFile, "\tInputDevice \"%s_0\" \"CoreKeyboard\"\n", usedKeyboards[0].type.c_str());
	fprintf(outFile, "\tInputDevice \"%s_0\" \"CorePointer\"\n", usedMice[0].type.c_str());
	fprintf(outFile, "EndSection\n");

	fprintf(outFile, "Section \"ServerFlags\"\n");
	// We enable AllowMouseOpenFail always. Else X server may crash if ther is no real mouse connected
	if(usedMice.size()>0)
	{
		fprintf(outFile, "\tOption \"AllowMouseOpenFail\" \"True\"\n");
	}
	// Possible options that we may be interested in:
	if(combineFB)
	{
		fprintf(outFile, "\tOption \"Xinerama\" \"True\"\n");
	}
	// fprintf("\tOption \"DontVTSwitch\" \"True\"\n");
	// fprintf("\tOption \"DontZap\" \"True\"\n"); // disable CTRL-ALT-Backspace
	// fprintf("\tOption \"DontZoom\" \"True\"\n"); // disable Mode Switches
	fprintf(outFile, "EndSection\n");
}

bool extractXMLData(
	VSDOMNode root, 
	bool& combineFB, 
	vector<Framebuffer>& framebuffers,
	vector<GPUInfo>& gpuInfo,
	vector<string>& modulesToLoad,
	vector<OptVal>& extensionSectionOptions,
	vector<Keyboard>& usedKeyboards,
	vector<Mouse>& usedMice,
	const vector<DisplayTemplate>& validDisplayTemplates,
	vector<DisplayTemplate>& usedDisplayTemplates,
	vector<Keyboard>& validKeyboards,
	vector<Mouse>& validMice,
	vector<OptVal> &cmdArgVal,
	vector<SLI>& sliBridges,
	vector<SLI>& usedSLIBridge)
{
	VSDOMNode child;
	vector<unsigned int> usedDisplayIndex;

	bool configUsesStereo = false;

	framebuffers.clear();
	modulesToLoad.clear();
	extensionSectionOptions.clear();
	usedKeyboards.clear();
	usedMice.clear();
	usedSLIBridge.clear();

	if(root.isEmpty())
	{
		cerr << "No root node passed ! Nothing to do" << endl;
		return false;
	}

	// Check root node
	if((root.getNodeName())!="server")
	{
		cerr << "Improper Root node '" << root.getNodeName() <<"'" << endl;
		return false;
	}

	vector<VSDOMNode> cmdArgNodes = root.getChildNodes("x_cmdline_arg");
	for(unsigned int i=0;i<cmdArgNodes.size();i++)
	{
		OptVal ov;
		ov.name = cmdArgNodes[i].getChildNode("name").getValueAsString();
		VSDOMNode valNode = cmdArgNodes[i].getChildNode("value");
		if(!valNode.isEmpty())
			ov.value = valNode.getValueAsString();
		
		cmdArgVal.push_back(ov);
	}

	// Get the list of X modules to load
	vector<VSDOMNode> moduleNodes = root.getChildNodes("x_module");
	for(unsigned int i=0;i<moduleNodes.size();i++)
	{
		string modName = moduleNodes[i].getValueAsString();
		modulesToLoad.push_back(modName);
	}

	// Get the list of extension section options, and their values
	vector<VSDOMNode> optvalNodes = root.getChildNodes("x_extension_section_option");
	for(unsigned int i=0;i<optvalNodes.size();i++)
	{
		OptVal ov;
		ov.name = optvalNodes[i].getChildNode("name").getValueAsString();
		ov.value = optvalNodes[i].getChildNode("value").getValueAsString();
		extensionSectionOptions.push_back(ov);
	}

	// Get the input devices being used
	vector<VSDOMNode> keyboardNodes = root.getChildNodes("keyboard");
	for(unsigned int i=0;i<keyboardNodes.size();i++)
	{
		VSDOMNode keyboardNode = keyboardNodes[i];
		unsigned int kbdIndex = keyboardNode.getChildNode("index").getValueAsInt();
		if (kbdIndex>=validKeyboards.size())
		{
			cerr << "Out-of-range keyboard index "<<kbdIndex << " used." << endl;
			return false;
		}
		if(validKeyboards[kbdIndex].usageCount==0)
		{
			usedKeyboards.push_back(validKeyboards[kbdIndex]);
			validKeyboards[kbdIndex].usageCount++;
		}
		else
		{
			cerr << "Keyboard index "<<kbdIndex<< " used more than once." << endl;
			return false;
		}
	}

	vector <VSDOMNode> mouseNodes = root.getChildNodes( "mouse");
	for(unsigned int i=0;i<mouseNodes.size();i++)
	{
		VSDOMNode mouseNode = mouseNodes[i];
		unsigned int mouseIndex = mouseNode.getChildNode("index").getValueAsInt();
		if (mouseIndex>=validMice.size())
		{
			cerr << "Out-of-range mouse index "<<mouseIndex << " used." << endl;
			return false;
		}
		if(validMice[mouseIndex].usageCount==0)
		{
			usedMice.push_back(validMice[mouseIndex]);
			validMice[mouseIndex].usageCount++;
		}
		else
		{
			cerr << "Mouse index "<<mouseIndex<< " used more than once." << endl;
			return false;
		}
	}

	vector<VSDOMNode> framebufferNodes = root.getChildNodes("framebuffer");
	if(framebufferNodes.size()==0)
	{
		cerr << "X server has no framebuffers(Screens) associated with it. This is not a valid X server configuration." << endl;
		return false;
	}
	for(unsigned int i=0;i<framebufferNodes.size();i++)
	{
		VSDOMNode fbNode = framebufferNodes[i];

		Framebuffer fb;

		fb.posX = VALUE_UNSPECIFIED;
		fb.posY = VALUE_UNSPECIFIED;
		fb.width = VALUE_UNSPECIFIED;
		fb.height = VALUE_UNSPECIFIED;
		fb.bpp = 24;
		fb.stereoMode = STEREO_NONE;
		fb.rotation = ROTATE_NONE;

		// FIXME -- We REALLY need to ensure that the framebuffer (i.e. screen) numbers are in sequences ??
		fb.index = fbNode.getChildNode("index").getValueAsInt();

		VSDOMNode propertyNode = fbNode.getChildNode("properties");
		if(!propertyNode.isEmpty())
		{
			VSDOMNode propNode;

			// Get the position relative to the other framebuffers
			propNode = propertyNode.getChildNode("x");
			if(!propNode.isEmpty())
				fb.posX = propNode.getValueAsInt();

			propNode = propertyNode.getChildNode( "y");
			if(!propNode.isEmpty())
				fb.posY = propNode.getValueAsInt();

			propNode = propertyNode.getChildNode("width");
			if(!propNode.isEmpty())
				fb.width = propNode.getValueAsInt();

			propNode = propertyNode.getChildNode( "height");
			if(!propNode.isEmpty())
				fb.height = propNode.getValueAsInt();

			propNode = propertyNode.getChildNode( "bpp");
			if(!propNode.isEmpty())
				fb.bpp = propNode.getValueAsInt();

			propNode = propertyNode.getChildNode( "stereo");
			if(!propNode.isEmpty())
			{
				string val = propNode.getValueAsString();
				if(val=="none")
					fb.stereoMode = STEREO_NONE;
				else
				if(val=="active")
					fb.stereoMode = ACTIVE_STEREO;
				else
				if(val=="passive")
					fb.stereoMode = PASSIVE_STEREO;
				else
				if(val=="SeeReal_stereo_dfp")
					fb.stereoMode = STEREO_SEEREAL_DFP;
				else
				if(val=="Sharp3D_stereo_dfp")
					fb.stereoMode = STEREO_SHARP3D_DFP;
				else
				{
					// NOTE: the schema should ensure we never come here
					// but just in case it doesn't...
					cerr << "Invalid stereo mode specified '"<<val<<"'"<<endl;
					return false;
				}
			}

			propNode = propertyNode.getChildNode( "rotate");
			if(!propNode.isEmpty())
			{
				string val = propNode.getValueAsString();
				if(val=="none")
					fb.rotation = ROTATE_NONE;
				else
				if(val=="portrait")
					fb.rotation = ROTATE_PORTRAIT;
				else
				if(val=="inverted_portrait")
					fb.rotation = ROTATE_INVERTED_PORTRAIT;
				else
				if(val=="inverted_landscape")
					fb.rotation = ROTATE_INVERTED_LANDSCAPE;
				else
				{
					// NOTE: the schema should ensure we never come here
					// but just in case it doesn't...
					cerr << "Invalid rotation mode specified '"<<val<<"'"<<endl;
					return false;
				}
			}
		}

		vector<VSDOMNode> gpuNodes = fbNode.getChildNodes("gpu");
		bool hasScanout = false;
		for(unsigned int k=0;k<gpuNodes.size(); k++)
		{
			VSDOMNode gpuNode = gpuNodes[k];
			FBGPUConfig gpu;
			//
			// FIXME: should we take the rest of the GPU properties
			// i.e. type, bus ID and match them after index ?
			// 
			gpu.gpuIndex = gpuNode.getChildNode("index").getValueAsInt();

			// check validity of GPU
			if (gpu.gpuIndex>=gpuInfo.size())
			{
				cerr << "Invalid GPU specified with index = "<<gpu.gpuIndex<<endl;
				return false;
			}

			GPUInfo &thisGPU = gpuInfo[gpu.gpuIndex];
			thisGPU.usageCount++; //increment usage count for this GPU

			vector<VSDOMNode> scanoutList = gpuNode.getChildNodes("scanout");

			if (scanoutList.size()==0)
			{
				// Stereo is disallowed if you have no scanouts.
				if (fb.stereoMode != STEREO_NONE)
				{
					cerr << "To use stereo modes, you must connect this GPU to displays! (i.e. define scanouts)" << endl;
					return false; 
				}

				// Must specify width and height both if no scanouts
				// Restriction applies only on the first GPU in case a combiner is being used
				if (((fb.width == VALUE_UNSPECIFIED) || (fb.height == VALUE_UNSPECIFIED))&&(k==0))
				{
					cerr << "If you have no scanouts, they you must define a complete (width,height) value for the framebuffer dimensions." << endl;
					return false; 
				}
			}
			else
			{
				hasScanout = true;
				// scanouts are defined, so ensure that the GPU is configured to allow scanouts
				if (thisGPU.allowScanOut==false)
				{
					cerr << "This GPU has been configured to disallow scanouts. So you can't configure Scanouts on it." << endl;
					return false; 
				}
			}


			for(unsigned int j=0;j<scanoutList.size();j++)
			{
				VSDOMNode thisScanout = scanoutList[j];
				unsigned int portIndex = thisScanout.getChildNode("port_index").getValueAsInt();

				if(portIndex>=thisGPU.portUsageCount.size())
				{
					cerr << "Invalid port index "<<portIndex<< endl;
					return false;
				}

				// no port can be used more than once in the same X server
				if(thisGPU.portUsageCount[portIndex]!=0)
				{
					cerr << "Attempt to use port "<< portIndex << " more than once" << endl;
					return false;
				}

				string displayDevice = thisScanout.getChildNode("display_device").getValueAsString();

				// get information for this display device
				DisplayTemplate dt;
				unsigned int thisDisplayIndex = getDisplay(validDisplayTemplates, displayDevice, dt);
				if(thisDisplayIndex<0)
				{
					cerr << "Unknown display device '" << displayDevice <<"'" << endl;
					return false;
				}

				if (find(usedDisplayIndex.begin(), usedDisplayIndex.end(), thisDisplayIndex)==usedDisplayIndex.end())
				{
					usedDisplayIndex.push_back(thisDisplayIndex);
					usedDisplayTemplates.push_back(dt);
				}

				// Get the type of display device
				VSDOMNode scanoutPortTypeNode = thisScanout.getChildNode("type");
				string portType;
				if(!scanoutPortTypeNode.isEmpty())
				{
					// get the type from the input
					portType = scanoutPortTypeNode.getValueAsString();
					// NOTE: we don't validate this, since it's supposed to be have come here after
					// passing the schema check!
				}
				else 
				{
					// use the default input type of the display if not
					// specified. This simplifies the upper layers.
					portType = dt.input;
				}

				// get the display mode requested. If a mode is not requested, then
				// use the default of the display device
				string mode;
				VSDOMNode modeNode = thisScanout.getChildNode("mode");
				if(!modeNode.isEmpty())
				{
					mode = modeNode.getValueAsString();
				}
				else
				{
					mode = dt.defaultDisplayMode;
				}

				// check if this mode is valid for this display device
				DisplayMode dm;
				if(!findDisplayMode(dt, mode, dm))
				{
					cerr << "Unknown display mode '" << mode <<"'" << endl;
					return false;
				}

				if((fb.width!=VALUE_UNSPECIFIED) && (dm.width>fb.width))
				{
					cerr << "Display mode '"<< mode <<"' width is larger than the framebuffer" << endl;
					return false;
				}

				if((fb.height!=VALUE_UNSPECIFIED) && (dm.height>fb.height))
				{
					cerr << "Display mode '"<< mode <<"' height is larger than the framebuffer" << endl;
					return false;
				}

				unsigned int areaX, areaY, areaWidth, areaHeight;
				VSDOMNode areaNode = thisScanout.getChildNode( "area");
				// if a scanout area is defined, then use that.
				if(!areaNode.isEmpty())
				{
					areaX=areaNode.getChildNode("x").getValueAsInt();
					areaY=areaNode.getChildNode("y").getValueAsInt();
					VSDOMNode propNode = areaNode.getChildNode("width");
					if(!propNode.isEmpty())
						areaWidth = propNode.getValueAsInt();
					else
						areaWidth = dm.width;
					propNode = areaNode.getChildNode("height");
					if(!propNode.isEmpty())
						areaHeight = propNode.getValueAsInt();
					else
						areaHeight = dm.height;


					if(areaWidth<dm.width)
					{
						cerr << "Area width cannot be less than scaanout width!" << endl;
						return false;
					}
					if(areaHeight<dm.height)
					{
						cerr << "Area height cannot be less than scaanout height!" << endl;
						return false;
					}
				}
				else
					// scanout the whole area corresponding to the mode. Note that this may still be a subsection of the
					// framebuffer
				{

					areaX = areaY = 0;
					areaWidth = dm.width;
					areaHeight = dm.height;
				}

				FBGPUScanout scanout;
				scanout.portIndex = portIndex;
				scanout.type = portType;
				scanout.x = areaX;
				scanout.y = areaY;
				scanout.width = areaWidth;
				scanout.height = areaHeight;
				scanout.mode = mode;
				scanout.device = displayDevice;
				gpu.scanout.push_back(scanout);

				// update the current configuration of the GPU
				thisGPU.portUsageCount[portIndex]=1;
				thisGPU.portScanout[portIndex]=scanout;
			}

			// Stereo support does not work with the composite extension
			// so we will specifically check that the user is not trying
			// to enable the composite extension
			if (fb.stereoMode != STEREO_NONE)
			{
				configUsesStereo = true;

				for(unsigned int i=0;i<extensionSectionOptions.size();i++)
				{
					OptVal &ov = extensionSectionOptions[i];
					if (strcmp(ov.name.c_str(),"Composite")==0) //X specification says case insensitive comparison, but that doesn't work in practise
					{
						if(strcasecmp(ov.value.c_str(),"Enable")==0)
						{
							cerr << "Stereo is not supported with the Composite Extension" << endl;
							return false;
						}
					}
				}
			}

			// The FX 5800, 4800, 3800 & 1800 have _three_ ports, but only two of them
			// may be active at a time
			if (gpu.scanout.size() > 2)
			{
				cerr << "No more than two scanouts may be configured per GPU." << endl;
				return false;
			}

			// if stereo mode is enabled, then extra checks are needed
			//
			// 1. Active Stereo with "TwinView" is supported only if the modes used on all the displays
			//    have the same timing values.
			//
			//    We can check for this in two ways --
			//    a. If the devices connected to all outputs are the same and same kind of output is being
			//       driven (i.e. analog/digital), then we require the same mode be used. This will ensure that 
			//       the same timing is used.
			//    b. If the devices connected to the outputs are not same, then we require that a modeline
			//       be used for both, and the modeline contents to be the same.
			//
			// Stereo modes for the SeeReal and Sharp3D DFP's are not special cases. They are treated the same
			// as Active Stereo.
			if((!((fb.stereoMode == STEREO_NONE) || (fb.stereoMode == PASSIVE_STEREO))) && (gpu.scanout.size() > 1))
			{
				bool sameDevicesAndTypes = false;
				for(unsigned int i=1;i<gpu.scanout.size();i++)
				{
					if(!((gpu.scanout[i].device==gpu.scanout[0].device) && 
								(gpu.scanout[i].type==gpu.scanout[0].type)))
					{
						sameDevicesAndTypes = false;
						break;
					}
				}

				if(sameDevicesAndTypes)
				{
					for(unsigned int i=1;i<gpu.scanout.size();i++)
					{
						if(gpu.scanout[i].mode!=gpu.scanout[0].mode)
						{
							cerr << "Active Stereo requires that all outputs are driven at identical modes." << endl;
							return false;
						}
					}
				}
				else
				{
					// to keep information about modes to compare.
					DisplayTemplate dt1, dt2;
					DisplayMode dm1,dm2;

					// the getDisplay and findDisplayMode calls below 
					// shouldn't fail, since they were resolved earlier
					// FIXME: put asserts here!
					getDisplay(validDisplayTemplates, gpu.scanout[0].device, dt1);
					findDisplayMode(dt1, gpu.scanout[0].mode, dm1);

					for(unsigned int i=1;i<gpu.scanout.size();i++)
					{
						getDisplay(validDisplayTemplates, gpu.scanout[i].device, dt2);
						findDisplayMode(dt2, gpu.scanout[i].mode, dm2);

						if((dm1.type!="modeline") || (dm2.type!="modeline"))
						{
							cerr << "For Active Stereo, if the two(or more) outputs drive different devices OR output types, then a modeline needs to be used" << endl;
							return false;
						}
						else
						{
							// fail if modelines don't match
							if(dm1.value!=dm2.value)
							{
								cerr << "For Active Stereo, if the two(or more) outputs drive different devices OR output types, then the modeline must match." << endl;
								return false;
							}
						}
					}
				}
			}
			// 2. Passive Stereo requirements --
			//       1. needs the user to use both outputs !
			//       2. both modes must have same resolution, panning offset and panning domain!
			if(fb.stereoMode == PASSIVE_STEREO)
			{
				if(gpu.scanout.size() != 2)
				{
					cerr << "ERROR: Passive stereo needs usage of _exactly_ two outputs." << endl;
					return false;
				}

				if((gpu.scanout[0].width != gpu.scanout[1].width) || (gpu.scanout[0].height != gpu.scanout[1].height))
				{
					cerr << "ERROR: Passive stereo needs the same panning domain on both displays!" << endl;
					return false;
				}

				if((gpu.scanout[0].x != gpu.scanout[1].x) || (gpu.scanout[0].y != gpu.scanout[1].y))
				{
					cerr << "ERROR: Passive stereo needs the same panning offset on both displays!" << endl;
					return false;
				}

				// get information about both modes.
				DisplayTemplate dt1, dt2;
				DisplayMode dm1,dm2;

				// the getDisplay and findDisplayMode calls below 
				// shouldn't fail, since they were resolved earlier
				// FIXME: put asserts here!
				getDisplay(validDisplayTemplates, gpu.scanout[0].device, dt1);
				findDisplayMode(dt1, gpu.scanout[0].mode, dm1);

				getDisplay(validDisplayTemplates, gpu.scanout[1].device, dt2);
				findDisplayMode(dt2, gpu.scanout[1].mode, dm2);

				if((dm1.width != dm2.width) || (dm1.height != dm2.height))
				{
					cerr << "ERROR: Passive stereo needs the same resolution on both displays!" << endl;
					return false;
				}

			}

			//
			// comply with current limitations : no more than two scanouts
			// FIXME: This must be checked inside the template, right ?
			if(scanoutList.size()>2)
			{
				cerr << "No more than two simultaneous scanouts are supported with current GPUs" << endl;
				return false;
			}

			fb.gpuConfig.push_back(gpu);
		}

		if(hasScanout)
		{
			// find the bounding box of the scanouts and ensure that the framebuffer is big enough for this
			unsigned int maxX=0, maxY=0;
			for(unsigned int j=0;j<fb.gpuConfig.size();j++)
			{
				FBGPUConfig &gpu = fb.gpuConfig[j];
				for(unsigned int i=0;i<fb.gpuConfig[j].scanout.size();i++)
				{
					unsigned int finalX = gpu.scanout[i].x + gpu.scanout[i].width;
					unsigned int finalY = gpu.scanout[i].y + gpu.scanout[i].height;
					if(finalX > maxX)
					{
						maxX = finalX;	
					}
					if(finalY > maxY)
					{
						maxY = finalY;	
					}
					//cerr << " i = " << i << " finalX = "<< finalX << " finalY = "<< finalY << " maxX = "<< maxX << " maxY = "<<maxY<< endl;
				}
			}
			// Fill in unspecified value, validate otherwise
			if(fb.width==VALUE_UNSPECIFIED)
			{
				fb.width = maxX;
			}
			else
			{
				if (maxX>fb.width)
				{
					cerr << "Improper value for framebuffer width ("<<fb.width<<"). Correct value is " << maxX << endl;
					return false;
				}
			}

			// Fill in unspecified value, validate otherwise
			if(fb.height==VALUE_UNSPECIFIED)
			{
				fb.height = maxY;
			}
			else
			{
				if (maxY>fb.height)
				{
					cerr << "Improper value for framebuffer height("<<fb.height<<"). Correct value is " << maxY << endl;
					return false;
				}
			}
		}
		for(unsigned int j=0;j<fb.gpuConfig.size();j++)
		{
			FBGPUConfig &gpu = fb.gpuConfig[j];
			GPUInfo &thisGPU = gpuInfo[gpu.gpuIndex];
			if(fb.width>thisGPU.maxFramebufferWidth)
			{
				cerr << "Framebuffer is too wide("<<fb.width<<" pixels) to be supported on this GPU. Max supported width is "<<thisGPU.maxFramebufferWidth<<" pixels"<< endl;
				return false;
			}

			if(fb.height>thisGPU.maxFramebufferHeight)
			{
				cerr << "Framebuffer is too tall("<<fb.height<<" pixels) to be supported on this GPU. Max supported height is"<< thisGPU.maxFramebufferHeight<<" pixels"<< endl;
				return false;
			}
		}

		// FIXME: hardcoded nvidia specific check
		if((fb.width<304) || (fb.height<200))
		{
			cerr << "Framebuffer must have a dimension of at-least 304x200" << endl;
			return false;
		}

		// get the combiner
		VSDOMNode combinerNode = fbNode.getChildNode( "gpu_combiner");
		if(combinerNode.isEmpty())
		{
			if(fb.gpuConfig.size()>1)
			{
				cerr << "A screen may only control one GPU if a combiner(like SLI) is not used." << endl;
				return false;
			}
		}
		else
		{
			VSDOMNode sliNode = combinerNode.getChildNode( "sli");
			if(sliNode.isEmpty())
			{
				cerr << "Bad XML. gpu_combiner used without sli." << endl;
				return false;
			}

			// get the right SLI object looking up using the index
			unsigned int sliIndex = sliNode.getChildNode("index").getValueAsInt();
			if ((sliIndex<0) || (sliIndex>=sliBridges.size()))
			{
				cerr << "Bad SLI bridge reference." << endl;
				return false;
			}

			//
			// SLI related details
			//
			// Limitation notes
			//
			// 0. Display rotation is not allowed.
			//
			// 1. Passive Stereo is not allowed at all. Passive stereo is 
			// implemented using TwinView "Clone" mode. All TwinView modes
			// are disabled when SLI is enabled, so there's no way to enable
			// passive stereo.
			//
			// 2. All non-passive stereo mode seem to work. However, no exhaustive
			// tests have been done for this...
			//
			// 3. Same resolution & refresh rate on all displays.
			//
			// Display combinations --
			// 
			// 1. Non-mosaic mode (auto/SFR/AFR/AA)
			//
			// Only one output from first GPU. Could be any output.
			//
			// 2. Mosaic mode
			//
			//   1x1
			//   2x1 or 1x2    : Two combinations are possible
			//                     1. One output per GPU
			//                     2. Two outputs from the first GPU,
			//                        one output from the second.
			//
			//   1x3, 3x1      : Two outputs from first GPU and one from second GPU
			//   2x2, 4x1, 1x4 : All outputs enabled.
			//

			// No rotation is not allowed with SLI
			if(fb.rotation != ROTATE_NONE)
			{
				cerr << "You have enabled SLI, and display rotation as well. These two options can't be active at the same time." << endl;
				return false;
			}
			// No passive stereo allowed
			if(fb.stereoMode == PASSIVE_STEREO)
			{
				cerr << "Passive stereo cannot be enabled with any SLI mode." << endl;
				return false;
			}

			SLI &thisSLI = sliBridges[sliIndex];

			// convert SLI mode from string to enum
			VSDOMNode sliMode = sliNode.getChildNode("mode");
			if(sliMode.isEmpty())
				thisSLI.mode = SLI_AUTO;
			else
			{
				string val = sliMode.getValueAsString();
				if(val=="auto")
					thisSLI.mode = SLI_AUTO;
				else
				if(val=="SFR")
					thisSLI.mode = SLI_SFR;
				else
				if(val=="AFR")
					thisSLI.mode = SLI_AFR;
				else
				if(val=="AA")
					thisSLI.mode = SLI_AA;
				else
				if(val=="mosaic")
				{
					// mosaic mode is valid only on a quadroplex
					if(thisSLI.isQuadroPlex)
						thisSLI.mode = SLI_MOSAIC;
					else
					{
						cerr << "SLI mosaic mode is valid only for QuadroPlex." << endl;
						return false;
					}
				}
				else
				{
					cerr << "Bad SLI mode '"<<val<<"'" << endl;
					return false;
				}
			}

			// Check that the right GPUs are being used
			if (fb.gpuConfig.size()<2)
			{
				cerr << "To use SLI, you need to use two GPUs." << endl;
				return false;
			}
			if(fb.gpuConfig[0].gpuIndex != thisSLI.gpu0)
			{
				cerr << "To use SLI, you need to pass in the 'primary' GPU for the SLI connector first." << endl;
				return false;
			}
			if(fb.gpuConfig[1].gpuIndex != thisSLI.gpu1)
			{
				cerr << "Improper second GPU for SLI. Expecting GPU index "<<thisSLI.gpu1 << endl;
				return false;
			}

			// SLI modes other than SLI mosaic have the following restrictions
			// 1. The first GPU should be configured with exactly one display output
			// 2. Second GPU should be configured with no display outputs
			if(thisSLI.mode != SLI_MOSAIC)
			{
				if(fb.gpuConfig[1].scanout.size()>0)
				{
					cerr << "SLI modes other than mosaic do not allow the second GPU to drive displays." << endl;
					return false;
				}
				if(fb.gpuConfig[0].scanout.size()>1)
				{
					cerr << "SLI modes other than mosaic do not allow the first GPU to drive more than one display." << endl;
					return false;
				}
				if(fb.gpuConfig[0].scanout.size()==0)
				{
					cerr << "SLI modes other than mosaic needs the first GPU to drive exactly one display." << endl;
					return false;
				}
			}
			else
			{
				// Restriction :SLI mosaic needs atleast one output on the first GPU.
				if(fb.gpuConfig[0].scanout.size()==0)
				{
					cerr << "With SLI mosaic mode, the first GPU needs to have atleast 1 output configured." << endl;
					return false;
				}
				// Restriction : SLI mosaic needs atleast one output on the second GPU.
				//
				// NOTE: strictly speaking, this is not correct. I've been able to configure SLI mosaic mode to run
				// on single output, as well as two outputs on the first GPU. However, I have no benchmarks right now
				// to show that the workload in these cases gets spread to the second GPU.
				//
				// Nvidia recommends connecting second GPU to display as well, and I'm hoping they have good reasons
				// for that.
				//
				if(fb.gpuConfig[1].scanout.size()==0)
				{
					cerr << "With SLI mosaic mode, the second GPU needs to have atleast 1 output configured." << endl;
					return false;
				}

				// Check second port also, if needed
				if(fb.gpuConfig[0].scanout.size()==2)
				{
					if (fb.gpuConfig[1].scanout.size()==2)
					{
						if(fb.gpuConfig[0].scanout[1].portIndex!=fb.gpuConfig[1].scanout[1].portIndex)
						{
							cerr << "With SLI mosaic mode, the same ports must be configured for scanout on both GPUs. You have configured port index "<<fb.gpuConfig[0].scanout[1].portIndex<<" as the second output on the first GPU, and port index "<< fb.gpuConfig[1].scanout[1].portIndex << " as the second output on the second GPU" << endl;
							return false;
						}
					}
					if (fb.gpuConfig[1].scanout.size()>0)
					{
						if(fb.gpuConfig[0].scanout[0].portIndex!=fb.gpuConfig[1].scanout[0].portIndex)
						{
							cerr << "With SLI mosaic mode, the same ports must be configured for scanout on both GPUs. You have configured port index "<<fb.gpuConfig[0].scanout[0].portIndex<<" as the first output on the first GPU, and port index "<< fb.gpuConfig[1].scanout[0].portIndex << " as the first output on the second GPU" << endl;
							return false;
						}
					}
				}
				else
				if(fb.gpuConfig[0].scanout.size()==1)
				{
					if (fb.gpuConfig[1].scanout.size()==2)
					{
						// 3 display layouts that use SLI mosaic need to use two on the first GPU and
						// 1 on the second GPU. The nvidia driver provides no way to specify 2 displays
						// on the second GPU and one on the first. 
						//
						// This is a limitation of the mosaic mode, and enforced by VizStack
						// 
						cerr << "You've configured three displays with SLI mosaic mode. In this configuration, the first GPU should be configured to drive two displays and the second GPU should be configured to drive one display." << endl;
						return false;
					}
					else
						if(fb.gpuConfig[1].scanout.size()==1)
						{
							// Same ports must be configured for scanout on both GPUs
							if(fb.gpuConfig[0].scanout[0].portIndex!=fb.gpuConfig[1].scanout[0].portIndex)
							{
								cerr << "With SLI mosaic mode, the same ports must be configured for scanout on both GPUs. You have configured port index "<<fb.gpuConfig[0].scanout[0].portIndex<<" for output on the first GPU, and port index "<< fb.gpuConfig[1].scanout[0].portIndex<<" on the second GPU" << endl;
								return false;
							}
						}
				}
				// All scanouts must have same same parameters
				vector<FBGPUScanout> vScanOut;
				for(unsigned int i=0;i<fb.gpuConfig.size();i++)
				{
					for(unsigned int j=0;j<fb.gpuConfig[i].scanout.size();j++)
						vScanOut.push_back(fb.gpuConfig[i].scanout[j]);
				}

				for(unsigned int i=1;i<vScanOut.size();i++)
				{
					if (vScanOut[i].device!=vScanOut[0].device)
					{
						cerr << "You have configured SLI mosaic mode with different devices. SLI mosaic mode requires the same device" << endl;
						return false;
					}
					if (vScanOut[i].type!=vScanOut[0].type)
					{
						cerr << "You have configured SLI mosaic mode with different type of devices. SLI mosaic mode requires the same type of device (digital/analog) on all outputs." << endl;
						return false;
					}
					if (vScanOut[i].mode!=vScanOut[0].mode)
					{
						cerr << "You have configured SLI mosaic mode with different display modes. SLI mosaic mode expects same mode on all displays." << endl;
						return false;
					}
				}

			}

			// FIXME: ensure several more things
			// 1. GPU used with SLI should not be used elsewhere
			// 2.  SLI works only with Screen 0. The nvidia docs say 
			// """
			// If X is configured to use multiple screens and screen 0 has SLI or
			// Multi-GPU enabled, the other screens configured to use the nvidia driver
			// will be disabled.
			// """

			fb.sliBridge.push_back(thisSLI);
		}
		framebuffers.push_back(fb);
	}

	VSDOMNode combineFramebuffers = root.getChildNode("combine_framebuffers");
	if(combineFramebuffers.isEmpty())
	{
		combineFB = false;
	}
	else
	{
		string val=combineFramebuffers.getValueAsString();
		if((val=="1") || (val=="true"))
			combineFB=true;
		else
			combineFB=false;
	}

	if(configUsesStereo)
	{
		// Stereo does not work with the composite extension, so we disable it
		// Note: even if one screen uses stereo, then the whole X server 
		// cannot use the Composite extension

		bool found=false;
		for(unsigned int i=0;i<extensionSectionOptions.size();i++)
		{
			OptVal &ov = extensionSectionOptions[i];
			if (strcmp(ov.name.c_str(),"Composite")==0) // X spec say case insensitive compare, but that doesn't work in practise.
			{
				found=true;
				break;
			}
		}
		if (!found)
		{
			OptVal ov;
			ov.name = "Composite";
			ov.value = "Disable";
			extensionSectionOptions.push_back(ov);
		}
	}

	return true;
}

bool getGPU(const vector<GPUInfo>& gpuTemplates, string gpuModelName, GPUInfo &gi)
{
	for(unsigned int i=0;i<gpuTemplates.size();i++)
	{
		if(gpuTemplates[i].modelName == gpuModelName)
		{
			gi = gpuTemplates[i];
			return true;
		}
	}
	return false;
}

bool setGPU(vector<GPUInfo>& gpuTemplates, GPUInfo &gi)
{
	for(unsigned int i=0;i<gpuTemplates.size();i++)
	{
		if(gpuTemplates[i].modelName == gi.modelName)
		{
			gpuTemplates[i] = gi;
			return true;
		}
	}
	gpuTemplates.push_back(gi);
	return false;
}

bool getKeyboard(const vector<Keyboard>& keyboardTemplates, string keyboardType, Keyboard &kbd)
{
	for(unsigned int i=0;i<keyboardTemplates.size();i++)
	{
		if(keyboardTemplates[i].type == keyboardType)
		{
			kbd = keyboardTemplates[i];
			return true;
		}
	}
	return false;
}
bool setKeyboard(vector<Keyboard>& keyboardTemplates, Keyboard &kbd)
{
	for(unsigned int i=0;i<keyboardTemplates.size();i++)
	{
		if(keyboardTemplates[i].type == kbd.type)
		{
			keyboardTemplates[i] = kbd;
			return true;
		}
	}
	keyboardTemplates.push_back(kbd);
	return false;
}

bool getMouse(const vector<Mouse>& mouseTemplates, string mouseType, Mouse &mouse)
{
	for(unsigned int i=0;i<mouseTemplates.size();i++)
	{
		if(mouseTemplates[i].type == mouseType)
		{
			mouse = mouseTemplates[i];
			return true;
		}
	}
	return false;
}
bool setMouse(vector<Mouse>& mouseTemplates, Mouse &mouse)
{
	for(unsigned int i=0;i<mouseTemplates.size();i++)
	{
		if(mouseTemplates[i].type == mouse.type)
		{
			mouseTemplates[i] = mouse;
			return true;
		}
	}
	mouseTemplates.push_back(mouse);
	return false;
}

void getTemplateFiles(string restype, vector<string> &templateFiles)
{
	for(unsigned int i=0;i<g_templatedir.size();i++)
	{
		string path = g_templatedir[i];
		path += "/";
		path += restype;
		path += "/*.xml";
		Glob(path.c_str(), templateFiles);
	} 
}

void getKeyboardTemplates(vector<Keyboard>& keyboardTemplates)
{
	VSDOMParserErrorHandler errorHandler;
	// Load the display device templates
	VSDOMParser *keyboardParser = new VSDOMParser;

	vector<string> kbdFiles;
	vector<VSDOMNode> nodes;
	int numNodes;

	if(g_standalone)
	{
		getTemplateFiles("keyboard", kbdFiles);
		numNodes = kbdFiles.size();
	}
	else
	{
		if(!getTemplates(nodes, "keyboard", g_ssmSocket))
		{
			return;
		}
		numNodes = nodes.size();
	}

	if(g_debugPrints)
		cout << "Loading keyboard templates" << endl;
	
	for(unsigned int i=0;i<numNodes;i++)
	{
		VSDOMNode rootNode;
		if(g_standalone)
		{
			if(g_debugPrints)
				cout << "Loading "<< kbdFiles[i] << " .. " << endl;
			errorHandler.resetErrors();
			VSDOMDoc *kbdDoc = keyboardParser->ParseFile(kbdFiles[i].c_str(), errorHandler);

			// Print out warning and error messages
			vector<string> msgs;
			errorHandler.getMessages (msgs);
			for (unsigned int j = 0; j < msgs.size (); j++)
				cout << msgs[j] << endl;
			if(!kbdDoc)
				continue;
			rootNode = kbdDoc->getRootNode();
		}
		else
		{
			rootNode = nodes[i];
		}

		bool noErrors = true;

		Keyboard kbd;

		kbd.index = 0;
		kbd.type = rootNode.getChildNode("type").getValueAsString();
		kbd.driver = rootNode.getChildNode("driver").getValueAsString();

		vector<VSDOMNode> optionNodes = rootNode.getChildNodes("option");
		for(unsigned int j=0;j<optionNodes.size();j++)
		{
			OptVal ov;
			ov.name  = optionNodes[j].getChildNode("name").getValueAsString();
			ov.value  = optionNodes[j].getChildNode("value").getValueAsString();
			kbd.optval.push_back(ov);
		}

		setKeyboard(keyboardTemplates, kbd);
	}
}

void getMouseTemplates(vector<Mouse>& mouseTemplates)
{
	VSDOMParserErrorHandler errorHandler;
	// Load the display device templates
	VSDOMParser *mouseParser = new VSDOMParser;

	vector<string> mouseFiles;
	vector<VSDOMNode> nodes;
	int numNodes;

	if(g_standalone)
	{
		getTemplateFiles("mouse", mouseFiles);
		numNodes = mouseFiles.size();
	}
	else
	{
		if(!getTemplates(nodes, "mouse", g_ssmSocket))
		{
			return;
		}
		numNodes = nodes.size();
	}

	if(g_debugPrints)
		cout << "Loading mouse templates" << endl;

	for(unsigned int i=0;i<numNodes;i++)
	{
		VSDOMNode rootNode;
		if(g_standalone)
		{
			if(g_debugPrints)
				cout << "Loading "<< mouseFiles[i] << " .. " << endl;

			errorHandler.resetErrors();
			VSDOMDoc *mouseDoc = mouseParser->ParseFile(mouseFiles[i].c_str(), errorHandler);

			// Print out warning and error messages
			vector<string> msgs;
			errorHandler.getMessages (msgs);
			for (unsigned int j = 0; j < msgs.size (); j++)
				cout << msgs[j] << endl;
			if(!mouseDoc)
				continue;
			rootNode = mouseDoc->getRootNode();
		}
		else
		{
			rootNode = nodes[i];
		}

		bool noErrors = true;

		Mouse mouse;

		mouse.index = 0;
		mouse.type = rootNode.getChildNode("type").getValueAsString();
		mouse.driver = rootNode.getChildNode("driver").getValueAsString();

		vector<VSDOMNode> optionNodes = rootNode.getChildNodes("option");
		for(unsigned int j=0;j<optionNodes.size();j++)
		{
			OptVal ov;
			ov.name  = optionNodes[j].getChildNode("name").getValueAsString();
			ov.value  = optionNodes[j].getChildNode("value").getValueAsString();
			mouse.optval.push_back(ov);
		}

		setMouse(mouseTemplates,mouse);		
	}
}

void getDisplayTemplates(vector<DisplayTemplate>& displayTemplates)
{
	VSDOMParserErrorHandler errorHandler;
	// Load the display device templates
	VSDOMParser *displayParser = new VSDOMParser;

	vector<string> monitorFiles;
	vector<VSDOMNode> nodes;
	int numNodes;

	if(g_standalone)
	{
		getTemplateFiles("displays", monitorFiles);
		numNodes = monitorFiles.size();
	}
	else
	{
		if(!getTemplates(nodes, "display", g_ssmSocket))
		{
			return;
		}
		numNodes = nodes.size();
	}

	for(unsigned int i=0;i<numNodes;i++)
	{
		VSDOMNode rootNode;
		if(g_standalone)
		{
			if(g_debugPrints)
				cout << "Loading "<< monitorFiles[i] << " .. " << endl;

			errorHandler.resetErrors();
			VSDOMDoc *monitor = displayParser->ParseFile(monitorFiles[i].c_str(), errorHandler);

			// Print out warning and error messages
			vector<string> msgs;
			errorHandler.getMessages (msgs);
			for (unsigned int i = 0; i < msgs.size (); i++)
				cout << msgs[i] << endl;

			if(!monitor)
				continue;

			rootNode = monitor->getRootNode();
		}
		else
		{
			rootNode = nodes[i];
		}

		DisplayTemplate dt;

		dt.name = rootNode.getChildNode("model").getValueAsString();
		dt.input = rootNode.getChildNode("input").getValueAsString();
		dt.hasEdid = false;
		VSDOMNode  edidNode = rootNode.getChildNode("edid");
		if(!edidNode.isEmpty())
		{
			dt.edidFile = edidNode.getValueAsString();
			FILE *fp = fopen(dt.edidFile.c_str(),"rb"); // FIXME: we can implement this easier using fstat ??
			if(!fp)
			{
				cerr << "ERROR: Unable to open EDID file '"<< dt.edidFile <<"'"<<endl;
				exit(-1);
			}
			if(fseek(fp,  0, SEEK_END)<0)
			{
				cerr << "ERROR: unable to process EDID file '"<< dt.edidFile << "'. Failed to seek to the end."<<endl;
				exit(-1);
			}
			int fileSize;
			if((fileSize=ftell(fp))<=0)
			{
				cerr << "ERROR: unable to process EDID file '"<< dt.edidFile << "'. Failed to get file size."<<endl;
				exit(-1);
			}

			if(fileSize>EDID_BLOCK_SIZE*MAX_EDID_BLOCKS)
			{
				cerr << "ERROR: Bad EDID file '"<< dt.edidFile <<"'. It's size("<<fileSize<<") is too large for me to handle"<<endl;
				exit(-1);
			}
			if((fileSize%EDID_BLOCK_SIZE)!=0)
			{
				cerr << "ERROR: Bad EDID file '"<< dt.edidFile <<"'. It's size("<<fileSize<<") is incorrect - needs to be a multiple of "<< EDID_BLOCK_SIZE<<" bytes."<<endl;
				exit(-1);
			}
			fclose(fp);
			dt.hasEdid = true;
		}
		else
		{
			VSDOMNode  edidBytesNode = rootNode.getChildNode( "edidBytes");
			if(!edidBytesNode.isEmpty())
			{
				string edidBytes = edidBytesNode.getValueAsString();
				int edidSize = edidBytes.size();
				if (edidSize==0)
				{
					cerr << "ERROR: Number of EDID bytes is zero!"<<endl;
					exit(-1);
				}
				if((edidSize%(EDID_BLOCK_SIZE*2))!=0) // FIXME: the "2" here is about the bytes being in hex
				{
					cerr << "ERROR: Number of EDID bytes is incorrect - needs to be a multiple of "<< EDID_BLOCK_SIZE<<" bytes."<<endl;
					exit(-1);
				}
				if(edidSize>(EDID_BLOCK_SIZE*MAX_EDID_BLOCKS*2))
				{
					cerr << "ERROR: Too many edid bytes. Max allowed is " << EDID_BLOCK_SIZE*MAX_EDID_BLOCKS << endl;
					exit(-1);
				}
				// The EDID string will have two hex chars per byte
				for(unsigned int i=0;i<edidSize;i+=2)
				{
					const char *instr = edidBytes.c_str();
					char hexVal[3] = { instr[i], instr[i+1], 0 };
					unsigned int val;
					sscanf(hexVal, "%x", &val);
					//printf("%2x ", val);
					dt.edidBytes[i/2] = (val & 0xff);
				}
				dt.numEdidBytes = edidSize/2;
				dt.hasEdid = true;
				//cout << "Has EDID bytes = " << dt.numEdidBytes << endl;
			}
		}

		if(!dt.hasEdid)
		{
			VSDOMNode  hsync = rootNode.getChildNode("hsync");
			VSDOMNode valNode;
			valNode = hsync.getChildNode("min");
			if(valNode.isEmpty())
			{
				dt.hsyncRange[0] = MIN_HSYNC;
			}
			else
			{
				dt.hsyncRange[0] = valNode.getValueAsString();
			}
			valNode = hsync.getChildNode("max");
			if(valNode.isEmpty())
			{
				dt.hsyncRange[1] = MAX_HSYNC;
			}
			else
			{
				dt.hsyncRange[1] = valNode.getValueAsString();
			}

			VSDOMNode  vrefresh = rootNode.getChildNode("vrefresh");
			valNode = vrefresh.getChildNode("min");
			if(valNode.isEmpty())
			{
				dt.vrefreshRange[0] = MIN_VREFRESH;
			}
			else
			{
				dt.vrefreshRange[0] = valNode.getValueAsString();
			}
			valNode = vrefresh.getChildNode("max");
			if(valNode.isEmpty())
			{
				dt.vrefreshRange[1] = MAX_VREFRESH;
			}
			else
			{
				dt.vrefreshRange[1] = valNode.getValueAsString();
			}
		}
		else
		{
			dt.hsyncRange[0] = MIN_HSYNC;
			dt.hsyncRange[1] = MAX_HSYNC;
			dt.vrefreshRange[0] = MIN_VREFRESH;
			dt.vrefreshRange[1] = MAX_VREFRESH;
		}

		vector<VSDOMNode > modes = rootNode.getChildNodes("mode");
		for(unsigned int i=0;i<modes.size();i++)
		{
			DisplayMode dm;
			dm.type = modes[i].getChildNode("type").getValueAsString();
			dm.width = modes[i].getChildNode("width").getValueAsInt();
			dm.height = modes[i].getChildNode("height").getValueAsInt();
			dm.refreshRate = modes[i].getChildNode("refresh").getValueAsFloat();
			VSDOMNode valueNode = modes[i].getChildNode("value");
			if(!valueNode.isEmpty())
				dm.value = valueNode.getValueAsString();
			else
				dm.value = "";

			vector<VSDOMNode > aliasNodes = modes[i].getChildNodes( "alias");
			for(unsigned int j=0;j<aliasNodes.size();j++)
			{
				dm.alias = aliasNodes[j].getValueAsString();
				// validation : check if this alias is already defined !
				for(unsigned int k=0;k<dt.displayModes.size();k++)
				{
					if(dt.displayModes[k].alias == dm.alias)
					{
						cerr << "ERROR: Mode alias '"<<dm.alias<<"' used more than once. You may define a mode alias only once."<< endl;
						exit(-1);
					}
				}
				dt.displayModes.push_back(dm);
			}
		}

		VSDOMNode  defaultModeNode = rootNode.getChildNode("default_mode");
		string defaultMode = defaultModeNode.getValueAsString();
		bool modeFound = false;
		for(unsigned int i=0;i<dt.displayModes.size();i++)
		{
			if(dt.displayModes[i].alias==defaultMode)
			{
				modeFound = true;
				break;
			}
		}
		if(!modeFound)
		{
			cerr << "ERROR: No default mode specified for this display device. Ignoring!" << endl;
		}

		dt.defaultDisplayMode = defaultMode;
		setDisplay(displayTemplates,dt);
	}

	delete displayParser;
}

void getGPUTemplates(vector<GPUInfo>& gpuTemplates)
{
	VSDOMParserErrorHandler errorHandler;
	// Load the display device templates
	VSDOMParser *gpuParser = new VSDOMParser;

	vector<string> gpuFiles;
	vector<VSDOMNode > nodes;
	int numNodes;

	if(g_standalone)
	{
		getTemplateFiles("gpus", gpuFiles);
		numNodes = gpuFiles.size();
	}
	else
	{
		if(!getTemplates(nodes, "gpu", g_ssmSocket))
		{
			return;
		}
		numNodes = nodes.size();
	}

	for(unsigned int i=0;i<numNodes;i++)
	{
		VSDOMNode  rootNode;
		if(g_standalone)
		{
			if(g_debugPrints)
				cout << "Loading "<< gpuFiles[i] << " .. " << endl;

			errorHandler.resetErrors();
			VSDOMDoc *gpu = gpuParser->ParseFile(gpuFiles[i].c_str(), errorHandler);

			// Print out warning and error messages
			vector<string> msgs;
			errorHandler.getMessages (msgs);
			for (unsigned int i = 0; i < msgs.size (); i++)
				cout << msgs[i] << endl;

			if(!gpu)
				continue;

			rootNode = gpu->getRootNode();
		}
		else
		{
			rootNode = nodes[i];
		}

		GPUInfo gi;
		gi.usageCount = 0;

		gi.modelName = rootNode.getChildNode("model").getValueAsString();
		gi.vendorName = rootNode.getChildNode("vendor").getValueAsString();

		vector<VSDOMNode > scanouts = rootNode.getChildNodes("scanout_caps");

		bool noErrors = true;

		for(unsigned int j=0;j<scanouts.size();j++)
		{
			VSDOMNode  thisScanout = scanouts[j];
			unsigned int portIndex = thisScanout.getChildNode("index").getValueAsInt();
			if(portIndex != j)
			{
				cerr << "Port index specified is "<<portIndex<<", expected "<<j << endl;
				noErrors = false;
				break;
			}

			vector<VSDOMNode > typeNodes = thisScanout.getChildNodes("type");
			vector<string> scanTypes;
			for(unsigned int k=0;k<typeNodes.size();k++)
			{
				scanTypes.push_back(typeNodes[k].getValueAsString());
			}
			gi.portUsageCount.push_back(0);
			gi.portOutputCaps.push_back(scanTypes);
			FBGPUScanout dummy;
			gi.portScanout.push_back(dummy);
		}

		if(noErrors)
		{
			VSDOMNode  limitsNode = rootNode.getChildNode( "limits");
			gi.maxFramebufferWidth = limitsNode.getChildNode("max_width").getValueAsInt();
			gi.maxFramebufferHeight = limitsNode.getChildNode("max_height").getValueAsInt();
		}


		if(!noErrors)
		{
			cerr << "Skipped adding " << gi.modelName << endl;
		}
		else
		{
			gpuTemplates.push_back(gi);
		}
	}
}

bool getLocalConfig(string configFile, vector<GPUInfo>& gpuTemplates, vector<Keyboard>& keyboardTemplates, vector<Mouse>& mouseTemplates, vector<GPUInfo>& gpuInfo, vector<Keyboard>& validKeyboards, vector<Mouse>& validMice, vector<SLI>& sliBridges)
{
	char myHostName[256];
	gethostname(myHostName, sizeof(myHostName));

	vector<VSDOMNode > nodesList;

	if(g_standalone)
	{
		VSDOMParserErrorHandler errorHandler;
		// Load the display device templates
		VSDOMParser *configParser = new VSDOMParser;

		errorHandler.resetErrors();
		VSDOMDoc *config = configParser->ParseFile(configFile.c_str(), errorHandler);

		// Print out warning and error messages
		vector<string> msgs;
		errorHandler.getMessages (msgs);
		for (unsigned int i = 0; i < msgs.size (); i++)
			cout << msgs[i] << endl;

		if(!config)
		{
			cerr << "FATAL: Unable to get the local configuration of this node." << endl;
			return false;
		}

		VSDOMNode  rootNode = config->getRootNode();

		VSDOMNode  nodesNode = rootNode.getChildNode("nodes");
		if(nodesNode.isEmpty())
		{
			cerr << "FATAL: Need node inforamtion in the local configuration file" << endl;
			return false;
		}

		nodesList = nodesNode.getChildNodes("node");
	}
	else
	{
		char *nodeConfig = getNodeConfig(g_hostName.c_str(), g_ssmSocket);

		VSDOMParserErrorHandler errorHandler;
		VSDOMParser *configParser = new VSDOMParser;
		errorHandler.resetErrors();
		VSDOMDoc *config = configParser->ParseString(nodeConfig, errorHandler);
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
			fprintf(stderr, "%s", nodeConfig);
			fprintf(stderr, "\n----------------------------------------------\n");
			return false;
		}

		// Ensure that return status is "success"
		VSDOMNode  rootNode = config->getRootNode();
		VSDOMNode  responseNode = rootNode.getChildNode("response");
		int status = responseNode.getChildNode("status").getValueAsInt();
		if(status!=0)
		{
			string msg = responseNode.getChildNode("message").getValueAsString();
			fprintf(stderr, "ERROR - Failure returned from SSM : %s\n", msg.c_str());
			delete configParser;
			return false;
		}

		VSDOMNode  retValNode = responseNode.getChildNode("return_value");
		nodesList = retValNode.getChildNodes( "node");
	}

	bool configFound = false;
	bool errorsFound = false;
	for(unsigned int i=0;i<nodesList.size();i++)
	{
		VSDOMNode  thisNode = nodesList[i];
		string nodeName = thisNode.getChildNode("hostname").getValueAsString();

		// dont process non-matching nodes. localhost is supposed to
		// be the only node if it exists (kind of a bug if I think of it).
		if (!((nodeName=="localhost") || (nodeName==myHostName)))
			continue;

		vector<VSDOMNode > gpuNodes = thisNode.getChildNodes("gpu");
		for(unsigned int j=0; j<gpuNodes.size(); j++)
		{
			VSDOMNode thisGPU=gpuNodes[j];

			unsigned int index = thisGPU.getChildNode("index").getValueAsInt();

			if(index != j)
			{
				errorsFound = true;
				cerr << "FATAL : GPU index is not in order" << endl;
				break;
			}

			VSDOMNode node;
			node = thisGPU.getChildNode("model");
			if(node.isEmpty())
			{
				cerr << "FATAL: No model defined for GPU #"<<index<< endl;
				errorsFound = true;
				break;
			}
			string gpuModel = node.getValueAsString();

			GPUInfo gpu;
			if(!getGPU(gpuTemplates, gpuModel, gpu))
			{
				cerr << "FATAL: Could not get the GPU information for GPU model '"<<gpuModel<<"'. I don't know any such device." << endl;
				errorsFound = true;
				break;
			}

			node = thisGPU.getChildNode("busID");
			string busId;
			if(node.isEmpty())
			{
				busId.clear();
			}
			else
			{
				busId = node.getValueAsString();
			}

			int allowScanOut;
			node = thisGPU.getChildNode("useScanOut");
			if(node.isEmpty())
			{
				allowScanOut = gpu.allowScanOut;
			}
			else
			{
				allowScanOut = node.getValueAsInt();
			}

			int allowNoScanOut;
			node = thisGPU.getChildNode("allowNoScanOut");
			if(node.isEmpty())
			{
				allowNoScanOut = gpu.allowNoScanOut;
			}
			else
			{
				allowNoScanOut = node.getValueAsInt();
			}

			gpu.busID = busId;
			gpu.allowScanOut = allowScanOut;
			gpu.allowNoScanOut = allowNoScanOut;
			gpuInfo.push_back(gpu);
		}

		vector<VSDOMNode > kbdNodes = thisNode.getChildNodes("keyboard");
		for(unsigned int j=0; j<kbdNodes.size(); j++)
		{
			VSDOMNode thisKbd=kbdNodes[j];
			unsigned int index = thisKbd.getChildNode("index").getValueAsInt();
			string kbdType = thisKbd.getChildNode("type").getValueAsString();
			string physAddr;
			VSDOMNode pNode = thisKbd.getChildNode("phys_addr");
			if(!pNode.isEmpty())
			{
				physAddr = pNode.getValueAsString();
			}

			Keyboard kbd;
			if(!getKeyboard(keyboardTemplates, kbdType, kbd))
			{
				cerr << "FATAL: Could not get the information for keyboard type '"<<kbdType<<"'. I don't know any such device." << endl;
				errorsFound = true;
				break;
			}
			kbd.index = index;
			kbd.physAddr = physAddr;
			validKeyboards.push_back(kbd);
		}

		vector<VSDOMNode > mouseNodes = thisNode.getChildNodes("mouse");
		for(unsigned int j=0; j<mouseNodes.size(); j++)
		{
			VSDOMNode thisMouse=mouseNodes[j];
			unsigned int index = thisMouse.getChildNode("index").getValueAsInt();
			string mouseType = thisMouse.getChildNode("type").getValueAsString();
			string physAddr;
			VSDOMNode pNode = thisMouse.getChildNode("phys_addr");
			if(!pNode.isEmpty())
			{
				physAddr = pNode.getValueAsString();
			}

			Mouse mouse;
			if(!getMouse(mouseTemplates, mouseType, mouse))
			{
				cerr << "FATAL: Could not get the information for mouse type '"<<mouseType<<"'. I don't know any such device." << endl;
				errorsFound = true;
				break;
			}
			mouse.index = index;
			mouse.physAddr = physAddr;
			validMice.push_back(mouse);
		}

		vector<VSDOMNode > sliBridgeNodes = thisNode.getChildNodes( "sli");
		for(unsigned int j=0;j<sliBridgeNodes.size();j++)
		{
			VSDOMNode thisSLI = sliBridgeNodes[j];
			unsigned int index = thisSLI.getChildNode("index").getValueAsInt();
			string sliType = thisSLI.getChildNode("type").getValueAsString();
			unsigned int gpu0 = thisSLI.getChildNode("gpu0").getValueAsInt();
			unsigned int gpu1 = thisSLI.getChildNode("gpu1").getValueAsInt();
			SLI sli;
			sli.index = index;
			if (sliType=="discrete")
				sli.isQuadroPlex = false;
			else
				if (sliType=="quadroplex")
					sli.isQuadroPlex = true;
				else
				{
					cerr << "FATAL: Bad sli type '"<<sliType<<"'"<<endl;
					return false;
				}
			sli.gpu0 = gpu0;
			sli.gpu1 = gpu1;
			sliBridges.push_back(sli);
		}
		if(!errorsFound)
			configFound = true;

		break;
	}

	if(errorsFound)
	{
		cerr << "FATAL: Errors happened trying to load config" << endl;
		return false;
	}
	else if(!configFound)
	{
		cerr << "FATAL: Could not find the config for this node" << endl;
		return false;
	}

	return true;
}

void usage(char *argv0)
{
	cerr << argv0 << " [--nodeconfig=<sysconfig-filename>] <--input=<input-file>> [--output=<output-file>] [--edid-output-prefix=<prefix>] [--server-info=<filename>] [--no-ssm]" << endl;
	exit(-1);
}

bool getArgVal(const char *argval, const char *option, string& val)
{
	if(strncmp(argval, option, strlen(option))==0)
	{
		val=argval+strlen(option);
		return true;
	}

	return false;
}

int main(int argc, char** argv)
{
	string inputFileName;
	FILE *outputFile = stdout;
	string outputFileName = "<stdout>";
	string nodeConfigFile = "/etc/vizstack/node_config.xml";
	string edidFilePrefix;
	string serverInfoFileName;
	FILE *serverInfoFile = 0;
	bool ignoreMissingDevices = false;
	bool serverSpecified=false;
	string whichHost;
	string whichDisplay;
	bool forceNoSSM=false;

	if(getenv("VS_X_DEBUG"))
	{
		g_debugPrints = true;
	}

	g_templatedir.push_back("/opt/vizstack/share/templates");
	g_templatedir.push_back("/etc/vizstack/templates");

	for(unsigned int argIndex=1; argIndex<argc; argIndex++)
	{
		string argVal;
		if (getArgVal(argv[argIndex],"--templatedir=", argVal))
		{
			g_templatedir.push_back(argVal);
		}
		else
		if (getArgVal(argv[argIndex],"--nodeconfig=", argVal))
		{
			nodeConfigFile = argVal;
		}
		else
		if (strcmp(argv[argIndex],"--no-ssm")==0)
		{
			forceNoSSM=true;
		}
		else
		if (getArgVal(argv[argIndex],"--input=", argVal))
		{
			inputFileName = argVal;
		}
		else
		if (getArgVal(argv[argIndex],"--output=", argVal))
		{
			outputFileName = argVal;
			outputFile = fopen(argVal.c_str(),"w");
			if(!outputFile)
			{
				fprintf(stderr, "Unable to open output file %s\n", argVal.c_str());
				perror("FATAL: unable to open output file");
				exit(-1);
			}
		}
		else
		if (getArgVal(argv[argIndex],"--edid-output-prefix=", argVal))
		{
			edidFilePrefix = argVal;
		}
		else
		if (getArgVal(argv[argIndex],"--server-info=", argVal))
		{
			serverInfoFileName = argVal;
			serverInfoFile = fopen(argVal.c_str(),"w");
			if(!serverInfoFile)
			{
				perror("FATAL: unable to open server info file for writing");
				fprintf(stderr, "Unable to server info file for writing %s\n", argVal.c_str());
				exit(-1);
			}
		}
		else
		if (strcmp(argv[argIndex], "--ignore-missing-devices")==0)
		{
			ignoreMissingDevices = true;
		}
		else
		if ((strcmp(argv[argIndex],"-h")==0) || (strcmp(argv[argIndex],"--help")==0))
		{
			usage(argv[0]);
		}
		else
		if (strchr(argv[argIndex], ':')!=NULL)
		{
			serverSpecified = true;
			char * serverSpec = strdup(argv[argIndex]);
			if(serverSpec[0]!=':')
			{
				whichHost = strtok(serverSpec, ":");
				whichDisplay = strtok(NULL, ":");
			}
			else
			{
				whichDisplay = strtok(serverSpec, ":");
			}

			whichDisplay = ":" + whichDisplay ; // Append a ":"

			if(strtok(NULL,":")!=NULL)
			{
				cerr << "Invalid X server specification " << argv[argIndex] << endl;
			}
			free(serverSpec);
		}
		else
		{
			cerr << "Bad argument :"<< argv[argIndex]<<endl;
			usage(argv[0]);
		}
	}

	if((inputFileName.size()==0) && (!serverSpecified))
	{
		cerr << "You need to specify an input file, or a server"<< endl;
		usage(argv[0]);
	}

	// Start using the XML parser
	VSDOMParser::Initialize();

	if(forceNoSSM)
	{
		g_hostName = "localhost";
		g_standalone = true;
	}
	else
	if(!getSystemType())
	{
		exit(-1);
	}

	if((serverSpecified) && (whichHost.size()==0))
	{
		whichHost = g_hostName;
	}

	if(!g_standalone)
	{
		g_ssmSocket = connectToSSM(g_ssmHost, g_ssmPort);
		if(g_ssmSocket==-1)
		{
			exit(-1);
		}

		// identify ourselves as a regular client.
		string myIdentity = "<client />";

		if(!authenticateToSSM(myIdentity, g_ssmSocket))
		{
			fprintf(stderr, "ERROR - Unable to authenticate to SSM\n");
			closeSocket(g_ssmSocket);
			exit(-1);
		}
	}

	if(inputFileName.size()>0)
	{
		FILE *fp=fopen(inputFileName.c_str(),"r");
		if(!fp)
		{
			char msg[4096];
			sprintf(msg,"FATAL: unable to open input file %s", inputFileName.c_str());
			perror(msg);
			exit(-1);
		}
		fclose(fp);
	}

	// Data coming from config files
	vector<GPUInfo> gpuInfo;
	vector<DisplayTemplate> displayTemplates;
	vector<Keyboard> keyboardTemplates;
	vector<Mouse> mouseTemplates;
	vector<Keyboard> validKeyboards;
	vector<Mouse> validMice;
	vector<Keyboard> usedKeyboards;
	vector<Mouse> usedMice;
	vector<GPUInfo> gpuTemplates;

	VSDOMParserErrorHandler errorHandler;

	// Get information about types of GPU in this system
	getGPUTemplates(gpuTemplates);
	if(gpuTemplates.size()==0)
	{
		cerr << "FATAL : No usable GPU types in this system." << endl;
		return -1;
	}

	// Get information about displays supported on this system
	getDisplayTemplates(displayTemplates);

	// Get information about input devices on this system
	getKeyboardTemplates(keyboardTemplates);
	getMouseTemplates(mouseTemplates);

	// Get information about all input devices known to the kernel
	vector<KernelDevice> allDevs;
	if(!getKernelDevices(allDevs))
	{
		cerr << "FATAL : Unable to get information about input devices from the kernel." << endl;
		return -1;
	}

	if(g_debugPrints)
	{
		printf("Finished getting Kernel devices\n");
	}

	vector<SLI> sliBridges;
	// Get information about VizResources in this system
	if(!getLocalConfig(nodeConfigFile, gpuTemplates, keyboardTemplates, mouseTemplates, gpuInfo, validKeyboards, validMice, sliBridges))
	{
		cerr << "FATAL: Unable to get local config. Cannot continue" << endl;
		return -1;
	}
	if(g_debugPrints)
	{
		printf("Successfully parsed local config : %d GPU(s) %d Keyboard(s) %d Mice %d SLI bridge(s)\n", gpuInfo.size(), validKeyboards.size(), validMice.size(), sliBridges.size());
	}

	if(gpuInfo.size()==0)
	{
		cerr << "FATAL : No usable GPUs in this system." << endl;
		return -1;
	}

	// Print out warning and error messages
	vector < string > msgs;
	errorHandler.getMessages (msgs);
	for (unsigned int i = 0; i < msgs.size (); i++)
		cout << msgs[i] << endl;

	vector<Framebuffer> framebuffers;
	vector<string> modulesToLoad;
	vector<OptVal> extensionSectionOptions;
	vector<string> usedIODeviceNames;

	VSDOMParser *parser = new VSDOMParser;
	VSDOMDoc * domDocument=0;
	VSDOMNode serverConfigNode;

	if(serverSpecified)
	{
		if(g_debugPrints)
			cout << "Getting configuration for "<< whichHost << whichDisplay << " from SSM." <<endl;
		char* serverConfigText = getServerConfig(whichHost.c_str(), whichDisplay.c_str(), g_ssmSocket);
		if(!serverConfigText)
		{
			fprintf(stderr, "Unable to get configuration of server %s%s\n",whichHost.c_str(), whichDisplay.c_str());
			exit(-1);
		}
		domDocument = parser->ParseString(serverConfigText, errorHandler);
	}
	else
	{
		if(g_debugPrints)
			cout << "Parsing input file " <<endl;
		domDocument = parser->ParseFile(inputFileName.c_str(), errorHandler);
	}

	// Print out warning and error messages
	errorHandler.getMessages (msgs);
	for (unsigned int i = 0; i < msgs.size (); i++)
		cout << msgs[i] << endl;

	// Nothing else to do if errors happened
	if(!domDocument)
	{
		std::cout << "\nErrors occurred while processing "<< inputFileName << " (or other configuration file(s)). Failed to generate X configuration file. Aborting." << std::endl;
		return -1;
	}

	if(serverSpecified)
	{
		// Ensure that return status is "success"
		VSDOMNode  rootNode = domDocument->getRootNode();
		VSDOMNode  responseNode = rootNode.getChildNode("response");
		int status = responseNode.getChildNode("status").getValueAsInt();
		if(status!=0)
		{
			string msg = responseNode.getChildNode("message").getValueAsString();
			fprintf(stderr, "ERROR - Failure returned from SSM : %s\n", msg.c_str());
			exit(-1);
		}

		VSDOMNode  retValNode = responseNode.getChildNode("return_value");
		serverConfigNode = retValNode.getChildNode( "server");
	}
	else
	{
		serverConfigNode = domDocument->getRootNode();
	}

	// Process the XML tree, extract data from it
	bool combineFB;
	vector<DisplayTemplate> usedDisplayTemplates;
	vector<OptVal> cmdArgVal;
	vector<SLI> usedSLIBridge;
	if(!extractXMLData(serverConfigNode, combineFB, framebuffers, gpuInfo, modulesToLoad, extensionSectionOptions, usedKeyboards, usedMice, displayTemplates, usedDisplayTemplates, validKeyboards, validMice, cmdArgVal, sliBridges, usedSLIBridge))
	{
		cerr << "Improper configuration specified. Cannot continue!" << endl;
		return(-1);
	}

	// Map physical location of keyboards to the real devices
	vector<Keyboard> finalKeyboards;
	for(unsigned int i=0;i<usedKeyboards.size();i++)
	{
		bool found = true;
		Keyboard &thisKbd = usedKeyboards[i];
		if(thisKbd.physAddr.size()>0)
		{
			found = false;
			for(unsigned int k=0;k<allDevs.size();k++)
			{
				string &thisAddr = allDevs[k].physicalAddress;
				if(thisKbd.physAddr == thisAddr)
				{
					if (!allDevs[k].isKeyboard)
					{
						cerr << "ERROR: Keyboard Index "<<thisKbd.index<<" of type "<<thisKbd.type<<" with Physical Address '"<<thisKbd.physAddr<<" is actually _not_ a keyboard according to the kernel. Please check your configuration." << endl;
						return (-1);
					}
					OptVal nv;
					nv.name = "Device";
					nv.value = allDevs[k].handler;
					thisKbd.optval.push_back(nv);
					found = true;
					break;
				}
			}
			if(!found)
			{
				// If the user did not request ignoring these, then we can only exit.
				if(!ignoreMissingDevices)
				{
					cerr << "ERROR: Keyboard Index "<<thisKbd.index<<" of type "<<thisKbd.type<<" with Physical Address '"<<thisKbd.physAddr<<" is not connected to this node." << endl;
					return (-1);
				}
			}
		}
		if(found)
		{
			finalKeyboards.push_back(thisKbd);
		}
	}

	// Map physical location of mice to the real devices
	vector<Mouse> finalMice;
	for(unsigned int i=0;i<usedMice.size();i++)
	{
		bool found = true;
		Mouse &thisMouse = usedMice[i];
		if(thisMouse.physAddr.size()>0)
		{
			found = false;
			for(unsigned int k=0;k<allDevs.size();k++)
			{
				string &thisAddr = allDevs[k].physicalAddress;
				if(thisMouse.physAddr == thisAddr)
				{
					if (allDevs[k].isKeyboard)
					{
						cerr << "ERROR: Mouse Index "<<thisMouse.index<<" of type "<<thisMouse.type<<" with Physical Address '"<<thisMouse.physAddr<<" is actually a keyboard according to the kernel. Please check your configuration." << endl;
						return (-1);
					}
					OptVal nv;
					nv.name = "Device";
					nv.value = allDevs[k].handler;
					thisMouse.optval.push_back(nv);
					found = true;
					break;
				}
			}
			if(!found)
			{
				// If the user did not request ignoring these, then we can only exit.
				if(!ignoreMissingDevices)
				{
					cerr << "ERROR: Mouse Index "<<thisMouse.index<<" of type "<<thisMouse.type<<" with Physical Address '"<<thisMouse.physAddr<<" is not connected to this node." << endl;
					return (-1);
				}
			}
		}
		for(unsigned int j=0;j<thisMouse.optval.size();j++)
		{
			OptVal &ov = thisMouse.optval[j];
			if (ov.name=="Dev Phys")
			{
			}
		}
		if(found)
		{
			finalMice.push_back(thisMouse);
		}
	}

	// Error checking
	// TODO: check any errors that couldn't be detected by extractXMLData
	// (if there's such a thing !)

	// If any of the used display templates have edidBytes, but no Edid File, then
	// generate the edid files for them now, so that the X configuration file can be generated
	// with proper references
	vector<string> createdEdidFiles;
	for(unsigned int i=0;i<usedDisplayTemplates.size();i++)
	{
		DisplayTemplate &thisDisplay = usedDisplayTemplates[i];
		// If this Display has an edid, but not in a file, then we'll
		// need to generate a temporary file.
		if((thisDisplay.hasEdid) && (thisDisplay.edidFile.size()==0))
		{
			if(edidFilePrefix.size()==0)
			{
				cerr << "You need to define a path/file prefix where I'll create the EDID files" << endl;
				return(-1);
			}
			string filename = edidFilePrefix + thisDisplay.name;
			FILE *fp = fopen(filename.c_str(), "w");
			if(!fp)
			{
				perror("Unable to open EDID file for writing");
				cerr << "Unable to write to file '"<<filename<<"'"<<endl;
				exit(-1);
			}
			
			if(fwrite(thisDisplay.edidBytes, thisDisplay.numEdidBytes, 1, fp)!=1)
			{
				perror("Unable to write to EDID file");
				cerr << "Unable to write to file '"<<filename<<"'"<<endl;
				exit(-1);
			}
			fclose(fp);
			//cout << "Created file for " << thisDisplay.name << " = " << filename<< endl;
			thisDisplay.edidFile = filename;
			setDisplay(displayTemplates, thisDisplay);
			// record the fact that we created this file
			createdEdidFiles.push_back(filename);
		}
	}

	// write out information about the X server
	if(serverInfoFile!=0)
	{
		// Find if there are any unused GPUs
		bool usingAllGPUs=1;
		for(unsigned int i=0;i<gpuInfo.size();i++)
		{
			if (gpuInfo[i].usageCount==0)
			{	
				usingAllGPUs = 0;
				break;
			}
		}

		fprintf(serverInfoFile,"<serverinfo>\n");
		fprintf(serverInfoFile,"\t<uses_all_gpus>%d</uses_all_gpus>\n", usingAllGPUs);
		for(unsigned int i=0;i<createdEdidFiles.size();i++)
			fprintf(serverInfoFile,"\t<temp_edid_file>%s</temp_edid_file>\n", createdEdidFiles[i].c_str());
		for(unsigned int i=0;i<cmdArgVal.size();i++)
		{
			fprintf(serverInfoFile,"\t<x_cmdline_arg><name>%s</name>", cmdArgVal[i].name.c_str());
			if(cmdArgVal[i].value.size()>0)
				fprintf(serverInfoFile,"<value>%s</value>", cmdArgVal[i].value.c_str());
			fprintf(serverInfoFile,"</x_cmdline_arg>\n");
		}
		fprintf(serverInfoFile,"</serverinfo>\n");
	}
	if(serverInfoFileName.size()>0)
		fclose(serverInfoFile);

	// Finally, generate the configuration
	if(g_debugPrints)
		cout << "Generating config file in '"<< outputFileName << "'" <<endl;
	generateXConfig(outputFile, combineFB, framebuffers, gpuInfo, modulesToLoad, extensionSectionOptions, finalKeyboards, finalMice, displayTemplates, usedSLIBridge);

	if(g_debugPrints)
		cout << "Wrote config file '"<< outputFileName << "'" <<endl;
	// done with the parser
	delete parser;

	// done with XML
	VSDOMParser::Finalize();

	return 0;
}
