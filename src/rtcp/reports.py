# rtcp report builders 

import struct
import time
from constants import RTP_VERSION, RTCP_SR_PACKET_TYPE, RTCP_RR_PACKET_TYPE, NTP_UNIX_EPOCH_OFFSET


def build_rtcp_sr(ssrc, packet_count, octet_count, rtp_timestamp=0):
	"""build rtcp sender report based on rfc 3550"""
	now = time.time()
	ntp_seconds = int(now) + NTP_UNIX_EPOCH_OFFSET
	ntp_fraction = int((now - int(now)) * (1 << 32))

	# 28 bytes total means 7 words; RTCP length field stores (words - 1).
	header = struct.pack("!BBH", RTP_VERSION << 6, RTCP_SR_PACKET_TYPE, 6)
	body = struct.pack(
		"!IIIIII",
		ssrc & 0xFFFFFFFF,
		ntp_seconds & 0xFFFFFFFF,
		ntp_fraction & 0xFFFFFFFF,
		rtp_timestamp & 0xFFFFFFFF,
		packet_count & 0xFFFFFFFF,
		octet_count & 0xFFFFFFFF,
	)
	return header + body


def build_rtcp_rr(ssrc, sender_ssrc, fraction_lost, cumulative_lost, 
                  highest_seq, jitter, lsr=0, dlsr=0):
	"""build rtcp receiver report  based on rfc 3550"""
	# RC (reception report count) = 1
	# 32 bytes total: 8 bytes header + 24 bytes report block = 8 words, length = 7
	header = struct.pack("!BBH", (RTP_VERSION << 6) | 1, RTCP_RR_PACKET_TYPE, 7)
	receiver_ssrc = struct.pack("!I", ssrc & 0xFFFFFFFF)
	
	# r	eport block for single source
	report_block = struct.pack(
		"!IBBHIIII",
		sender_ssrc & 0xFFFFFFFF,
		fraction_lost & 0xFF,
		(cumulative_lost >> 16) & 0xFF,
		cumulative_lost & 0xFFFF,
		highest_seq & 0xFFFFFFFF,
		int(jitter) & 0xFFFFFFFF,
		lsr & 0xFFFFFFFF,
		dlsr & 0xFFFFFFFF,
	)
	return header + receiver_ssrc + report_block
