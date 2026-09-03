import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { SeatToken } from "@/features/multiplayer/wolves/gfx"
import { TickerTape } from "@/features/multiplayer/gfx/shell"
import { seatLabelFor } from "./seatName"
import type { WolvesWsPublicState, WolvesWsSeat } from "./wolves-ws"

const WINNER_TITLE: Record<string, string> = {
  wolves: "Победа волков",
  humans: "Победа людей",
  freeze: "Заморозка",
}

type RevealScreenProps = {
  pub: WolvesWsPublicState
  isHost: boolean
  onRematch: () => void
  onLobby: () => void
}

/**
 * Э9: театральный Reveal — переворот фишек, газета, «Ещё раунд» / «В лобби».
 * Remount по winner, чтобы сбросить анимацию без sync setState в effect.
 */
export function RevealScreen({ pub, isHost, onRematch, onLobby }: RevealScreenProps) {
  return (
    <RevealScreenBody
      key={`${pub.winner ?? "freeze"}:${pub.winner_line ?? ""}`}
      pub={pub}
      isHost={isHost}
      onRematch={onRematch}
      onLobby={onLobby}
    />
  )
}

function RevealScreenBody({ pub, isHost, onRematch, onLobby }: RevealScreenProps) {
  const [flipped, setFlipped] = useState(false)
  const seats = (pub.seats ?? []).filter((s) => s.kind === "candidate" && s.filled)
  const winner = pub.winner ?? "freeze"
  const headline =
    pub.winner_line ?? pub.slot_ticker ?? WINNER_TITLE[winner] ?? "Конец партии"

  useEffect(() => {
    const t = window.setTimeout(() => setFlipped(true), 280)
    return () => window.clearTimeout(t)
  }, [])

  return (
    <div className="space-y-4 rounded-md border border-[color:var(--mp-felt-line)] bg-[color:var(--mp-felt-deep)]/90 p-4">
      <div className="text-center">
        <p
          className="mp-display text-lg font-semibold text-[color:var(--mp-paper)]"
          style={{ animation: "mp-ticker-enter 420ms cubic-bezier(0.22, 1, 0.36, 1) both" }}
        >
          {WINNER_TITLE[winner] ?? "Конец"}
        </p>
        <div className="mx-auto mt-2 max-w-lg">
          <TickerTape text={headline} />
        </div>
      </div>

      <div className="flex flex-wrap justify-center gap-5 py-2">
        {seats.map((s, i) => (
          <RevealSeat key={s.id} seat={s} flipped={flipped} delayMs={i * 140} />
        ))}
      </div>

      <div className="flex flex-wrap justify-center gap-2 pt-1">
        {isHost ? (
          <Button type="button" size="sm" onClick={onRematch}>
            Ещё раунд
          </Button>
        ) : (
          <p className="mp-mono text-[11px] text-[color:var(--mp-paper)]/60">
            Ждём хоста на новый раунд…
          </p>
        )}
        <Button type="button" size="sm" variant="outline" onClick={onLobby}>
          В лобби
        </Button>
      </div>
    </div>
  )
}

function RevealSeat({
  seat,
  flipped,
  delayMs,
}: {
  seat: WolvesWsSeat
  flipped: boolean
  delayMs: number
}) {
  const faction = seat.faction === "wolf" ? "wolf" : seat.faction === "human" ? "human" : null
  const stamps = (seat.lifetime_stamps ?? []).join(" · ") || "—"
  return (
    <div
      className="flex flex-col items-center gap-1.5 transition-opacity duration-500"
      style={{ transitionDelay: `${delayMs}ms`, opacity: flipped ? 1 : 0.55 }}
    >
      <SeatToken
        label={seatLabelFor(seat)}
        accent={faction === "wolf" ? "wolf" : "default"}
        revealed={flipped ? faction : null}
        flipDelayMs={delayMs}
      />
      <span className="mp-mono text-[10px] uppercase tracking-wide text-[color:var(--mp-paper)]/80">
        {faction === "wolf" ? (seat.revealed_as_wolf ? "волк · пойман" : "волк") : "человек"}
      </span>
      <span className="mp-mono max-w-28 truncate text-[9px] text-[color:var(--mp-paper)]/50">
        {stamps}
      </span>
    </div>
  )
}
