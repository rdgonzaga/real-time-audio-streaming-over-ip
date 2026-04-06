# rtp sender loop

import random
import time
from rtp.packet import build_rtp_packet
from stats import RtpStats


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
