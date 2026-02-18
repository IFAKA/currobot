"use client"
// Web Audio API synthesizer — no MP3 files required
// Adapted from interaction-design skill reference

let sharedCtx: AudioContext | null = null

function getContext(): AudioContext | null {
  try {
    if (!sharedCtx) sharedCtx = new AudioContext()
    if (sharedCtx.state === "suspended") sharedCtx.resume()
    return sharedCtx
  } catch {
    return null
  }
}

export function unlockAudio(): void {
  const ctx = getContext()
  if (ctx?.state === "suspended") ctx.resume()
}

function playTone(
  frequency: number,
  duration: number,
  volume = 0.3,
  startDelay = 0,
  waveform: OscillatorType = "sine"
): void {
  const ctx = getContext()
  if (!ctx) return
  try {
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.connect(gain)
    gain.connect(ctx.destination)
    osc.type = waveform
    osc.frequency.value = frequency
    gain.gain.setValueAtTime(volume, ctx.currentTime + startDelay)
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + startDelay + duration)
    osc.start(ctx.currentTime + startDelay)
    osc.stop(ctx.currentTime + startDelay + duration + 0.05)
  } catch { /* ignore */ }
}

function playWarmNote(
  ctx: AudioContext,
  frequency: number,
  startTime: number,
  duration: number,
  volume: number,
  waveform: OscillatorType = "sine"
): void {
  const osc = ctx.createOscillator()
  const gain = ctx.createGain()
  osc.connect(gain)
  gain.connect(ctx.destination)
  osc.type = waveform
  osc.frequency.value = frequency
  gain.gain.setValueAtTime(0.001, startTime)
  gain.gain.linearRampToValueAtTime(volume, startTime + 0.01)
  gain.gain.exponentialRampToValueAtTime(0.001, startTime + duration)
  osc.start(startTime)
  osc.stop(startTime + duration + 0.05)
}

// ── Currobot sounds ─────────────────────────────────────────────────────────

/** Authorize success / settings saved — ascending perfect fifth, rewarding */
export function playSuccess(): void {
  playTone(520, 0.15, 0.22)
  playTone(780, 0.25, 0.22, 0.12)
  playTone(780, 0.25, 0.10, 0.22, "triangle")
}

/** Authorize / save failed — descending, "not quite" */
export function playError(): void {
  playTone(520, 0.15, 0.20)
  playTone(350, 0.25, 0.18, 0.12)
  playTone(350, 0.25, 0.09, 0.22, "triangle")
}

/** New pending review arrived via SSE — soft ascending chime */
export function playNotification(): void {
  const ctx = getContext()
  if (!ctx) return
  const notes = [523, 659, 784]
  notes.forEach((freq, i) => {
    playWarmNote(ctx, freq, ctx.currentTime + i * 0.1, 0.18, 0.20)
  })
}

/** Command palette tick — single triangle click */
export function playTick(): void {
  playTone(660, 0.07, 0.18, 0, "triangle")
}

/** Command palette open — soft descending sweep */
export function playSwoosh(): void {
  playTone(500, 0.08, 0.15, 0, "triangle")
  playTone(380, 0.06, 0.12, 0.08, "triangle")
}
