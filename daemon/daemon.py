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

from daemon.asr import Asr
from daemon.audio import Recorder
from daemon.ipc import IpcServer

HOST = "127.0.0.1"
PORT = int(os.environ.get("DICTATION_PORT", "47823"))


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
                return {"ok": False, "error": f"audio_stop: {e}"}
            self.recorder = None
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
