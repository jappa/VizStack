import unittest
import vsapi
from pprint import pprint
from pprint import pformat
import sys

ssmConn = None
connectionIsGlobal = False

def doConnect():
	global ssmConn
	ssmConn = vsapi.ResourceAccess()

def doDisconnect():
	global ssmConn
	ssmConn.stop()

def doAllocate(spec):
	global ssmConn
	return ssmConn.allocate(spec)

def doDeallocate(ob):
	global ssmConn
	return ssmConn.deallocate(ob)

def getTemplates(query):
	return ssmConn.getTemplates(query)

def getResources(query):
	return ssmConn.queryResources(query)

def getAllocationList():
	global ssmConn
	return ssmConn.getAllocationList()

class AllocationTestCases(unittest.TestCase):
	def setUp(self):
		global connectionIsGlobal
		if not connectionIsGlobal:
			doConnect()
		self.allocObj = None

		res = getAllocationList()
		self.assertEqual(len(res), 0, "Resources are in allocated state before test starts! Those used up are : %s"%(pformat(res)))

	def freeResources(self):
		if self.allocObj is not None:
			doDeallocate(self.allocObj)
			self.allocObj = None

	def tearDown(self):
		global connectionIsGlobal
		self.freeResources()

		res = getAllocationList()
		self.assertEqual(len(res), 0, "Resources are in allocated state after test ends! Those used up are : %s"%(pformat(res)))

		if not connectionIsGlobal:
			doDisconnect()

	def test_00000_allocate_GPU(self):
		self.allocObj = doAllocate([vsapi.GPU()])

	def test_00001_allocate_GPU0(self):
		self.allocObj = doAllocate([vsapi.GPU(0)])

	def test_00002_allocate_shared_GPU(self):
		g = vsapi.GPU()
		g.setShared(True)
		self.allocObj = doAllocate([g])

	def test_00003_allocate_shared_GPU0(self):
		g = vsapi.GPU(0)
		g.setShared(True)
		self.allocObj = doAllocate([g])

	def test_00004_allocate_one_node_two_GPUs(self):
		self.allocObj = doAllocate([[vsapi.GPU(), vsapi.GPU()]])

	def test_00005_allocate_one_node_three_GPUs(self):
		self.allocObj = doAllocate([[vsapi.GPU(), vsapi.GPU(), vsapi.GPU()]])

	def test_00006_allocate_one_node_four_GPUs(self):
		self.allocObj = doAllocate([[vsapi.GPU(), vsapi.GPU(), vsapi.GPU(), vsapi.GPU()]])

	def test_00007_allocate_separate_node_two_GPUs(self):
		self.allocObj = doAllocate([ [vsapi.GPU()], [vsapi.GPU()]])

	def test_00007_allocate_separate_node_three_GPUs(self):
		self.allocObj = doAllocate([ [vsapi.GPU()], [vsapi.GPU()], [vsapi.GPU()]])

	def test_00007_allocate_separate_node_four_GPUs(self):
		self.allocObj = doAllocate([ [vsapi.GPU()], [vsapi.GPU()], [vsapi.GPU()], [vsapi.GPU()] ])

	def test_00100_allocate_Server(self):
		self.allocObj = doAllocate([vsapi.Server()])

	def test_00101_allocate_Server(self):
		self.allocObj = doAllocate([vsapi.Server(0)])

	def test_00101_allocate_Virtual_Server(self):
		self.allocObj = doAllocate([vsapi.Server(serverType=vsapi.VIRTUAL_SERVER)])

	def test_00200_allocate_GPU_Server(self):
		self.allocObj = doAllocate([ [vsapi.GPU(), vsapi.Server()] ])

	def test_00201_allocate_Server_GPU(self):
		self.allocObj = doAllocate([ [vsapi.Server(), vsapi.GPU()] ])

	def test_00202_allocate_shared_GPU_virtual_Server(self):
		g = vsapi.GPU()
		g.setShared(True)
		self.allocObj = doAllocate([ [g, vsapi.Server(serverType=vsapi.VIRTUAL_SERVER)] ])

	def test_00300_allocate_GPUs_of_all_types(self):
		gpuTypes = getTemplates(vsapi.GPU())
		self.assertTrue(len(gpuTypes)>0)
		allGPUs = getResources(vsapi.GPU())
		self.assertTrue(len(allGPUs)>0)
		validGPUResTypes = map(lambda x: x.getType(), allGPUs)
		self.assertTrue(len(validGPUResTypes)>0)
		for gpu in gpuTypes:
			# Ignore GPUs 
			if gpu.getType() not in validGPUResTypes:
				continue
			self.allocObj = doAllocate([gpu])
			res = self.allocObj.getResources()[0]
			self.assertEqual(res.getType(), gpu.getType(), "Asked for GPU of type '%s', got '%s'"%(gpu.getType(), res.getType()))
			self.freeResources()

	def test_00301_allocate_all_GPUs(self):
		allGPUs = getResources(vsapi.GPU())
		self.assertTrue(len(allGPUs)>0)
		self.allocObj = doAllocate(allGPUs)

	def test_00302_allocate_all_GPUs_one_by_one(self):
		allGPUs = getResources(vsapi.GPU())
		self.assertTrue(len(allGPUs)>0)
		numGPUs = len(allGPUs)
		allocs = []
		for i in range(numGPUs):
			allocObj = doAllocate([vsapi.GPU()])
			allocs.append(allocObj)
		for ob in allocs:
			doDeallocate(ob)

	def test_00303_allocate_all_GPUs_one_by_one_each_separate(self):
		allGPUs = getResources(vsapi.GPU())
		self.assertTrue(len(allGPUs)>0)
		allocs = []
		for gpu in allGPUs:
			allocObj = doAllocate([gpu])
			allocs.append(allocObj)
		for ob in allocs:
			doDeallocate(ob)

	def test_00304_allocate_all_GPUs_each_separate(self):
		allGPUs = getResources(vsapi.GPU())
		self.assertTrue(len(allGPUs)>0)
		for gpu in allGPUs:
			self.allocObj = doAllocate([gpu])
			self.freeResources()

	def test_00305_allocate_one_to_all_GPUs(self):
		allGPUs = getResources(vsapi.GPU())
		self.assertTrue(len(allGPUs)>0)
		for i in range(1, len(allGPUs)):
			self.allocObj = doAllocate(allGPUs[:i])
			self.freeResources()

	def test_00306_allocate_all_GPUs_as_n_gpus(self):
		allGPUs = getResources(vsapi.GPU())
		self.assertTrue(len(allGPUs)>0)
		self.allocObj = doAllocate([vsapi.GPU()]*len(allGPUs))

	def test_00307_allocate_one_to_all_GPUs_as_n_gpus(self):
		allGPUs = getResources(vsapi.GPU())
		self.assertTrue(len(allGPUs)>0)
		for i in range(1, len(allGPUs)):
			self.allocObj = doAllocate([vsapi.GPU()]*i)
			self.freeResources()

	def test_00308_allocate_one_to_all_GPUs_as_n_gpus_as_separate_reslists(self):
		allGPUs = getResources(vsapi.GPU())
		self.assertTrue(len(allGPUs)>0)
		for i in range(1, len(allGPUs)):
			self.allocObj = doAllocate([[vsapi.GPU()]]*i)
			self.freeResources()

	def test_00309_allocate_all_shared_GPUs(self):
		g = vsapi.GPU()
		g.setShared(True)
		allSharedGPUs = getResources(g)
		self.assertTrue(len(allSharedGPUs)>0)
		self.allocObj = doAllocate(allSharedGPUs)

	def test_00310_allocate_all_shared_GPUs_one_by_one(self):
		g = vsapi.GPU()
		g.setShared(True)
		allSharedGPUs = getResources(g)
		self.assertTrue(len(allSharedGPUs)>0)
		allocs = []
		for i in range(1, len(allSharedGPUs)):
			allocObj = doAllocate([g])
			allocs.append(allocObj)
		for ob in allocs:
			doDeallocate(ob)

	def test_00310_allocate_all_shared_GPUs_one_by_one_to_limit(self):
		g = vsapi.GPU()
		g.setShared(True)
		allSharedGPUs = getResources(g)
		self.assertTrue(len(allSharedGPUs)>0)
		allocs = []
		for i in range(1, len(allSharedGPUs)):
			for j in range(allSharedGPUs[i].getShareLimit()):
				allocObj = doAllocate([g])
				allocs.append(allocObj)
		for ob in allocs:
			doDeallocate(ob)

	def test_00311_allocate_all_resources(self):
		allRes = getResources(vsapi.GPU())+getResources(vsapi.Server())+getResources(vsapi.Keyboard())+getResources(vsapi.Mouse())+getResources(vsapi.SLI())
		self.assertTrue(len(allRes)>0)
		self.allocObj = doAllocate(allRes)

	def test_00312_allocate_all_GPUs_each_separate_with_server(self):
		allGPUs = getResources(vsapi.GPU())
		self.assertTrue(len(allGPUs)>0)
		allocs = []
		for gpu in allGPUs:
			# allocate each GPU with additional server on the same node
			# this is what apps will use
			allocObj = doAllocate([ [gpu, vsapi.Server() ]])
			allocs.append(allocObj)
		for ob in allocs:
			doDeallocate(ob)

	def test_00313_allocate_all_GPUs_with_server(self):
		allGPUs = getResources(vsapi.GPU())
		self.assertTrue(len(allGPUs)>0)
		resList = []
		for gpu in allGPUs:
			resList.append([ gpu, vsapi.Server() ])
		self.allocObj = doAllocate(resList)

	def test_00314_allocate_all_GPUs_with_server_and_virtual_server(self):
		allGPUs = getResources(vsapi.GPU())
		self.assertTrue(len(allGPUs)>0)
		resList = []
		for gpu in allGPUs:
			resList.append([gpu, vsapi.Server(), vsapi.Server(serverType=vsapi.VIRTUAL_SERVER)])
		self.allocObj = doAllocate(resList)

	def test_00315_allocate_all_shared_GPUs_with_virtual_server(self):
		g = vsapi.GPU()
		g.setShared(True)
		allSharedGPUs = getResources(g)
		self.assertTrue(len(allSharedGPUs)>0)
		resList = []
		for gpu in allSharedGPUs:
			for i in range(gpu.getShareLimit()):
				resList.append([g, vsapi.Server(serverType=vsapi.VIRTUAL_SERVER)])
		self.allocObj = doAllocate(resList)

	def test_00315_allocate_all_shared_GPUs_with_dof3_reference_and_virtual_server(self):
		g = vsapi.GPU()
		g.setShared(True)
		allSharedGPUs = getResources(g)
		self.assertTrue(len(allSharedGPUs)>0)
		resList = []
		for gpu in allSharedGPUs:
			gpu.setShared(True)
			for i in range(gpu.getShareLimit()):
				# the difference between this test and the previous one is that 
				# it asks for a particular shared GPU. The tests in the VizStack
				# framework check DOF=0 resources, and these must not report errors
				resList.append([gpu, vsapi.Server(serverType=vsapi.VIRTUAL_SERVER)])
		self.allocObj = doAllocate(resList)

	def test_00316_allocate_all_tvnc_shared_sessions(self):
		g = vsapi.GPU()
		g.setShared(True)
		allSharedGPUs = getResources(g)
		self.assertTrue(len(allSharedGPUs)>0)
		allocs = []
		for gpu in allSharedGPUs:
			gpu.setShared(True)
			for i in range(gpu.getShareLimit()):
				allocObj = doAllocate([ [ g, vsapi.Server(serverType=vsapi.VIRTUAL_SERVER)] ])
				allocs.append(allocObj)

		failed = False
		try:
			allocObj = doAllocate([ [ g, vsapi.Server(serverType=vsapi.VIRTUAL_SERVER) ] ])
			allocs.append(allocObj)
			failed = True
		except vsapi.VizError, e:
			pass

		for ob in allocs:
			doDeallocate(ob)

		if failed:
			self.fail("Was able to allocate a shared TVNC session extra compared to what is possible (%d)"%(len(allocs)-1))

	def test_00317_allocate_all_tvnc_shared_sessions_fixed_gpus(self):
		g = vsapi.GPU()
		g.setShared(True)
		allSharedGPUs = getResources(g)
		self.assertTrue(len(allSharedGPUs)>0)
		allocs = []
		for gpu in allSharedGPUs:
			gpu.setShared(True)
			for i in range(gpu.getShareLimit()):
				allocObj = doAllocate([ [ gpu, vsapi.Server(serverType=vsapi.VIRTUAL_SERVER)] ])
				allocs.append(allocObj)

		failed = False
		try:
			allocObj = doAllocate([ [ g, vsapi.Server(serverType=vsapi.VIRTUAL_SERVER) ] ])
			allocs.append(allocObj)
			failed = True
		except vsapi.VizError, e:
			pass

		for ob in allocs:
			doDeallocate(ob)

		if failed:
			self.fail("Was able to allocate a shared TVNC session extra compared to what is possible (%d)"%(len(allocs)-1))

	def test_00318_allocate_all_rgs_sessions_fixed_servers(self):
		s = vsapi.Server(0)
		allRGSServers = getResources(s)
		self.assertTrue(len(allRGSServers)>0)
		allocs = []
		for srv in allRGSServers:
			allocObj = doAllocate([ [ srv, vsapi.GPU(0) ] ])
			allocs.append(allocObj)

		failed = False
		try:
			allocObj = doAllocate([ [ s, vsapi.GPU(0) ] ])
			allocs.append(allocObj)
			failed = True
		except vsapi.VizError, e:
			pass

		for ob in allocs:
			doDeallocate(ob)

		if failed:
			self.fail("Was able to allocate an RGS session extra compared to what is possible (%d)"%(len(allRGSServers)))

	def test_00319_allocate_all_rgs_sessions(self):
		s = vsapi.Server(0)
		allRGSServers = getResources(s)
		self.assertTrue(len(allRGSServers)>0)
		allocs = []
		for srv in allRGSServers:
			allocObj = doAllocate([ [ s, vsapi.GPU(0) ] ])
			allocs.append(allocObj)

		failed = False
		try:
			allocObj = doAllocate([ [ s, vsapi.GPU(0) ] ])
			allocs.append(allocObj)
			failed = True
		except vsapi.VizError, e:
			pass

		for ob in allocs:
			doDeallocate(ob)
		if failed:
			self.fail("Was able to allocate an RGS session extra compared to what is possible (%d)"%(len(allRGSServers)))

if __name__ == '__main__':
	tl = unittest.TestLoader()
	#tl.sortTestMethodsUsing(None) # disable sorting of tests
	#suite1 = AllocationTestCases('test_00310_allocate_all_shared_GPUs_one_by_one')
	suite1 = tl.loadTestsFromTestCase(AllocationTestCases)
	suite2 = tl.loadTestsFromTestCase(AllocationTestCases)

	print 'Running allcoation tests with SSM connection/disconnection on every test'
	connectionIsGlobal = False
	#unittest.TextTestRunner(verbosity=2).run(suite1)
	unittest.TextTestRunner().run(suite1)

	print 'Running allcoation tests with a global SSM connection'
	connectionIsGlobal = True
	doConnect()
	#unittest.TextTestRunner(verbosity=2).run(suite2)
	unittest.TextTestRunner().run(suite2)
	doDisconnect()

