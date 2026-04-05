# RTP/RTCP helpers and media loops for UDP audio transport

from __future__ import annotations

import random
import struct
import time

RTP_VERSION = 2
RTP_HEADER_SIZE = 12
RTCP_SR_PACKET_TYPE = 200
NTP_UNIX_EPOCH_OFFSET = 2_208_988_800


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


def build_rtcp_sr(ssrc, packet_count, octet_count):
	"""	build rtcp sender report """
	now = time.time()
	ntp_seconds = int(now) + NTP_UNIX_EPOCH_OFFSET
	ntp_fraction = int((now - int(now)) * (1 << 32))
	rtp_timestamp = 0

	# 28 bytes total means 7 words; RTCP length field stores (words - 1).
	header = struct.pack("!BBH", RTP_VERSION << 6, RTCP_SR_PACKET_TYPE, 6)
	body = struct.pack(
		"!IIIIII",
		ssrc & 0xFFFFFFFF,
		ntp_seconds & 0xFFFFFFFF,
		ntp_fraction & 0xFFFFFFFF,
		rtp_timestamp,
		packet_count & 0xFFFFFFFF,
		octet_count & 0xFFFFFFFF,
	)
	return header + body


def rtp_send_loop(sock, remote_addr, audio_source, stop_event):
	"""send frames until source ends or stop_event is set"""
	seq = random.randint(0, 0xFFFF)
	timestamp = random.randint(0, 0xFFFFFFFF)
	ssrc = random.randint(0, 0xFFFFFFFF)

	timestamp_step = getattr(audio_source, "timestamp_step", 160) # 160 samples per packet
	packet_interval = getattr(audio_source, "packet_interval", 0.02) # assumes 20ms packets
	payload_type = getattr(audio_source, "payload_type", 0)

	packet_count = 0
	octet_count = 0
	next_send = time.monotonic()

	for frame in audio_source:
		if stop_event.is_set():
			break

		packet = build_rtp_packet(
			payload=frame,
			seq=seq,
			timestamp=timestamp,
			ssrc=ssrc,
			payload_type=payload_type,
		)
		sock.sendto(packet, remote_addr)

		# for RTCP sender reports 
		packet_count += 1
		octet_count += len(frame)

		# rtp sequence increments by 1 packet
		seq = (seq + 1) & 0xFFFF
		# RTP timestamp increments by audio samples per packet
		timestamp = (timestamp + timestamp_step) & 0xFFFFFFFF

		# keep pacing close to real-time packet interval
		next_send += packet_interval
		sleep_for = next_send - time.monotonic()
		if sleep_for > 0:
			time.sleep(sleep_for)

	return {
		"ssrc": ssrc,
		"packet_count": packet_count,
		"octet_count": octet_count,
		"timestamp": timestamp,
		"sequence_number": seq,
	}


def rtp_receive_loop(sock, audio_player, stop_event):
	"""receive rtp packets and forward payload bytes to audio_player"""
	received_packets = 0
	malformed_packets = 0
	expected_seq = None
	estimated_loss = 0

	sock.settimeout(0.5)
	while not stop_event.is_set():
		try:
			data, _ = sock.recvfrom(65535)
		except TimeoutError:
			continue
		except OSError:
			break

		try:
			packet = parse_rtp_packet(data)
		except ValueError:
			# ignore malformed packets and keep receiver alive.
			malformed_packets += 1
			continue

		seq = packet["sequence_number"]
		if expected_seq is not None:
			delta = (seq - expected_seq) & 0xFFFF
			if delta > 0:
				# rough loss estimate: skipped sequence numbers
				estimated_loss += max(0, delta - 1)

		expected_seq = (seq + 1) & 0xFFFF
		audio_player(packet["payload"])
		received_packets += 1

	return {
		"received_packets": received_packets,
		"malformed_packets": malformed_packets,
		"estimated_loss": estimated_loss,
	}


def rtcp_send_loop(sock, remote_addr, stop_event, stats):
	"""send rtcp sender reports periodically gamit shared counters"""
	interval = getattr(stats, "interval", 5.0)
	while not stop_event.is_set():
		packet_count = 0
		octet_count = 0
		ssrc = random.randint(0, 0xFFFFFFFF)

		if isinstance(stats, dict):
			packet_count = int(stats.get("packet_count", 0))
			octet_count = int(stats.get("octet_count", 0))
			ssrc = int(stats.get("ssrc", ssrc))

		sr = build_rtcp_sr(ssrc=ssrc, packet_count=packet_count, octet_count=octet_count)
		sock.sendto(sr, remote_addr)

		if stop_event.wait(interval):
			break