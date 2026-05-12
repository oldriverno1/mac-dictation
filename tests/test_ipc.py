import json
import urllib.request
import urllib.error

import pytest

from daemon.ipc import IpcServer


class StubHandler:
    """Fake handler that records calls and returns canned responses."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def on_start(self, msg: dict) -> dict:
        self.calls.append(("start", msg))
        return {"ok": True, "session": "session-1"}

    def on_stop(self, msg: dict) -> dict:
        self.calls.append(("stop", msg))
        return {"ok": True, "text": "hello world", "duration_ms": 1000, "truncated": False}


def _post(port: int, path: str, body: dict | str) -> tuple[int, dict]:
    """POST JSON body, return (status, parsed_json_response)."""
    data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


@pytest.fixture
def server():
    handler = StubHandler()
    s = IpcServer(host="127.0.0.1", port=0, handler=handler)
    s.start()
    try:
        yield s, handler
    finally:
        s.stop()


def test_start_then_stop(server):
    s, handler = server
    code, resp = _post(s.port, "/start", {"language": "en", "context": "ctx"})
    assert code == 200
    assert resp == {"ok": True, "session": "session-1"}
    assert handler.calls[0] == ("start", {"language": "en", "context": "ctx"})

    code, resp = _post(s.port, "/stop", {})
    assert code == 200
    assert resp["ok"] is True
    assert resp["text"] == "hello world"
    assert handler.calls[1][0] == "stop"


def test_unknown_path_404(server):
    s, _ = server
    code, resp = _post(s.port, "/lol", {})
    assert code == 404
    assert resp["ok"] is False


def test_malformed_json_returns_400(server):
    s, _ = server
    code, resp = _post(s.port, "/start", "not json")
    assert code == 400
    assert resp["ok"] is False
    assert "bad_json" in resp["error"]


def test_handler_exception_returns_500(server):
    s, handler = server

    def boom(_msg):
        raise RuntimeError("kaboom")

    handler.on_start = boom  # type: ignore
    code, resp = _post(s.port, "/start", {})
    assert code == 500
    assert resp["ok"] is False
    assert "kaboom" in resp["error"]


def test_only_listens_on_loopback(server):
    """Defensive: the bound host must be 127.0.0.1, not 0.0.0.0."""
    s, _ = server
    assert s.host == "127.0.0.1"
