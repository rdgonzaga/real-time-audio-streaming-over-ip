# rtp packet building and parsing

import struct
from constants import RTP_VERSION, RTP_HEADER_SIZE


def build_rtp_packet(payload, seq, timestamp, ssrc, payload_type=0):
	"""
	build RTP packet with header and payload.
	format of header: rtp version (2bits), padding (1bit), extension (1bit), 
	cc (4 bit), m(1bit), payload type (7bit)
	"""
	if not (0 <= payload_type <= 127):
		raise ValueError("payload_type must be in [0, 127]")

	first_byte = RTP_VERSION << 6
	second_byte = payload_type & 0x7F

	# B B H I I = 1B,1B,2B,4B,4B = 12 bytes total
	header = struct.pack(
		"!BBHII",
		first_byte,
		second_byte,
		seq & 0xFFFF,
		timestamp & 0xFFFFFFFF,
		ssrc & 0xFFFFFFFF,
	)
	return header + payload


def parse_rtp_packet(data):
	"""parse RTP header fields and return payload + metadata"""
	if len(data) < RTP_HEADER_SIZE:
		raise ValueError("RTP packet too short")

	first_byte, second_byte, seq, timestamp, ssrc = struct.unpack("!BBHII", data[:RTP_HEADER_SIZE])
	version = first_byte >> 6
	if version != RTP_VERSION:
		raise ValueError(f"Unsupported RTP version: {version}")

	return {
		"version": version,
		"padding": (first_byte >> 5) & 0x01,
		"extension": (first_byte >> 4) & 0x01,
		"csrc_count": first_byte & 0x0F,
		"marker": (second_byte >> 7) & 0x01,
		"payload_type": second_byte & 0x7F,
		"sequence_number": seq,
		"timestamp": timestamp,
		"ssrc": ssrc,
		"payload": data[RTP_HEADER_SIZE:],
	}
