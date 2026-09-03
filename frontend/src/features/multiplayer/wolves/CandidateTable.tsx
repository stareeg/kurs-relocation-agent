import { memo } from "react"
import { TableFelt } from "@/features/multiplayer/gfx/shell"
import { SeatToken, CardBack, CardFace, type ExperienceTag } from "@/features/multiplayer/wolves/gfx"
import { cn } from "@/lib/utils"
import { GameButton } from "./GameButton"
import { seatLabelFor } from "./seatName"
import { isSeatActiveTurn, seatStatusLabel } from "./seatStatus"
import type { WolvesWsPublicState, WolvesWsSeat, WolvesPlayedCard } from "./wolves-ws"

type CandidateTableProps = {
  pub: WolvesWsPublicState
  isHost: boolean
  isHr: boolean
  faceUp: boolean
  cardsToPlay: number
  canClaimEmpty: boolean
  canClaimBot: boolean
  onFocus: (seatId: string) => void
  onClaim: (seatId: string) => void
  onKick?: (seatId: string) => void
  onFillBot?: (seatId: string) => void
  onAddSlot?: () => void
}

/** Стол кандидатов — карточки с семантическим цветом состояния (SIGame PlayerView). */
export function CandidateTable({
  pub,
  isHost,
  isHr,
  faceUp,
  canClaimEmpty,
  canClaimBot,
  onFocus,
  onClaim,
  onKick,
  onFillBot,
  onAddSlot,
}: CandidateTableProps) {
  const candidates = (pub.seats ?? []).filter((s) => s.kind === "candidate")
  const between = pub.phase === "between"
  const canAddSlot = isHost && candidates.length < 6 && onAddSlot

  return (
    <TableFelt className="mp-candidate-table shrink-0 px-4 py-3">
      <p className="mp-mono mp-stage-text mb-2 text-center text-[length:var(--mp-text-xs)] uppercase tracking-widest text-white/40">
        кандидаты слота
      </p>
      <div className="flex flex-wrap items-end justify-center gap-3">
        {candidates.map((s) =>
          s.filled ? (
            <SeatCard
              key={s.id}
              seat={s}
              pub={pub}
              isHr={isHr}
              faceUp={faceUp}
              canClaimBot={canClaimBot && Boolean(s.is_bot)}
              onFocus={onFocus}
              onClaim={onClaim}
              onKick={isHost && !s.is_bot ? onKick : undefined}
            />
          ) : (
            <EmptySlotCard
              key={s.id}
              seatId={s.id}
              canClaim={canClaimEmpty}
              canFillBot={between && isHost && Boolean(onFillBot)}
              onClaim={onClaim}
              onFillBot={onFillBot}
            />
          ),
        )}
        {canAddSlot ? <AddSlotCard onAdd={onAddSlot} /> : null}
      </div>
    </TableFelt>
  )
}

const SeatCard = memo(function SeatCard({
  seat,
  pub,
  isHr,
  faceUp,
  canClaimBot,
  onFocus,
  onClaim,
  onKick,
}: {
  seat: WolvesWsSeat
  pub: WolvesWsPublicState
  isHr: boolean
  faceUp: boolean
  canClaimBot: boolean
  onFocus: (id: string) => void
  onClaim: (id: string) => void
  onKick?: (id: string) => void
}) {
  const focused = seat.id === pub.focus_candidate_id
  const stamped = Boolean(pub.stamps_this_slot?.[seat.id])
  const answered = Boolean(pub.answers?.[seat.id])
  const canFocus =
    isHr &&
    !stamped &&
    (pub.phase === "inspect" || pub.phase === "lines" || pub.phase === "stamp")
  const pickNow = isHr && pub.phase === "stamp" && !pub.focus_candidate_id
  const interactive = canFocus || canClaimBot

  const stateClass = seatStateClass(seat.public_status, stamped, answered, pub.phase)
  const stampKind = pub.stamps_this_slot?.[seat.id] ?? null
  const statusLabel = seatStatusLabel(seat.public_status, {
    stamped: stampKind,
    phase: pub.phase,
  })
  const activeTurn = isSeatActiveTurn(seat, pub, isHr)

  return (
    <div className="group relative flex flex-col items-center">
      {focused && isHr ? (
        <span className="mp-seat-ribbon mp-seat-ribbon--focus">в работе</span>
      ) : null}
      {onKick ? (
        <button
          type="button"
          onClick={() => onKick(seat.id)}
          className="mp-btn-glass mp-btn absolute -top-2 -right-2 z-20 hidden !px-1.5 !py-0.5 group-hover:block"
          aria-label={`Кик ${seatLabelFor(seat)}`}
        >
          ✕
        </button>
      ) : null}

      <button
        type="button"
        disabled={!interactive}
        onClick={() => {
          if (canClaimBot) onClaim(seat.id)
          else onFocus(seat.id)
        }}
        className={cn(
          "mp-seat-card mp-seat-card--filled relative transition-transform duration-300",
          stateClass,
          focused && "mp-seat-card--focused",
          interactive && "mp-seat-card--selectable cursor-pointer",
          !interactive && "cursor-default opacity-80",
          pickNow && canFocus && !focused && "mp-demo-blink ring-2 ring-[color:var(--mp-energy)]",
          activeTurn && "mp-seat-card--turn",
        )}
      >
        {statusLabel ? (
          <span className="mp-seat-status">{statusLabel}</span>
        ) : (
          <span className="mp-seat-status mp-seat-status--empty" aria-hidden />
        )}

        <div className="mp-seat-card__marks flex gap-1">
          {answered ? (
            <span className="mp-mark-dot bg-purple-400" title="Ответил" aria-hidden />
          ) : null}
          {stamped ? (
            <span className="mp-mark-dot bg-[color:var(--mp-bulletin)]" title="Штамп" aria-hidden />
          ) : null}
          {!stamped && pub.stamps_this_slot?.[seat.id] === "probe" ? (
            <span className="mp-mark-dot bg-[color:var(--mp-chip-wait)]" title="Проверка" aria-hidden />
          ) : null}
        </div>

        {stampKind ? <StampImprint kind={stampKind} rotation={hashRotation(seat.id)} /> : null}

        <PlayedDeck cards={seat.played ?? []} faceUp={faceUp} />

        <SeatToken
          label={seatLabelFor(seat)}
          accent={seat.faction === "wolf" ? "wolf" : "default"}
          className="mt-auto"
        />
      </button>
    </div>
  )
})

const EmptySlotCard = memo(function EmptySlotCard({
  seatId,
  canClaim,
  canFillBot,
  onClaim,
  onFillBot,
}: {
  seatId: string
  canClaim: boolean
  canFillBot: boolean
  onClaim: (id: string) => void
  onFillBot?: (id: string) => void
}) {
  return (
    <div className="flex flex-col items-center gap-1.5">
      <button
        type="button"
        disabled={!canClaim}
        onClick={() => onClaim(seatId)}
        className={cn(
          "mp-seat-card mp-seat-card--empty flex h-[8.5rem] w-[5.25rem] flex-col items-center justify-center gap-1",
          canClaim && "mp-demo-blink cursor-pointer",
          !canClaim && "cursor-default opacity-40",
        )}
      >
        <span className="mp-display text-3xl font-light text-[color:var(--mp-bulletin)]">+</span>
      </button>
      {canFillBot && onFillBot ? (
        <GameButton variant="glass" className="!px-2 !py-1 !text-xs" onClick={() => onFillBot(seatId)}>
          бот
        </GameButton>
      ) : null}
    </div>
  )
})

function AddSlotCard({ onAdd }: { onAdd: () => void }) {
  return (
    <button
      type="button"
      onClick={onAdd}
      className="mp-seat-card mp-seat-card--empty flex h-[8.5rem] w-[5.25rem] cursor-pointer flex-col items-center justify-center gap-1 transition-transform hover:-translate-y-1"
    >
      <span className="mp-display text-2xl font-light text-[color:var(--mp-accent-text)]">+</span>
    </button>
  )
}

const PlayedDeck = memo(function PlayedDeck({
  cards,
  faceUp,
}: {
  cards: WolvesPlayedCard[]
  faceUp: boolean
}) {
  return (
    <div className="mp-seat-card__deck">
      {cards.length ? (
        <div className="mp-card-deck py-0">
          {cards.map((c, i) =>
            !faceUp || c.tag === "hidden" ? (
              <div key={c.id} className="mp-card-deal" style={{ animationDelay: `${i * 60}ms` }}>
                <CardBack className="h-14 w-10" />
              </div>
            ) : (
              <div key={c.id} className="mp-card-deal origin-bottom" style={{ animationDelay: `${i * 60}ms` }}>
                <CardFace tag={asTag(c.tag)} title={c.title} size="sm" />
              </div>
            ),
          )}
        </div>
      ) : null}
    </div>
  )
})

function seatStateClass(
  status: string,
  stamped: boolean,
  answered: boolean,
  phase: string,
): string {
  if (stamped) return "mp-seat-card--stamped"
  if (answered && phase === "lines") return "mp-seat-card--answered"
  if (status === "interview") return "mp-seat-card--interview"
  if (status === "ghosted") return "mp-seat-card--ghosted"
  if (status === "rejected") return "mp-seat-card--rejected"
  if (status === "offer") return "mp-seat-card--offer"
  return ""
}

function asTag(tag: string): ExperienceTag {
  const ok: ExperienceTag[] = [
    "ownership",
    "scale",
    "incident",
    "soft",
    "stack",
    "bluff",
    "batna",
    "second_job",
  ]
  return (ok.includes(tag as ExperienceTag) ? tag : "soft") as ExperienceTag
}

const STAMP_IMPRINT_LABEL: Record<string, string> = {
  interview: "СОБЕС",
  reject: "ОТКАЗ",
  probe: "ПРОВЕРКА",
  offer: "ОФФЕР",
}

const STAMP_IMPRINT_COLOR: Record<string, string> = {
  interview: "var(--mp-chip-ok)",
  reject: "var(--mp-stamp)",
  probe: "var(--mp-chip-wait)",
  offer: "var(--mp-chip-offer)",
}

function StampImprint({ kind, rotation }: { kind: string; rotation: number }) {
  const label = STAMP_IMPRINT_LABEL[kind] ?? kind.toUpperCase()
  const color = STAMP_IMPRINT_COLOR[kind] ?? "var(--mp-ink)"
  return (
    <span
      className="mp-imprint absolute bottom-1 left-1/2 -translate-x-1/2 border px-1.5 py-0.5 text-[8px] font-semibold uppercase tracking-wider"
      style={{
        borderColor: color,
        color,
        fontFamily: "var(--mp-font-display)",
        ["--mp-rot" as string]: `${rotation}deg`,
      }}
    >
      {label}
    </span>
  )
}

/** Детерминированный поворот от id места — без Math.random() в render. */
function hashRotation(id: string): number {
  let h = 0
  for (let i = 0; i < id.length; i++) {
    h = (h * 31 + id.charCodeAt(i)) | 0
  }
  return -8 + (Math.abs(h) % 17)
}
