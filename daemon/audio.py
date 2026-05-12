"""Microphone capture using sounddevice. 16 kHz mono float32 numpy buffer."""

from __future__ import annotations

import threading

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16_000
CHANNELS = 1
DTYPE = "float32"
MAX_SECONDS = 60
MAX_SAMPLES = SAMPLE_RATE * MAX_SECONDS


class Recorder:
    def __init__(self) -> None:
        self._stream: sd.InputStream | None = None
        self._chunks: list[np.ndarray] = []
        self._sample_count = 0
        self._lock = threading.Lock()
        self._truncated = False

    def start(self) -> None:
        if self._stream is not None:
            raise RuntimeError("recorder already started")
        with self._lock:
            self._chunks = []
            self._sample_count = 0
            self._truncated = False
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            callback=self._callback,
            blocksize=1024,
        )
        self._stream.start()

    def stop(self) -> tuple[np.ndarray, bool]:
        """Stop and return (audio, truncated_flag)."""
        if self._stream is None:
            raise RuntimeError("recorder not started")
        self._stream.stop()
        self._stream.close()
        self._stream = None
        with self._lock:
            if not self._chunks:
                return np.zeros(0, dtype=np.float32), False
            audio = np.concatenate(self._chunks)
            truncated = self._truncated
        return audio, truncated

    def _callback(self, indata, frames, time_info, status):  # noqa: ARG002
        if status:
            # XRun, overflow — log but don't crash
            print(f"[audio] status: {status}", flush=True)
        with self._lock:
            if self._sample_count >= MAX_SAMPLES:
                self._truncated = True
                return
            remaining = MAX_SAMPLES - self._sample_count
            chunk = indata[:remaining].copy().reshape(-1)
            self._chunks.append(chunk)
            self._sample_count += len(chunk)
