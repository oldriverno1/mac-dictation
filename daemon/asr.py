"""mlx-qwen3-asr wrapper.

The MLX session is owned by a single dedicated worker thread, because MLX's
default GPU stream is thread-local — calling `session.transcribe()` from a
different thread than the one that loaded the model raises
"There is no Stream(gpu, 1) in current thread."

`Asr.transcribe()` submits a request to the worker via a queue and blocks on
a per-request `threading.Event` until the worker fills in the result. This
serializes inference (which is what we want anyway — one mic, one user).
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Any

import numpy as np


def build_prompt_kwargs(language: str, context: str) -> dict[str, Any]:
    """Build kwargs to pass to the underlying transcribe() call.

    Returns a dict with:
      - "context": always present (may be empty string)
      - "language": present only when a specific language is requested
        (i.e. language is non-empty and not "auto").
    """
    kwargs: dict[str, Any] = {"context": context}
    if language and language != "auto":
        kwargs["language"] = language
    return kwargs


@dataclass
class _TranscribeRequest:
    audio: np.ndarray
    language: str
    context: str
    result: tuple[str, int] | None = None
    error: BaseException | None = None
    done: threading.Event = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.done = threading.Event()


class Asr:
    """Thin wrapper around mlx_qwen3_asr.Session, pinned to a worker thread.

    Real API (mlx-qwen3-asr 0.3.3):
      - mlx_qwen3_asr.Session(model_id)
      - session.transcribe(audio, context="", language=None|"en"|"zh", ...)
          -> TranscriptionResult with .text, .language
    """

    MODEL_SAMPLE_RATE: int = 16_000

    def __init__(self, model_id: str = "Qwen/Qwen3-ASR-1.7B") -> None:
        self.model_id = model_id
        self._session: Any | None = None
        self._queue: queue.Queue[_TranscribeRequest | None] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._loaded = threading.Event()
        self._load_error: BaseException | None = None

    def load(self) -> None:
        """Start the worker thread and block until the model is loaded.

        Call once at daemon startup. Subsequent calls are no-ops.
        """
        if self._worker is not None:
            return
        self._worker = threading.Thread(
            target=self._worker_loop, daemon=True, name="asr-worker"
        )
        self._worker.start()
        self._loaded.wait()
        if self._load_error is not None:
            raise self._load_error

    def transcribe(
        self, audio: np.ndarray, language: str, context: str
    ) -> tuple[str, int]:
        """Submit audio to the worker thread and wait for the transcription.

        Returns (text, duration_ms). Raises any exception the worker hit.
        """
        if self._worker is None:
            raise RuntimeError("Asr.load() must be called before transcribe()")
        if len(audio) == 0:
            return "", 0
        req = _TranscribeRequest(audio=audio, language=language, context=context)
        self._queue.put(req)
        req.done.wait()
        if req.error is not None:
            raise req.error
        assert req.result is not None
        return req.result

    def shutdown(self) -> None:
        """Signal the worker to exit. Used in tests; daemon process just exits."""
        if self._worker is not None and self._worker.is_alive():
            self._queue.put(None)
            self._worker.join(timeout=5)

    def _worker_loop(self) -> None:
        try:
            import mlx_qwen3_asr  # noqa: PLC0415 — intentional lazy import

            t0 = time.monotonic()
            self._session = mlx_qwen3_asr.Session(self.model_id)
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            print(f"[asr] model loaded in {elapsed_ms} ms", flush=True)
        except BaseException as e:  # propagate any failure
            self._load_error = e
            self._loaded.set()
            return
        self._loaded.set()

        while True:
            req = self._queue.get()
            if req is None:
                return
            try:
                kwargs = build_prompt_kwargs(req.language, req.context)
                session_kwargs: dict[str, Any] = {"context": kwargs["context"]}
                if "language" in kwargs and kwargs["language"] is not None:
                    session_kwargs["language"] = kwargs["language"]
                t0 = time.monotonic()
                result = self._session.transcribe(req.audio, **session_kwargs)
                duration_ms = int((time.monotonic() - t0) * 1000)
                req.result = (result.text.strip(), duration_ms)
            except BaseException as e:
                req.error = e
            finally:
                req.done.set()
