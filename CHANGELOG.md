# Changelog

All notable changes to ifseen. The Home Assistant add-on has its own
[changelog](homeassistant/ifseen/CHANGELOG.md).

## 0.1.0 - unreleased

First release.

- `ifseen` CLI: plain-English rules over screen, camera, video/RTSP, snapshot URL, image and
  mic sources, with thresholds, `for: N`, cooldowns, hysteresis, change detection and a live
  cost dashboard (`watch`, `test`, `recipes`, `init`, `doctor`).
- Eleven built-in recipes.
- Providers: Gemini Decision, TypeSafe Jev, Azure Microsoft-Decision, self-hosted System One,
  OpenAI-compatible models (including Ollama), free on-device SigLIP (`local`), `mock`, and a
  cheap-first-check cascade (`prefilter`).
- Actions: desktop notifications, speech, shell, webhooks, ntfy with snapshots, saving frames.
- `ifseen serve`: HTTP API with live server-sent events, plus a Python API (`check`, `Watcher`).
- MQTT with Home Assistant discovery, and a Home Assistant add-on (prebuilt amd64/aarch64
  images on GHCR).
- `ifseen` npm package: a typed TypeScript client for one-shot checks and `ifseen serve`.
- Distribution: PyPI, standalone binaries for macOS (arm64, x86_64), Linux (x86_64, arm64)
  and Windows (x64), `install.sh` / `install.ps1` one-liners, Homebrew tap, Scoop bucket and a
  multi-arch Docker image at `ghcr.io/krishjoshi/ifseen`.
