import { cn } from "@/lib/utils"

export type PhaseId = "bulletin" | "play" | "inspect" | "lines" | "stamp" | "judge" | "result"

export const PHASE_LABEL: Record<PhaseId, string> = {
  bulletin: "Бюллетень",
  play: "Подача",
  inspect: "Осмотр",
  lines: "Реплики",
  stamp: "Штамп",
  judge: "Суд",
  result: "Итог",
}

type PhaseRailProps = {
  current: PhaseId
  /** Иск подан — в шкале появляется сегмент «Суд» между осмотром и репликами (Э30.6). */
  claimFiled?: boolean
  /** Передышка между слотами — отдельное состояние, а не выпадение из шкалы. */
  between?: boolean
  secondsLeft?: number
  slotLabel?: string
  className?: string
  /** Встроенный режим для шапки: без рамки/фона, компактные чипы. */
  compact?: boolean
}

/** Подпись текущей фазы для шапки стола (SIGame tableCaption). */
export function phaseCaptionLabel(
  phase: PhaseId,
  between: boolean,
): string {
  if (between) return "Передышка"
  return PHASE_LABEL[phase] ?? phase
}

/** Полоска фаз слота: где мы в раскладе «Бюллетень → … → Итог». */
export function PhaseRail({
  current,
  claimFiled = false,
  between = false,
  secondsLeft,
  slotLabel,
  className,
  compact = false,
}: PhaseRailProps) {
  const phases: PhaseId[] = claimFiled
    ? ["bulletin", "play", "inspect", "judge", "lines", "stamp", "result"]
    : ["bulletin", "play", "inspect", "lines", "stamp", "result"]
  const idx = phases.indexOf(current)

  return (
    <div
      className={cn(
        compact
          ? "flex shrink-0 items-center gap-x-1.5"
          : "flex shrink-0 flex-wrap items-center gap-x-2 gap-y-1 rounded-md border border-[color:var(--mp-felt-line)] bg-[color:var(--mp-felt-deep)]/80 px-3 py-1.5",
        className,
      )}
    >
      {compact ? null : slotLabel ? (
        <span className="mp-display text-[11px] font-semibold text-[color:var(--mp-paper)]">
          {slotLabel}
        </span>
      ) : null}
      {compact ? null : between ? (
        <span className="mp-mono rounded bg-[color:var(--mp-bulletin)]/30 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-[color:var(--mp-bulletin)]">
          передышка
        </span>
      ) : null}
      <ol className={cn("flex flex-wrap items-center gap-1", compact && "gap-x-1")}>
        {phases.map((p, i) => {
          const done = !between && i < idx
          const active = !between && p === current
          return (
            <li key={p} className="flex items-center gap-1">
              {i > 0 ? (
                <span aria-hidden className={cn("text-[color:var(--mp-felt-line)]", compact && "text-white/25")}>
                  ·
                </span>
              ) : null}
              <span
                className={cn(
                  "mp-mono rounded px-2 py-0.5 text-[length:var(--mp-text-xs)] uppercase tracking-wide",
                  compact && "px-1.5 py-0 !rounded-none !text-[10px]",
                  active && compact ? "font-semibold text-[color:var(--mp-bulletin)]" : "",
                  active && !compact && "bg-[color:var(--mp-paper)] font-semibold text-[color:var(--mp-ink)]",
                  done && !active && "text-[color:var(--mp-paper)]/55",
                  !done && !active && compact ? "text-white/35" : "text-[color:var(--mp-paper)]/35",
                )}
              >
                {PHASE_LABEL[p]}
              </span>
            </li>
          )
        })}
      </ol>
      {!compact && typeof secondsLeft === "number" ? (
        <span
          className={cn(
            "mp-display tabular-nums text-sm font-semibold",
            secondsLeft <= 5 ? "text-[color:var(--mp-stamp)]" : "text-[color:var(--mp-paper)]",
          )}
        >
          {secondsLeft}с
        </span>
      ) : null}
    </div>
  )
}
