import { memo } from "react"
import { cn } from "@/lib/utils"

export type RoleStatus = "waiting" | "interview" | "rejected" | "offer" | "spectator"

const STATUS_STYLE: Record<RoleStatus, { label: string; bg: string; fg: string }> = {
  waiting: { label: "ждёт", bg: "var(--mp-chip-wait)", fg: "#fff" },
  interview: { label: "на собесе", bg: "var(--mp-chip-ok)", fg: "#fff" },
  rejected: { label: "отказ", bg: "var(--mp-chip-bad)", fg: "#fff" },
  offer: { label: "оффер", bg: "var(--mp-chip-offer)", fg: "#fff" },
  spectator: { label: "зритель", bg: "var(--mp-plastic-deep)", fg: "#fff" },
}

type RoleChipProps = {
  status: RoleStatus
  className?: string
}

/** Публичный статус места за столом. */
export const RoleChip = memo(function RoleChip({ status, className }: RoleChipProps) {
  const s = STATUS_STYLE[status]
  return (
    <span
              className={cn(
                  "mp-mono rounded px-2 py-0.5 text-[length:var(--mp-text-xs)] font-medium uppercase tracking-wide",
        className,
      )}
      style={{ backgroundColor: s.bg, color: s.fg }}
    >
      {s.label}
    </span>
  )
})
