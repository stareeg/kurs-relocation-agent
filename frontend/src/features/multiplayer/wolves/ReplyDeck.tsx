import { cn } from "@/lib/utils"
import { questionChipById } from "./chips"
import { seatName } from "./seatName"
import { seatStatusLabel } from "./seatStatus"
import type { WolvesWsPublicState } from "./wolves-ws"

type ReplyDeckProps = {
  pub: WolvesWsPublicState
}

/** Колода реплик слота — вопрос хрюши сверху, карточки ответов внизу (SIGame replic area). */
export function ReplyDeck({ pub }: ReplyDeckProps) {
  const answers = pub.answers ?? {}
  const live = pub.live_lines ?? {}
  const questionId = pub.question_chip
  const question = questionId ? questionChipById(questionId) : undefined
  const filledCandidates = (pub.seats ?? []).filter((s) => s.kind === "candidate" && s.filled)
  const inLines = pub.phase === "lines"

  const cards = filledCandidates
    .map((seat) => {
      const answer = answers[seat.id]
      const liveText = live[seat.id]
      const reaction = pub.stamp_reactions?.[seat.id]
      const text = liveText ?? answer ?? reaction
      const stampKind = pub.stamps_this_slot?.[seat.id] ?? null
      const statusLabel = seatStatusLabel(seat.public_status, {
        stamped: stampKind,
        phase: pub.phase,
      })
      if (!text && seat.public_status === "waiting" && !inLines) return null
      return {
        id: seat.id,
        name: seatName(pub, seat.id),
        status: seat.public_status,
        statusLabel,
        text,
        isLive: Boolean(liveText),
        waitingAnswer: inLines && questionId && !answer && !liveText && !stampKind,
      }
    })
    .filter(Boolean) as Array<{
    id: string
    name: string
    status: string
    statusLabel: string | null
    text?: string
    isLive: boolean
    waitingAnswer: boolean
  }>

  const hasContent = cards.length > 0 || Boolean(question)

  return (
    <div className="mp-reply-deck-slot shrink-0">
      <div className="mp-reply-deck mp-glass-panel px-4 py-3">
        {hasContent ? (
          <>
            {question ? (
              <div className="mp-question-banner mb-3 px-1">
                <span className="mp-mono text-[length:var(--mp-text-xs)] uppercase tracking-wider text-white/45">
                  вопрос хрюши
                </span>
                <p className="mp-display mp-stage-text mt-1 text-[length:var(--mp-text-base)] font-semibold leading-snug text-white">
                  {question.prompt}
                </p>
              </div>
            ) : null}

            {cards.length > 0 ? (
              <div className="flex flex-wrap items-end justify-center gap-3">
                {cards.map((c) => (
                  <ReplyCard key={c.id} {...c} />
                ))}
              </div>
            ) : inLines && question ? (
              <p className="mp-mono text-center text-[length:var(--mp-text-sm)] text-white/40">
                ждём ответы кандидатов…
              </p>
            ) : null}
          </>
        ) : (
          <p className="mp-mono text-center text-[length:var(--mp-text-xs)] text-white/20" aria-hidden>
            реплики слота
          </p>
        )}
      </div>
    </div>
  )
}

function ReplyCard({
  name,
  status,
  statusLabel,
  text,
  isLive,
  waitingAnswer,
}: {
  name: string
  status: string
  statusLabel: string | null
  text?: string
  isLive?: boolean
  waitingAnswer?: boolean
}) {
  const stateBorder = replyBorderClass(status)

  return (
    <div
      className={cn(
        "mp-enter flex w-48 min-w-[12rem] flex-col gap-1.5 rounded-lg border bg-gradient-to-b from-[color:var(--mp-paper)] to-[color:var(--mp-paper-edge)] p-3 shadow-lg transition-transform",
        stateBorder,
        isLive && "mp-reply-card--live -translate-y-2 ring-2 ring-[color:var(--mp-energy)]/40",
        waitingAnswer && !text && "mp-seat-card--turn opacity-90",
      )}
      style={{ transform: isLive ? undefined : `rotate(${hashRotate(name)}deg)` }}
    >
      <div className="flex items-center justify-between gap-1">
        <span className="mp-display truncate text-[length:var(--mp-text-sm)] font-semibold text-[color:var(--mp-ink)]">
          {name}
        </span>
        {statusLabel ? (
          <span className="mp-mono shrink-0 rounded bg-black/10 px-1 py-0.5 text-[10px] uppercase text-[color:var(--mp-ink)]/70">
            {statusLabel}
          </span>
        ) : null}
      </div>
      {text ? (
        <p className="mp-mono text-[length:var(--mp-text-xs)] leading-snug text-[color:var(--mp-ink)]/85">
          {isLive ? (
            <>
              {text}
              <span className="mp-caret" aria-hidden="true">
                ▌
              </span>
            </>
          ) : (
            text
          )}
        </p>
      ) : waitingAnswer ? (
        <p className="mp-mono text-[length:var(--mp-text-xs)] italic text-[color:var(--mp-ink)]/45">
          думает…
        </p>
      ) : null}
    </div>
  )
}

function replyBorderClass(status: string): string {
  if (status === "interview") return "border-green-600/50"
  if (status === "rejected" || status === "ghosted") return "border-red-700/50"
  if (status === "offer") return "border-blue-600/50"
  return "border-[color:var(--mp-glass-border)]"
}

function hashRotate(name: string): number {
  let h = 0
  for (let i = 0; i < name.length; i++) h = (h + name.charCodeAt(i) * (i + 1)) % 7
  return (h - 3) * 1.5
}

