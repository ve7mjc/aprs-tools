#!/usr/bin/perl
use Ham::APRS::FAP qw(tnc2_to_kiss);
print tnc2_to_kiss($ARGV[0]);