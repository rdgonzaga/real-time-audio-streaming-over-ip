# audio input/output helpers used by RTP sender/receiver

from __future__ import annotations

from dataclasses import dataclass
import os
import wave
import numpy as np
import sounddevice as sd
import queue

G711_SAMPLE_RATE = 8000
G711_CHANNELS = 1
G711_FRAME_DURATION_MS = 20
G711_FRAME_SIZE = G711_SAMPLE_RATE * G711_FRAME_DURATION_MS // 1000
G711_PCM_SAMPLE_WIDTH = 2
PCMU_PAYLOAD_TYPE = 0

_MU_LAW_BIAS = 0x84
_MU_LAW_CLIP = 32635


def _linear2ulaw_sample(sample: int) -> int:
	"""encode one int16 sample to G.711 mu-law byte."""
	s = int(sample)
	sign = 0
	if s < 0:
		s = -s
		sign = 0x80
	if s > _MU_LAW_CLIP:
		s = _MU_LAW_CLIP
	s += _MU_LAW_BIAS

	exponent = 7
	exp_mask = 0x4000
	while exponent > 0 and (s & exp_mask) == 0:
		exponent -= 1
		exp_mask >>= 1

	mantissa = (s >> (exponent + 3)) & 0x0F
	ulaw = ~(sign | (exponent << 4) | mantissa) & 0xFF
	return ulaw


def _ulaw2linear_sample(ulaw: int) -> int:
	"""decode one G.711 mu-law byte into int16 sample."""
	u = (~ulaw) & 0xFF
	sign = u & 0x80
	exponent = (u >> 4) & 0x07
	mantissa = u & 0x0F

	sample = ((mantissa << 3) + _MU_LAW_BIAS) << exponent
	sample -= _MU_LAW_BIAS
	if sign:
		sample = -sample
	return int(np.clip(sample, -32768, 32767))


def _lin16_bytes_to_ulaw(pcm_bytes: bytes) -> bytes:
	"""convert signed 16-bit PCM bytes into G.711 mu-law bytes."""
	samples = np.frombuffer(pcm_bytes, dtype=np.int16)
	encoded = bytearray(len(samples))
	for i, sample in enumerate(samples):
		encoded[i] = _linear2ulaw_sample(int(sample))
	return bytes(encoded)


def _ulaw_bytes_to_lin16(ulaw_bytes: bytes) -> bytes:
	"""convert G.711 mu-law bytes into signed 16-bit PCM bytes."""
	decoded = np.empty(len(ulaw_bytes), dtype=np.int16)
	for i, value in enumerate(ulaw_bytes):
		decoded[i] = _ulaw2linear_sample(value)
	return decoded.tobytes()

def _encode_wav_to_g711_frames(filename: str):
	"""Yield G.711 PCMU packets encoded from WAV frames using 20 ms packets."""
	with wave.open(filename, "rb") as wav_file:
		channels = wav_file.getnchannels()
		sample_width = wav_file.getsampwidth()
		sample_rate = wav_file.getframerate()
		if channels != G711_CHANNELS:
			raise ValueError("G.711 mode expects mono WAV (1 channel)")
		if sample_width != G711_PCM_SAMPLE_WIDTH:
			raise ValueError("G.711 mode expects 16-bit PCM WAV (sample_width=2)")
		if sample_rate != G711_SAMPLE_RATE:
			raise ValueError("G.711 mode expects 8000 Hz WAV")

		while True:
			pcm = wav_file.readframes(G711_FRAME_SIZE)
			if not pcm:
				break

			required_len = G711_FRAME_SIZE * G711_PCM_SAMPLE_WIDTH
			if len(pcm) < required_len:
				pcm = pcm + b"\x00" * (required_len - len(pcm))

			yield _lin16_bytes_to_ulaw(pcm)


@dataclass
class G711AudioSource:
	"""Iterable audio source that yields G.711 PCMU RTP payloads."""
	filename: str
	payload_type: int = PCMU_PAYLOAD_TYPE
	timestamp_step: int = G711_FRAME_SIZE
	packet_interval: float = G711_FRAME_DURATION_MS / 1000.0

	def __iter__(self):
		return _encode_wav_to_g711_frames(self.filename)


class G711AudioPlayer:
	"""Decode G.711 PCMU RTP payloads and play decoded PCM in real time."""

	def __init__(self, sample_rate: int = G711_SAMPLE_RATE, channels: int = G711_CHANNELS, debug: bool = False):
		self.sample_rate = sample_rate
		self.channels = channels
		self.debug = debug
		self.frame_count = 0
		self.stream = None
		self._initialize_stream()

	def _initialize_stream(self):
		"""Initialize a persistent audio output stream"""
		try:
			self.stream = sd.OutputStream(
				samplerate=self.sample_rate,
				channels=self.channels,
				dtype='int16',
				blocksize=G711_FRAME_SIZE,  # 160 samples per frame
			)
			self.stream.start()
			if self.debug:
				print(f"[AUDIO] Output stream initialized: {self.sample_rate}Hz, {self.channels} channel(s)")
		except Exception as e:
			print(f"[AUDIO ERROR] Failed to initialize output stream: {e}")
			self.stream = None

	def __call__(self, payload: bytes) -> bool:
		if not payload:
			return True
		
		if self.stream is None:
			if self.debug:
				print("[AUDIO ERROR] No audio stream available")
			return False
		
		self.frame_count += 1
		if self.debug and self.frame_count % 50 == 1:
			print(f"[AUDIO] Playing frame {self.frame_count}, payload size: {len(payload)} bytes")
		
		try:
			decoded_pcm = _ulaw_bytes_to_lin16(payload)
			samples = np.frombuffer(decoded_pcm, dtype=np.int16)
			
			# Write to the persistent stream instead of creating new streams
			self.stream.write(samples)
			return True
		except Exception as e:
			if self.debug:
				print(f"[AUDIO ERROR] Frame {self.frame_count} playback failed: {e}")
			return False
	
	def close(self):
		"""Close the audio stream"""
		if self.stream:
			try:
				self.stream.stop()
				self.stream.close()
				if self.debug:
					print("[AUDIO] Output stream closed")
			except Exception as e:
				print(f"[AUDIO ERROR] Failed to close stream: {e}")
			self.stream = None

class G711MicrophoneSource:
	payload_type = PCMU_PAYLOAD_TYPE
	timestamp_step = G711_FRAME_SIZE
	packet_interval = G711_FRAME_DURATION_MS / 1000.0

	def __init__(
		self,
		sample_rate: int = G711_SAMPLE_RATE,
		channels: int = G711_CHANNELS,
		frames_per_chunk: int = G711_FRAME_SIZE,
		debug: bool = False,
	):
		self.sample_rate = sample_rate
		self.channels = channels
		self.frames_per_chunk = frames_per_chunk
		self.debug = debug
		self.frame_count = 0
		self.closed = False
		self.buffer = queue.Queue(maxsize=50)
		self.stream = None
		self._initialize_stream()

	def _initialize_stream(self):
		try:
			self.stream = sd.InputStream(
				samplerate=self.sample_rate,
				channels=self.channels,
				dtype="int16",
				blocksize=self.frames_per_chunk,
				callback=self._callback,
			)
			self.stream.start()
			if self.debug:
				print(f"[MIC] Input stream initialized: {self.sample_rate} Hz, {self.channels} channel(s)")
		except Exception as e:
			print(f"[MIC ERROR] Failed to initialize input stream: {e}")
			self.stream = None

	def _callback(self, indata, frames, time_info, status):
		if status and self.debug:
			print(f"[MIC] Status: {status}")

		try:
			pcm_bytes = indata.copy().tobytes()
			ulaw_bytes = _lin16_bytes_to_ulaw(pcm_bytes)

			# enforce 20 ms packet size
			if len(ulaw_bytes) < G711_FRAME_SIZE:
				ulaw_bytes += b"\xff" * (G711_FRAME_SIZE - len(ulaw_bytes))
			elif len(ulaw_bytes) > G711_FRAME_SIZE:
				ulaw_bytes = ulaw_bytes[:G711_FRAME_SIZE]

			if self.buffer.full():
				try:
					self.buffer.get_nowait()
				except queue.Empty:
					pass

			self.buffer.put_nowait(ulaw_bytes)
		except Exception as e:
			if self.debug:
				print(f"[MIC ERROR] Callback failed: {e}")

	def __iter__(self):
		return self

	def __next__(self):
		if self.closed:
			raise StopIteration

		try:
			frame = self.buffer.get(timeout=self.packet_interval * 2)
			self.frame_count += 1
			if self.debug and self.frame_count % 50 == 1:
				print(f"[MIC] Captured frame {self.frame_count}, size={len(frame)} bytes")
			return frame
		except queue.Empty:
			# comfort-noise style silence frame
			return b"\xff" * G711_FRAME_SIZE

	def close(self):
		self.closed = True
		if self.stream:
			try:
				self.stream.stop()
				self.stream.close()
				if self.debug:
					print("[MIC] Input stream closed")
			except Exception as e:
				print(f"[MIC ERROR] Failed to close input stream: {e}")
			self.stream = None

def play_audio_frame(
	frame: bytes,
	sample_rate: int = 8000,
	channels: int = 1,
	sample_width: int = 2,
) -> bool:
	"""play one pcm frame using non-blocking audio to prevent packet loss"""
	if not frame:
		return True

	if sample_width == 1:
		dtype = "uint8"
	elif sample_width == 2:
		dtype = "int16"
	elif sample_width == 4:
		dtype = "int32"
	else:
		raise ValueError(f"Unsupported sample_width: {sample_width}")

	try:
		samples = np.frombuffer(frame, dtype=dtype)
		if channels > 1:
			# for stereo and above, shape as (frames, channels).
			samples = samples.reshape(-1, channels)
		
		# prevents rtp receiver thread from blocking
		sd.play(samples, samplerate=sample_rate, blocking=False)
		return True
	except Exception as e:
		print(f"[AUDIO ERROR] Failed to play frame: {e}")
		return False


def validate_mode(mode: str, audio_file: str = "") -> None:
	"""	validate source mode before media threads start. """
	normalized_mode = mode.strip().lower()
	if normalized_mode not in {"file", "mic"}:
		raise ValueError("mode must be either 'file' or 'mic'")

	if normalized_mode == "file":
		if not audio_file:
			raise ValueError("audio_file is required when mode is 'file'")
		if not os.path.isfile(audio_file):
			raise FileNotFoundError(f"Audio file not found: {audio_file}")