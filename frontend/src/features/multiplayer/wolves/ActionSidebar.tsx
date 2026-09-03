import { ActionBar, type ActionRole } from "./ActionBar"
import { CandidateHand } from "./CandidateHand"
import { LinesPanel } from "./LinesPanel"
import type { WolvesWsPublicState, WolvesWsSeat } from "./wolves-ws"

type HandCard = { id: string; tag: string; title: string }

type ActionSidebarProps = {
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
  /** Кандидат: рука карт */
  isCandidate: boolean
  effectiveHand: HandCard[]
  cardsToPlay: number
  alreadyPlayed: boolean
  pendingPlayIds: boolean
  playError: string | null
  onPlay: (cardIds: string[]) => void
  isHr: boolean
  mySeatId: string | null
  paused: boolean
}

/**
 * Правая колонка действий — все игровые кнопки друг под другом (SIGame SideControlPanel).
 */
export function ActionSidebar({
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
  isCandidate,
  effectiveHand,
  cardsToPlay,
  alreadyPlayed,
  pendingPlayIds,
  playError,
  onPlay,
  isHr,
  mySeatId,
  paused,
}: ActionSidebarProps) {
  const showHand =
    isCandidate && (pub.phase === "play" || alreadyPlayed) && (effectiveHand.length > 0 || alreadyPlayed || pendingPlayIds)
  const showLines = isHr || Boolean(mySeatId)
  const inLines = pub.phase === "lines"
  const linesVisible =
    (isHr && inLines) ||
    (Boolean(mySeatId) &&
      !isHr &&
      inLines &&
      Boolean(pub.question_chip) &&
      !pub.stamps_this_slot?.[mySeatId ?? ""] &&
      !pub.answers?.[mySeatId ?? ""])

  return (
    <aside
      className={`mp-action-sidebar mp-glass-panel flex min-h-0 flex-col p-3 ${paused ? "pointer-events-none opacity-50" : ""}`}
      aria-disabled={paused || undefined}
    >
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto overscroll-contain">
        {showHand ? (
          <CandidateHand
            hand={effectiveHand}
            cardsToPlay={cardsToPlay}
            alreadyPlayed={alreadyPlayed}
            canPlay={pub.phase === "play" && !alreadyPlayed}
            submitting={pendingPlayIds}
            errorText={playError}
            onPlay={onPlay}
            vertical
          />
        ) : null}

        {showLines && linesVisible ? (
          <LinesPanel
            pub={pub}
            isHr={isHr}
            mySeatId={isCandidate ? mySeatId : null}
            onIntent={onIntent}
            vertical
          />
        ) : null}

        <ActionBar
          pub={pub}
          role={role}
          focusSeat={focusSeat}
          focusStamped={focusStamped}
          energy={energy}
          offerAllowed={offerAllowed}
          marks={marks}
          claimFiled={claimFiled}
          pendingIntentType={pendingIntentType}
          errorText={errorText}
          onIntent={onIntent}
          onStamp={onStamp}
          vertical
        />
      </div>
    </aside>
  )
}
