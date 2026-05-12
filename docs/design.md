# Mac Voice Dictation — IME-aware Push-to-Talk

**Author:** Henry · **Date:** 2026-05-12 · **Status:** Design approved, ready for implementation plan

## 1. Goal

Build a personal, always-on macOS dictation tool with the following user experience:

1. Hold **Right Command** anywhere in macOS.
2. Speak (English or Traditional Chinese).
3. Release the key.
4. Transcribed text is pasted at the current cursor position inside whatever app is focused (Slack, VS Code, Cursor, browser, Terminal, Spotlight, ...).

The system reads the current macOS input source (輸入法) at the moment recording starts, and uses it as a **language hint and context prompt** for the ASR model — improving accuracy and reducing language-detection mistakes during mixed Chinese/English speech.

All inference runs locally on Apple Silicon. No network calls, no cloud.

## 2. Hardware & runtime assumptions

- M5 Max, 128 GB unified memory
- macOS (Apple Silicon)
- Python venv with MLX already in use (`omlx` + `mlx_lm` separately running a Qwen3.6-35B LLM)
- Hammerspoon installed (or will be installed)
- Microphone access granted to the daemon process

## 3. Component decisions

| Concern | Decision | Rationale |
|---|---|---|
| Trigger key | **Right Command hold** (keycode 0x36) | No conflict with macOS shortcuts (Left Cmd is overloaded). Right Cmd is rarely used intentionally — instant-trigger viable, no debounce delay needed. |
| Interaction mode | **Hold-to-talk** | Lowest cognitive load; impossible to forget "am I recording?". Matches SuperWhisper / Wispr Flow defaults. |
| ASR model | **Qwen3-ASR-1.7B** (single model, both languages) | Ties Whisper-large-v3 on English LibriSpeech (1.63% vs 1.6% WER) and crushes it on Chinese (4.97 vs 9.86 WER on AISHELL-2 / WenetSpeech). Two-model routing buys nothing. |
| Inference backend | **`mlx-qwen3-asr`** (Python) | Official Apple Silicon MLX port. ~4.19x faster than PyTorch. Independent audio pipeline; no need to bridge through `omlx`. |
| Language strategy | IME state → `language=` hint + dynamic context prompt | Qwen3-ASR supports context biasing; passing "以下是繁體中文（台灣）的口述輸入..." vs "The following is English dictation..." materially improves WER. |
| IME detection | `TISCopyCurrentKeyboardInputSource` via shell (`macism` CLI or AppleScript) | Standard macOS API. One-line call, no daemon dependency. |
| Text injection | **Clipboard paste + Escape pre-send + changeCount-based restore** | Industry standard (Handsfree, SuperWhisper, VoiceInk). Pure `AXUIElementSetAttributeValue` is unreliable, especially in Electron apps. Keystroke injection breaks for CJK + active IME composition. |
| Recording max length | **60 seconds**, hard cap | Safety guard against stuck key. Qwen3-ASR's sweet spot for non-chunked inference. |
| VAD | **Not in v1** (YAGNI) | Hold-to-talk makes start/stop deterministic. Add silero-vad later if leading-silence hallucinations are observed. |
| Feedback | Menu bar icon color + chimes on start/stop | macOS native mic indicator (orange dot in Control Center) is too small/laggy as sole feedback. ~30 lines of Hammerspoon. |
| Hotkey + IME read + Cmd+V simulation | **Hammerspoon** | Lightweight, no app bundle needed, mature Mac scripting layer. |
| Daemon lifecycle | **LaunchAgent** (`~/Library/LaunchAgents/com.henry.dictation.plist`) | Per-user, login-triggered, can access mic permission (LaunchDaemon cannot). |
| Model loading | **Preload at daemon startup** | Eliminates 5-15s cold start on first dictation. ~3-4 GB RAM cost is trivial on 128 GB. |
| Crash recovery | `KeepAlive: true` in plist | launchd auto-restart on segfault / OOM. |
| Coexistence with omlx | **Independent process, no shared inference** | omlx uses continuous-batching for LLM throughput; ASR has a different lifecycle. Sharing GPU queue would hurt LLM tokens/s. Daemon must NOT call `mx.set_wired_limit()` (omlx already wires 75% of RAM in its server). |

## 4. Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     macOS user session                        │
│                                                                │
│   ┌────────────────────────┐         ┌────────────────────┐  │
│   │  Hammerspoon (Lua)     │         │  Dictation Daemon  │  │
│   │  ────────────────       │         │  (Python, LaunchAgent)│
│   │  • Right Cmd flagsChanged listener  │  • mlx-qwen3-asr     │
│   │  • Records mic via sounddevice (or shells to a recorder) │
│   │  • On stop: read IME (macism)       │  • Loaded at startup │
│   │  • IPC request → daemon             │  • Listens on Unix   │
│   │  • Menu bar icon state              │    socket / HTTP     │
│   │  • Plays start/stop chimes          │  • Returns text       │
│   │  • Writes result → pasteboard       │                       │
│   │  • Sends Esc + Cmd+V                │                       │
│   │  • Restores pasteboard via         │                       │
│   │    changeCount poll                 │                       │
│   └────────────────────────┘         └────────────────────┘  │
│                  │                              ▲              │
│                  │  HTTP localhost:port or       │              │
│                  │  Unix socket (audio bytes +    │              │
│                  │   language hint + ctx prompt)  │              │
│                  └──────────────────────────────┘              │
│                                                                │
│   ┌────────────────────────┐                                  │
│   │  omlx (existing)        │  ← unrelated, must NOT share   │
│   │  Qwen3.6-35B LLM        │     wired-memory limit         │
│   └────────────────────────┘                                  │
└──────────────────────────────────────────────────────────────┘
```

**Why split between Hammerspoon and Python?** Hammerspoon owns the macOS-native concerns (hotkeys, accessibility, pasteboard, menu bar, sounds). Python owns the MLX model. Crossing the boundary once per dictation is cheap and keeps each side simple.

### 4.1 Audio capture decision

Hammerspoon has no direct audio recording API. Two options were considered:

- **(a)** Hammerspoon spawns a recording subprocess (e.g., `sox`) and pipes audio to the daemon.
- **(b)** Hammerspoon signals the daemon "start recording now" via IPC; the daemon opens the mic itself using `sounddevice`.

**Chosen: (b)** — daemon owns the mic. Hammerspoon sends `start` / `stop` messages over the IPC socket. Simpler audio path, no subprocess plumbing, only one process needs Mic permission, no risk of dropped samples at the pipe boundary.

### 4.2 IPC protocol

Tiny line-delimited JSON over Unix domain socket at `/tmp/dictation.sock`:

```
→ {"cmd": "start", "language": "zh", "context": "以下是繁體中文（台灣）..."}
← {"ok": true, "session": "abc"}
→ {"cmd": "stop", "session": "abc"}
← {"ok": true, "text": "你好世界", "duration_ms": 1834}
```

If daemon returns `{"ok": false, "error": "..."}`, Hammerspoon shows a notification banner.

## 5. Language strategy

The IME identifier returned by `TISCopyCurrentKeyboardInputSource` is mapped at runtime:

| Input source prefix | → Treated as |
|---|---|
| `com.apple.keylayout.ABC` | en |
| `com.apple.keylayout.US` | en |
| `com.apple.keylayout.British` | en |
| `com.apple.inputmethod.TCIM.*` (Zhuyin, Cangjie, Sucheng, ...) | zh |
| `com.apple.inputmethod.SCIM.*` (簡中) | zh |
| anything else | auto (let Qwen3-ASR detect) |

Mapping table lives in a small JSON config the user can edit.

**Context prompts (initial values, user-tunable):**
- `zh`: `以下是繁體中文（台灣）的口述輸入，可能包含技術術語如 MLX、Python、LLM。`
- `en`: `The following is English dictation. May include technical terms such as MLX, Python, transformer.`
- `auto`: empty prompt; let model auto-detect.

## 6. Text injection flow (detailed)

```
1. Daemon returns text T.
2. Hammerspoon:
   a. Read NSPasteboard.changeCount → C0
   b. Save current pasteboard contents (all types: string, RTF, image, ...)
   c. Set pasteboard to T → changeCount becomes C0+1
   d. Send Escape keystroke (collapses any active IME composition buffer)
   e. Send Cmd+V keystroke
   f. Poll changeCount every 50ms for up to 1s
      - If changeCount == C0+2 → target app pasted; proceed to restore
      - If timeout → assume paste consumed; proceed anyway
   g. Write saved contents back to pasteboard
   h. Final changeCount = C0+3 (this is expected, won't trigger re-restore)
```

The Escape step is critical when the user is in a Chinese IME with an unsubmitted composition buffer — without it, the paste gets swallowed by the IME.

## 7. Feedback

Menu bar icon (Hammerspoon `hs.menubar`):

| State | Icon | Trigger |
|---|---|---|
| Idle | ⚪ | default |
| Recording | 🔴 | Right Cmd pressed |
| Transcribing | 🟡 | Right Cmd released, awaiting daemon response |
| Pasting | 🟢 | response received, paste in progress |
| Error | ❌ | timeout / daemon error; reverts to ⚪ after 3s |

Sounds (`hs.sound`, macOS built-in system sounds):
- On Right Cmd press: `Tink.aiff` (50ms, confirms hotkey registered)
- On Right Cmd release: silent (the visual menu bar transition is enough)
- On successful paste: silent (the text appearing IS the confirmation)
- On error: `Funk.aiff`

## 8. Files & layout

```
/Users/Lars/llm/dictation/
├── daemon/
│   ├── daemon.py              # main entry, IPC server, model lifecycle
│   ├── asr.py                 # mlx-qwen3-asr wrapper, prompt building
│   ├── audio.py               # mic capture, 16 kHz mono PCM
│   ├── ipc.py                 # Unix socket JSON protocol
│   └── config.py              # IME mapping, context prompts
├── hammerspoon/
│   ├── init.lua               # entry point (loads dictation module)
│   └── dictation.lua          # Right Cmd listener, menu bar, paste flow
├── launchagent/
│   └── com.henry.dictation.plist
├── scripts/
│   ├── install.sh             # symlinks plist, loads LaunchAgent
│   └── uninstall.sh
└── tests/
    ├── test_asr.py            # offline audio fixture → expected transcript
    ├── test_ime_mapping.py
    └── test_ipc.py
```

## 9. Failure modes & handling

| Failure | Behavior |
|---|---|
| Daemon not running | Hammerspoon detects socket connect refuse → shows notification "Dictation daemon down. Run `launchctl load ...`" |
| Mic permission denied | Daemon logs error → returns `{"ok": false, "error": "mic_permission"}` → notification |
| Recording exceeds 60s | Daemon auto-stops, transcribes what it has, returns result |
| Model load fails at startup | Daemon exits non-zero → launchd KeepAlive retries with backoff (handled by launchd) |
| Transcription timeout (>10s for 60s audio) | Hammerspoon cancels, shows error icon |
| Empty transcription (e.g., user said nothing) | Skip paste, no error |
| Pasteboard restore fails | Log warning, original clipboard lost; no user-visible error (rare) |
| Metal context corrupted after long sleep | First request returns garbled text; v1: user manually restarts daemon. v2: heartbeat ping at wake. |

## 10. Out of scope for v1

- Streaming / partial-result rendering during speech
- VAD-based auto-stop on silence (hold-to-talk makes this redundant)
- Custom vocabulary / pronunciation dictionary (rely on context prompt only)
- Settings UI (config files only, edit by hand)
- Multi-mic selection (use system default)
- Punctuation auto-formatting beyond what Qwen3-ASR produces natively
- Heartbeat / Metal-context healing after sleep
- Multi-language code-switching within a single utterance (passing `language=zh` already handles most cases acceptably)

## 11. Open questions resolved

- **One model or two?** → One (Qwen3-ASR-1.7B).
- **Use omlx for ASR too?** → No, independent process.
- **fn key vs another modifier?** → Right Command (fn requires Karabiner, not worth the complexity).
- **Clipboard or keystroke injection?** → Clipboard with changeCount restore.
- **Preload model or lazy load?** → Preload at startup.
- **Daemon or agent?** → LaunchAgent (mic permission requires GUI session).

## 12. Success criteria

1. Press-and-hold Right Cmd → speak "你好世界" → release → "你好世界" appears at cursor in <2s end-to-end.
2. Press-and-hold Right Cmd in English IME → speak "hello world" → "hello world" appears, properly capitalized/spaced.
3. Works in: VS Code, Cursor, Slack desktop, Notion desktop, Safari, Chrome, Terminal, Spotlight search bar.
4. No mic indicator stays orange after release.
5. Original clipboard survives a dictation event (verifiable: copy a URL, dictate, paste — URL still there).
6. Daemon survives Mac sleep/wake; first dictation after waking works without restart.
7. No regression to omlx tokens/s while dictating.

## 13. References

- [Qwen3-ASR-1.7B (HuggingFace)](https://huggingface.co/Qwen/Qwen3-ASR-1.7B)
- [mlx-qwen3-asr (Apple Silicon port)](https://github.com/moona3k/mlx-qwen3-asr/)
- [Qwen3-ASR Technical Report](https://arxiv.org/html/2601.21337v1)
- [Handsfree (reference dictation app, clipboard pattern)](https://github.com/Lighthouse-Consultings/handsfree)
- [SuperWhisper Advanced Settings (active duration / clipboard)](https://superwhisper.com/docs/get-started/settings-advanced)
- [NSPasteboard changeCount docs](https://developer.apple.com/documentation/appkit/nspasteboard/1533544-changecount)
- [launchd tutorial (Agent vs Daemon)](https://www.launchd.info/)
- [macism (macOS IME CLI)](https://github.com/laishulu/macism)
- [Hammerspoon docs](https://www.hammerspoon.org/docs/)
- [omlx (existing LLM server, must coexist)](https://github.com/jundot/omlx)
