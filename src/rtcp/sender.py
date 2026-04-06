# rtcp sender loops 

from rtcp.reports import build_rtcp_sr, build_rtcp_rr
from stats import RtpStats


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
