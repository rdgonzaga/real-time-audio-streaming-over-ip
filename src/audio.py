# audio input/output helpers used by RTP sender/receiver

from __future__ import annotations

from dataclasses import dataclass
import os
import wave
import numpy as np
import sounddevice as sd

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

	def __init__(self, sample_rate: int = G711_SAMPLE_RATE, channels: int = G711_CHANNELS):
		self.sample_rate = sample_rate
		self.channels = channels

	def __call__(self, payload: bytes) -> bool:
		if not payload:
			return True
		decoded_pcm = _ulaw_bytes_to_lin16(payload)
		return play_audio_frame(decoded_pcm, sample_rate=self.sample_rate, channels=self.channels, sample_width=2)

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

	samples = np.frombuffer(frame, dtype=dtype)
	if channels > 1:
		# for stereo and above, shape as (frames, channels).
		samples = samples.reshape(-1, channels)
	
	# prevents rtp receiver thread from blocking
	sd.play(samples, samplerate=sample_rate, blocking=False)
	return True


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