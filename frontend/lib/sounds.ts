"use client"
// Sound facade — delegates to Web Audio API synthesizer (no MP3 files needed)
// Respects prefers-reduced-motion

import {
  unlockAudio as _unlockAudio,
  playSuccess as _playSuccess,
  playError as _playError,
  playNotification as _playNotification,
  playTick,
  playSwoosh,
} from "@/lib/audio"

const prefersReducedMotion = () =>
  typeof window !== "undefined" &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches

function guarded(fn: () => void): void {
  if (prefersReducedMotion()) return
  try { fn() } catch { /* ignore */ }
}

export function unlockAudio():      void { _unlockAudio() }
export function playSuccess():      void { guarded(_playSuccess) }
export function playError():        void { guarded(_playError) }
export function playNotification(): void { guarded(_playNotification) }

// Legacy playSound() used by CommandPalette
export type SoundName = "tick" | "swoosh" | "success" | "error" | "notification"

export function playSound(name: SoundName): void {
  if (prefersReducedMotion()) return
  try {
    switch (name) {
      case "tick":         playTick();          break
      case "swoosh":       playSwoosh();        break
      case "success":      _playSuccess();      break
      case "error":        _playError();        break
      case "notification": _playNotification(); break
    }
  } catch { /* ignore */ }
}
