# Dictation

Personal push-to-talk voice dictation for macOS. Hold **Right Command**, speak (English or Traditional Chinese), release — text is pasted at the cursor. All inference runs locally on Apple Silicon via `mlx-qwen3-asr`.

Design doc: `../docs/specs/2026-05-12-mac-voice-dictation-design.md`.

## Prerequisites

- macOS on Apple Silicon (M1+ recommended; tested on M5 Max).
- Hammerspoon installed (`brew install --cask hammerspoon`) and granted Accessibility permission.
- `macism` installed at `~/.local/bin/macism` or `/opt/homebrew/bin/macism`.
- A Python 3.10+ venv with this project installed (`uv venv .venv-dictation && uv pip install -e .[dev]`).
- Qwen3-ASR-1.7B weights downloaded on first daemon start (auto), or pre-pull with `huggingface-cli download Qwen/Qwen3-ASR-1.7B`.

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
