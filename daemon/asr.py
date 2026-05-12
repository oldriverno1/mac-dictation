"""mlx-qwen3-asr wrapper. Owns the loaded model for the lifetime of the daemon."""

from __future__ import annotations

import time
from typing import Any

import numpy as np


def build_prompt_kwargs(language: str, context: str) -> dict[str, Any]:
    """Build kwargs to pass to the underlying transcribe() call.

    Returns a dict with:
      - "context": always present (may be empty string)
      - "language": present only when a specific language is requested
        (i.e. language is non-empty and not "auto").  The value is the
        ISO code as passed in ("en", "zh", …); mlx_qwen3_asr.transcribe()
        calls canonicalize_language() internally so short codes work fine.
    """
    kwargs: dict[str, Any] = {"context": context}
    if language and language != "auto":
        kwargs["language"] = language
    return kwargs


class Asr:
    """Thin wrapper around mlx_qwen3_asr.Session.

    The heavy MLX import is deferred into load() so that tests importing
    only build_prompt_kwargs never touch the MLX stack.

    Real API (mlx-qwen3-asr 0.3.3):
      - mlx_qwen3_asr.Session(model_id)   — constructor, loads model
      - session.transcribe(
            audio,                          # np.ndarray (float32, 16 kHz mono)
            context="...",                  # system-prompt vocabulary bias
            language="en"|"zh"|None,        # ISO code or full name; None = auto
        ) -> TranscriptionResult
      - TranscriptionResult.text           # str
      - TranscriptionResult.language       # str (canonical language name)

    audio input may be:
      - np.ndarray  (assumed 16 kHz; Session resamples if passed as tuple (arr, sr))
      - (np.ndarray, sample_rate) tuple
    We always pass raw np.ndarray because we capture at 16 kHz.
    """

    MODEL_SAMPLE_RATE: int = 16_000

    def __init__(self, model_id: str = "Qwen/Qwen3-ASR-1.7B") -> None:
        self.model_id = model_id
        self._session: Any | None = None  # mlx_qwen3_asr.Session instance

    def load(self) -> None:
        """Preload the model into memory. Call once at daemon startup."""
        import mlx_qwen3_asr  # noqa: PLC0415 — intentional lazy import

        t0 = time.monotonic()
        self._session = mlx_qwen3_asr.Session(self.model_id)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        print(f"[asr] model loaded in {elapsed_ms} ms")

    def transcribe(
        self, audio: np.ndarray, language: str, context: str
    ) -> tuple[str, int]:
        """Run inference. Return (text, duration_ms).

        Args:
            audio:    Float32 numpy array, mono, 16 kHz.
            language: ISO code ("en", "zh") or "auto".
            context:  Free-form vocab-bias string passed as the system prompt.
        """
        if self._session is None:
            raise RuntimeError("Asr.load() must be called before transcribe()")
        if len(audio) == 0:
            return "", 0

        kwargs = build_prompt_kwargs(language, context)
        # Translate build_prompt_kwargs output into Session.transcribe() kwargs.
        # "language" key may be absent (auto) or hold an ISO code; the library
        # accepts both ISO codes and full names, so pass through as-is.
        session_kwargs: dict[str, Any] = {
            "context": kwargs["context"],
        }
        if "language" in kwargs and kwargs["language"] is not None:
            session_kwargs["language"] = kwargs["language"]

        t0 = time.monotonic()
        result = self._session.transcribe(audio, **session_kwargs)
        duration_ms = int((time.monotonic() - t0) * 1000)

        return result.text.strip(), duration_ms
