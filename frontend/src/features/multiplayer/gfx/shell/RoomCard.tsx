import { cn } from "@/lib/utils"

type RoomCardProps = {
  name: string
  code: string
  seatsFree: number
  seatsTotal: number
  phaseLabel?: string
  className?: string
  onJoin?: () => void
}

/** Плитка стола в лобби (SI-style). Кнопка «Войти» — снаружи. */
export function RoomCard({
  name,
  code,
  seatsFree,
  seatsTotal,
  phaseLabel = "лобби",
  className,
  onJoin,
}: RoomCardProps) {
  const body = (
    <>
      <div className="min-w-0">
        <div className="mp-display truncate text-sm font-semibold">{name}</div>
        <div className="mp-mono mt-0.5 text-[10px] opacity-70">
          код {code} · {phaseLabel}
        </div>
      </div>
      <div className="mp-mono shrink-0 rounded bg-[color:var(--mp-paper)]/15 px-2 py-1 text-[11px]">
        {seatsFree}/{seatsTotal}
      </div>
    </>
  )

  if (onJoin) {
    return (
      <button
        type="button"
        onClick={onJoin}
        className={cn(
          "flex w-full items-center justify-between gap-3 rounded-md border border-[color:var(--mp-felt-line)] bg-[color:var(--mp-felt)] px-3 py-2.5 text-left text-[color:var(--mp-paper)] transition-colors hover:bg-[color:var(--mp-felt-deep)]",
          className,
        )}
      >
        {body}
      </button>
    )
  }

  return (
    <div
      className={cn(
        "flex w-full items-center justify-between gap-3 rounded-md border border-[color:var(--mp-felt-line)] bg-[color:var(--mp-felt)] px-3 py-2.5 text-left text-[color:var(--mp-paper)]",
        className,
      )}
    >
      {body}
    </div>
  )
}
