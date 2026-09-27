---
title: "Client companion skills for macOS audio HUD, Rokid smart glasses, and multimodal voice protocol"
id: F-014
status: refined
from_idea: I-014
---

# Client companion skills for macOS audio HUD, Rokid smart glasses, and multimodal voice protocol

## Problem
In the joy-companion project and related voice/vision companion efforts, client implementations on macOS and Rokid smart glasses repeatedly encountered critical traps:
1. **macOS HUD Traps:**
   - Enabling Voice Processing (`AUVoiceProcessing`) after querying format causes channel count mismatches (3-channel vs 9-channel on Apple Silicon).
   - Multi-mic arrays supply beamformed AEC speech exclusively on Channel 0; downmixing all 9 channels corrupts audio.
   - Dynamic hardware route changes (AirPods/Bluetooth) cause buffer format shifts that crash unhandled converters.
   - Realtime CoreAudio thread collisions with `NSLock` cause deadlocks.
   - Lifecycle errors get overwritten with `.ended` during teardown, hiding failures from users.
2. **Rokid Smart Glasses Traps:**
   - Phone BLE relay (CXR SDK) introduces 17–23s latency and terminates on phone sleep; direct Wi-Fi WebSocket is required.
   - `AudioSource.VOICE_RECOGNITION` returns pure zeros due to vendor service locks; `AudioSource.MIC` is ~30 dB too quiet and requires AGC + limiter (not fixed gain clipping).
   - Speaker-to-mic acoustic echo causes full-duplex AI to self-interrupt; walkie-talkie half-duplex suppression is needed.
   - Raw keycodes must be intercepted in `dispatchKeyEvent` with debouncing, and an ordered priority 999 `KeyReceiver` must abort system camera hijacks.
   - `assistserver` turns off Wi-Fi; `FLAG_KEEP_SCREEN_ON` and `WifiLock` are mandatory.
3. **Multimodal Protocol Traps:**
   - Missing barge-in buffer flush contracts (16k mono up / 24k mono down) leave stale audio playing.
   - Missing dual-ended RMS dBFS telemetry makes it impossible to distinguish silenced mics from network stalls.

## Why now
Both platforms have had to be repeatedly debugged on physical hardware through painful trial and error. Codifying these hard-won lessons into reusable Antigravity/Claude skills prevents recurring regressions across client platforms and future hardware releases.

## Sketch
Create three modular, technology-agnostic skills in `skills/`:
1. `macos-audio-hud`: Native macOS Voice HUD & CoreAudio companion engineering (AppKit, AVFoundation, Voice Processing, Channel 0 extraction, dynamic converters, NSRecursiveLock, floating NSPanel, Carbon hotkeys).
2. `rokid-glasses-companion`: Rokid & Android AR smart glasses companion engineering (Direct Wi-Fi architecture, AudioSource.MIC with AGC, walkie-talkie echo suppression, raw key debouncing, priority 999 KeyReceiver, WifiLock).
3. `multimodal-voice-companion`: Universal real-time live voice/vision companion protocol standards (WebSocket wire format, 16k up / 24k down PCM, barge-in buffer flushing, dual-ended RMS dBFS diagnostics, reconnect resilience).

## Acceptance criteria

- [ ] `skills/macos-audio-hud/SKILL.md` is created with complete architectural laws, code patterns, and verification checklist.
- [ ] `skills/rokid-glasses-companion/SKILL.md` is created with direct Wi-Fi architecture, audio traps, AGC, walkie-talkie echo suppression, and gesture debouncing.
- [ ] `skills/multimodal-voice-companion/SKILL.md` is created covering wire audio formats, barge-in flush contracts, RMS dBFS telemetry, and reconnect resilience.
- [ ] All three skills adhere to Antigravity `SKILL.md` frontmatter standards and pass skill structure checks.
- [ ] `./install.sh --parity` links all new skills to Claude, Gemini, Cursor, and Agents directories.
- [ ] `joy-companion/CLAUDE.md` is updated with references to these client companion skills.
