import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react"
import { toast } from "sonner"
import { PhaseRail, type PhaseId } from "@/features/multiplayer/wolves/gfx"
import type { RoomOut } from "@/api/multiplayer"
import { ActionSidebar } from "./ActionSidebar"
import { Booth } from "./Booth"
import { CandidateTable } from "./CandidateTable"
import { EventsFeed } from "./EventsFeed"
import { GameButton } from "./GameButton"
import { GameHeader } from "./GameHeader"
import { PauseOverlay } from "./PauseOverlay"
import { RevealScreen } from "./RevealScreen"
import { Transcript } from "./Transcript"
import { seatName } from "./seatName"
import { useSlotOutcomes } from "./useSlotOutcomes"
import { turnGuide, type TurnRole } from "./turnGuide"
import {
  WolvesRoomSocket,
  type WolvesWsPublicState,
} from "./wolves-ws"

const PHASE_IDS: PhaseId[] = ["bulletin", "play", "inspect", "lines", "stamp", "judge", "result"]

function asPhaseId(phase: string): PhaseId {
  return (PHASE_IDS.includes(phase as PhaseId) ? phase : "bulletin") as PhaseId
}

type WolvesTableProps = {
  room: RoomOut
  onLeave: () => void
  onCloseRoom?: () => void
  closing?: boolean
  /** После создания стола сразу старт партии. */
  autoStart?: boolean
  /** @deprecated используйте autoStart */
  autoStartSolo?: boolean
}

/**
 * Живой стол: шапка с игровым контекстом, кабинка + боковая колонка действий,
 * внизу — стол кандидатов (карточки-слоты) и колода реплик. SIGame-inspired layout.
 */
export function WolvesTable({
  room,
  onLeave,
  onCloseRoom,
  closing,
  autoStart,
  autoStartSolo = false,
}: WolvesTableProps) {
  const shouldAutoStart = autoStart ?? autoStartSolo
  const [socket] = useState(() => {
    const isHr = room.my_seat_kind === "hr"
    let engineSeatId: string | null = null
    if (isHr) {
      engineSeatId = "hr"
    } else if (room.my_seat_kind === "candidate") {
      const seat = room.seats.find((s) => s.id === room.my_seat_id)
      if (seat) engineSeatId = `c${seat.seat_index}`
    }
    return new WolvesRoomSocket(room.code, {
      isHost: isHr,
      engineSeatId,
      isSpectator: room.my_seat_kind !== "hr" && room.my_seat_kind !== "candidate",
    })
  })
  const autoStarted = useRef(false)

  const snap = useSyncExternalStore(socket.subscribeStore, socket.getSnapshot)

  useEffect(() => {
    socket.connect()
    return () => socket.close()
  }, [socket])

  useEffect(() => {
    if (!shouldAutoStart || autoStarted.current) return
    if (snap?.isHost && snap.lobby && snap.connected) {
      autoStarted.current = true
      socket.startMatch()
    }
  }, [shouldAutoStart, snap?.isHost, snap?.lobby, snap?.connected, socket])

  useEffect(() => {
    const onVis = () => {
      if (document.visibilityState === "visible") socket.sync()
    }
    document.addEventListener("visibilitychange", onVis)
    return () => document.removeEventListener("visibilitychange", onVis)
  }, [socket])

  const rawPub = snap?.public
  const pause = snap?.pause ?? null
  const paused = Boolean(pause?.paused)
  const pendingIntent = snap?.pendingIntent?.intent ?? null
  const intentError = snap?.intentError ?? null

  // Оптимистичное эхо (Э19.5): пока свой интент не подтверждён, показываем его результат
  // локально — фокус, штамп, ушедшую из руки карту.
  const pendingType = typeof pendingIntent?.type === "string" ? pendingIntent.type : ""
  const pendingFocusId =
    pendingType === "focus_candidate" ? String(pendingIntent?.candidate_id ?? "") : ""
  const pendingStampId =
    pendingType === "stamp_candidate" ? String(pendingIntent?.candidate_id ?? "") : ""
  const pendingStampKind =
    pendingType === "stamp_candidate" ? String(pendingIntent?.stamp ?? "") : ""
  const filingDiscrepancy = pendingType === "mark_discrepancy"
  const pendingPlayIds = useMemo<string[] | null>(
    () =>
      pendingType === "play_cards" && Array.isArray(pendingIntent?.card_ids)
        ? (pendingIntent.card_ids as string[])
        : null,
    [pendingType, pendingIntent],
  )

  const pub: WolvesWsPublicState | undefined = useMemo(() => {
    if (!rawPub) return undefined
    if (!pendingFocusId && !pendingStampId && !pendingPlayIds) return rawPub
    return {
      ...rawPub,
      focus_candidate_id: pendingFocusId || rawPub.focus_candidate_id,
      stamps_this_slot: pendingStampId
        ? {
            ...(rawPub.stamps_this_slot ?? {}),
            [pendingStampId]: rawPub.stamps_this_slot?.[pendingStampId] ?? pendingStampKind,
          }
        : rawPub.stamps_this_slot,
    }
  }, [rawPub, pendingFocusId, pendingStampId, pendingStampKind, pendingPlayIds])

  // Отслеживание новых ответов кандидатов — показываем через toast
  const knownAnswersRef = useRef<Set<string>>(new Set())
  useEffect(() => {
    if (!pub?.answers) return
    const currentKeys = Object.keys(pub.answers)
    const newKeys = currentKeys.filter((k) => !knownAnswersRef.current.has(k))
    newKeys.forEach((seatId) => {
      const name = seatName(pub, seatId)
      const text = pub.answers?.[seatId]
      if (text) {
        toast(`${name}: ${text}`, { duration: 4000 })
      }
    })
    knownAnswersRef.current = new Set(currentKeys)
  }, [pub, pub?.answers])

  // Отслеживание live-реплик (живой ввод) — показываем через toast
  const knownLiveRef = useRef<Set<string>>(new Set())
  useEffect(() => {
    if (!pub?.live_lines) return
    const currentKeys = Object.keys(pub.live_lines)
    const newKeys = currentKeys.filter((k) => !knownLiveRef.current.has(k))
    newKeys.forEach((seatId) => {
      const name = seatName(pub, seatId)
      const text = pub.live_lines?.[seatId]
      if (text) {
        toast(`${name}: ${text}`, { duration: 3000 })
      }
    })
    knownLiveRef.current = new Set(currentKeys)
  }, [pub, pub?.live_lines])

  const slotOutcomes = useSlotOutcomes(pub)

  const phaseRaw = pub?.phase ?? "lobby"
  const atReveal = phaseRaw === "reveal" || phaseRaw === "ended"
  const inMatch = Boolean(snap && !snap.lobby && pub && phaseRaw !== "lobby")
  const phase = pub ? asPhaseId(pub.phase) : "bulletin"
  const isHr = snap?.engineSeatId === "hr"
  const mySeatId = snap?.engineSeatId ?? null
  const isSpectator = Boolean(snap?.isSpectator)
  const isCandidate = Boolean(mySeatId && mySeatId !== "hr" && !isSpectator)
  const isHostUi = Boolean(snap?.isHost) || room.my_seat_kind === "hr"
  const mySeat = (pub?.seats ?? []).find((s) => s.id === mySeatId)
  const alreadyPlayed = Boolean(mySeat?.played?.length) || Boolean(pendingPlayIds)
  const cardsToPlay = pub?.bulletin?.cards_to_play ?? 1
  const faceUp = pub?.bulletin?.face_up !== false
  const offerAllowed = pub?.bulletin?.offer_allowed !== false
  const canClaimEmpty =
    Boolean(snap?.isSpectator) && phaseRaw === "between" && Boolean(snap?.connected)
  const canClaimBot = Boolean(snap?.isSpectator) && Boolean(snap?.connected)

  const filledCandidates = (pub?.seats ?? []).filter((s) => s.kind === "candidate" && s.filled)
  const playedCount = filledCandidates.filter((s) => (s.played?.length ?? 0) > 0).length
  const stampedCount = Object.keys(pub?.stamps_this_slot ?? {}).length
  const toStamp = Math.max(0, filledCandidates.length - stampedCount)
  const focusId = pub?.focus_candidate_id ?? null
  const focusSeat = (pub?.seats ?? []).find((s) => s.id === focusId) ?? null
  const focusStamped = Boolean(focusId && pub?.stamps_this_slot?.[focusId])
  const energyMax = pub?.hr_energy_max ?? 5
  const energy = pub?.hr_energy ?? energyMax
  const claimFiled =
    Boolean(pub?.pending_judge) || filingDiscrepancy || (pub?.discrepancy_marks?.length ?? 0) >= 2
  const canInspect = isHr && phaseRaw === "inspect" && !claimFiled

  // Выбор несостыковок — состояние здесь (кабинка и панель действий обе на него смотрят).
   const [marks, setMarks] = useState<string[]>([])
   const [boothShake, setBoothShake] = useState(false)
   const serverMarksKey = (pub?.discrepancy_marks ?? []).join("\0")
  const [syncedMarks, setSyncedMarks] = useState({
    key: serverMarksKey,
    pending: Boolean(pub?.pending_judge),
    focusId,
    slot: pub?.slot_index,
  })
  if (
    syncedMarks.key !== serverMarksKey ||
    syncedMarks.pending !== Boolean(pub?.pending_judge) ||
    syncedMarks.focusId !== focusId ||
    syncedMarks.slot !== pub?.slot_index
  ) {
    setSyncedMarks({
      key: serverMarksKey,
      pending: Boolean(pub?.pending_judge),
      focusId,
      slot: pub?.slot_index,
    })
    if (pub?.discrepancy_marks && pub.discrepancy_marks.length > 0) {
      setMarks([...pub.discrepancy_marks])
    } else {
      setMarks([])
    }
  }
   const toggleMark = useCallback(
     (id: string) => {
       setMarks((prev) => {
         if (prev.includes(id)) return prev.filter((x) => x !== id)
         if (prev.length >= 2) return [prev[1]!, id]
         return [...prev, id]
       })
     },
     [],
   )

   const setBoothShakeRef = useRef(setBoothShake)
   useEffect(() => {
     setBoothShakeRef.current = setBoothShake
   }, [setBoothShake])
   const handleStamp = useCallback(() => {
     setBoothShakeRef.current(false)
     requestAnimationFrame(() => setBoothShakeRef.current(true))
   }, [])

  const iStamped = Boolean(mySeatId && pub?.stamps_this_slot?.[mySeatId])
  const iAnswered = Boolean(mySeatId && pub?.answers?.[mySeatId])
  const questionAsked = Boolean(pub?.question_chip)
  const turnRole: TurnRole = isHr ? "hr" : isCandidate ? "candidate" : "spectator"
  const guide =
    inMatch && !atReveal
      ? turnGuide({
          phase: phaseRaw,
          role: turnRole,
          playedCount,
          candidateCount: filledCandidates.length,
          cardsToPlay,
          toStamp,
          claimFiled,
          iPlayed: alreadyPlayed,
          iAnswered,
          iStamped,
          questionAsked,
          canSit: canClaimEmpty || canClaimBot,
        })
      : null

  const effectiveHand =
    pendingPlayIds && snap?.private
      ? snap.private.hand.filter((c) => !pendingPlayIds.includes(c.id))
      : (snap?.private?.hand ?? [])

  const packMates = isCandidate && snap?.private?.faction === "wolf" ? (snap.private.pack_mates ?? []) : []

  const focusCandidate = useCallback(
    (seatId: string) => socket.sendIntent({ type: "focus_candidate", candidate_id: seatId }),
    [socket],
  )
  const claimSeatById = useCallback((seatId: string) => socket.claimSeat(seatId), [socket])
  const sendIntent = useCallback(
    (intent: Record<string, unknown>) => socket.sendIntent(intent),
    [socket],
  )

  const copyInvite = useCallback(() => {
    const link = `${window.location.origin}/multiplayer?join=${room.code}`
    navigator.clipboard?.writeText(link).then(
      () => toast.success("Ссылка-приглашение скопирована"),
      () => toast.error("Не вышло скопировать — код стола: " + room.code),
    )
  }, [room.code])

  const connLabel = snap?.connected
    ? "на связи"
    : snap?.reconnecting
      ? "переподключение…"
      : "нет связи"
  const roleText = isHr
    ? "Ты хрюша"
    : isCandidate
      ? snap?.private?.faction === "wolf"
        ? "Ты волк"
        : snap?.private?.faction === "human"
          ? "Ты человек"
          : "Ты кандидат"
      : "Зритель"
  const roleGoal = isHr
    ? "не дай волкам оффер · 3 выговора = проигрыш"
    : isCandidate
      ? snap?.private?.faction === "wolf"
        ? "проскочи собес или доживи до конца"
        : "получи оффер, не попади под ложный отказ"
      : ""

  return (
    <div className="mp-game-stage flex flex-1 min-h-0 flex-col gap-2 p-2">
      {/* Комната: имя, код, связь, роль, управление столом. */}
      <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1.5 px-1">
        <span className="mp-display text-[length:var(--mp-text-base)] font-semibold text-white/95">
          {room.name}
        </span>
        <span className="mp-mono text-[length:var(--mp-text-xs)] text-white/45">код {room.code}</span>
        <span
          className={`mp-mono inline-flex items-center gap-1 text-[length:var(--mp-text-xs)] ${
            snap?.connected ? "text-white/45" : "text-[color:var(--mp-stamp)]"
          }`}
        >
          <span
            aria-hidden
            className={`inline-block size-2 rounded-full ${
              snap?.connected ? "bg-[color:var(--mp-chip-ok)]" : "bg-[color:var(--mp-stamp)]"
            }`}
          />
          {connLabel}
        </span>
        <span
          className="mp-mono rounded-md bg-white/10 px-2 py-0.5 text-[length:var(--mp-text-xs)] font-semibold uppercase tracking-wide text-white/80"
        >
          {roleText}
        </span>
        {roleGoal ? (
          <span className="mp-mono text-[length:var(--mp-text-xs)] text-white/50">
            · {roleGoal}
          </span>
        ) : null}

        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          {inMatch && pub ? (
            <PhaseRail
              current={phase}
              claimFiled={claimFiled}
              between={phaseRaw === "between"}
            />
          ) : null}
          {snap?.isHost && snap.lobby ? (
            <GameButton variant="primary" pulse className="!px-3 !py-1.5 !text-xs" onClick={() => socket.startMatch()}>
              Старт
            </GameButton>
          ) : null}
          {inMatch && !atReveal ? (
            paused ? (
              <GameButton
                variant="glass"
                disabled={Boolean(pause?.resumingAt)}
                className="!px-3 !py-1.5 !text-xs"
                onClick={() => socket.resumeMatch()}
              >
                {pause?.resumingAt ? "…" : "▶ Пауза"}
              </GameButton>
            ) : (
              <GameButton variant="glass" className="!px-3 !py-1.5 !text-xs" onClick={() => socket.pauseMatch()}>
                ⏸ Пауза
              </GameButton>
            )
          ) : null}
          {inMatch ? (
            <GameButton variant="glass" className="!px-3 !py-1.5 !text-xs" onClick={copyInvite}>
              + Пригласить
            </GameButton>
          ) : null}
          {!snap?.connected ? (
            <GameButton variant="glass" className="!px-3 !py-1.5 !text-xs" onClick={() => socket.reconnectNow()}>
              ↻ Обновить
            </GameButton>
          ) : null}
          <GameButton variant="glass" className="!px-3 !py-1.5 !text-xs" onClick={onLeave}>
            ← В лобби
          </GameButton>
          {isHostUi ? (
            <GameButton
              variant="reject"
              disabled={closing}
              className="!px-3 !py-1.5 !text-xs"
              onClick={onCloseRoom}
            >
              ✕ Закрыть
            </GameButton>
          ) : null}
        </div>
      </div>

      {snap?.lastError && !inMatch ? (
        <div className="shrink-0 rounded-md border border-[color:var(--mp-stamp)]/40 bg-[color:var(--mp-stamp)]/5 px-3 py-2">
          <p className="text-sm text-[color:var(--mp-stamp)]">{snap.lastError}</p>
        </div>
      ) : null}

      {inMatch && pub && atReveal ? (
        <div className="min-h-0 flex-1 overflow-y-auto">
          <RevealScreen
            pub={pub}
            isHost={Boolean(snap?.isHost)}
            onRematch={() => socket.startMatch()}
            onLobby={onLeave}
          />
        </div>
      ) : null}

      {inMatch && pub && !atReveal ? (
        <div className="mp-game-body relative min-h-0 flex-1">
          <GameHeader
            packMatesLabel={
              packMates.length > 0
                ? `стая: ${packMates.map((id) => seatName(pub, id)).join(", ")}`
                : undefined
            }
            slotIndex={pub.slot_index}
            slotCount={pub.slot_count}
            phase={phase}
            phaseRaw={phaseRaw}
            eventLabel={pub.event?.label ?? null}
            slotTicker={pub.slot_ticker}
            slotOutcomes={slotOutcomes}
            guide={guide}
            paused={paused}
            socket={socket}
          />

          <div className="flex min-h-0 flex-col gap-2 lg:contents">
            <div className="mp-booth-col min-h-0">
              <Booth
                pub={pub}
                isHr={Boolean(isHr)}
                canInspect={canInspect}
                marks={marks}
                onToggleMark={toggleMark}
                focusSeat={focusSeat}
                shaking={boothShake}
                onShakeEnd={() => setBoothShake(false)}
              />
            </div>

            <div className="mp-center-col hidden min-h-0 lg:block" aria-hidden />

            <div className="mp-right-col min-h-0">
              <ActionSidebar
                pub={pub}
                role={turnRole}
                focusSeat={focusSeat}
                focusStamped={focusStamped}
                energy={energy}
                offerAllowed={offerAllowed}
                marks={marks}
                claimFiled={claimFiled}
                pendingIntentType={pendingType}
                errorText={
                  intentError && intentError.intent.type !== "play_cards"
                    ? intentError.message
                    : null
                }
                onIntent={sendIntent}
                onStamp={handleStamp}
                isCandidate={isCandidate}
                effectiveHand={effectiveHand}
                cardsToPlay={cardsToPlay}
                alreadyPlayed={alreadyPlayed}
                pendingPlayIds={Boolean(pendingPlayIds)}
                playError={
                  intentError?.intent.type === "play_cards" ? intentError.message : null
                }
                onPlay={(cardIds) => socket.sendIntent({ type: "play_cards", card_ids: cardIds })}
                isHr={Boolean(isHr)}
                mySeatId={isCandidate ? mySeatId : null}
                paused={paused}
              />
              <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain">
                <EventsFeed
                  pub={pub}
                  eventLabel={pub?.event?.label ?? null}
                  slotTicker={pub?.slot_ticker}
                />
                <Transcript pub={pub} />
              </div>
            </div>

            <CandidateTable
              pub={pub}
              isHost={Boolean(snap.isHost)}
              isHr={Boolean(isHr)}
              faceUp={faceUp}
              cardsToPlay={cardsToPlay}
              canClaimEmpty={canClaimEmpty}
              canClaimBot={canClaimBot}
              onFocus={focusCandidate}
              onClaim={claimSeatById}
              onKick={(seatId) => socket.hostAction("kick", { seatId })}
              onFillBot={(seatId) => socket.hostAction("fill_bot", { seatId })}
              onAddSlot={snap.isHost ? () => socket.hostAction("add_slot") : undefined}
            />
          </div>

          {paused ? <PauseOverlay by={pause?.by} resumingAt={pause?.resumingAt ?? null} /> : null}
        </div>
      ) : null}

      {!inMatch && !atReveal ? (
        <p className="shrink-0 px-1 text-[length:var(--mp-text-sm)] text-white/60">
          {isHostUi
            ? snap?.connected
              ? "Ждём игроков. Нажмите «Начать партию», когда готовы — или стол стартует сам."
              : "Подключаемся к столу…"
            : snap?.connected
              ? "Ожидание старта от хоста…"
              : "Подключаемся к столу…"}
        </p>
      ) : null}
    </div>
  )
}
