#!/usr/bin/python

# connect to this socketserver as if you are connecting
# to a KISS TNC and begin receiving pre-recorded data
# with KISS framing

import socket
import SocketServer
import threading
import sys
import time

# APRS Test data
# Must be KISS framed
APRS_KISS_DATA_FILE = "aprs-test.dat"

# Simulate approximately 1200 bps
# 1200 baud per second is no faster than 120 bytes per second
# This also ensures each byte may likely end up in its own TCP
# packet and thus ensure buffering and tokenizing is occuring
# properly on the remote client.  No cheating!
INTER_BYTE_DELAY_SECS = 1 / (1200 / 10)
INTER_PACKET_DELAY_SECS = 1

HOST, PORT = "localhost", 5000

# FEND = b'0xC0'

class ThreadedTCPRequestHandler(SocketServer.BaseRequestHandler):

	def handle(self):
		cur_thread = threading.current_thread()
		
		# Next FEND packet will be a SOF
		startNext = True
		
		try:
			dataFile = open(APRS_KISS_DATA_FILE, "rb")
			data = dataFile.read()
			dataFile.close()
		except:
			print("unable to open {0}".format(APRS_KISS_DATA_FILE))
		
		startNext = True
		try:		
			for i in range(len(data)):
				self.request.send(data[i])
				
				if ord(bytes(data[i])) == 192:
					if startNext:
						startNext = False
					else:
						startNext = True
						time.sleep(INTER_PACKET_DELAY_SECS)
	
				time.sleep(INTER_BYTE_DELAY_SECS)
		except:
			print("client disconnected")
		
class ThreadedTCPServer(SocketServer.ThreadingMixIn, SocketServer.TCPServer):
	pass

class MyTCPHandler(SocketServer.BaseRequestHandler):
	"""
	The RequestHandler class for our server.

	It is instantiated once per connection to the server, and must
	override the handle() method to implement communication to the
	client.
	"""

	def handle(self):
		# self.request is the TCP socket connected to the client
		self.data = self.request.recv(1024).strip()
		print "{} wrote:".format(self.client_address[0])
		print self.data
		# just send back the same data, but upper-cased
		self.request.sendall(self.data.upper())


if __name__ == "__main__":
	
	server = ThreadedTCPServer((HOST, PORT), ThreadedTCPRequestHandler)

	# Start a thread with the server -- that thread will then start one
	# more thread for each request
	server_thread = threading.Thread(target=server.serve_forever)
	# Exit the server thread when the main thread terminates
	server_thread.daemon = True
	server_thread.start()
	print("waiting for connections on {0}:{1}".format(HOST, PORT)) 

	# loop until we kill
	try:
		while True:
			time.sleep(1)
	except:
		print("Closing server...")
		server.shutdown()
		server.server_close()
		sys.exit()