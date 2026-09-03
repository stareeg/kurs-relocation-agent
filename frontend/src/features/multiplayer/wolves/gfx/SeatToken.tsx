import { memo } from "react"
import { cn } from "@/lib/utils"

type SeatTokenProps = {
  label: string
  initials?: string
  accent?: "default" | "wolf" | "hr"
  /** После Reveal: переворот фишки (null = рубашка). */
  revealed?: "wolf" | "human" | null
  flipDelayMs?: number
  className?: string
}

/** Фишка кандидата / хрюши за столом. */
export const SeatToken = memo(function SeatToken({
  label,
  initials,
  accent = "default",
  revealed = null,
  flipDelayMs = 0,
  className,
}: SeatTokenProps) {
  const ring =
    accent === "wolf" || revealed === "wolf"
      ? "ring-[color:var(--mp-wolf)]"
      : accent === "hr"
        ? "ring-[color:var(--mp-stamp)]"
        : "ring-[color:var(--mp-paper-edge)]"
  const letters =
    initials ??
    label
      .split(/\s+/)
      .map((w) => w[0])
      .join("")
      .slice(0, 2)
      .toUpperCase()

  const showFlip = revealed === "wolf" || revealed === "human"

  return (
    <div className={cn("flex flex-col items-center gap-1", className)}>
      <div
        className="mp-seat-flip"
        style={{ perspective: "420px" }}
      >
        <div
          className={cn(
            "mp-seat-flip-inner relative size-11 transition-transform duration-500 ease-out",
            showFlip && "mp-seat-flip-inner--revealed",
          )}
          style={{
            transformStyle: "preserve-3d",
            transitionDelay: `${flipDelayMs}ms`,
            transform: showFlip ? "rotateY(180deg)" : "rotateY(0deg)",
          }}
        >
          <div
            className={cn(
              "absolute inset-0 flex items-center justify-center rounded-full bg-[color:var(--mp-paper)] text-sm font-semibold text-[color:var(--mp-ink)] ring-2 ring-offset-2 ring-offset-[color:var(--mp-felt)]",
              ring,
            )}
            style={{
              fontFamily: "var(--mp-font-display)",
              backfaceVisibility: "hidden",
            }}
          >
            {letters}
          </div>
          <div
            className={cn(
              "absolute inset-0 flex items-center justify-center rounded-full text-sm font-semibold ring-2 ring-offset-2 ring-offset-[color:var(--mp-felt)]",
              revealed === "wolf"
                ? "bg-[color:var(--mp-wolf)] text-[color:var(--mp-paper)] ring-[color:var(--mp-wolf)]"
                : "bg-[color:var(--mp-paper)] text-[color:var(--mp-ink)] ring-[color:var(--mp-chip-ok)]",
            )}
            style={{
              fontFamily: "var(--mp-font-display)",
              backfaceVisibility: "hidden",
              transform: "rotateY(180deg)",
            }}
            aria-hidden={!showFlip}
          >
            {revealed === "wolf" ? "В" : revealed === "human" ? "Ч" : letters}
          </div>
        </div>
      </div>
      <span
        title={label}
        className="mp-mono max-w-24 truncate text-[length:var(--mp-text-xs)] text-[color:var(--mp-paper)]"
      >
        {label}
      </span>
    </div>
  )
})
