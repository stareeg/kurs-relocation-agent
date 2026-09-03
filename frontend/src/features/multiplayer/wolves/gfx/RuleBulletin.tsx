import { cn } from "@/lib/utils"

export type BulletinGate = { id: string; label: string }

type RuleBulletinProps = {
  dayLabel: string
  gates: BulletinGate[]
  className?: string
}

/** Жёлтый бланк дня: правила слота и knockout-гейты. */
export function RuleBulletin({ dayLabel, gates, className }: RuleBulletinProps) {
  return (
    <aside
      className={cn(
        "relative overflow-hidden rounded-sm border border-[color:var(--mp-bulletin-edge)] bg-[color:var(--mp-bulletin)] p-3 shadow-[2px_2px_0_rgba(30,41,59,0.15)]",
        className,
      )}
    >
      <div className="mp-display text-xs font-semibold uppercase tracking-wide text-[color:var(--mp-ink)]">
        Бюллетень · {dayLabel}
      </div>
      <ul className="mt-2 space-y-1.5">
        {gates.map((g) => (
          <li
            key={g.id}
            className="mp-mono flex items-start gap-2 text-[11px] leading-snug text-[color:var(--mp-ink)]"
          >
            <span
              aria-hidden
              className="mt-0.5 inline-block size-1.5 shrink-0 rounded-full bg-[color:var(--mp-stamp)]"
            />
            {g.label}
          </li>
        ))}
      </ul>
      <div
        aria-hidden
        className="pointer-events-none absolute -right-2 -top-2 size-10 rotate-12 rounded-full border-2 border-[color:var(--mp-stamp)]/40"
      />
    </aside>
  )
}
