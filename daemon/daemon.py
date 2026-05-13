"""Dictation daemon entry. Run via LaunchAgent.

Lifecycle:
  - Load ASR model at startup.
  - Run HTTP server on 127.0.0.1:47823.
  - Each (POST /start, POST /stop) pair handles one dictation session.
"""

from __future__ import annotations

import os
import signal
import sys
import threading

import numpy as np

from daemon.asr import Asr
from daemon.audio import Recorder
from daemon.ipc import IpcServer

HOST = "127.0.0.1"
PORT = int(os.environ.get("DICTATION_PORT", "47823"))

# Energy gate: when the captured audio's RMS amplitude is below this threshold,
# treat the recording as silence and return empty text without invoking ASR.
# Qwen3-ASR is prompt-conditioned and hallucinates the context prompt back on
# silent input. Float32 mic audio sits at ~0.001 RMS in a quiet room; quiet
# speech is ~0.02; normal speech 0.05–0.2. 0.005 cleanly separates the two.
SILENCE_RMS_THRESHOLD = 0.005


def _self_terminate_after(delay_seconds: float, reason: str) -> None:
    # PortAudio caches AudioUnit state from Pa_Initialize and cannot recover when
    # coreaudiod restarts under us (macOS jetsam-recycles long-idle daemons).
    # Returning an error response leaves the process alive, so launchd's KeepAlive
    # never fires. Exiting forces a respawn with a fresh PortAudio. The delay lets
    # the in-flight HTTP response flush back to Hammerspoon before we die.
    def _exit() -> None:
        print(f"[daemon] self-terminating for restart: {reason}", flush=True)
        os._exit(1)
    threading.Timer(delay_seconds, _exit).start()


class DaemonHandler:
    """Glues IPC requests to recorder + ASR. One active session at a time."""

    def __init__(self, asr: Asr) -> None:
        self.asr = asr
        self.recorder: Recorder | None = None
        self.language = "auto"
        self.context = ""
        self._lock = threading.Lock()

    def on_start(self, msg: dict) -> dict:
        with self._lock:
            if self.recorder is not None:
                return {"ok": False, "error": "already_recording"}
            self.language = msg.get("language", "auto")
            self.context = msg.get("context", "")
            self.recorder = Recorder()
            try:
                self.recorder.start()
            except Exception as e:
                self.recorder = None
                _self_terminate_after(0.5, f"mic_error: {e}")
                return {"ok": False, "error": f"mic_error: {e}"}
            return {"ok": True, "session": "active"}

    def on_stop(self, msg: dict) -> dict:  # noqa: ARG002
        with self._lock:
            if self.recorder is None:
                return {"ok": False, "error": "not_recording"}
            recorder = self.recorder
            language = self.language
            context = self.context
            try:
                audio, truncated = recorder.stop()
            except Exception as e:
                self.recorder = None
                _self_terminate_after(0.5, f"audio_stop: {e}")
                return {"ok": False, "error": f"audio_stop: {e}"}
            self.recorder = None

        # Skip ASR on silent audio — prevents Qwen3-ASR from echoing the context prompt.
        if len(audio) > 0:
            rms = float(np.sqrt(np.mean(audio.astype(np.float32) ** 2)))
            if rms < SILENCE_RMS_THRESHOLD:
                print(f"[daemon] silent audio (rms={rms:.4f}), skipping ASR", flush=True)
                return {"ok": True, "text": "", "duration_ms": 0, "truncated": truncated}

        try:
            text, duration_ms = self.asr.transcribe(audio, language=language, context=context)
        except Exception as e:
            return {"ok": False, "error": f"asr_error: {e}"}
        return {"ok": True, "text": text, "duration_ms": duration_ms, "truncated": truncated}


def main() -> None:
    asr = Asr()
    print("[daemon] loading ASR model...", flush=True)
    asr.load()
    handler = DaemonHandler(asr)
    server = IpcServer(host=HOST, port=PORT, handler=handler)

    def shutdown(_signum, _frame):
        print("[daemon] shutting down", flush=True)
        server.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    server.start()
    print(f"[daemon] listening on http://{HOST}:{server.port}", flush=True)
    # Block forever
    threading.Event().wait()


if __name__ == "__main__":
    main()
