import type { WolvesWsPublicState, WolvesWsSeat } from "./wolves-ws"

/** Короткая подпись публичного статуса места — на карточке и в колоде реплик. */
export function seatStatusLabel(
  status: string,
  opts?: { stamped?: string | null; phase?: string },
): string | null {
  const stamp = opts?.stamped
  if (stamp === "probe") return "проверка"
  if (stamp === "reject") return "отказ"
  if (stamp === "interview") return "собес"
  if (stamp === "offer") return "оффер"

  if (status === "interview") return "собес"
  if (status === "rejected") return "отказ"
  if (status === "ghosted") return "тишина"
  if (status === "offer") return "оффер"
  if (status === "waiting") {
    if (opts?.phase === "play") return "ждёт карту"
    if (opts?.phase === "lines") return "ждёт вопрос"
    return "ждёт"
  }
  return null
}

/** Кого подсветить как «сейчас действует» — чья очередь в текущей фазе. */
export function isSeatActiveTurn(
  seat: WolvesWsSeat,
  pub: WolvesWsPublicState,
  isHr: boolean,
): boolean {
  if (!seat.filled || seat.kind !== "candidate") return false
  const phase = pub.phase
  const played = (seat.played?.length ?? 0) > 0
  const answered = Boolean(pub.answers?.[seat.id])
  const stamped = Boolean(pub.stamps_this_slot?.[seat.id])
  const live = Boolean(pub.live_lines?.[seat.id])

  if (phase === "play") return !played
  if (phase === "lines") {
    if (!pub.question_chip) return false
    return !answered && !stamped && !live
  }
  if (phase === "stamp" && isHr) {
    if (stamped) return false
    const focus = pub.focus_candidate_id
    if (focus) return seat.id === focus
    return true
  }
  return false
}
