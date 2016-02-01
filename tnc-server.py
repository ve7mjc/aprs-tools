#!/usr/bin/python

# Share KISS TNC among a number of clients
# Each client is unaware of eachother; They do not cross-post to eachother
# (this may be a feature to change in the future)
# Each client receives complete KISS frames from TNC as they are received
# The TNC will transmit KISS frames from each client as they are received
#
# Matthew Currie VE7MJC
# January 2016
#

import threading
import logging, errno
import socket
import sys
import time
import Queue
import SocketServer
import select

TNC_HOST = "localhost"
TNC_PORT = 4001

SERVER_HOST = "0.0.0.0"
SERVER_PORT = 6700

class Server:
	
	def __init__(self):

		# init server properties
		self.host = SERVER_HOST
		self.port = SERVER_PORT
		self.backlog = 5
		self.size = 1024
		self.server = None
		self.clients = []
		
	def processReceiveBuffer(self, clientBuffer):
		
		frame = ""
		lastEndDelimiterPos = 0
		
		# iterate the data buffer assuming that we are starting
		# with valid data.  We will act on read data once we reach
		# a FEND EOF byte.  If we do not receive one, we leave the
		# buffer untouched to return in a future call with more data
		#
		for i in range(len(self.receiveBuffer[clientBuffer])):
			
			# assemble a frame in case we stumble across
			# the EOF delimiter
			frame += self.receiveBuffer[clientBuffer][i]
			
			# is the current character a SOF/EOF delimiter
			if ord(bytes(self.receiveBuffer[clientBuffer][i])) == 192:
				
				lastEndDelimiterPos = i
				
				# pass on if meets length requirements
				if (len(frame) > 10):
					self.inboundQueues[clientBuffer].put(frame)

				# we clear the frame regardless as FEND may have
				# been at the beginning to flush the buffer
				frame = ""

		# did we locate an EOF?	
		if lastEndDelimiterPos:
			if lastEndDelimiterPos is (len(self.receiveBuffer[clientBuffer])-1):
				# a delimiter was the last character and thus we processed
				# the entire buffer
				self.receiveBuffer[clientBuffer] = ""
			else:
				# we did not process to the end so clear up until the last delimiter
				self.receiveBuffer[clientBuffer] = self.receiveBuffer[clientBuffer][0:lastEndDelimiterPos-1]

	def run(self):
		
		self.receiveBuffer = {}
		self.outboundQueues = {}
		self.inboundQueues = {}
		
		server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		server.setblocking(0)
		try:
			server.bind((self.host,self.port))
			server.listen(5)
		except socket.error, (value,message):
			if server:
				server.close()
			print ">> Could not open socket: " + message
			sys.exit(1)

				
		address = (TNC_HOST, TNC_PORT)
		tncSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		try:
			tncSocket.connect(address)
		except:
			logging.debug("unable to connect to TNC - not trying again")
			sys.exit(1)
		tncSocket.setblocking(False)
			
		self.outboundQueues[tncSocket] = Queue.Queue()
		self.inboundQueues[tncSocket] = Queue.Queue()
		self.receiveBuffer[tncSocket] = ""
		
		# Sockets from which we expect to read
		inputs = [ server, tncSocket ]
		clients = []
		
		# Sockets to which we expect to write
		outputs = [ tncSocket ]
		
		# Outgoing message queues (socket:Queue)
		message_queues = {}

		self.running = True
		print '>> listen on {} port'.format(self.port)
		while self.running:

			# Wait for at least one of the sockets to be ready for processing
			readable, writable, exceptional = select.select(inputs, outputs, inputs)

			# Handle inputs
			for s in readable:
		
				if s is server:
					# A "readable" server socket is ready to accept a connection
					connection, client_address = s.accept()
					connection.setblocking(0)
					self.outboundQueues[connection] = Queue.Queue()
					self.inboundQueues[connection] = Queue.Queue()
					self.receiveBuffer[connection] = ""
					inputs.append(connection)
					outputs.append(connection)
					clients.append(connection)
					print >>sys.stderr, 'new connection from', client_address
											
				else:
					
					data = s.recv(1024)
					if data:
						self.receiveBuffer[s] += data
						self.processReceiveBuffer(s)
					else:
						
						if s is tncSocket:
							print("TNC CONNECTION LOST!!")
							
						# likely disconnection
						# Interpret empty result as closed connection
						logging.debug("client disconnect or error")
						
						print >>sys.stderr, 'closing', client_address, 'after reading no data'
						# Stop listening for input on the connection
						inputs.remove(s)
						if s in outputs:
							outputs.remove(s)
						if s in clients:
							clients.remove(s)
						s.close()
			
						# Remove associated message queues and buffers
						del self.inboundQueues[s]
						del self.outboundQueues[s]
						del self.receiveBuffer[s]
					
					# TODO: account for TNC not being available
					
					# place copies of incoming data into
					# connected clients outgoing buffers
					while not self.inboundQueues[tncSocket].empty():
						frame = self.inboundQueues[tncSocket].get_nowait()
						for client in clients:
							self.outboundQueues[client].put(frame)
							
					# check client outbound buffers and clear them
					# into tnc outbound buffer
					for client in clients:
						while not self.inboundQueues[client].empty():
							frame = self.inboundQueues[client].get_nowait()
							self.outboundQueues[tncSocket].put(frame)

			# Handle outputs
			for s in writable:
	
				# do we have traffic holding for this client?
				# only write traffic to kiss clients
				if (s in clients) or (s is tncSocket):
					if not self.outboundQueues[s].empty():
						try:
							frame = self.outboundQueues[s].get_nowait()
							s.send(frame)
						except Exception, e:
							logging.debug(e)
							
			# Handle "exceptional conditions"
			for s in exceptional:
				print >>sys.stderr, 'handling exceptional condition for', s.getpeername()
				# Stop listening for input on the connection
				inputs.remove(s)
				if s in outputs:
					outputs.remove(s)
				s.close()
		
				# Remove message queue
				del message_queues[s]

		# close all threads
		print("Closing server and threads")
		self.server.close()
		sys.exit(0)


logging.basicConfig(level=logging.DEBUG, format='(%(threadName)-10s) %(message)s',)

server = Server()

try:
	server.run()
except KeyboardInterrupt:
	server.running = False
	print '>> Exit from keyboard. Shut down server'