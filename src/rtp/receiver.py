# rtp receiver loop

import random
import time
from rtp.packet import parse_rtp_packet
from rtp.jitter import JitterBuffer
from constants import JITTER_BUFFER_SIZE
from stats import RtpStats


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
