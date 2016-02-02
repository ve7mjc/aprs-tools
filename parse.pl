#!/usr/bin/perl
use Ham::APRS::FAP qw(parseaprs);


#my $ret = parseaprs("OH2XYZ>APRS,RELAY*,WIDE:!2345.56N/12345.67E-PHG0123 hi", \%hash, 'isax25' => 0, 'accept_broken_mice' => 0);

#print parseaprs($ARGV[0], , \%hash, 'isax25' => 0, 'accept_broken_mice' => 0);
#print "Output";

$aprspacket = $ARGV[0];

my $retval = parseaprs($aprspacket, \%packetdata);
if ($retval == 1) {
    # decoding ok, do something with the data
    while (my ($key, $value) = each(%packetdata)) {
            print "$key: $value\n";
    }
} else {
    warn "Parsing failed: $packetdata{resultmsg} ($packetdata{resultcode})\n";
}