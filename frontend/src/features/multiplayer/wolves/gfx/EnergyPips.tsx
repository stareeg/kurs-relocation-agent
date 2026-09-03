import { memo } from "react"
import { cn } from "@/lib/utils"

type EnergyPipsProps = {
  max?: number
  value: number
  /** Низкий заряд — оранжевый акцент (SIGame stakes). */
  low?: boolean
  className?: string
}

export const EnergyPips = memo(function EnergyPips({
  max = 5,
  value,
  low = false,
  className,
}: EnergyPipsProps) {
  const safe = Math.max(0, Math.min(max, value))
  return (
    <div
      className={cn("flex items-center gap-1", className)}
      role="meter"
      aria-label="Энергия"
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuenow={safe}
    >
      {Array.from({ length: max }, (_, i) => {
        const on = i < safe
        return (
          <svg
            key={i}
            viewBox="0 0 24 24"
            aria-hidden
            className={cn(
              "size-5 transition-all",
              on ? "opacity-100" : "opacity-15",
              on && low && "drop-shadow-[0_0_4px_var(--mp-energy)]",
            )}
            fill={on ? (low ? "var(--mp-stamp)" : "var(--mp-energy)") : "var(--mp-ink)"}
          >
            <path d="M13 2 4.5 13.5H11l-1.5 8.5 8.5-12H11z" />
          </svg>
        )
      })}
      <span
        className={cn(
          "mp-display ml-1 tabular-nums text-[length:var(--mp-text-sm)] font-semibold",
          low ? "text-[color:var(--mp-stamp)]" : "text-[color:var(--mp-ink)]",
        )}
      >
        {safe}
      </span>
    </div>
  )
})
