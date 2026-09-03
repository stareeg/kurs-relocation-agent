import { GameButton } from "./GameButton"
import { StampButton, type StampKind } from "@/features/multiplayer/wolves/gfx"
import { seatLabelFor } from "./seatName"
import type { WolvesWsPublicState, WolvesWsSeat } from "./wolves-ws"

const STAMP_TO_ENGINE: Record<StampKind, string> = {
  approve: "interview",
  reject: "reject",
  probe: "probe",
  offer: "offer",
}

export type ActionRole = "hr" | "candidate" | "spectator"

type ActionBarProps = {
  pub: WolvesWsPublicState
  role: ActionRole
  focusSeat: WolvesWsSeat | null
  focusStamped: boolean
  energy: number
  offerAllowed: boolean
  marks: string[]
  claimFiled: boolean
  pendingIntentType: string
  errorText: string | null
  onIntent: (intent: Record<string, unknown>) => void
  /** Колбэк при нажатии штампа — для стряски кабинки (Э21.3). */
  onStamp?: () => void
  vertical?: boolean
}

/** Действия фазы — только кнопки, без лишних подсказок (контекст в шапке). */
export function ActionBar({
  pub,
  role,
  focusSeat,
  focusStamped,
  energy,
  offerAllowed,
  marks,
  claimFiled,
  pendingIntentType,
  errorText,
  onIntent,
  onStamp,
  vertical = false,
}: ActionBarProps) {
  const phase = pub.phase
  const buttons = renderButtons()

  if (!buttons && !errorText) return null

  return (
    <div className={vertical ? "space-y-2" : "shrink-0 px-1"}>
      {buttons ? (
        <div
          className={
            vertical ? "flex flex-col gap-2 [&_.mp-btn]:w-full" : "flex flex-wrap items-center gap-2"
          }
        >
          {buttons}
        </div>
      ) : null}
      {errorText ? (
        <p className="mp-mono text-[length:var(--mp-text-xs)] text-[color:var(--mp-stamp)]">
          {errorText}
        </p>
      ) : null}
    </div>
  )

  function renderButtons() {
    if (role === "hr") return hrButtons()
    return null
  }

  function hrButtons() {
    if (phase === "bulletin") {
      return (
        <GameButton
          variant="primary"
          pulse
          disabled={pendingIntentType === "ack_bulletin"}
          className={vertical ? "w-full" : ""}
          onClick={() => onIntent({ type: "ack_bulletin" })}
        >
          {pendingIntentType === "ack_bulletin" ? "…" : "К подаче карт"}
        </GameButton>
      )
    }

    if (phase === "inspect") {
      const filing = pendingIntentType === "mark_discrepancy"
      return (
        <>
          {!claimFiled ? (
            <GameButton
              variant="reject"
              disabled={filing || marks.length !== 2 || energy <= 0}
              className={vertical ? "w-full" : ""}
              onClick={() => onIntent({ type: "mark_discrepancy", markers: marks })}
            >
              {filing ? "…" : `Иск · −1⚡ (${marks.length}/2)`}
            </GameButton>
          ) : null}
          <GameButton
            variant="standard"
            pulse={!claimFiled && marks.length < 2}
            disabled={pendingIntentType === "advance_phase"}
            className={vertical ? "w-full" : ""}
            onClick={() => onIntent({ type: "advance_phase" })}
          >
            {claimFiled ? "К суду" : "Дальше"}
          </GameButton>
        </>
      )
    }

    if (phase === "lines") {
      return (
        <GameButton
          variant="standard"
          pulse
          disabled={pendingIntentType === "advance_phase"}
          className={vertical ? "w-full" : ""}
          onClick={() => onIntent({ type: "advance_phase" })}
        >
          К штампу
        </GameButton>
      )
    }

    if (phase === "stamp") {
      if (!focusSeat || focusStamped) return null
      const disabled = pendingIntentType === "stamp_candidate"
      const stampFor = (kind: StampKind) => {
        onStamp?.()
        onIntent({ type: "stamp_candidate", candidate_id: focusSeat.id, stamp: STAMP_TO_ENGINE[kind] })
      }
      return (
        <div className={vertical ? "flex w-full flex-col gap-2" : "contents"}>
          <span className="mp-display mp-stage-text text-center text-[length:var(--mp-text-sm)] font-semibold text-white/90">
            {seatLabelFor(focusSeat)}
          </span>
          <StampButton kind="approve" highlight disabled={disabled} onStamp={stampFor} />
          <StampButton kind="reject" highlight disabled={disabled} onStamp={stampFor} />
          <StampButton
            kind="probe"
            highlight={energy > 0}
            disabled={disabled || energy <= 0}
            onStamp={stampFor}
          />
          <StampButton
            kind="offer"
            highlight={offerAllowed}
            disabled={disabled || !offerAllowed}
            onStamp={stampFor}
          />
        </div>
      )
    }

    if (phase === "judge") return null

    if (phase === "result") {
      return (
        <GameButton
          variant="primary"
          pulse
          disabled={pendingIntentType === "advance_phase"}
          className={vertical ? "w-full" : ""}
          onClick={() => onIntent({ type: "advance_phase" })}
        >
          Закрыть слот
        </GameButton>
      )
    }

    return null
  }
}
