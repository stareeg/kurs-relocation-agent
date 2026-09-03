import { cn } from "@/lib/utils"
import {
  slotOutcomeGlyph,
  slotOutcomeTitle,
  type SlotOutcomeMap,
} from "@/features/multiplayer/wolves/slotOutcomes"

type SlotStripProps = {
  slotIndex: number
  slotCount: number
  /** SIGame GameProgress — тонкая полоска прогресса партии под номерами слотов. */
  showProgress?: boolean
  /** Итоги уже закрытых слотов (клиентский журнал). */
  outcomes?: SlotOutcomeMap
  className?: string
}

/** Полоска слотов найма (1…N) — прогресс партии до Reveal. */
export function SlotStrip({
  slotIndex,
  slotCount,
  showProgress = false,
  outcomes = {},
  className,
}: SlotStripProps) {
  const n = Math.max(1, slotCount)
  const current = Math.min(Math.max(0, slotIndex), n - 1)
  const progressPct = n <= 1 ? 100 : (current / (n - 1)) * 100

  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <ol
        className="flex flex-wrap items-center gap-1.5"
        aria-label={`Слот ${current + 1} из ${n}`}
      >
        {Array.from({ length: n }, (_, i) => {
          const done = i < current
          const active = i === current
          const outcome = outcomes[i]
          const hasOutcome = Boolean(outcome)

          return (
            <li
              key={i}
              title={outcome ? slotOutcomeTitle(outcome) : undefined}
              className={cn(
                "mp-mono relative flex size-8 items-center justify-center rounded-sm border text-[length:var(--mp-text-sm)] font-semibold transition-colors duration-300",
                active &&
                  !hasOutcome &&
                  "border-[color:var(--mp-energy)] bg-[color:var(--mp-energy)]/25 text-[color:var(--mp-bulletin)] shadow-[0_0_8px_rgba(255,124,30,0.35)]",
                hasOutcome && `mp-slot-outcome mp-slot-outcome--${outcome!.tone}`,
                done &&
                  !active &&
                  !hasOutcome &&
                  "border-[color:var(--mp-chip-ok)]/50 bg-[color:var(--mp-chip-ok)]/20 text-white/80",
                !done &&
                  !active &&
                  !hasOutcome &&
                  "border-[color:var(--mp-glass-border)] text-white/30",
              )}
            >
              {hasOutcome ? (
                <span aria-hidden className="text-[length:var(--mp-text-base)] leading-none">
                  {slotOutcomeGlyph(outcome!.tone)}
                </span>
              ) : (
                i + 1
              )}
            </li>
          )
        })}
      </ol>
      {showProgress ? (
        <div
          className="mp-slot-progress h-0.5 w-full min-w-[5rem] overflow-hidden rounded-full bg-white/10"
          aria-hidden
        >
          <div
            className="h-full rounded-full bg-gradient-to-r from-[color:var(--mp-chip-ok)] to-[color:var(--mp-energy)] transition-[width] duration-500"
            style={{ width: `${Math.min(100, progressPct)}%` }}
          />
        </div>
      ) : null}
    </div>
  )
}
