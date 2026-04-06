# sdp implementation

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional


DEFAULT_CODEC = "PCMU"
DEFAULT_PAYLOAD_TYPE = 0
DEFAULT_SAMPLE_RATE = 8000
DEFAULT_CHANNELS = 1


@dataclass
class SdpInfo:
	"""sdp info"""
	ip: str
	port: int
	codec: str = DEFAULT_CODEC
	payload_type: int = DEFAULT_PAYLOAD_TYPE
	sample_rate: int = DEFAULT_SAMPLE_RATE
	channels: int = DEFAULT_CHANNELS


def build_sdp(local_ip: str, rtp_port: int, codec: str = DEFAULT_CODEC,
              payload_type: int = DEFAULT_PAYLOAD_TYPE, sample_rate: int = DEFAULT_SAMPLE_RATE,
              channels: int = DEFAULT_CHANNELS) -> str:
	""" builds SDP body for media negotiation. """
	sdp_lines = [
		"v=0",  # protocol version
		f"o=- {random.randint(1000000, 9999999)} {random.randint(1000000, 9999999)} IN IP4 {local_ip}",
		"s=VoIP Call",  # session name
		f"c=IN IP4 {local_ip}",  # connection information
		"t=0 0",  # time description (0 0 = permanent session)
		f"m=audio {rtp_port} RTP/AVP {payload_type}",  # media description
		f"a=rtpmap:{payload_type} {codec}/{sample_rate}",  # RTP map attribute
	]
	return "\r\n".join(sdp_lines) + "\r\n"


def parse_sdp(sdp_body: str) -> Optional[SdpInfo]:
	""" parse SDP body to extract media information """
	if not sdp_body:
		return None
	
	lines = sdp_body.strip().split("\r\n")
	ip = ""
	port = 0
	codec = DEFAULT_CODEC
	payload_type = DEFAULT_PAYLOAD_TYPE
	sample_rate = DEFAULT_SAMPLE_RATE
	channels = DEFAULT_CHANNELS
	
	for line in lines:
		line = line.strip()
		if line.startswith("c=IN IP4 "):
			ip = line.split()[-1]
		elif line.startswith("m=audio "):
			parts = line.split()
			if len(parts) >= 4:
				port = int(parts[1])
				payload_type = int(parts[3])
		elif line.startswith("a=rtpmap:"):
			# format is: a=rtpmap:<payload_type> <codec>/<sample_rate>
			parts = line.split()
			if len(parts) >= 2:
				codec_info = parts[1].split("/")
				if len(codec_info) >= 2:
					codec = codec_info[0]
					sample_rate = int(codec_info[1])
				if len(codec_info) >= 3:
					channels = int(codec_info[2])
	
	if ip and port:
		return SdpInfo(ip=ip, port=port, codec=codec, 
		              payload_type=payload_type, sample_rate=sample_rate, channels=channels)
	return None
