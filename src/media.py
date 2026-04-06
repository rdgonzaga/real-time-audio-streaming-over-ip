# RTP/RTCP helpers and media loops for UDP audio transport

from __future__ import annotations

import random
import struct
import time
from collections import deque
from typing import Callable

RTP_VERSION = 2
RTP_HEADER_SIZE = 12
RTCP_SR_PACKET_TYPE = 200
RTCP_RR_PACKET_TYPE = 201
NTP_UNIX_EPOCH_OFFSET = 2_208_988_800
JITTER_BUFFER_SIZE = 2  # number of packets to buffer


class RtpStats:
	"""Shared RTP statistics for real-time RTCP reporting"""
	
	def __init__(self):
		# sender stats
		self.ssrc = 0
		self.packet_count = 0
		self.octet_count = 0
		self.timestamp = 0
		self.sequence_number = 0
		
		# receiver stats
		self.received_packets = 0
		self.malformed_packets = 0
		self.cumulative_lost = 0
		self.highest_seq = 0
		self.jitter = 0.0
		self.sender_ssrc = 0
		self.fraction_lost = 0
		self.receiver_ssrc = 0
	
	def update_sender(self, **kwargs):
		"""Update sender statistics"""
		for key, value in kwargs.items():
			if hasattr(self, key):
				setattr(self, key, value)
	
	def update_receiver(self, **kwargs):
		"""Update receiver statistics"""
		for key, value in kwargs.items():
			if hasattr(self, key):
				setattr(self, key, value)
	
	def get_sender_stats(self) -> dict:
		"""Get current sender statistics for RTCP SR"""
		return {
			"ssrc": self.ssrc,
			"packet_count": self.packet_count,
			"octet_count": self.octet_count,
			"timestamp": self.timestamp,
			"sequence_number": self.sequence_number,
		}
	
	def get_receiver_stats(self) -> dict:
		"""Get current receiver statistics for RTCP RR"""
		return {
			"sender_ssrc": self.sender_ssrc,
			"fraction_lost": self.fraction_lost,
			"cumulative_lost": self.cumulative_lost,
			"highest_seq": self.highest_seq,
			"jitter": self.jitter,
			"receiver_ssrc": self.receiver_ssrc,
		}


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


class JitterBuffer:
	"""simple jitter buffer for RTP packet reordering and smoothing"""
	
	def __init__(self, buffer_size: int = JITTER_BUFFER_SIZE):
		self.buffer_size = buffer_size
		self.buffer = deque(maxlen=buffer_size * 2)
		self.ready_threshold = buffer_size
		self.initialized = False
	
	def add_packet(self, seq: int, payload: bytes) -> None:
		"""Add packet to buffer in sequence order"""
		# insert packet in sorted order by sequence number
		inserted = False
		for i, (existing_seq, _) in enumerate(self.buffer):
			if seq == existing_seq:
				# duplicate packet, ignore
				return
			if (seq - existing_seq) & 0xFFFF < 32768:
				# seq is newer, keep looking
				continue
			else:
				# found insertion point
				self.buffer.insert(i, (seq, payload))
				inserted = True
				break
		
		if not inserted:
			self.buffer.append((seq, payload))
		
		# mark as initialized once we have enough packets
		if not self.initialized and len(self.buffer) >= self.ready_threshold:
			self.initialized = True
	
	def get_next_packet(self) -> bytes | None:
		"""Get next packet in sequence if buffer is ready"""
		if not self.initialized:
			return None
		
		if len(self.buffer) == 0:
			return None
		
		# return oldest packet (lowest sequence number)
		_, payload = self.buffer.popleft()
		return payload
	
	def is_ready(self) -> bool:
		"""Check if buffer has been initialized with enough packets"""
		return self.initialized


def rtp_send_loop(sock, remote_addr, audio_source, stop_event, stats: RtpStats = None):
	"""send frames until source ends or stop_event is set"""
	seq = random.randint(0, 0xFFFF)
	timestamp = random.randint(0, 0xFFFFFFFF)
	ssrc = random.randint(0, 0xFFFFFFFF)

	timestamp_step = getattr(audio_source, "timestamp_step", 160) # 20ms at 8khz G.711 clock
	packet_interval = getattr(audio_source, "packet_interval", 0.02) # assumes 20ms packets
	payload_type = getattr(audio_source, "payload_type", 0)

	packet_count = 0
	octet_count = 0
	next_send = time.monotonic()
	last_timestamp = timestamp
	
	# initialize shared stats if provided
	if stats:
		stats.update_sender(ssrc=ssrc)

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
		last_timestamp = timestamp
		
		# update shared stats in real-time
		if stats:
			stats.update_sender(
				packet_count=packet_count,
				octet_count=octet_count,
				timestamp=last_timestamp,
				sequence_number=seq
			)

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
		"timestamp": last_timestamp,
		"sequence_number": seq,
	}


def rtp_receive_loop(sock, audio_player, stop_event, stats: RtpStats = None, debug: bool = False):
	"""receive rtp packets, buffer with jitter buffer, and forward to audio_player"""
	received_packets = 0
	malformed_packets = 0
	expected_seq = None
	cumulative_lost = 0
	highest_seq_received = 0
	
	# jitter calculation per RFC 3550 Appendix A.8
	jitter = 0.0
	last_transit = None
	last_rtp_timestamp = 0
	sender_ssrc = 0
	receiver_ssrc = random.randint(0, 0xFFFFFFFF)
	
	# jitter buffer for packet reordering
	jitter_buffer = JitterBuffer()
	
	# initialize shared stats if provided
	if stats:
		stats.update_receiver(receiver_ssrc=receiver_ssrc)

	if debug:
		print(f"[RTP RECV] Starting receive loop, listening for packets...")

	sock.settimeout(0.5)
	while not stop_event.is_set():
		try:
			data, _ = sock.recvfrom(65535)
			arrival_time = time.time()
		except TimeoutError:
			# check if jitter buffer has packets to play during timeout
			if jitter_buffer.is_ready():
				payload = jitter_buffer.get_next_packet()
				if payload:
					audio_player(payload)
			continue
		except OSError:
			break

		try:
			packet = parse_rtp_packet(data)
		except ValueError as e:
			# ignore malformed packets and keep receiver alive.
			malformed_packets += 1
			if debug:
				print(f"[RTP RECV] Malformed packet: {e}")
			continue

		seq = packet["sequence_number"]
		rtp_timestamp = packet["timestamp"]
		sender_ssrc = packet["ssrc"]
		
		if debug and received_packets < 5:
			print(f"[RTP RECV] Packet #{received_packets+1}: seq={seq}, timestamp={rtp_timestamp}, payload={len(packet['payload'])} bytes")
		
		# track highest sequence number received
		if received_packets == 0:
			highest_seq_received = seq
			if debug:
				print(f"[RTP RECV] First packet received, starting sequence at {seq}")
		else:
			# handle sequence number wrapping
			delta = (seq - highest_seq_received) & 0xFFFF
			if delta < 32768:  # forward progression
				if delta > 0:
					highest_seq_received = seq
		
		# calculate packet loss
		if expected_seq is not None:
			delta = (seq - expected_seq) & 0xFFFF
			if delta > 0 and delta < 32768:
				# packets were lost
				cumulative_lost += delta

		expected_seq = (seq + 1) & 0xFFFF
		
		# calculate interarrival jitter based sa rfc 3550 

		transit = int(arrival_time * 8000) - rtp_timestamp
		if last_transit is not None:
			d = abs(transit - last_transit)
			jitter += (d - jitter) / 16.0
		last_transit = transit
		last_rtp_timestamp = rtp_timestamp

		# add packet to jitter buffer
		jitter_buffer.add_packet(seq, packet["payload"])
		received_packets += 1
		
		# calculate fraction lost for current state
		fraction_lost = 0
		if expected_seq is not None and received_packets > 0:
			expected_packets = ((highest_seq_received - (expected_seq - received_packets - cumulative_lost)) & 0xFFFF) + 1
			if expected_packets > 0:
				lost_interval = cumulative_lost
				fraction_lost = min(255, int((lost_interval / expected_packets) * 256))
		
		# update shared stats in real-time
		if stats:
			stats.update_receiver(
				sender_ssrc=sender_ssrc,
				fraction_lost=fraction_lost,
				cumulative_lost=cumulative_lost,
				highest_seq=highest_seq_received,
				jitter=jitter,
				received_packets=received_packets,
				malformed_packets=malformed_packets
			)
		
		# play packets from jitter buffer if ready
		if jitter_buffer.is_ready():
			if debug and received_packets == JITTER_BUFFER_SIZE:
				print(f"[RTP RECV] Jitter buffer initialized with {JITTER_BUFFER_SIZE} packets, starting playback...")
			
			payload = jitter_buffer.get_next_packet()
			if payload:
				audio_player(payload)

	if debug:
		print(f"[RTP RECV] Receive loop ended. Total packets: {received_packets}, Malformed: {malformed_packets}, Lost: {cumulative_lost}")

	# flush remaining packets from jitter buffer
	while True:
		payload = jitter_buffer.get_next_packet()
		if not payload:
			break
		audio_player(payload)
	
	# close audio stream if it has a close method
	if hasattr(audio_player, 'close'):
		audio_player.close()

	# calculate final fraction lost
	fraction_lost = 0
	if expected_seq is not None and received_packets > 0:
		expected_packets = ((highest_seq_received - (expected_seq - received_packets - cumulative_lost)) & 0xFFFF) + 1
		if expected_packets > 0:
			lost_interval = cumulative_lost
			fraction_lost = min(255, int((lost_interval / expected_packets) * 256))

	return {
		"received_packets": received_packets,
		"malformed_packets": malformed_packets,
		"cumulative_lost": cumulative_lost,
		"highest_seq": highest_seq_received,
		"jitter": jitter,
		"sender_ssrc": sender_ssrc,
		"fraction_lost": fraction_lost,
	}


def rtcp_send_loop(sock, remote_addr, stop_event, stats: RtpStats):
	"""send rtcp sender reports periodically using shared stats"""
	interval = 5.0
	while not stop_event.is_set():
		sender_stats = stats.get_sender_stats()
		
		sr = build_rtcp_sr(
			ssrc=sender_stats["ssrc"], 
			packet_count=sender_stats["packet_count"], 
			octet_count=sender_stats["octet_count"],
			rtp_timestamp=sender_stats["timestamp"]
		)
		sock.sendto(sr, remote_addr)

		if stop_event.wait(interval):
			break


def rtcp_send_rr_loop(sock, remote_addr, stop_event, stats: RtpStats):
	"""send rtcp receiver reports periodically using shared stats"""
	interval = 5.0
	
	while not stop_event.is_set():
		receiver_stats = stats.get_receiver_stats()
		
		# only send RR if we have received packets
		if receiver_stats["sender_ssrc"] != 0:
			rr = build_rtcp_rr(
				ssrc=receiver_stats["receiver_ssrc"],
				sender_ssrc=receiver_stats["sender_ssrc"],
				fraction_lost=receiver_stats["fraction_lost"],
				cumulative_lost=receiver_stats["cumulative_lost"],
				highest_seq=receiver_stats["highest_seq"],
				jitter=receiver_stats["jitter"],
			)
			sock.sendto(rr, remote_addr)

		if stop_event.wait(interval):
			break