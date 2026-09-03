/** Оценка длительности устной речи: слова / 2.2 (та же формула, что `core/screening/style.py:speak_seconds`). */
export function speakSeconds(text: string): number {
  const words = text.trim().split(/\s+/).filter(Boolean).length
  if (words === 0) return 0
  return Math.round(words / 2.2)
}

/** 70 → "1:10". */
export function formatSpeakDuration(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${s.toString().padStart(2, "0")}`
}
