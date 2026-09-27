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

### Law 1: Voice Processing Configuration Lifecycle
**Configure voice processing while `AVAudioEngine` is STOPPED, before preparing or starting the audio engine.**
```swift
// ❌ WRONG: Attempting to configure or reconfigure while the engine is running
engine.start()
inputNode.setVoiceProcessingEnabled(true) // May fail or drop audio packets!

// ✅ CORRECT: Stop -> Configure VP -> Query Format -> Prepare -> Start
if engine.isRunning {
    engine.stop()
}
// setVoiceProcessingEnabled is throwing in modern AVFoundation
try engine.inputNode.setVoiceProcessingEnabled(true)

// Hardware format must be queried AFTER voice processing is enabled
let hwFormat = engine.inputNode.outputFormat(forBus: 0)

// Prepare converter and preallocated buffers BEFORE starting the engine
configureConverter(for: hwFormat)

engine.prepare()
try engine.start()
```
*Why:* On Apple Silicon, `setVoiceProcessingEnabled(true)` reconfigures the audio hardware driver into Voice Processing I/O (`AUVoiceProcessing`). This reconfigures the internal mic array and dynamically mutates the hardware bus channel count (e.g., from 3 channels to 9 channels on MacBook built-in arrays). Querying the format after enabling voice processing guarantees the converter matches the real audio format.

---

### Law 2: Realtime Callback Thread Safety (Zero Allocations & Locks)
**Never allocate heap memory, rebuild converters, or acquire blocking locks inside the `installTap` audio callback.**
Audio tap callbacks execute on high-priority, real-time CoreAudio OS threads (`AURemoteIO::IOThread`).
1. **Preallocate Buffers:** Preallocate `AVAudioPCMBuffer` instances outside the callback or use a lock-free Single-Producer Single-Consumer (SPSC) ring buffer to transfer raw PCM to a worker queue.
2. **Offload Format Changes:** If a format shift is detected in the tap block, do NOT reconstruct `AVAudioConverter` inline. Signal a format-change event to a background serial queue and drop transient frames until the converter is updated.
3. **Lock Safety:** Use lock-free atomics or `NSRecursiveLock` on the management boundary. Never invoke blocking `NSLock` inside the tap.

---

### Law 3: Multi-Mic Arrays & Channel 0 AEC Extraction
**On Apple Silicon built-in microphone arrays under AUVoiceProcessing, clean AEC speech is on Channel 0.**

| Hardware Route | Channel Count | Clean Voice Source | Fallback / Behavior |
|---|---|---|---|
| **MacBook Built-In Array (AEC ON)** | 3, 4, or 9 channels | **Channel 0** | Channel 0 carries Apple's beamformed, echo-cancelled voice. Extract Channel 0. |
| **Standard Stereo Mic (e.g. USB)** | 2 channels | Downmix `(ch0 + ch1) * 0.5` | Standard stereo sum. |
| **Mono Mic / Headset** | 1 channel | Direct Pass-through | No extraction needed. |

```swift
func extractMonoBuffer(from buffer: AVAudioPCMBuffer, into destinationBuffer: AVAudioPCMBuffer) {
    guard buffer.format.channelCount > 1 else {
        // Direct copy if already mono
        return
    }
    destinationBuffer.frameLength = buffer.frameLength

    guard let src = buffer.floatChannelData, let dst = destinationBuffer.floatChannelData?[0] else {
        return
    }

    if buffer.format.channelCount == 2 {
        // Stereo downmix into preallocated destination
        let ch0 = src[0]
        let ch1 = src[1]
        for i in 0..<Int(buffer.frameLength) {
            dst[i] = (ch0[i] + ch1[i]) * 0.5
        }
    } else {
        // Built-in Apple Silicon mic array (3ch, 4ch, 9ch) under AUVoiceProcessing:
        // Channel 0 carries the beamformed, AEC-processed speech.
        dst.initialize(from: src[0], count: Int(buffer.frameLength))
    }
}
```

---

### Law 4: Idempotent Teardown & Observer Management
```swift
public func stop() {
    managementQueue.async { [weak self] in
        guard let self = self, self.isCapturing else { return }
        
        // 1. Unregister notification observer token cleanly
        if let observer = self.routeObserverToken {
            NotificationCenter.default.removeObserver(observer)
            self.routeObserverToken = nil
        }
        
        // 2. Stop engine first so realtime tap halts
        if self.engine.isRunning {
            self.engine.stop()
        }
        
        // 3. Remove tap safely
        if self.hasTapInstalled {
            self.engine.inputNode.removeTap(onBus: 0)
            self.hasTapInstalled = false
        }
        
        self.isCapturing = false
    }
}
```

---

### Law 5: Honest Session Lifecycle & Failure Transparency
**Teardown functions must NEVER overwrite a genuine error with a generic `.ended` or `.idle` state.**
- If a session fails due to WebSocket termination, audio engine crash, or permission denial:
  1. Record the exact failure reason in coordinator state: `state = .failed(reason)`.
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

## ❌ Don'ts & Anti-Patterns

| Anti-Pattern | Consequence | Correct Pattern |
|---|---|---|
| Querying `inputNode.outputFormat` before `setVoiceProcessingEnabled(true)` | Converter initialized with pre-AEC format; audio drops or crashes | Call `setVoiceProcessingEnabled(true)` while stopped, then query format |
| Allocating `AVAudioPCMBuffer` inside `installTap` block | CoreAudio priority inversion, audio stutters and glitches | Preallocate buffers or use lock-free ring buffers |
| Rebuilding `AVAudioConverter` inside the realtime audio callback | Deadlocks or dropped frames on RT thread | Dispatch format reconfiguration to a serial background queue |
| Downmixing all 9 channels of a Mac mic array | Corrupts beamformed voice with raw capsule noise and reference channels | Extract Channel 0 exclusively as the clean AEC voice stream |
| Plain `NSLock` guarding audio start/stop/tap | Deadlock between CoreAudio realtime thread and MainActor route handler | Use `NSRecursiveLock` or serial actor queues |
| Using `CGEventTap` for global hotkey | Prompts scary Accessibility Privacy dialog; fails if permission revoked | Use Carbon `RegisterEventHotKey` (zero permissions needed) |

---

## Verification & Diagnostics Checklist

When verifying a macOS voice companion client:
- [ ] **AEC Hardware Verification:** Play audio from Mac speakers while speaking into mic. Verify the model does not hear or self-interrupt on its own speech.
- [ ] **Realtime Profiling:** Run Instruments (Time Profiler + System Trace) on audio tap callback. Verify zero `malloc` or lock contention on `AURemoteIO::IOThread`.
- [ ] **Route Switch Soak:** Connect and disconnect AirPods mid-session. Verify converter self-heals without audio dropouts or crashes.
- [ ] **Log Verification:** Check `~/Library/Logs/<App>/hud.log` for session lifecycle events (`session.start`, `session.failed`, `session.ended`).
- [ ] **Unit & Pipeline Tests:** Run `swift test` in the macOS app directory to verify pipeline format conversions and mock buffer processing.
