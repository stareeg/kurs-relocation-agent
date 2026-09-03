/** Shared clamp for 0..100 bar/scale pct (W-12). */
export function clampPct(v: number): number {
  if (!Number.isFinite(v)) return 0
  return Math.max(0, Math.min(100, v))
}
