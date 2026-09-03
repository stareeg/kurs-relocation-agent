import { useEffect, useState } from "react"

const DEFAULT_MS = 400

function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches
}

/** Кадр интерполяции from→to за elapsed/duration (ease-out). Для юнитов и хука. */
export function countUpFrame(from: number, to: number, elapsed: number, duration: number): number {
  if (duration <= 0 || elapsed >= duration) return to
  if (elapsed <= 0) return from
  const t = elapsed / duration
  const eased = 1 - (1 - t) * (1 - t)
  return Math.round(from + (to - from) * eased)
}

type Animation = { from: number; to: number; start: number }
type Flash = { dir: "up" | "down" } | null

/**
 * Анимирует число к цели за `durationMs` (по умолчанию 400).
 * При быстрых сменах цели перезапускается от текущего отображаемого значения
 * (без дребезга «туда-сюда» к старым целям).
 * `flash` — направление последней дельты для вспышки цвета (up/down).
 */
export function useCountUp(
  target: number | null | undefined,
  durationMs = DEFAULT_MS,
): { display: number | null; flash: "up" | "down" | null } {
  const finite = target != null && Number.isFinite(target) ? target : null
  const [display, setDisplay] = useState<number | null>(finite)
  const [prevFinite, setPrevFinite] = useState<number | null>(finite)
  const [animation, setAnimation] = useState<Animation | null>(null)
  const [flash, setFlash] = useState<Flash>(null)

  if (finite !== prevFinite) {
    const from = display
    setPrevFinite(finite)
    if (finite == null) {
      setDisplay(null)
      setFlash(null)
      setAnimation(null)
    } else if (from == null || prefersReducedMotion() || from === finite) {
      setDisplay(finite)
      setAnimation(null)
      setFlash(from != null && from !== finite ? { dir: finite > from ? "up" : "down" } : null)
    } else {
      setFlash({ dir: finite > from ? "up" : "down" })
      setAnimation({ from, to: finite, start: performance.now() })
    }
  }

  useEffect(() => {
    if (!animation) return
    let rafId = requestAnimationFrame(function tick(now: number) {
      const next = countUpFrame(animation.from, animation.to, now - animation.start, durationMs)
      setDisplay(next)
      if (next !== animation.to) {
        rafId = requestAnimationFrame(tick)
      }
    })
    return () => cancelAnimationFrame(rafId)
  }, [animation, durationMs])

  useEffect(() => {
    if (!flash) return
    const id = setTimeout(() => setFlash(null), durationMs)
    return () => clearTimeout(id)
  }, [flash, durationMs])

  return { display, flash: flash?.dir ?? null }
}
