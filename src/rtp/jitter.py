# jitter buffer for rtp packet reordering and smoothing

from collections import deque
from constants import JITTER_BUFFER_SIZE


class JitterBuffer:
	"""simple jitter buffer for RTP packet reordering and smoothing"""
	
	def __init__(self, buffer_size: int = JITTER_BUFFER_SIZE):
		self.buffer_size = buffer_size
		self.buffer = deque(maxlen=buffer_size * 2)
		self.ready_threshold = buffer_size
		self.initialized = False
	
	def add_packet(self, seq: int, payload: bytes) -> None:
		"""add packet to buffer in sequence order"""
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
		"""get next packet in sequence if buffer is ready"""
		if not self.initialized:
			return None
		
		if len(self.buffer) == 0:
			return None
		
		# return oldest packet (lowest sequence number)
		_, payload = self.buffer.popleft()
		return payload
	
	def is_ready(self) -> bool:
		"""check if buffer has been initialized with enough packets"""
		return self.initialized
