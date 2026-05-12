# Mac Voice Dictation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local-only macOS push-to-talk dictation tool: hold Right Command, speak (English or Traditional Chinese), release — transcribed text appears at the cursor.

**Architecture:** Two-process design. A Python LaunchAgent (`daemon.py`) preloads `mlx-qwen3-asr`, owns the microphone, and runs an HTTP server on `127.0.0.1:47823`. A Hammerspoon Lua module handles the Right Cmd hotkey, reads the macOS input source, talks to the daemon over `hs.http.asyncPost`, simulates Cmd+V, and shows menu bar feedback.

**Tech Stack:** Python 3.12 + `mlx-qwen3-asr` + `sounddevice`, Hammerspoon (Lua), `macism` (CLI for IME), launchd, `uv` for venv.

**Spec:** `/Users/Lars/llm/docs/specs/2026-05-12-mac-voice-dictation-design.md`

**Reference repo layout:** `/Users/Lars/llm/dictation/` (new, will be `git init`-ed in Task 0)

---

## Pre-flight environment notes (for the executing engineer)

- `Hammerspoon` is **not** installed yet — Task 1 installs it.
- `macism` is **not** installed yet — Task 1 installs it.
- Use `uv` (already installed at `~/.local/bin/uv`) for the venv; the user has `.venv-*` style siblings under `/Users/Lars/llm/`.
- The user has an existing `omlx` LLM server running. Do **not** call `mx.set_wired_limit()` anywhere in the daemon — it would conflict with omlx's wiring. Just let MLX manage memory normally.
- Today's date for any timestamps: `2026-05-12`.
- The user's login is `Lars`. Home is `/Users/Lars`.
- The user runs zsh.
- `/Users/Lars/llm/` is **not** a git repo. The `dictation/` subdirectory will be its own repo.

---

## File structure

```
/Users/Lars/llm/dictation/
├── daemon/
│   ├── __init__.py
│   ├── daemon.py              # entry point: load model, run IPC server
│   ├── asr.py                 # mlx-qwen3-asr wrapper, prompt building
│   ├── audio.py               # sounddevice mic capture → numpy float32 @ 16 kHz
│   ├── ipc.py                 # Unix socket JSON line protocol
│   └── config.py              # IME-to-language mapping, context prompts
├── hammerspoon/
│   ├── init.lua               # Hammerspoon entry that loads dictation.lua
│   └── dictation.lua          # hotkey, menu bar, IPC client, paste flow
├── launchagent/
│   └── com.henry.dictation.plist
├── scripts/
│   ├── install.sh             # install LaunchAgent + Hammerspoon symlink
│   └── uninstall.sh
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_config.py
│   ├── test_ipc.py
│   ├── test_asr_prompt.py
│   └── fixtures/              # short wav files for ASR smoke test
├── pyproject.toml
├── README.md
└── .gitignore
```

**File responsibilities (one-liner each):**

- `daemon.py` — orchestrator: starts HTTP server, owns the ASR + Audio objects, glues requests to actions.
- `asr.py` — wraps `mlx-qwen3-asr`; `Asr.load()` preloads the model; `Asr.transcribe(audio_np, language, context)` returns text.
- `audio.py` — `Recorder.start()` opens mic with sounddevice in a background thread, appends to a buffer; `Recorder.stop()` returns the buffer as numpy float32 @ 16 kHz mono.
- `ipc.py` — HTTP server bound to `127.0.0.1:47823`. Two endpoints: `POST /start` and `POST /stop`. JSON in / JSON out.
- `config.py` — pure module of constants: `IME_TO_LANG` mapping, `CONTEXT_PROMPTS` dict. Plus a small `resolve_language(ime_id: str) -> tuple[lang, context]`.
- `dictation.lua` — all the Mac side: hotkey, menubar, HTTP client, paste flow.

---

## Task 0: Repo scaffolding and git init

**Files:**
- Create: `/Users/Lars/llm/dictation/` (directory)
- Create: `/Users/Lars/llm/dictation/.gitignore`
- Create: `/Users/Lars/llm/dictation/README.md`
- Create: `/Users/Lars/llm/dictation/pyproject.toml`

- [ ] **Step 1: Create directory tree**

```bash
mkdir -p /Users/Lars/llm/dictation/{daemon,hammerspoon,launchagent,scripts,tests/fixtures}
touch /Users/Lars/llm/dictation/daemon/__init__.py
touch /Users/Lars/llm/dictation/tests/__init__.py
```

- [ ] **Step 2: Write `.gitignore`**

File: `/Users/Lars/llm/dictation/.gitignore`

```
__pycache__/
*.pyc
.pytest_cache/
.venv-dictation/
*.log
*.err
.DS_Store
```

- [ ] **Step 3: Write `pyproject.toml`**

File: `/Users/Lars/llm/dictation/pyproject.toml`

```toml
[project]
name = "dictation"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "mlx-qwen3-asr>=0.1.0",
    "sounddevice>=0.5.0",
    "numpy>=2.0.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0.0", "pytest-mock>=3.12.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v"
```

- [ ] **Step 4: Write a minimal `README.md`**

File: `/Users/Lars/llm/dictation/README.md`

```markdown
# Dictation

Personal push-to-talk voice dictation for macOS. Hold Right Command, speak English or Traditional Chinese, release — text is pasted at the cursor. All inference local via `mlx-qwen3-asr`.

See `../docs/specs/2026-05-12-mac-voice-dictation-design.md` for the design.

## Install
See `scripts/install.sh`.
```

- [ ] **Step 5: Initialize git**

```bash
cd /Users/Lars/llm/dictation
git init
git add .
git commit -m "chore: scaffold dictation project"
```

Expected: `git status` shows clean working tree.

---

## Task 1: Install host-side dependencies

These are system tools the daemon and Hammerspoon code depend on. Done by hand (these are not committed).

- [ ] **Step 1: Install Hammerspoon via brew cask**

```bash
brew install --cask hammerspoon
```

Expected: `/Applications/Hammerspoon.app` exists.

- [ ] **Step 2: Install macism via brew**

```bash
brew install laishulu/homebrew-macism/macism
```

Verify: `macism` (no args) prints the current input source identifier, e.g., `com.apple.keylayout.ABC`.

If the tap fails, fallback:

```bash
curl -L -o /usr/local/bin/macism https://github.com/laishulu/macism/releases/latest/download/macism
chmod +x /usr/local/bin/macism
```

- [ ] **Step 3: Create the Python venv with `uv`**

```bash
cd /Users/Lars/llm/dictation
uv venv --python 3.12 .venv-dictation
source .venv-dictation/bin/activate
uv pip install -e ".[dev]"
```

Expected: `python -c "import mlx_qwen3_asr; print(mlx_qwen3_asr.__version__)"` prints a version number without error.

- [ ] **Step 4: Pre-pull the Qwen3-ASR-1.7B model so first daemon start isn't a 5GB download**

```bash
huggingface-cli download Qwen/Qwen3-ASR-1.7B --local-dir ~/.cache/qwen3-asr-1.7b
```

(Or whatever path `mlx-qwen3-asr` defaults to — check its README first; some versions auto-download on first import.)

Expected: `~/.cache/qwen3-asr-1.7b/` contains weight files (~3-4 GB on disk).

- [ ] **Step 5: Grant the venv Python mic access**

Open System Settings → Privacy & Security → Microphone. After Task 5 runs (which will trigger a permission prompt), this entry will appear. For now, just be aware this is where to look.

No commit for this task — these are environment setup steps, not code.

---

## Task 2: `config.py` — IME mapping (TDD)

**Files:**
- Create: `/Users/Lars/llm/dictation/daemon/config.py`
- Test: `/Users/Lars/llm/dictation/tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

File: `/Users/Lars/llm/dictation/tests/test_config.py`

```python
from daemon.config import resolve_language, IME_TO_LANG, CONTEXT_PROMPTS


def test_us_keyboard_resolves_to_english():
    lang, ctx = resolve_language("com.apple.keylayout.ABC")
    assert lang == "en"
    assert "English" in ctx


def test_zhuyin_resolves_to_chinese():
    lang, ctx = resolve_language("com.apple.inputmethod.TCIM.Zhuyin")
    assert lang == "zh"
    assert "繁體中文" in ctx


def test_cangjie_resolves_to_chinese():
    lang, ctx = resolve_language("com.apple.inputmethod.TCIM.Cangjie")
    assert lang == "zh"


def test_simplified_chinese_resolves_to_chinese():
    lang, ctx = resolve_language("com.apple.inputmethod.SCIM.Pinyin")
    assert lang == "zh"


def test_unknown_falls_back_to_auto():
    lang, ctx = resolve_language("com.example.foo.bar")
    assert lang == "auto"
    assert ctx == ""


def test_empty_string_falls_back_to_auto():
    lang, ctx = resolve_language("")
    assert lang == "auto"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/Lars/llm/dictation
source .venv-dictation/bin/activate
pytest tests/test_config.py -v
```

Expected: ImportError / ModuleNotFoundError on `daemon.config`.

- [ ] **Step 3: Write `daemon/config.py`**

File: `/Users/Lars/llm/dictation/daemon/config.py`

```python
"""IME identifier → (language, context prompt) resolution."""

IME_TO_LANG: dict[str, str] = {
    # English
    "com.apple.keylayout.ABC": "en",
    "com.apple.keylayout.US": "en",
    "com.apple.keylayout.British": "en",
    "com.apple.keylayout.Australian": "en",
    "com.apple.keylayout.Canadian": "en",
    "com.apple.keylayout.Dvorak": "en",
}

# Prefixes for fuzzy matching (input methods whose ID has a variable suffix).
IME_PREFIX_TO_LANG: list[tuple[str, str]] = [
    ("com.apple.inputmethod.TCIM.", "zh"),  # Traditional Chinese (Zhuyin, Cangjie, ...)
    ("com.apple.inputmethod.SCIM.", "zh"),  # Simplified Chinese
    ("com.apple.inputmethod.TYIM.", "zh"),  # Yale-style
]

CONTEXT_PROMPTS: dict[str, str] = {
    "en": "The following is English dictation. May include technical terms such as MLX, Python, transformer.",
    "zh": "以下是繁體中文（台灣）的口述輸入，可能包含技術術語如 MLX、Python、LLM。",
    "auto": "",
}


def resolve_language(ime_id: str) -> tuple[str, str]:
    """Return (lang_code, context_prompt) for a macOS input source identifier.

    Returns ('auto', '') for unknown identifiers — let the ASR model auto-detect.
    """
    if ime_id in IME_TO_LANG:
        lang = IME_TO_LANG[ime_id]
        return lang, CONTEXT_PROMPTS[lang]

    for prefix, lang in IME_PREFIX_TO_LANG:
        if ime_id.startswith(prefix):
            return lang, CONTEXT_PROMPTS[lang]

    return "auto", CONTEXT_PROMPTS["auto"]
```

- [ ] **Step 4: Run tests, confirm pass**

```bash
pytest tests/test_config.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/Lars/llm/dictation
git add daemon/config.py daemon/__init__.py tests/test_config.py tests/__init__.py
git commit -m "feat(config): add IME-to-language resolver with prompts"
```

---

## Task 3: `ipc.py` — HTTP server on 127.0.0.1:47823 (TDD)

**Files:**
- Create: `/Users/Lars/llm/dictation/daemon/ipc.py`
- Test: `/Users/Lars/llm/dictation/tests/test_ipc.py`

The protocol: two HTTP endpoints, JSON bodies. `POST /start` accepts `{"language", "context"}`, returns `{"ok": true, "session": ...}`. `POST /stop` accepts `{}`, returns `{"ok": true, "text", "duration_ms", "truncated"}`. We pick HTTP over Unix socket because Hammerspoon's `hs.http.asyncPost` is the cleanest async API available to it. Bind to `127.0.0.1` only — never accept remote connections.

- [ ] **Step 1: Write the failing tests**

File: `/Users/Lars/llm/dictation/tests/test_ipc.py`

```python
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
```

- [ ] **Step 2: Run tests, confirm they fail**

```bash
cd /Users/Lars/llm/dictation
source .venv-dictation/bin/activate
pytest tests/test_ipc.py -v
```

Expected: ImportError on `daemon.ipc`.

- [ ] **Step 3: Implement `daemon/ipc.py`**

File: `/Users/Lars/llm/dictation/daemon/ipc.py`

```python
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
```

- [ ] **Step 4: Run tests, confirm pass**

```bash
pytest tests/test_ipc.py -v
```

Expected: all 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add daemon/ipc.py tests/test_ipc.py
git commit -m "feat(ipc): HTTP server on 127.0.0.1:47823 with /start /stop"
```

---

## Task 4: `audio.py` — mic capture wrapper (test-light)

**Files:**
- Create: `/Users/Lars/llm/dictation/daemon/audio.py`

This module talks to real hardware (mic). No TDD — we'd need to mock sounddevice. Instead: write a thin wrapper with a clear API, and verify it manually.

- [ ] **Step 1: Implement `daemon/audio.py`**

File: `/Users/Lars/llm/dictation/daemon/audio.py`

```python
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
```

- [ ] **Step 2: Manual smoke test**

```bash
cd /Users/Lars/llm/dictation
source .venv-dictation/bin/activate
python -c "
from daemon.audio import Recorder
import time
r = Recorder()
print('Speak for 2 seconds...')
r.start()
time.sleep(2)
audio, truncated = r.stop()
print(f'Got {len(audio)} samples ({len(audio)/16000:.2f}s), truncated={truncated}')
assert 30000 < len(audio) < 35000, 'expected ~32000 samples'
print('OK')
"
```

Expected: macOS prompts for Microphone permission on first run. Grant it. Then it prints `Got ~32000 samples (~2.00s), truncated=False`, then `OK`.

If the prompt does not appear, mic access may already be denied to the bundle Python is running from. Open Settings → Privacy & Security → Microphone and add the Python binary.

- [ ] **Step 3: Commit**

```bash
git add daemon/audio.py
git commit -m "feat(audio): sounddevice-based 16kHz mono mic capture with 60s cap"
```

---

## Task 5: `asr.py` — `mlx-qwen3-asr` wrapper (test prompt logic, smoke-test inference)

**Files:**
- Create: `/Users/Lars/llm/dictation/daemon/asr.py`
- Test: `/Users/Lars/llm/dictation/tests/test_asr_prompt.py`
- Test fixture: `/Users/Lars/llm/dictation/tests/fixtures/hello.wav` (record manually, see Step 5)

We TDD the prompt-building logic (pure) and smoke-test actual inference (heavy).

- [ ] **Step 1: Write the failing test for prompt building**

File: `/Users/Lars/llm/dictation/tests/test_asr_prompt.py`

```python
from daemon.asr import build_prompt_kwargs


def test_english_prompt():
    kwargs = build_prompt_kwargs("en", "Some English context.")
    assert kwargs["language"] == "en"
    assert "Some English context." in kwargs["context"]


def test_chinese_prompt():
    kwargs = build_prompt_kwargs("zh", "以下是繁體中文")
    assert kwargs["language"] == "zh"
    assert "繁體中文" in kwargs["context"]


def test_auto_omits_language_hint():
    kwargs = build_prompt_kwargs("auto", "")
    # 'auto' means let the model decide → don't pass language=
    assert "language" not in kwargs or kwargs["language"] is None
```

- [ ] **Step 2: Run test, confirm failure**

```bash
pytest tests/test_asr_prompt.py -v
```

Expected: ImportError on `daemon.asr`.

- [ ] **Step 3: Implement `daemon/asr.py`**

File: `/Users/Lars/llm/dictation/daemon/asr.py`

```python
"""mlx-qwen3-asr wrapper. Owns the loaded model for the lifetime of the daemon."""

from __future__ import annotations

import time
from typing import Any

import numpy as np


def build_prompt_kwargs(language: str, context: str) -> dict[str, Any]:
    """Build kwargs to pass to the underlying transcribe() call."""
    kwargs: dict[str, Any] = {"context": context}
    if language and language != "auto":
        kwargs["language"] = language
    return kwargs


class Asr:
    """Lazy-imports mlx-qwen3-asr so the module can be imported without MLX present (for unit tests)."""

    def __init__(self, model_id: str = "Qwen/Qwen3-ASR-1.7B") -> None:
        self.model_id = model_id
        self._model: Any | None = None

    def load(self) -> None:
        """Preload the model into memory. Call once at daemon startup."""
        from mlx_qwen3_asr import load_model  # type: ignore

        t0 = time.monotonic()
        self._model = load_model(self.model_id)
        print(f"[asr] loaded {self.model_id} in {time.monotonic() - t0:.1f}s", flush=True)

    def transcribe(
        self, audio: np.ndarray, language: str, context: str
    ) -> tuple[str, int]:
        """Run inference. Return (text, duration_ms)."""
        if self._model is None:
            raise RuntimeError("Asr.load() must be called before transcribe()")
        if len(audio) == 0:
            return "", 0
        kwargs = build_prompt_kwargs(language, context)
        t0 = time.monotonic()
        result = self._model.transcribe(audio, sample_rate=16_000, **kwargs)
        duration_ms = int((time.monotonic() - t0) * 1000)
        # Normalize: mlx-qwen3-asr returns either str or dict-with-'text' depending on version
        text = result["text"] if isinstance(result, dict) else str(result)
        return text.strip(), duration_ms
```

- [ ] **Step 4: Run prompt tests, confirm pass**

```bash
pytest tests/test_asr_prompt.py -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Record a fixture wav and smoke-test inference manually**

```bash
cd /Users/Lars/llm/dictation
source .venv-dictation/bin/activate
# Record 3 seconds of yourself saying "hello world" to fixtures/hello.wav
python -c "
import sounddevice as sd
import scipy.io.wavfile as wav
import numpy as np
print('Say: hello world (3s)')
audio = sd.rec(int(3 * 16000), samplerate=16000, channels=1, dtype='float32')
sd.wait()
wav.write('tests/fixtures/hello.wav', 16000, audio)
print('saved')
"
```

If `scipy` isn't installed: `uv pip install scipy`.

Now run inference end-to-end:

```bash
python -c "
import scipy.io.wavfile as wav
from daemon.asr import Asr
sr, audio = wav.read('tests/fixtures/hello.wav')
audio = audio.astype('float32') / 32768.0 if audio.dtype != 'float32' else audio
asr = Asr()
asr.load()
text, ms = asr.transcribe(audio, language='en', context='English dictation')
print(f'[{ms}ms]: {text!r}')
"
```

Expected: prints something close to `'hello world'` after a one-time model-load delay (~10s).

- [ ] **Step 6: Commit (without the wav fixture — it's user-specific)**

```bash
echo "tests/fixtures/*.wav" >> .gitignore
git add daemon/asr.py tests/test_asr_prompt.py .gitignore
git commit -m "feat(asr): mlx-qwen3-asr wrapper with prompt builder"
```

---

## Task 6: `daemon.py` — wire IPC + Audio + ASR together

**Files:**
- Create: `/Users/Lars/llm/dictation/daemon/daemon.py`

- [ ] **Step 1: Implement `daemon/daemon.py`**

File: `/Users/Lars/llm/dictation/daemon/daemon.py`

```python
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
            self.recorder = None
            language = self.language
            context = self.context
        try:
            audio, truncated = recorder.stop()
        except Exception as e:
            return {"ok": False, "error": f"audio_stop: {e}"}
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
```

- [ ] **Step 2: Manual smoke test the daemon**

Terminal A:

```bash
cd /Users/Lars/llm/dictation
source .venv-dictation/bin/activate
python -m daemon.daemon
```

Wait for `[daemon] listening on /tmp/dictation.sock`.

Terminal B:

```bash
curl -s -X POST http://127.0.0.1:47823/start \
  -H 'Content-Type: application/json' \
  -d '{"language":"en","context":"English dictation"}'
echo
echo "SPEAK NOW for 2 seconds..."
sleep 2
curl -s -X POST http://127.0.0.1:47823/stop \
  -H 'Content-Type: application/json' \
  -d '{}'
echo
```

Expected: `{"ok": true, "session": "active"}` then `{"ok": true, "text": "<your speech>", "duration_ms": ..., "truncated": false}`.

Stop daemon with Ctrl-C in Terminal A. Expected: clean exit (no traceback).

- [ ] **Step 3: Commit**

```bash
git add daemon/daemon.py
git commit -m "feat(daemon): wire IPC + audio + ASR with one-session-at-a-time handler"
```

---

## Task 7: LaunchAgent plist + install/uninstall scripts

**Files:**
- Create: `/Users/Lars/llm/dictation/launchagent/com.henry.dictation.plist`
- Create: `/Users/Lars/llm/dictation/scripts/install.sh`
- Create: `/Users/Lars/llm/dictation/scripts/uninstall.sh`

- [ ] **Step 1: Write the plist**

File: `/Users/Lars/llm/dictation/launchagent/com.henry.dictation.plist`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.henry.dictation</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/Lars/llm/dictation/.venv-dictation/bin/python</string>
        <string>-m</string>
        <string>daemon.daemon</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/Lars/llm/dictation</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>10</integer>
    <key>StandardOutPath</key>
    <string>/Users/Lars/Library/Logs/dictation.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/Lars/Library/Logs/dictation.err</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
```

- [ ] **Step 2: Write `install.sh`**

File: `/Users/Lars/llm/dictation/scripts/install.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAUNCH_AGENT_DIR="$HOME/Library/LaunchAgents"
PLIST_NAME="com.henry.dictation.plist"
HAMMERSPOON_DIR="$HOME/.hammerspoon"

mkdir -p "$LAUNCH_AGENT_DIR" "$HAMMERSPOON_DIR"

# 1. Symlink the LaunchAgent plist
if [ -L "$LAUNCH_AGENT_DIR/$PLIST_NAME" ] || [ -f "$LAUNCH_AGENT_DIR/$PLIST_NAME" ]; then
    echo "Removing existing $PLIST_NAME"
    launchctl unload "$LAUNCH_AGENT_DIR/$PLIST_NAME" 2>/dev/null || true
    rm -f "$LAUNCH_AGENT_DIR/$PLIST_NAME"
fi
ln -s "$REPO_DIR/launchagent/$PLIST_NAME" "$LAUNCH_AGENT_DIR/$PLIST_NAME"
echo "Linked $LAUNCH_AGENT_DIR/$PLIST_NAME"

# 2. Symlink the Hammerspoon module (dictation.lua) into ~/.hammerspoon/
if [ -L "$HAMMERSPOON_DIR/dictation.lua" ] || [ -f "$HAMMERSPOON_DIR/dictation.lua" ]; then
    rm -f "$HAMMERSPOON_DIR/dictation.lua"
fi
ln -s "$REPO_DIR/hammerspoon/dictation.lua" "$HAMMERSPOON_DIR/dictation.lua"
echo "Linked $HAMMERSPOON_DIR/dictation.lua"

# 3. Make sure ~/.hammerspoon/init.lua loads our module
INIT_LUA="$HAMMERSPOON_DIR/init.lua"
LOAD_LINE='require("dictation")'
if [ ! -f "$INIT_LUA" ] || ! grep -qF "$LOAD_LINE" "$INIT_LUA"; then
    echo "$LOAD_LINE" >> "$INIT_LUA"
    echo "Appended dictation loader to $INIT_LUA"
fi

# 4. Load the LaunchAgent
launchctl load "$LAUNCH_AGENT_DIR/$PLIST_NAME"
echo "LaunchAgent loaded. Daemon starting (model load takes ~10s)."

# 5. Reload Hammerspoon if it's running
if pgrep -x Hammerspoon >/dev/null; then
    osascript -e 'tell application "Hammerspoon" to reload'
    echo "Hammerspoon reloaded."
else
    echo "Hammerspoon is not running. Launch it from /Applications and grant Accessibility permission."
fi
```

```bash
chmod +x /Users/Lars/llm/dictation/scripts/install.sh
```

- [ ] **Step 3: Write `uninstall.sh`**

File: `/Users/Lars/llm/dictation/scripts/uninstall.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

LAUNCH_AGENT_DIR="$HOME/Library/LaunchAgents"
PLIST_NAME="com.henry.dictation.plist"
HAMMERSPOON_DIR="$HOME/.hammerspoon"

launchctl unload "$LAUNCH_AGENT_DIR/$PLIST_NAME" 2>/dev/null || true
rm -f "$LAUNCH_AGENT_DIR/$PLIST_NAME"
rm -f "$HAMMERSPOON_DIR/dictation.lua"

INIT_LUA="$HAMMERSPOON_DIR/init.lua"
if [ -f "$INIT_LUA" ]; then
    sed -i '' '/require("dictation")/d' "$INIT_LUA"
fi

if pgrep -x Hammerspoon >/dev/null; then
    osascript -e 'tell application "Hammerspoon" to reload'
fi

echo "Uninstalled. Daemon stopped, plist removed, Hammerspoon module unlinked."
```

```bash
chmod +x /Users/Lars/llm/dictation/scripts/uninstall.sh
```

- [ ] **Step 4: Commit**

```bash
git add launchagent/com.henry.dictation.plist scripts/install.sh scripts/uninstall.sh
git commit -m "feat(launch): LaunchAgent plist + install/uninstall scripts"
```

---

## Task 8: Hammerspoon module — hotkey, IPC client, paste flow, menubar

**Files:**
- Create: `/Users/Lars/llm/dictation/hammerspoon/dictation.lua`

This is the user-facing piece. Hammerspoon's Lua API is documented at https://www.hammerspoon.org/docs/. Key APIs used: `hs.eventtap` (capture flagsChanged), `hs.menubar`, `hs.sound`, `hs.execute` (shell out to `macism`), `hs.http.asyncPost` (talk to daemon), `hs.pasteboard`, `hs.eventtap.keyStroke`.

- [ ] **Step 1: Implement `hammerspoon/dictation.lua`**

File: `/Users/Lars/llm/dictation/hammerspoon/dictation.lua`

```lua
-- Dictation: hold Right Command anywhere, speak, release, transcript pastes at cursor.

local M = {}

local DAEMON = "http://127.0.0.1:47823"
local HEADERS = {["Content-Type"] = "application/json"}

-- IOKit device-specific flag mask for the right Command key.
-- NX_DEVICERCMDKEYMASK = 0x10 (bit 4 of the low byte of CGEventFlags).
-- We must use this rather than ev:getFlags().cmd, which is set when *either* Cmd is down.
local RIGHT_CMD_MASK = 0x10
local RIGHT_CMD_KEYCODE = 54  -- Apple keyCode for Right Command

-- ---------- State ----------
M.menubar = nil
M.recording = false
M.saved_clipboard = nil
M.saved_changeCount = nil

-- ---------- Menubar ----------
local ICONS = {
    idle         = "⚪",
    recording    = "🔴",
    transcribing = "🟡",
    pasting      = "🟢",
    error        = "❌",
}

local function set_state(state)
    if M.menubar then M.menubar:setTitle(ICONS[state] or "?") end
end

-- ---------- Sounds ----------
local function play(name)
    local s = hs.sound.getByName(name)
    if s then s:play() end
end

-- ---------- IME detection ----------
local function current_ime()
    -- macism prints the current input source ID, e.g. com.apple.keylayout.ABC
    local out, ok = hs.execute("/opt/homebrew/bin/macism", false)
    if not ok or not out then return "" end
    return (out:gsub("%s+$", ""))
end

local IME_EXACT = {
    ["com.apple.keylayout.ABC"]        = "en",
    ["com.apple.keylayout.US"]         = "en",
    ["com.apple.keylayout.British"]    = "en",
    ["com.apple.keylayout.Australian"] = "en",
    ["com.apple.keylayout.Canadian"]   = "en",
    ["com.apple.keylayout.Dvorak"]     = "en",
}

local IME_PREFIX = {
    {"com.apple.inputmethod.TCIM.", "zh"},
    {"com.apple.inputmethod.SCIM.", "zh"},
    {"com.apple.inputmethod.TYIM.", "zh"},
}

local CTX = {
    en = "The following is English dictation. May include technical terms such as MLX, Python, transformer.",
    zh = "以下是繁體中文（台灣）的口述輸入，可能包含技術術語如 MLX、Python、LLM。",
    auto = "",
}

local function resolve_lang(ime)
    if IME_EXACT[ime] then return IME_EXACT[ime], CTX[IME_EXACT[ime]] end
    for _, pair in ipairs(IME_PREFIX) do
        if ime:sub(1, #pair[1]) == pair[1] then
            return pair[2], CTX[pair[2]]
        end
    end
    return "auto", ""
end

-- ---------- IPC (HTTP to daemon) ----------
local function post(path, body, on_done)
    local req_body = hs.json.encode(body)
    hs.http.asyncPost(DAEMON .. path, req_body, HEADERS, function(status, resp_body, _resp_headers)
        if status < 0 then
            on_done({ok = false, error = "daemon_unreachable: " .. tostring(status)})
            return
        end
        local ok_decode, resp = pcall(hs.json.decode, resp_body or "{}")
        if not ok_decode or type(resp) ~= "table" then
            on_done({ok = false, error = "bad_response: " .. tostring(resp_body)})
            return
        end
        on_done(resp)
    end)
end

-- ---------- Paste flow ----------
local function paste_with_restore(text)
    set_state("pasting")
    M.saved_clipboard = hs.pasteboard.getContents()
    M.saved_changeCount = hs.pasteboard.changeCount()

    -- Send Escape to collapse any active IME composition buffer.
    hs.eventtap.keyStroke({}, "escape", 0)

    -- Write our text and immediately paste.
    hs.pasteboard.setContents(text)
    hs.eventtap.keyStroke({"cmd"}, "v", 0)

    -- Poll changeCount until it advances past our write, then restore (timeout 1s).
    local started_at = hs.timer.absoluteTime()
    local function poll()
        local elapsed_s = (hs.timer.absoluteTime() - started_at) / 1e9
        if hs.pasteboard.changeCount() > (M.saved_changeCount + 1) or elapsed_s > 1.0 then
            if M.saved_clipboard then
                hs.pasteboard.setContents(M.saved_clipboard)
            end
            set_state("idle")
            return
        end
        hs.timer.doAfter(0.05, poll)
    end
    hs.timer.doAfter(0.05, poll)
end

-- ---------- Right Cmd listener ----------
local function on_right_cmd_down()
    if M.recording then return end
    M.recording = true
    set_state("recording")
    play("Tink")
    local ime = current_ime()
    local lang, ctx = resolve_lang(ime)
    post("/start", {language = lang, context = ctx}, function(resp)
        if not resp.ok then
            M.recording = false
            set_state("error")
            play("Funk")
            hs.notify.new({title = "Dictation", informativeText = tostring(resp.error)}):send()
            hs.timer.doAfter(3, function() set_state("idle") end)
        end
    end)
end

local function on_right_cmd_up()
    if not M.recording then return end
    M.recording = false
    set_state("transcribing")
    post("/stop", {}, function(resp)
        if resp.ok and resp.text and #resp.text > 0 then
            paste_with_restore(resp.text)
        elseif resp.ok then
            set_state("idle")  -- empty transcription
        else
            set_state("error")
            play("Funk")
            hs.notify.new({title = "Dictation", informativeText = tostring(resp.error)}):send()
            hs.timer.doAfter(3, function() set_state("idle") end)
        end
    end)
end

-- ---------- Bootstrap ----------
function M.start()
    M.menubar = hs.menubar.new()
    set_state("idle")

    -- flagsChanged fires for every modifier change. Filter to events whose keyCode is
    -- the Right Command (54). The post-transition raw flag tells us whether right cmd
    -- is now down (bit set) or now up (bit cleared). This works correctly even when
    -- the left Command is simultaneously held.
    M.tap = hs.eventtap.new({hs.eventtap.event.types.flagsChanged}, function(ev)
        if ev:getKeyCode() ~= RIGHT_CMD_KEYCODE then return false end
        local raw = ev:rawFlags()
        local right_cmd_down = (raw & RIGHT_CMD_MASK) ~= 0
        if right_cmd_down then
            on_right_cmd_down()
        else
            on_right_cmd_up()
        end
        return false
    end)
    M.tap:start()
    print("[dictation] started, right-cmd listener active")
end

M.start()
return M
```

- [ ] **Step 2: Reload Hammerspoon and verify menu bar appears**

(Assuming `scripts/install.sh` was run, which symlinked the lua and appended to init.lua.)

```bash
osascript -e 'tell application "Hammerspoon" to reload'
```

Open Hammerspoon Console (menu bar → Hammerspoon icon → Console). You should see `[dictation] started, right-cmd listener active`. The menu bar should show ⚪.

- [ ] **Step 3: End-to-end smoke test (with daemon running)**

1. Open TextEdit, create a new doc, click in it.
2. Hold Right Command, say "hello world", release.
3. Expected: ⚪ → 🔴 (on press) → 🟡 (on release) → 🟢 → ⚪. The text "hello world" appears in TextEdit.
4. Copy a URL to clipboard. Dictate "test". Paste with Cmd+V — should be the URL (clipboard restored).

If nothing happens on Right Cmd press: Hammerspoon needs Accessibility permission. Open System Settings → Privacy & Security → Accessibility → enable Hammerspoon.

- [ ] **Step 4: Test Chinese path**

1. Switch input source to 注音 (Zhuyin) via Control+Space or menu bar input picker.
2. In TextEdit, hold Right Cmd, say "你好世界", release.
3. Expected: "你好世界" appears.
4. Verify in Hammerspoon Console that the IME was detected as `com.apple.inputmethod.TCIM.Zhuyin` and language passed to daemon was `zh`. To see this, add a `print` line in `dictation.lua` `on_right_cmd_down()` temporarily.

- [ ] **Step 5: Commit**

```bash
git add hammerspoon/dictation.lua
git commit -m "feat(hammerspoon): right-cmd hotkey, paste flow, menubar feedback"
```

---

## Task 9: Update README with usage instructions

**Files:**
- Modify: `/Users/Lars/llm/dictation/README.md`

- [ ] **Step 1: Replace README with full usage docs**

File: `/Users/Lars/llm/dictation/README.md`

```markdown
# Dictation

Personal push-to-talk voice dictation for macOS. Hold **Right Command**, speak (English or Traditional Chinese), release — text is pasted at the cursor. All inference runs locally on Apple Silicon via `mlx-qwen3-asr`.

Design doc: `../docs/specs/2026-05-12-mac-voice-dictation-design.md`.

## Prerequisites

- macOS on Apple Silicon (M1+ recommended; tested on M5 Max).
- Hammerspoon installed and granted Accessibility permission.
- `macism` installed (`brew install laishulu/homebrew-macism/macism`).
- A Python 3.10+ venv with this project installed (`uv venv .venv-dictation && uv pip install -e .`).
- Qwen3-ASR-1.7B weights downloaded (auto on first daemon start, or pre-pull with `huggingface-cli`).

## Install

```bash
./scripts/install.sh
```

This:
1. Symlinks `launchagent/com.henry.dictation.plist` → `~/Library/LaunchAgents/`.
2. Symlinks `hammerspoon/dictation.lua` → `~/.hammerspoon/`.
3. Appends `require("dictation")` to `~/.hammerspoon/init.lua` (if not already present).
4. Loads the LaunchAgent via `launchctl`.
5. Reloads Hammerspoon if it is running.

The daemon will preload the model (~10s) the first time it starts. Subsequent starts are immediate.

## Usage

- Hold **Right Cmd** → speak → release. Text appears at the cursor.
- The menu bar icon shows state: ⚪ idle, 🔴 recording, 🟡 transcribing, 🟢 pasting, ❌ error.
- Language is auto-selected from the current macOS input source.

## Logs

- Daemon stdout: `~/Library/Logs/dictation.log`
- Daemon stderr: `~/Library/Logs/dictation.err`
- Hammerspoon Console: click menu bar Hammerspoon → Console.

## Uninstall

```bash
./scripts/uninstall.sh
```

## Troubleshooting

- **Nothing happens on Right Cmd**: Hammerspoon lacks Accessibility permission. System Settings → Privacy & Security → Accessibility → enable Hammerspoon.
- **No mic permission**: System Settings → Privacy & Security → Microphone → enable the Python binary at `.venv-dictation/bin/python3.12`.
- **First dictation after wake garbled**: known sleep/wake Metal context issue. Run `launchctl unload ~/Library/LaunchAgents/com.henry.dictation.plist && launchctl load ~/Library/LaunchAgents/com.henry.dictation.plist`.
- **Wrong language**: check IME mapping in `daemon/config.py`. Hammerspoon Console will print the detected input source ID if you add a `print(ime)` in `dictation.lua`.

## Architecture

See spec doc.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: full README with install/usage/troubleshooting"
```

---

## Task 10: End-to-end verification checklist (manual)

Not a code task — a final smoke test the engineer runs to confirm the success criteria in the spec.

- [ ] **In TextEdit (cursor in a new doc):**
   - [ ] English IME (ABC): hold Right Cmd, say "Hello, this is a test", release. Text appears within 2 seconds, correctly punctuated/cased.
   - [ ] Traditional Chinese IME (注音): hold Right Cmd, say "你好世界，今天天氣很好", release. Chinese text appears.

- [ ] **In VS Code or Cursor:**
   - [ ] Same as above. Both languages work.

- [ ] **In Slack desktop (Electron):**
   - [ ] Text inserts into a DM compose box.

- [ ] **In Spotlight search (Cmd+Space):**
   - [ ] Text inserts into the search field.

- [ ] **Clipboard preservation:**
   - [ ] Copy a URL (Cmd+C on a link in Safari).
   - [ ] Dictate something into TextEdit.
   - [ ] Cmd+V into TextEdit — the URL pastes (not the dictated text).

- [ ] **Mic indicator:**
   - [ ] Releasing Right Cmd → the orange mic dot in Control Center disappears within 1s.

- [ ] **Sleep/wake:**
   - [ ] Close lid for 1 minute → reopen → dictate. Should work without manual daemon restart.

- [ ] **omlx regression:**
   - [ ] With omlx generating tokens (e.g., a streaming chat), dictate something. omlx tokens/s should not drop noticeably.

- [ ] **Crash recovery:**
   - [ ] `kill -9 $(launchctl list | grep com.henry.dictation | awk '{print $1}')`. Wait 15s. Dictate again — should work (launchd restarted the daemon).

- [ ] **Long recording cap:**
   - [ ] Hold Right Cmd for 70 seconds while babbling. Release. Result should contain ~60s of transcription and `truncated=True` in `~/Library/Logs/dictation.log`.

If all boxes check out: the v1 is shipped.

---

## Out of scope (do NOT add as tasks)

- Streaming / partial-result rendering during speech
- Silero-VAD silence trimming
- Settings UI / preferences window
- Multi-mic selection
- Heartbeat / Metal-context healing post-sleep
- Custom vocabulary beyond context prompts
- Punctuation auto-formatting beyond what Qwen3-ASR provides

These are deferred per the spec, Section 10. Resist the temptation.

---

## Plan self-review notes (for the writer's record)

- All 13 success criteria in spec § 12 are covered by Task 10 checklist or are passive (e.g., "no regression to omlx" is verified there).
- Every code step contains the actual code, no placeholders.
- TDD applied where pure (config, IPC, prompt builder). Smoke tests where stateful/hardware (audio, ASR, daemon, Hammerspoon).
- File responsibilities are bounded; no file does more than one thing.
- Commits are small and aligned with conventional commit format.
