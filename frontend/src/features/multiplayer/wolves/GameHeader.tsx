import { PhaseCountdown } from "@/features/multiplayer/wolves/gfx"
import { phaseCaptionLabel, type PhaseId } from "@/features/multiplayer/wolves/gfx"
import { SlotStrip } from "@/features/multiplayer/gfx/shell"
import { TickerTape } from "@/features/multiplayer/gfx/shell"
import type { WolvesRoomSocket } from "./wolves-ws"
import type { TurnGuide } from "./turnGuide"
import type { SlotOutcomeMap } from "./slotOutcomes"

type GameHeaderProps = {
  packMatesLabel?: string
  slotIndex: number
  slotCount: number
  phase: PhaseId
  phaseRaw: string
  eventLabel?: string | null
  slotTicker?: string | null
  slotOutcomes?: SlotOutcomeMap
  guide: TurnGuide | null
  paused: boolean
  socket: WolvesRoomSocket
}

/**
 * Шапка игровой сцены в духе SIGame GameState + tableCaption:
 * фиксированные по высоте полосы — динамический текст не сдвигает стол кандидатов.
 */
export function GameHeader({
  packMatesLabel,
  slotIndex,
  slotCount,
  phase,
  phaseRaw,
  eventLabel,
  slotTicker,
  slotOutcomes,
  guide,
  paused,
  socket,
}: GameHeaderProps) {
  const slotNum = Math.min(slotIndex + 1, slotCount)
  const between = phaseRaw === "between"
  const caption = phaseCaptionLabel(phase, between)

  return (
    <header className="mp-game-header flex shrink-0 flex-col overflow-hidden">
      <div className="mp-phase-caption-bar flex min-h-[2rem] flex-wrap items-center gap-x-3 gap-y-1 px-3 py-1.5">
        <SlotStrip slotIndex={slotIndex} slotCount={slotCount} showProgress outcomes={slotOutcomes} />
        <div className="flex min-w-0 flex-1 flex-col items-center justify-center gap-0 text-center">
          <span className="mp-display mp-stage-text text-[length:var(--mp-text-base)] font-bold uppercase tracking-wide text-white">
            {caption}
          </span>
          <span className="mp-mono text-[length:var(--mp-text-2xs)] text-white/50">
            слот {slotNum} из {slotCount}
            {packMatesLabel ? ` · ${packMatesLabel}` : ""}
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <PhaseCountdown socket={socket} reserveSpace />
        </div>
      </div>

      <div className="flex min-h-0 shrink-0 items-center gap-2 border-t border-[color:var(--mp-glass-border)] px-3 py-1">
        <div className="min-w-0 flex-1">
          <div
            className={`flex items-center gap-2 ${
              guide && !paused
                ? guide.waiting
                  ? "mp-turn-guide--waiting"
                  : "mp-turn-guide--active"
                : "mp-turn-guide--waiting"
            } ${paused ? "opacity-40" : ""}`}
            aria-hidden={paused || !guide}
          >
            <span
              aria-hidden
              className={`inline-block size-2 shrink-0 rounded-full ${
                guide && !paused && !guide.waiting
                  ? "mp-act-now bg-[color:var(--mp-energy)]"
                  : "bg-white/30"
              }`}
            />
            <p className="mp-display mp-stage-text line-clamp-1 flex-1 text-[length:var(--mp-text-xs)] font-semibold leading-snug">
              {guide?.text ?? "\u00a0"}
            </p>
          </div>
        </div>
        {eventLabel ? (
          <span className="mp-mono shrink-0 rounded bg-white/10 px-2 py-0.5 text-[length:var(--mp-text-xs)] text-white/80">
            {eventLabel}
          </span>
        ) : null}
      </div>

      <div
        className={`mp-header-ticker border-t border-[color:var(--mp-glass-border)] ${
          paused ? "opacity-35" : ""
        }`}
      >
        {slotTicker ? <TickerTape text={slotTicker} /> : null}
      </div>
    </header>
  )
}
