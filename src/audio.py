# audio input/output helpers used by RTP sender/receiver

from __future__ import annotations

from dataclasses import dataclass
import os
import wave
import numpy as np
import sounddevice as sd


@dataclass(frozen=True)
class WavParams:
	channels: int  # channels: 1 = mono, 2 = stereo
	sample_width: int # sample_width: bytes per sample (1, 2, or 4)
	sample_rate: int # sample_rate: samples per second (e.g., 8000, 16000, 44100)
	frame_count: int # frame_count: total samples-per-channel in the file


def get_wav_params(filename: str) -> WavParams:
	# read WAV metadata so sender/receiver can agree on playback settings
	with wave.open(filename, "rb") as wav_file:
		return WavParams(
			channels=wav_file.getnchannels(),
			sample_width=wav_file.getsampwidth(),
			sample_rate=wav_file.getframerate(),
			frame_count=wav_file.getnframes(),
		)


def read_wav_frames(filename: str, chunk_size: int):
	# Yield raw PCM chunks from a WAV file.
	if chunk_size <= 0:
		raise ValueError("chunk_size must be > 0")

	with wave.open(filename, "rb") as wav_file:
		while True:
			# wave.readframes returns bytes containing all channels interleaved.
			data = wav_file.readframes(chunk_size)
			if not data:
				break
			yield data


def microphone_frames(chunk_size: int):
	# later na to for bonus
	raise NotImplementedError("not yet implemented")


def play_audio_frame(
	frame: bytes,
	sample_rate: int = 8000,
	channels: int = 1,
	sample_width: int = 2,
) -> bool:
	# play one pcm frame. 
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
	sd.play(samples, samplerate=sample_rate, blocking=True)
	return True


def validate_mode(mode: str, audio_file: str = "") -> None:
	# validate source mode before media threads start
	# fail early so call setup does not start with a broken config.
	normalized_mode = mode.strip().lower()
	if normalized_mode not in {"file", "mic"}:
		raise ValueError("mode must be either 'file' or 'mic'")

	if normalized_mode == "file":
		if not audio_file:
			raise ValueError("audio_file is required when mode is 'file'")
		if not os.path.isfile(audio_file):
			raise FileNotFoundError(f"Audio file not found: {audio_file}")