---
name: macos-audio-hud
description: |
  Engineering standards and hard-won practices for native macOS floating HUDs and real-time CoreAudio/AVFoundation voice companion clients.
  Use when: building, debugging, or reviewing macOS native apps with floating panels, global hotkeys, CoreAudio Voice Processing (AUVoiceProcessing), multi-mic array capture, audio converters, or desktop voice streaming.
---

# macOS Native Voice HUD & CoreAudio Companion Engineering

You are an expert macOS systems and audio engineer specializing in Swift, AppKit, and AVFoundation / CoreAudio. You build low-latency, resilient, floating desktop companion HUDs that stream full-duplex voice with acoustic echo cancellation.

---

## When to Apply

Apply this skill when working on macOS native companion clients, specifically:
- Capturing microphone audio via `AVAudioEngine` and `AVAudioInputNode` for streaming to speech/LLM backends.
- Enabling hardware acoustic echo cancellation (`AUVoiceProcessing`) on Apple Silicon.
- Handling multi-channel microphone arrays (3-channel, 4-channel, 9-channel layouts) and sample rate conversion.
- Designing non-activating, floating desktop HUDs (`NSPanel`) that span all Spaces and full-screen apps.
- Registering global hotkeys without requiring invasive macOS Accessibility permissions.
- Preventing deadlocks and threading collisions between realtime CoreAudio threads and UI state.

---

## Core Architectural Laws

### Law 1: Voice Processing Initialization Order
**Always enable voice processing BEFORE querying the input node's hardware format.**
```swift
// ❌ WRONG: Querying format before enabling voice processing
let hwFormat = engine.inputNode.outputFormat(forBus: 0) // e.g. 3-channel raw
engine.inputNode.isVoiceProcessingEnabled = true        // Format changes to 9-channel!
let converter = AVAudioConverter(from: hwFormat, to: targetFormat) // Crash or silence!

// ✅ CORRECT: Enable voice processing first, then query format
try engine.inputNode.setVoiceProcessingEnabled(true)
let hwFormat = engine.inputNode.outputFormat(forBus: 0) // Reliable post-AEC format
```
*Why:* On Apple Silicon, `setVoiceProcessingEnabled(true)` reconfigures the audio hardware driver into Voice Processing I/O (`AUVoiceProcessing`). This re-routes the internal mic array and mutates the channel count (e.g., from 3 channels to 9 channels). If you query the format beforehand, your `AVAudioConverter` is initialized for the wrong channel count, causing buffer conversion failures or silent audio dropouts.

---

### Law 2: Multi-Mic Arrays & Channel 0 Extraction
**For multi-channel microphone arrays (> 2 channels) under Voice Processing, always extract Channel 0 as the mono AEC stream.**
```swift
func extractMonoBuffer(from buffer: AVAudioPCMBuffer) -> AVAudioPCMBuffer {
    guard buffer.format.channelCount > 1 else { return buffer }
    
    let monoFormat = AVAudioFormat(
        commonFormat: .pcmFormatFloat32,
        sampleRate: buffer.format.sampleRate,
        channels: 1,
        interleaved: false
    )!
    let monoBuffer = AVAudioPCMBuffer(pcmFormat: monoFormat, frameCapacity: buffer.frameLength)!
    monoBuffer.frameLength = buffer.frameLength

    guard let src = buffer.floatChannelData, let dst = monoBuffer.floatChannelData?[0] else {
        return buffer
    }

    if buffer.format.channelCount == 2 {
        // Standard stereo: average ch0 and ch1
        for i in 0..<Int(buffer.frameLength) {
            dst[i] = (src[0][i] + src[1][i]) * 0.5
        }
    } else {
        // Voice Processing / Multi-mic array (3ch, 4ch, 9ch):
        // Channel 0 is Apple's beamformed, echo-cancelled voice signal.
        dst.initialize(from: src[0], count: Int(buffer.frameLength))
    }
    return monoBuffer
}
```
*Why:* On modern MacBooks, Apple Silicon microphone arrays expose multiple raw capsule feeds plus reference channels. Under `AUVoiceProcessing`, Apple's DSP engine runs beamforming and Acoustic Echo Cancellation (AEC) and outputs the clean speech signal exclusively onto **Channel 0**. If you average all 9 channels together or attempt to feed all 9 channels into a standard resampler, you corrupt the clean voice signal with raw noise and unmixed capsule data.

---

### Law 3: Self-Healing Dynamic Audio Converters
**Never assume input buffer formats remain constant throughout a session.**
Hardware route changes (plugging in headphones, connecting AirPods, external USB interface switching) can deliver dynamic buffer format shifts on the fly into your `installTap` block.
```swift
func processCapturedBuffer(_ buffer: AVAudioPCMBuffer) {
    let monoBuffer = extractMonoBuffer(from: buffer)
    
    // Self-heal converter if hardware route or format shifted
    if converter == nil || converter?.inputFormat != monoBuffer.format {
        converter = AVAudioConverter(from: monoBuffer.format, to: targetFormat)
    }
    guard let converter = converter else { return }
    
    // Resample & convert to 16 kHz 16-bit mono PCM...
}
```

---

### Law 4: Lock Hierarchy & Teardown Safety (Zero Deadlocks)
Audio taps run on realtime OS CoreAudio threads. Route change notifications and session start/stop calls run on background threads or the MainActor.
- **Use `NSRecursiveLock`** (or Swift actor isolation with non-blocking atomics), NEVER plain `NSLock`, because teardown functions may re-enter during notification handlers.
- **Stop the engine BEFORE removing the tap:**
```swift
public func stop() {
    lock.lock()
    defer { lock.unlock() }

    routeChangeObserver = nil
    
    // 1. Stop engine first so realtime tap stops firing
    if engine.isRunning {
        engine.stop()
    }
    // 2. Safely remove tap once engine has halted
    engine.inputNode.removeTap(onBus: 0)
    isCapturing = false
}
```
*Why:* Calling `removeTap` while the engine is actively executing a tap callback on a CoreAudio thread creates race conditions and internal crashes inside `AVAudioEngineGraph`.

---

### Law 5: Honest Session Lifecycle & Failure Transparency
**Teardown functions must NEVER overwrite a genuine error with a generic `.ended` or `.idle` state.**
- If a session fails due to WebSocket termination, audio engine crash, or permission denial:
  1. Record the exact failure reason in the coordinator state: `state = .failed(reason)`.
  2. Append full contextual diagnostics to persistent logs (`~/Library/Logs/<App>/hud.log`).
  3. Ensure the UI empty state renders the honest error details with recovery actions (e.g. "Voice server disconnected: connection refused on 127.0.0.1:8091"), not a blank or silent idle state.

---

### Law 6: Floating Companion Panel (`NSPanel`)
A desktop companion HUD must float over full-screen apps and spaces without stealing focus from the user's primary workflow:
```swift
final class HUDPanel: NSPanel {
    init(...) {
        super.init(
            contentRect: rect,
            styleMask: [.nonactivatingPanel, .titled, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        self.isFloatingPanel = true
        self.level = .floating
        self.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        self.titleVisibility = .hidden
        self.titlebarAppearsTransparent = true
        self.isMovableByWindowBackground = true
    }

    // Allow keyboard typing in HUD without stealing main window status
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
}
```

---

### Law 7: Zero-Permission Global Hotkeys via Carbon
To activate the companion HUD via global hotkey without forcing the user to grant macOS Accessibility Privacy permissions:
- Use Carbon's `RegisterEventHotKey`.
- It requires **zero Accessibility permissions**, unlike `CGEventTap` or `NSEvent.addGlobalMonitorForEventsMatchingMask`.
- Signature: Use a unique 4-character OSType identifier (e.g. `'JHUD'`).
- Hotkey handler installs via `InstallEventHandler(GetApplicationEventTarget(), ...)`.

---

### Law 8: Native Input Ingestion (Clipboard & File Drop)
Companion chat inputs must support rich desktop gestures natively:
- **`Cmd+V` Image Paste:** Listen for `paste:` or intercept paste events. Inspect `NSPasteboard.general` for image types (`public.png`, `public.tiff`, `public.jpeg`). Compress to JPEG/WebP data and queue as an image attachment.
- **Drag-and-Drop:** Register `.onDrop(of: [.fileURL], isTargeted: ...)` in SwiftUI. Extract file URLs, validate extensions/size, and attach to the active turn context.

---

## ❌ Don'ts & Anti-Patterns

| Anti-Pattern | Consequence | Correct Pattern |
|---|---|---|
| Querying `inputNode.outputFormat` before `setVoiceProcessingEnabled(true)` | Converter initialized with pre-AEC format; audio drops or crashes | Call `setVoiceProcessingEnabled(true)` first, then query format |
| Downmixing or averaging all 9 channels of a Mac mic array | Corrupts beamformed voice with raw capsule noise and reference channels | Extract Channel 0 exclusively as the clean AEC voice stream |
| Plain `NSLock` guarding audio start/stop/tap | Deadlock between CoreAudio realtime thread and MainActor route handler | Use `NSRecursiveLock` or lock-free ring buffers |
| Calling `removeTap` while `engine.isRunning` | Race condition inside CoreAudio graph teardown | Stop `engine` first, then remove tap |
| Overwriting `.failed(reason)` with `.ended` in `stopSession()` | Masks errors; UI shows false empty state; developers cannot debug | Preserve `.failed` state and write details to `hud.log` |
| Using `CGEventTap` for global hotkey | Prompts scary Accessibility Privacy dialog; fails if permission revoked | Use Carbon `RegisterEventHotKey` (zero permissions needed) |

---

## Verification & Diagnostics Checklist

When verifying a macOS voice companion client:
- [ ] **AEC Hardware Verification:** Play audio from Mac speakers while speaking into mic. Verify the model does not hear or self-interrupt on its own speech.
- [ ] **Multi-Channel Check:** Log `buffer.format.channelCount`. Verify that Channel 0 is extracted when `channelCount > 2`.
- [ ] **Route Switch Soak:** Connect and disconnect AirPods mid-session. Verify converter self-heals without audio dropouts or crashes.
- [ ] **Lock Audit:** Confirm no `NSLock` calls are in the path of route change notifications or audio taps.
- [ ] **Log Verification:** Check `~/Library/Logs/<App>/hud.log` for session lifecycle events (`session.start`, `session.failed`, `session.ended`).
- [ ] **Bundle Self-Probe:** Run `./scripts/verify-bundle.sh` to validate `Info.plist`, `AppIcon.icns`, entitlements, and codesign.
