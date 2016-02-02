#!/usr/bin/python

import os
import datetime
import gps
import time
import socket

TNC_HOST = "127.0.0.1"
#TNC_PORT = 6700
TNC_PORT = 4001

CALLSIGN = "VE7MJC-9"

BEACON_FREQUENCY_STATIONARY_SECS =  60 * 20 # 20 minutes
BEACON_FREQUENCY_MOTION_MINIMUM_SECS = 60 # 1 minute
BEACON_FREQUENCY_MOTION_MAXIMUM_SECS = 10 # 10 seconds
BEACON_DISTANCE_MINIMUM_METERS = 500 # 500 meters
BEACON_MOTION_SPEED_MINIMUM_KPH = 5 # GPS can drift a bit
BEACON_COURSE_CHANGE_TRIGGER = 20 # 20 degrees

KISS_EOF = b'\x12'

# Build TNC2 formatted position packet
# which we will pass through FAP perl parse
# external script to produce wire AX.25 formatted
# frame wrapped with KISS SOF
def buildPacket(pvt):
	
	# jeep
	sym_set = "/"
	sym_ico = "j"
	
	source_callsign = CALLSIGN
	info = "Black Blazer; Custom APRS Client; ve7mjc.com"
	
	packet = source_callsign + ">"
	packet += "APZMJC"
	packet += ",WIDE2-2:@"
	
	# / denotes local date-time
	packet += datetime.datetime.now().strftime("%d%H%Mz")
	
	lat, lon = pvt.toDecimalMinutesString()
	
	packet += lat
	packet += sym_set
	packet += lon
	packet += sym_ico

#	if (pvt.course is not None) and (pvt.speed is not None):
#		course = pvt.course
#		if pvt.speed < 1: 
#			course = 0
#		packet += "{:d}/".format(int(course))
#		packet += "{:d}/".format(int(pvt.speed))

	packet += info
	
	return packet

# careful, this does not escape any EOF bytes
# which may be present in the string
def kiss_wrap(packet):
	print("before: {}".format(len(packet)))
	print("after: {}".format(len("{}{}{}".format(KISS_EOF,packet,KISS_EOF))))
	return "{}{}{}".format(KISS_EOF,packet,KISS_EOF)

def init_d710():
	try:
		command = os.path.dirname(os.path.realpath(__file__)) + '/init-d710.sh'
		output = os.popen(command).read()
	except Exception as e:
		output = ""
		print(e)
	return output

def tnc2_to_ax25(packet):
	try:
		command = os.path.dirname(os.path.realpath(__file__)) + '/tnc2toax25.pl \"' + packet + '\"'
		output = os.popen(command).read()
	except Exception as e:
		output = ""
		print(e)
	return output
	
def parse(packet):
	try:
		command = os.path.dirname(os.path.realpath(__file__)) + '/parse.pl \"' + packet + '\"'
		output = os.popen(command).read()
	except Exception as e:
		output = ""
		print(e)
	return output

class pvt():
	
	# constructor access decimal degrees positions
	def __init__(self, latitude, longitude, course=0, speed=0):
		self.latitude = latitude
		self.longitude = longitude
		self.course = course
		self.speed = speed * gps.MPS_TO_KPH
	
	# return position in decimal minutes string
	# for specific purpose of APRS position packets
	def toDecimalMinutesString(self):
		
		# latitude
		if (self.latitude >= 0): hem = "N"
		else: hem = "S"
		degrees = int(abs(self.latitude))
		minutes = ((abs(self.latitude) - degrees) * 60)
		lat = "{:d}{:05.2f}{}".format(degrees,minutes,hem)
		
		# longitude
		if (self.longitude >= 0): hem = "E"
		else: hem = "W"
		degrees = int(abs(self.longitude))
		minutes = ((abs(self.longitude) - degrees) * 60)
		lon = "{:d}{:05.2f}{}".format(degrees,minutes,hem)

		return (lat,lon)

currentPvt = None
lastBeaconPvt = None
lastBeacon = None

# beacon while obeying network rate limits
# unless force is True
def beacon(pvt=None, force=False):
	
	if pvt is None: pvt = currentPvt
	
	global lastBeacon
	
	shouldBeacon = False
	beaconTrigger = "UNKNOWN"
	
	if lastBeacon is None:
		shouldBeacon = True
		beaconTrigger = "FIRST_BEACON"
	else:
		
		# lets figure out whether it is courteous to beacon
		elapsedTime = (datetime.datetime.now() - lastBeacon).total_seconds()

		# wander
		if elapsedTime > BEACON_FREQUENCY_STATIONARY_SECS:
			beaconTrigger = "STATIONARY_MINIMUM"
			shouldBeacon = True
		elif pvt.speed >= BEACON_MOTION_SPEED_MINIMUM_KPH:
			# we are in motion
			if elapsedTime >= BEACON_FREQUENCY_MOTION_MINIMUM_SECS:
				beaconTrigger = "MOTION_MINIMUM"
				shouldBeacon = True
			elif (abs(lastBeaconPvt.course - currentPvt.course) >= BEACON_COURSE_CHANGE_TRIGGER) and (elapsedTime >= BEACON_FREQUENCY_MOTION_MAXIMUM_SECS):
				beaconTrigger = "COURSE_TRIGGER"
				shouldBeacon = True
	
	if shouldBeacon:
		
		lastBeaconPvt = currentPvt

		tnc2packet = buildPacket(pvt)

		# comes back kiss wrapped
		kiss = tnc2_to_ax25(tnc2packet)

		#print parse(tnc2packet)
		#print("Sending (tnc2): {} ({})".format(tnc2packet, len(tnc2packet)))
		#print("Sending (kiss): {} ({})".format(kiss, len(kiss)))		

		print("Beacon! cause: {}".format(beaconTrigger))
		
		client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		address = (TNC_HOST, TNC_PORT)
		client.connect(address)
		client.sendall(kiss)
		client.close()
		
		lastBeacon = datetime.datetime.now()
		
		
# port 2947 (gpsd) of localhost
session = gps.gps("localhost", "2947")
session.stream(gps.WATCH_ENABLE | gps.WATCH_NEWSTYLE)

# this is hilarious but it works!
init_d710()
time.sleep(5)

while True:
	
	try:
		report = session.next()

		if report['class'] == 'TPV':
			# do we have a fix
			if (report.mode is 2) or (report.mode is 3):
#				if hasattr(report, 'time'):
#					print report.time
				if hasattr(report, 'lat') and hasattr(report, 'lon'):

					if hasattr(report, 'speed') and hasattr(report, 'track'):
						currentPvt = pvt(report.lat,report.lon, report.track, report.speed)
					else:
						currentPvt = pvt(report.lat,report.lon)

					beacon()
					
			else:
				print("no fix")
		else:
			#print(report['class'])
			pass

	except KeyboardInterrupt:
		quit()
		
	except StopIteration:
		session = None
		print "GPSD has terminated"
		
	
	time.sleep(.1) #set to whatever