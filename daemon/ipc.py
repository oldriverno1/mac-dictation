"""Localhost HTTP server for the dictation daemon.

Binds to 127.0.0.1 only. Two endpoints, both POST with JSON bodies.
The handler object must expose `on_start(msg) -> dict` and `on_stop(msg) -> dict`.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Protocol


class IpcHandler(Protocol):
    def on_start(self, msg: dict) -> dict: ...
    def on_stop(self, msg: dict) -> dict: ...


class IpcServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 47823, handler: IpcHandler | None = None):
        if handler is None:
            raise ValueError("handler is required")
        if host != "127.0.0.1":
            raise ValueError("host must be 127.0.0.1 — daemon must not accept remote connections")
        self.host = host
        self._requested_port = port
        self.port = port
        self.handler = handler
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        handler_ref = self.handler

        class _RequestHandler(BaseHTTPRequestHandler):
            def log_message(self, *_args, **_kw):  # silence default access log
                return

            def _read_json(self) -> dict | None:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length else b""
                if not raw:
                    return {}
                try:
                    return json.loads(raw.decode())
                except (UnicodeDecodeError, json.JSONDecodeError) as e:
                    self._send(400, {"ok": False, "error": f"bad_json: {e}"})
                    return None

            def _send(self, status: int, body: dict) -> None:
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):  # noqa: N802
                if self.path == "/start":
                    msg = self._read_json()
                    if msg is None:
                        return
                    try:
                        resp = handler_ref.on_start(msg)
                        self._send(200, resp)
                    except Exception as e:
                        self._send(500, {"ok": False, "error": f"handler_exception: {e}"})
                elif self.path == "/stop":
                    msg = self._read_json()
                    if msg is None:
                        return
                    try:
                        resp = handler_ref.on_stop(msg)
                        self._send(200, resp)
                    except Exception as e:
                        self._send(500, {"ok": False, "error": f"handler_exception: {e}"})
                else:
                    self._send(404, {"ok": False, "error": f"unknown_path: {self.path}"})

        self._httpd = ThreadingHTTPServer((self.host, self._requested_port), _RequestHandler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
