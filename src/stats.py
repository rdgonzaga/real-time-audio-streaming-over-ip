# shared rtp statistics for real-time rtcp reporting

class RtpStats:
	"""shared rtp statistics for real-time rtcp reporting"""
	
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
		"""update sender statistics"""
		for key, value in kwargs.items():
			if hasattr(self, key):
				setattr(self, key, value)
	
	def update_receiver(self, **kwargs):
		"""update receiver statistics"""
		for key, value in kwargs.items():
			if hasattr(self, key):
				setattr(self, key, value)
	
	def get_sender_stats(self) -> dict:
		"""get current sender statistics for rtcp sr"""
		return {
			"ssrc": self.ssrc,
			"packet_count": self.packet_count,
			"octet_count": self.octet_count,
			"timestamp": self.timestamp,
			"sequence_number": self.sequence_number,
		}
	
	def get_receiver_stats(self) -> dict:
		"""get current receiver statistics for rtcp rr"""
		return {
			"sender_ssrc": self.sender_ssrc,
			"fraction_lost": self.fraction_lost,
			"cumulative_lost": self.cumulative_lost,
			"highest_seq": self.highest_seq,
			"jitter": self.jitter,
			"receiver_ssrc": self.receiver_ssrc,
		}
