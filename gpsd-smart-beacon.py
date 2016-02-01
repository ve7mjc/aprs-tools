#!/usr/bin/python

import os
import datetime



def tnc2_to_ax25(packet):
	try:
		command = os.path.dirname(os.path.realpath(__file__)) + '/tnc2toax25.pl \"' + packet + '\"'
		output = os.popen(command).read()
	except Exception as e:
		output = ""
		print(e)
	return output

stationary = True

sym_set = "/"
sym_ico = "j"
source_callsign = "VE7MJC"
info = "ve7mjc test packet -- disregard"

packet = source_callsign + ">"
packet += "APZ000"
packet += ",NRGH39:@"
packet += datetime.datetime.now().strftime("%d%H%M/")
packet += info

print(tnc2_to_ax25(packet))