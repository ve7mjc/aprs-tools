#!/usr/bin/python
#
# Share a KISS TNC among a number of KISS APRS/AX.25 clients
# Creates a single TCP connection to a KISS TNC
# A local TCP server is created and a buffered asynchronous process 
# queues KISS packets between clients and TNC and TNC and clients
# Each client is unaware of eachother; They do not cross-post to eachother
# (this may be a feature to change in the future)
# Each client receives complete KISS frames from TNC as completed
# The TNC will transmit KISS frames from each client as completed
#
# Requires at >= Python 2.7
# The software is not tested in Python3 but is written to be Python3
# compatible for future migration
#
# Matthew Currie VE7MJC
# January 2016
#
# TODO:
# - TNC init command pass-through (this could be done on an alternate TCP
#   port to prevent escape sequences and other risks with the streams
# - Ability to cross-post between clients
# - Log to disk and/or syslog
#

import argparse
#import threading
import logging, errno
import socket
import sys
import time
import Queue
import SocketServer
import select

DEFAULT_TNC_HOST = "localhost"
DEFAULT_TNC_PORT = 4001

DEFAULT_SERVER_HOST = "0.0.0.0"
DEFAULT_SERVER_PORT = 6700

class Server:
	
	def __init__(self, tnc_address, server_address, verbose = False):

		# init server properties
		self.listenHost, self.listenPort = server_address
		self.tncHost, self.tncPort = tnc_address
		
		self.listenPort = int(self.listenPort)
		self.tncPort = int(self.tncPort)
	
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

	def connectToTnc(self):
		# TODO: make non-blocking connection to TNC here
		# and manage persistent connection in the mainloop
		# but do not get stuck blocking at select
		try:
			self.tncSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
			self.tncSocket.setsockopt( socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
			self.tncSocket.connect((self.tncHost,self.tncPort))
			logging.info("Connected to TNC at {}:{}".format(self.tncHost,self.tncPort))
			self.tncSocket.setblocking(False)
			
			self.inputs.append(self.tncSocket)
			self.outputs.append(self.tncSocket)
			self.outboundQueues[self.tncSocket] = Queue.Queue()
			self.inboundQueues[self.tncSocket] = Queue.Queue()
			self.receiveBuffer[self.tncSocket] = ""
			
			self.tncConnected = True
			
		except Exception as e:
			logging.error("Unable to connect to TNC at {}:{}".format(self.tncHost,self.tncPort))
			logging.debug(e)
		
	def run(self):
		
		self.receiveBuffer = {}
		self.outboundQueues = {}
		self.inboundQueues = {}
		self.clients = []
		self.outputs = [] # Sockets to which we expect to write
		self.inputs = [] # Sockets to which we expect to read
		self.tncConnected = False
		
		self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		self.server.setblocking(0)

		try:
			self.server.bind((self.listenHost,self.listenPort))
			self.server.listen(5)
			logging.info("Listening for connections on TCP/{}".format(self.listenPort))
			self.inputs.append(self.server)
		except socket.error, (value,message):
			if self.server:
				self.server.close()
			logging.error("Unable to bind local socket: {}".format(message))
			sys.exit(1)

		self.running = True
		while self.running:

			# Connect to TNC if not connected
			# which will be called each time this
			# loop fires
			if not self.tncConnected:
				self.connectToTnc()

			# Wait for at least one of the sockets to be ready for processing
			# timeout after one second so we can do some housework
			readable, writable, exceptional = select.select(self.inputs, self.outputs, self.inputs, 1)

			# Handle inputs
			for s in readable:
		
				if s is self.server:
					
					# A "readable" server socket is ready to accept a connection
					connection, client_address = s.accept()
					connection.setblocking(0)
					connection.setsockopt( socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
					self.outboundQueues[connection] = Queue.Queue()
					self.inboundQueues[connection] = Queue.Queue()
					self.receiveBuffer[connection] = ""
					
					self.inputs.append(connection)
					self.outputs.append(connection)
					self.clients.append(connection)
					
					logging.info("New client connection from {}".format(client_address))
											
				else:
					
					try:
						data = s.recv(1024)
					except Exception as e:
						# temp, catch if this is a TNC error
						if s is self.tncSocket:
							self.tncConnected = False
							logging.error("Caught exception reading from TNC, assuming disconnected")
						logging.error(e)
						readError = True
						
					if not readError:
					
						self.receiveBuffer[s] += data
						self.processReceiveBuffer(s)
					
					else:
						
						if s is self.tncSocket:

							self.tncConnected = False
							
							self.inputs.remove(s)
							self.outputs.remove(s)
							s.close()
							
							# we maintain our relationship with the tncSocket
							logging.error("TNC connection lost! Reconnecting.")
							time.sleep(1) # arbitrary delay to prevent an explosion
							# lets try to reconnect
							self.connectToTnc()
						
						else:
							
							# likely disconnection
							# Interpret empty result as closed connection
							# we are going to destroy this clients very existence
							logging.info("Client disconnected")				
	
							# Stop listening for input on the connection
							self.inputs.remove(s)
							if s in self.outputs:
								self.outputs.remove(s)
							if s in self.clients:
								self.clients.remove(s)
							s.close()
				
							# Remove associated message queues and buffers
							del self.inboundQueues[s]
							del self.outboundQueues[s]
							del self.receiveBuffer[s]

					# The following actions will continue in absence of a TNC
					# so we may want a buffer timeouto to prevent an explosion
					# once TNC is connected after a period of time
					# one option is to simply purge all the buffers when tncConnected
					# is False
					# NOTE: Had to disable anyways due to queues
					if self.tncConnected:
						
						# place copies of incoming data into
						# connected clients outgoing buffers
						while not self.inboundQueues[self.tncSocket].empty():
							frame = self.inboundQueues[self.tncSocket].get_nowait()
							for client in self.clients:
								self.outboundQueues[client].put(frame)
	
						# check client outbound buffers and clear them
						# into tnc outbound buffer
						for client in self.clients:
							while not self.inboundQueues[client].empty():
								frame = self.inboundQueues[client].get_nowait()
								self.outboundQueues[self.tncSocket].put(frame)

			# Handle outputs
			for s in writable:
	
				# do we have traffic holding for this client?
				# only write traffic to kiss clients
				if (s in self.clients) or (s is self.tncSocket):
					if not self.outboundQueues[s].empty():
						try:
							frame = self.outboundQueues[s].get_nowait()
							s.send(frame)
						except Exception, e:
							logging.error(e)
							
			# Handle "exceptional conditions"
			for s in exceptional:
				logging.error("handling exceptional condition for {}".format(s.getpeername()))
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


DEFAULT_TNC_HOST = "localhost"
DEFAULT_TNC_PORT = 4001

DEFAULT_SERVER_HOST = "0.0.0.0"
DEFAULT_SERVER_PORT = 6700

def main():

	parser = argparse.ArgumentParser(description='Share TNC between multiple clients')
	parser.add_argument('-t', '--host', dest='tnc_host', default=DEFAULT_TNC_HOST, help='network host of TNC')
	parser.add_argument('-p', '--port', dest='tnc_port', default=DEFAULT_TNC_PORT, help='network port of TNC')
	parser.add_argument('-l', '--listen-port', dest='listen_port', default=DEFAULT_SERVER_PORT,help='local client listen port')
	parser.add_argument('-v', dest='verbose', action='store_true', help="increase verbosity of output")
	
	# process supplied arguments
	args = parser.parse_args()
	tncAddress = (args.tnc_host,int(args.tnc_port))
	serverAddress = ("0.0.0.0",int(args.listen_port))
	verbose = args.verbose

	logging.basicConfig(level=logging.DEBUG, format='%(message)s',)
	
	server = Server(tncAddress, serverAddress, verbose)
	try:
		server.run()
  	except KeyboardInterrupt:
		server.server.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass

