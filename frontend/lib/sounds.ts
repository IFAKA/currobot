"use client"
// Howler.js sound manager — respects prefers-reduced-motion
import { Howl } from "howler"

const prefersReducedMotion = () =>
  typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches

// Placeholder paths — add actual sound files to /public/sounds/
const sounds = {
  tick:         new Howl({ src: ["/sounds/tick.mp3"],         volume: 0.15, preload: false }),
  success:      new Howl({ src: ["/sounds/success.mp3"],      volume: 0.2,  preload: false }),
  swoosh:       new Howl({ src: ["/sounds/swoosh.mp3"],       volume: 0.15, preload: false }),
  error:        new Howl({ src: ["/sounds/error.mp3"],        volume: 0.2,  preload: false }),
  notification: new Howl({ src: ["/sounds/notification.mp3"], volume: 0.2,  preload: false }),
}

export type SoundName = keyof typeof sounds

export function playSound(name: SoundName): void {
  if (prefersReducedMotion()) return
  try { sounds[name].play() } catch { /* ignore */ }
}
