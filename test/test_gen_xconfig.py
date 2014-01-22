import unittest
import vsapi
from pprint import pprint
from pprint import pformat
from os import system
import os

input_path = "input-sconfig.xml"
output_path = "output-sconfig.conf"
global_args = "--no-ssm"

class GenXConfigTestCases(unittest.TestCase):
	def setUp(self):
		# One node
		node = vsapi.VizNode(hostName="localhost", model='Test')
		# GPU0 is a FX5800 with a phony Bus ID
		gpu0 = vsapi.GPU(0, model='Quadro FX 5800', busID='PCI:1:0:0')
		gpu0.setUseScanOut(True)
		node.addResource(gpu0)
		# GPU1 is a FX5800 with a phony Bus ID
		gpu1 = vsapi.GPU(1, model='Quadro FX 5800', busID='PCI:2:0:0')
		gpu1.setUseScanOut(True)
		node.addResource(gpu1)
		# GPU0 & GPU1 are part of a quadroplex
		sli0 = vsapi.SLI(0, sliType='quadroplex', gpu0=0, gpu1=1)
		node.addResource(sli0)
		
		gpu1 = vsapi.GPU(2, model='Quadro NVS 420', busID='PCI:3:0:0')
		gpu1.setUseScanOut(True)
		node.addResource(gpu1)

		# Generate a node config file for this
		self.node_config_path = 'input-node-config.xml'
		f = open(self.node_config_path,'w')
		print >>f,"""
		<nodeconfig>
			<nodes>
				%s
			</nodes>
		</nodeconfig>"""%(node.serializeToXML())
		f.close()

	def tearDown(self):
		global input_path, output_path
		try:
			os.unlink(self.node_config_path)
		except:
			pass
		try:
			os.unlink(input_path)
		except:
			pass
		try:
			os.unlink(output_path)
		except:
			pass

	def genValidConfigFile(self, srv):
		global input_path, output_path, global_args

		input_file = open(input_path, 'w')
		print >>input_file, srv.serializeToXML()
		input_file.close()

		ret = system("/opt/vizstack/bin/vs-generate-xconfig %s --nodeconfig=%s --input=%s --output=%s"%(global_args, self.node_config_path, input_path, output_path))
		self.assertEqual(ret, 0, "Failed to generate valid configuration")

	def showGeneratedConfigFile(self):
		global output_path
		system("cat %s"%(output_path))

	def test_success_00000_1_gpu_vfb(self):
		srv = vsapi.Server(0)
		scr = vsapi.Screen(0)
		gpu = vsapi.GPU(0)
		scr.setFBProperty('resolution', [1024,768])
		scr.setGPU(gpu)
		srv.addScreen(scr)
		self.genValidConfigFile(srv)

	def test_success_00001_1_gpu_1scanout(self):
		srv = vsapi.Server(0)
		scr = vsapi.Screen(0)
		gpu = vsapi.GPU(0)
		gpu.setScanout(2, 'HP LP2065') # Configure scanout 2
		scr.setGPU(gpu)
		srv.addScreen(scr)
		self.genValidConfigFile(srv)

	def test_success_00001_1_gpu_1scanout(self):
		srv = vsapi.Server(0)
		scr = vsapi.Screen(0)
		gpu = vsapi.GPU(2) # Quadro NVS 420
		gpu.setScanout(3, 'HP LP2065') # Configure scanout 3
		scr.setGPU(gpu)
		srv.addScreen(scr)
		self.genValidConfigFile(srv)

	def test_success_00002_1_gpu_2scanout(self):
		srv = vsapi.Server(0)
		scr = vsapi.Screen(0)
		gpu = vsapi.GPU(0)
		gpu.setScanout(0, 'HP LP2065')
		gpu.setScanout(1, 'HP LP2065')
		scr.setGPU(gpu)
		srv.addScreen(scr)
		self.genValidConfigFile(srv)

	def test_success_00002_1_gpu_2scanout_nvs420_sdvi(self):
		srv = vsapi.Server(0)
		scr = vsapi.Screen(0)
		gpu = vsapi.GPU(2) # NVS 420
		gpu.setScanout(0, 'HP LP2065')
		gpu.setScanout(1, 'HP LP2065')
		scr.setGPU(gpu)
		srv.addScreen(scr)
		self.genValidConfigFile(srv)

	def test_success_00002_1_gpu_2scanout_nvs420_dp(self):
		srv = vsapi.Server(0)
		scr = vsapi.Screen(0)
		gpu = vsapi.GPU(2) # NVS 420
		gpu.setScanout(2, 'HP LP2065')
		gpu.setScanout(3, 'HP LP2065')
		scr.setGPU(gpu)
		srv.addScreen(scr)
		self.genValidConfigFile(srv)

	def test_success_00003_1_gpu_2scanout_2x1(self):
		srv = vsapi.Server(0)
		scr = vsapi.Screen(0)
		gpu = vsapi.GPU(0)
		gpu.setScanout(0, 'HP LP2065')
		gpu.setScanout(1, 'HP LP2065', outputX=1600, outputY=0)
		scr.setGPU(gpu)
		srv.addScreen(scr)
		self.genValidConfigFile(srv)

	def test_success_00004_1_gpu_2scanout_1x2(self):
		srv = vsapi.Server(0)
		scr = vsapi.Screen(0)
		gpu = vsapi.GPU(0)
		gpu.setScanout(0, 'HP LP2065')
		gpu.setScanout(1, 'HP LP2065', outputX=0, outputY=1200)
		scr.setGPU(gpu)
		srv.addScreen(scr)
		self.genValidConfigFile(srv)

	def test_success_00005_1_gpu_2scanout_2x1_horiz_overalap(self):
		srv = vsapi.Server(0)
		scr = vsapi.Screen(0)
		gpu = vsapi.GPU(0)
		gpu.setScanout(0, 'HP LP2065')
		gpu.setScanout(1, 'HP LP2065', outputX=1590, outputY=0)
		scr.setGPU(gpu)
		srv.addScreen(scr)
		self.genValidConfigFile(srv)

	def test_success_00006_1_gpu_2scanout_1x2_vert_overlap(self):
		srv = vsapi.Server(0)
		scr = vsapi.Screen(0)
		gpu = vsapi.GPU(0)
		gpu.setScanout(0, 'HP LP2065')
		gpu.setScanout(1, 'HP LP2065', outputX=0, outputY=1190)
		scr.setGPU(gpu)
		srv.addScreen(scr)
		self.genValidConfigFile(srv)

	def test_success_00007_1_gpu_second_gpu_vfb(self):
		srv = vsapi.Server(0)
		scr = vsapi.Screen(0)
		gpu = vsapi.GPU(1) # configure the second GPU
		scr.setFBProperty('resolution', [1024,768])
		scr.setGPU(gpu)
		srv.addScreen(scr)
		self.genValidConfigFile(srv)

	def test_success_00007_1_gpu_two_vfb(self):
		# One server, one GPU, but two virtual screens
		# on the same GPU
		srv = vsapi.Server(0)
		gpu = vsapi.GPU(0)

		scr0 = vsapi.Screen(0)
		scr0.setFBProperty('resolution', [1024,768])
		scr0.setGPU(gpu)
		srv.addScreen(scr0)

		scr1 = vsapi.Screen(1)
		scr1.setFBProperty('resolution', [1024,768])
		scr1.setGPU(gpu)
		srv.addScreen(scr1)

		self.genValidConfigFile(srv)

	def test_success_00008_2_gpu_vfb(self):
		srv = vsapi.Server(0)

		scr0 = vsapi.Screen(0)
		gpu0 = vsapi.GPU(0)
		scr0.setFBProperty('resolution', [1024,768])
		scr0.setGPU(gpu0)
		srv.addScreen(scr0)

		scr1 = vsapi.Screen(1)
		gpu1 = vsapi.GPU(1)
		scr1.setFBProperty('resolution', [1024,768])
		scr1.setGPU(gpu1)
		srv.addScreen(scr1)

		self.genValidConfigFile(srv)

	def test_success_00009_2_gpu_single_scanout(self):
		srv = vsapi.Server(0)

		scr0 = vsapi.Screen(0)
		gpu0 = vsapi.GPU(0)
		gpu0.setScanout(0, 'HP LP2065')
		scr0.setGPU(gpu0)
		srv.addScreen(scr0)

		scr1 = vsapi.Screen(1)
		gpu1 = vsapi.GPU(1)
		gpu1.setScanout(0, 'HP LP2065')
		scr1.setGPU(gpu1)
		srv.addScreen(scr1)

		self.genValidConfigFile(srv)

	def test_success_00010_2_gpu_single_scanout_2x1(self):
		srv = vsapi.Server(0)

		scr0 = vsapi.Screen(0)
		gpu0 = vsapi.GPU(0)
		gpu0.setScanout(0, 'HP LP2065')
		scr0.setGPU(gpu0)
		scr0.setFBProperty('position',[0,0])
		srv.addScreen(scr0)

		scr1 = vsapi.Screen(1)
		gpu1 = vsapi.GPU(1)
		gpu1.setScanout(0, 'HP LP2065')
		scr1.setFBProperty('position',[1600,0])
		scr1.setGPU(gpu1)
		srv.addScreen(scr1)

		self.genValidConfigFile(srv)

	def test_success_00011_2_gpu_single_scanout_1x2(self):
		srv = vsapi.Server(0)

		scr0 = vsapi.Screen(0)
		gpu0 = vsapi.GPU(0)
		gpu0.setScanout(0, 'HP LP2065')
		scr0.setGPU(gpu0)
		scr0.setFBProperty('position',[0,0])
		srv.addScreen(scr0)

		scr1 = vsapi.Screen(1)
		gpu1 = vsapi.GPU(1)
		gpu1.setScanout(0, 'HP LP2065')
		scr1.setFBProperty('position',[0,1200])
		scr1.setGPU(gpu1)
		srv.addScreen(scr1)

		self.genValidConfigFile(srv)

	def test_success_00012_2_gpu_single_scanout_2x1_xinerama(self):
		srv = vsapi.Server(0)

		scr0 = vsapi.Screen(0)
		gpu0 = vsapi.GPU(0)
		gpu0.setScanout(0, 'HP LP2065')
		scr0.setGPU(gpu0)
		scr0.setFBProperty('position',[0,0])
		srv.addScreen(scr0)

		scr1 = vsapi.Screen(1)
		gpu1 = vsapi.GPU(1)
		gpu1.setScanout(0, 'HP LP2065')
		scr1.setFBProperty('position',[1600,0])
		scr1.setGPU(gpu1)
		srv.addScreen(scr1)

		srv.combineScreens(True)
		self.genValidConfigFile(srv)

	def test_success_00013_2_gpu_single_scanout_1x2_xinerama(self):
		srv = vsapi.Server(0)

		scr0 = vsapi.Screen(0)
		gpu0 = vsapi.GPU(0)
		gpu0.setScanout(0, 'HP LP2065')
		scr0.setGPU(gpu0)
		scr0.setFBProperty('position',[0,0])
		srv.addScreen(scr0)

		scr1 = vsapi.Screen(1)
		gpu1 = vsapi.GPU(1)
		gpu1.setScanout(0, 'HP LP2065')
		scr1.setFBProperty('position',[0,1200])
		scr1.setGPU(gpu1)
		srv.addScreen(scr1)

		srv.combineScreens(True)
		self.genValidConfigFile(srv)
		#self.showGeneratedConfigFile()

	def test_success_00015_2_gpu_3x1_xinerama(self):
		srv = vsapi.Server(0)

		# 2 screens on first GPU, 1 on the second GPU
		# all placed in a horizontal layout
		scr0 = vsapi.Screen(0)
		gpu0 = vsapi.GPU(0)
		gpu0.setScanout(0, 'HP LP2065')
		gpu0.setScanout(1, 'HP LP2065', outputX=1600,outputY=0)
		scr0.setGPU(gpu0)
		scr0.setFBProperty('position',[0,0])
		srv.addScreen(scr0)

		scr1 = vsapi.Screen(1)
		gpu1 = vsapi.GPU(1)
		gpu1.setScanout(0, 'HP LP2065')
		scr1.setFBProperty('position',[1600*2,0])
		scr1.setGPU(gpu1)
		srv.addScreen(scr1)

		srv.combineScreens(True)
		self.genValidConfigFile(srv)

	def test_success_00016_2_gpu_2x2_xinerama(self):
		srv = vsapi.Server(0)

		# 2 screens on first GPU, 2 on the second GPU
		# placed one below the other
		scr0 = vsapi.Screen(0)
		gpu0 = vsapi.GPU(0)
		gpu0.setScanout(0, 'HP LP2065')
		gpu0.setScanout(1, 'HP LP2065', outputX=1600,outputY=0)
		scr0.setGPU(gpu0)
		scr0.setFBProperty('position',[0,0])
		srv.addScreen(scr0)

		scr1 = vsapi.Screen(1)
		gpu1 = vsapi.GPU(1)
		gpu1.setScanout(0, 'HP LP2065')
		gpu1.setScanout(1, 'HP LP2065', outputX=1600, outputY=0)
		scr1.setFBProperty('position',[0,1200])
		scr1.setGPU(gpu1)
		srv.addScreen(scr1)

		srv.combineScreens(True)
		self.genValidConfigFile(srv)

	def test_success_00017_2_gpu_4x1_xinerama(self):
		srv = vsapi.Server(0)

		# 2 screens on first GPU, 2 on the second GPU
		# all placed in a horizontal layout
		scr0 = vsapi.Screen(0)
		gpu0 = vsapi.GPU(0)
		gpu0.setScanout(0, 'HP LP2065')
		gpu0.setScanout(1, 'HP LP2065', outputX=1600,outputY=0)
		scr0.setGPU(gpu0)
		scr0.setFBProperty('position',[0,0])
		srv.addScreen(scr0)

		scr1 = vsapi.Screen(1)
		gpu1 = vsapi.GPU(1)
		gpu1.setScanout(0, 'HP LP2065')
		gpu1.setScanout(1, 'HP LP2065', outputX=1600, outputY=0)
		scr1.setFBProperty('position',[1600*2,0])
		scr1.setGPU(gpu1)
		srv.addScreen(scr1)

		srv.combineScreens(True)
		self.genValidConfigFile(srv)

	def test_success_00018_2_gpu_sli(self):
		srv = vsapi.Server(0)
		scr = vsapi.Screen(0)
		gpu0 = vsapi.GPU(0)
		gpu0.setScanout(0, 'HP LP2065')
		gpu1 = vsapi.GPU(1)
		scr.setGPUs([gpu0, gpu1])
		sli = vsapi.SLI(0)
		scr.setGPUCombiner(sli)
		srv.addScreen(scr)

		self.genValidConfigFile(srv)
		#self.showGeneratedConfigFile()

	def test_success_00019_2_gpu_sli_SFR(self):
		srv = vsapi.Server(0)
		scr = vsapi.Screen(0)
		gpu0 = vsapi.GPU(0)
		gpu0.setScanout(0, 'HP LP2065')
		gpu1 = vsapi.GPU(1)
		scr.setGPUs([gpu0, gpu1])
		sli = vsapi.SLI(0)
		sli.setMode("SFR")
		scr.setGPUCombiner(sli)
		srv.addScreen(scr)

		self.genValidConfigFile(srv)
		#self.showGeneratedConfigFile()

	def test_success_00020_2_gpu_sli_AFR(self):
		srv = vsapi.Server(0)
		scr = vsapi.Screen(0)
		gpu0 = vsapi.GPU(0)
		gpu0.setScanout(0, 'HP LP2065')
		gpu1 = vsapi.GPU(1)
		scr.setGPUs([gpu0, gpu1])
		sli = vsapi.SLI(0)
		sli.setMode("AFR")
		scr.setGPUCombiner(sli)
		srv.addScreen(scr)

		self.genValidConfigFile(srv)
		#self.showGeneratedConfigFile()

	def test_success_00021_2_gpu_sli_AA(self):
		srv = vsapi.Server(0)
		scr = vsapi.Screen(0)
		gpu0 = vsapi.GPU(0)
		gpu0.setScanout(0, 'HP LP2065')
		gpu1 = vsapi.GPU(1)
		scr.setGPUs([gpu0, gpu1])
		sli = vsapi.SLI(0)
		sli.setMode("AA")
		scr.setGPUCombiner(sli)
		srv.addScreen(scr)

		self.genValidConfigFile(srv)
		#self.showGeneratedConfigFile()

	def test_success_00022_2_gpu_sli_mosaic_2x1(self):
		srv = vsapi.Server(0)
		scr = vsapi.Screen(0)
		gpu0 = vsapi.GPU(0)
		gpu0.setScanout(0, 'HP LP2065')
		gpu1 = vsapi.GPU(1)
		gpu1.setScanout(0, 'HP LP2065',outputX=1600,outputY=0)
		scr.setGPUs([gpu0, gpu1])
		sli = vsapi.SLI(0)
		sli.setMode("mosaic")
		scr.setGPUCombiner(sli)
		srv.addScreen(scr)

		self.genValidConfigFile(srv)
		#self.showGeneratedConfigFile()

	def test_success_00023_2_gpu_sli_mosaic_3x1(self):
		srv = vsapi.Server(0)
		scr = vsapi.Screen(0)
		gpu0 = vsapi.GPU(0)
		gpu0.setScanout(0, 'HP LP2065')
		gpu0.setScanout(1, 'HP LP2065', outputX=1600,outputY=0)
		gpu1 = vsapi.GPU(1)
		gpu1.setScanout(0, 'HP LP2065',outputX=1600*2,outputY=0)
		scr.setGPUs([gpu0, gpu1])
		sli = vsapi.SLI(0)
		sli.setMode("mosaic")
		scr.setGPUCombiner(sli)
		srv.addScreen(scr)

		self.genValidConfigFile(srv)
		#self.showGeneratedConfigFile()

	def test_success_00024_2_gpu_sli_mosaic_4x1(self):
		srv = vsapi.Server(0)
		scr = vsapi.Screen(0)
		gpu0 = vsapi.GPU(0)
		gpu0.setScanout(0, 'HP LP2065')
		gpu0.setScanout(1, 'HP LP2065', outputX=1600,outputY=0)
		gpu1 = vsapi.GPU(1)
		gpu1.setScanout(0, 'HP LP2065',outputX=1600*2,outputY=0)
		gpu1.setScanout(1, 'HP LP2065', outputX=1600*3,outputY=0)
		scr.setGPUs([gpu0, gpu1])
		sli = vsapi.SLI(0)
		sli.setMode("mosaic")
		scr.setGPUCombiner(sli)
		srv.addScreen(scr)

		self.genValidConfigFile(srv)
		#self.showGeneratedConfigFile()

	def test_success_00025_2_gpu_sli_mosaic_2x2(self):
		srv = vsapi.Server(0)
		scr = vsapi.Screen(0)
		gpu0 = vsapi.GPU(0)
		gpu0.setScanout(0, 'HP LP2065')
		gpu0.setScanout(1, 'HP LP2065', outputX=1600,outputY=0)
		gpu1 = vsapi.GPU(1)
		gpu1.setScanout(0, 'HP LP2065',outputX=0,outputY=1200)
		gpu1.setScanout(1, 'HP LP2065', outputX=1600,outputY=1200)
		scr.setGPUs([gpu0, gpu1])
		sli = vsapi.SLI(0)
		sli.setMode("mosaic")
		scr.setGPUCombiner(sli)
		srv.addScreen(scr)

		self.genValidConfigFile(srv)
		#self.showGeneratedConfigFile()

	def test_failure_00001_1_gpu_1scanout(self):
		srv = vsapi.Server(0)
		scr = vsapi.Screen(0)
		gpu = vsapi.GPU(0)
		gpu.setScanout(3, 'HP LP2065') # Configure scanout. This would fail since the 5800 does not have the third scanout
		scr.setGPU(gpu)
		srv.addScreen(scr)
		try:
			print 'Trying to setup invalid port index 3 for scanout'
			self.genValidConfigFile(srv)
			self.fail("Succeeded to setup scanout 3 - this should have failed")
		except:
			# If we come here, there is failure -which is right
			print "Failed to generate config- the correct result right"

	def test_failure_00002_1_gpu_1scanout(self):
		srv = vsapi.Server(0)
		scr = vsapi.Screen(0)
		gpu = vsapi.GPU(0)
		# configure 3 scanouts - this should also fail
		gpu.setScanout(0, 'HP LP2065') 
		gpu.setScanout(1, 'HP LP2065') 
		gpu.setScanout(2, 'HP LP2065') 
		scr.setGPU(gpu)
		srv.addScreen(scr)
		try:
			print 'Trying to setup three scanouts on the GPU'
			self.genValidConfigFile(srv)
			self.fail("Succeeded to setup three scanouts - this should have failed")
		except:
			# If we come here, there is failure -which is right
			print "Failed to generate config - the correct result right"

if __name__ == '__main__':
	tl = unittest.TestLoader()
	suite1 = tl.loadTestsFromTestCase(GenXConfigTestCases)

	print 'Running X config generation tests'
	unittest.TextTestRunner().run(suite1)

