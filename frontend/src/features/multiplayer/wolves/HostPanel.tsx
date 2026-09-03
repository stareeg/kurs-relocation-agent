import { Button } from "@/components/ui/button"
import { seatLabelFor } from "./seatName"
import type { WolvesWsPublicState } from "./wolves-ws"

type HostPanelProps = {
  pub: WolvesWsPublicState
  onKick: (seatId: string) => void
  onFillBot: (seatId: string) => void
  onAddSlot?: () => void
  onAssignHr?: (accountId: number) => void
  spectatorAccountIds?: number[]
}

/**
 * Хост — кик, добор бота, добавить слот (до 6), (опц.) назначить хрюшу.
 */
export function HostPanel({
  pub,
  onKick,
  onFillBot,
  onAddSlot,
  onAssignHr,
  spectatorAccountIds = [],
}: HostPanelProps) {
  const candidates = (pub.seats ?? []).filter((s) => s.kind === "candidate")
  const between = pub.phase === "between"
  const filled = candidates.filter((s) => s.filled && !s.is_bot)
  const empty = candidates.filter((s) => !s.filled)
  const canAddSlot = candidates.length < 6

  return (
    <div className="rounded-md border border-[color:var(--mp-felt-line)] bg-[color:var(--mp-felt-deep)]/70 p-2">
      <p className="mp-mono mb-1.5 text-[10px] uppercase tracking-wide text-[color:var(--mp-paper)]/60">
        Хост · стол · {candidates.length}/6 слотов
      </p>
      <div className="flex flex-wrap gap-1.5">
        {onAddSlot && canAddSlot ? (
          <Button
            type="button"
            size="sm"
            variant="secondary"
            className="h-7 text-[11px]"
            onClick={onAddSlot}
          >
            + слот
          </Button>
        ) : null}
        {filled.map((s) => (
          <Button
            key={`kick-${s.id}`}
            type="button"
            size="sm"
            variant="outline"
            className="h-7 text-[11px]"
            onClick={() => onKick(s.id)}
          >
            Кик · {seatLabelFor(s)}
          </Button>
        ))}
        {between
          ? empty.map((s) => (
              <Button
                key={`bot-${s.id}`}
                type="button"
                size="sm"
                variant="secondary"
                className="h-7 text-[11px]"
                onClick={() => onFillBot(s.id)}
              >
                Бот → место {s.id}
              </Button>
            ))
          : null}
        {onAssignHr && spectatorAccountIds.length > 0
          ? spectatorAccountIds.map((aid) => (
              <Button
                key={`hr-${aid}`}
                type="button"
                size="sm"
                className="h-7 text-[11px]"
                onClick={() => onAssignHr(aid)}
              >
                Хрюша ← #{aid}
              </Button>
            ))
          : null}
      </div>
      {between && empty.length === 0 && filled.length === 0 && !canAddSlot ? (
        <p className="mp-mono mt-1 text-[10px] text-[color:var(--mp-paper)]/45">Нет действий</p>
      ) : null}
    </div>
  )
}
