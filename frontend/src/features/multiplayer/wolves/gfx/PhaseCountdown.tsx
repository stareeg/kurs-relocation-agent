import { useEffect, useReducer, useState } from "react"

/**
 * Э19.1 + Э35.5: секундомер фазы отдельным листом.
 *
 * Раньше `secondsLeft` жил в `useState` у `WolvesTable`, и тик 4 раза в секунду перерисовывал
 * всё дерево стола. Здесь тик замкнут на сам компонент: цифра меняется 1 раз в секунду и на
 * паузе при скрытой вкладке, а плавность даёт CSS-анимация полоски (одна на всю фазу,
 * длительностью до `phase_ends_at`), а не React.
 */

/** Минимум от сокета: этому листу не нужны ни формы состояния, ни фазы конкретной игры. */
type CountdownSource = {
  secondsLeft: () => number | null
  subscribe: (fn: (snap: { phaseEndsAt: number | null }) => void) => () => void
}

export function PhaseCountdown({
  socket,
  fullWidth = false,
  /** Резервировать полоску таймера, даже если фаза без дедлайна. */
  reserveSpace = false,
}: {
  socket: CountdownSource
  /** SIGame commonProgress — полоска на всю ширину шапки. */
  fullWidth?: boolean
  reserveSpace?: boolean
}) {
  const [, tick] = useReducer((n: number) => n + 1, 0)
  const [endsAt, setEndsAt] = useState<number | null>(null)

  useEffect(() => socket.subscribe((snap) => setEndsAt(snap.phaseEndsAt)), [socket])

  useEffect(() => {
    if (endsAt == null) return
    let timer = 0
    const schedule = () => {
      if (document.hidden) return
      timer = window.setTimeout(() => {
        tick()
        schedule()
      }, 1000)
    }
    const onVisible = () => {
      if (!document.hidden) {
        tick()
        schedule()
      }
    }
    document.addEventListener("visibilitychange", onVisible)
    schedule()
    return () => {
      window.clearTimeout(timer)
      document.removeEventListener("visibilitychange", onVisible)
    }
  }, [endsAt])

  const left = socket.secondsLeft()
  if ((left == null || endsAt == null) && !reserveSpace) return null

  const totalMs = left != null && endsAt != null ? Math.max(0, left * 1000) : 0
  const low = left != null && left <= 5

  if (left == null || endsAt == null) {
    return (
      <div className={`flex items-center gap-3 ${fullWidth ? "w-full" : ""}`} aria-hidden>
        <div
          className={`rounded-full bg-black/25 ${
            fullWidth ? "mp-phase-timer-bar h-1.5 flex-1" : "h-1 flex-1"
          }`}
        />
        <span
          className={`mp-display shrink-0 tabular-nums font-semibold text-white/25 ${
            fullWidth ? "text-[length:var(--mp-text-base)]" : "text-sm"
          }`}
        >
          —
        </span>
      </div>
    )
  }

  return (
    <div className={`flex items-center gap-3 ${fullWidth ? "w-full" : ""}`}>
      <div
        className={`overflow-hidden rounded-full bg-black/40 ${
          fullWidth ? "mp-phase-timer-bar h-1.5 flex-1" : "h-1 flex-1"
        }`}
      >
        <div
          key={endsAt}
          className="mp-phase-progress h-full origin-left rounded-full"
          style={{
            animationDuration: `${totalMs}ms`,
            background: low
              ? "linear-gradient(90deg, #ff7c1e, #e26f1d)"
              : "linear-gradient(90deg, var(--mp-bulletin), #e0c04a)",
          }}
        />
      </div>
      <span
        className={`mp-display shrink-0 tabular-nums font-semibold ${
          fullWidth ? "text-[length:var(--mp-text-base)]" : "text-sm"
        } ${low ? "text-[color:var(--mp-energy)]" : "text-white/90"}`}
      >
        {left}с
      </span>
    </div>
  )
}
