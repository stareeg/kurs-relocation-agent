/**
 * Клиент стола «Хрюши и Волки» — только то, что про эту игру (Э17.7).
 *
 * Транспорт, reconnect, heartbeat, seat_token и разбор служебных кадров — в generic
 * `net/GameRoomSocket`. Здесь остаются формы состояния и словарь ошибок: техническое
 * `detail` от сервера игрок должен читать на языке своего стола.
 */

import {
  GameRoomSocket,
  type GameRoomSeed,
  type GameRoomSnapshot,
  loadSeatToken as loadToken,
  saveSeatToken as saveToken,
} from "@/features/multiplayer/net/GameRoomSocket"

/** Ключи столов этой игры в sessionStorage. */
const STORAGE_PREFIX = "mp_wolves_seat_"

export type WolvesPlayedCard = {
  id: string
  tag: string
  title: string
}

export type WolvesWsSeat = {
  id: string
  kind: string
  public_status: string
  filled: boolean
  is_bot: boolean
  account_id?: number | null
  /** Ник за столом (@telegram или введённый) — не ФИО. */
  nick?: string | null
  faction?: string
  played?: WolvesPlayedCard[]
  revealed_as_wolf?: boolean
  lifetime_stamps?: string[]
}

export type WolvesWsPublicState = {
  phase: string
  slot_index: number
  slot_count: number
  hr_energy?: number
  citations?: number
  citations_limit?: number
  hr_energy_max?: number
  bulletin?: {
    day_label: string
    gates: string[]
    offer_allowed: boolean
    cards_to_play: number
    face_up?: boolean
    required_tag?: string | null
  } | null
  event?: { label: string; kind: string } | null
  winner?: string | null
  winner_line?: string | null
  seats?: WolvesWsSeat[]
  focus_candidate_id?: string | null
  discrepancy_marks?: string[]
  pending_judge?: boolean
  stamps_this_slot?: Record<string, string>
  question_chip?: string | null
  answers?: Record<string, string>
  judge_line?: string | null
  /** id улики из иска, на которую сослался судья (сверен движком, не сырой ответ модели). */
  judge_marker?: string | null
  slot_ticker?: string | null
  /** Одна строка режиссёра про сегодняшний день кабинета (Э19.8). */
  slot_brief?: string | null
  /** Кандидат → что он сказал вслед своему штампу. */
  stamp_reactions?: Record<string, string>
  /**
   * Реплики, которые печатаются прямо сейчас: место → текст, накопленный стримом.
   * Приходит не в состоянии, а кадрами `line_delta`; в `answers` попадает уже готовая фраза.
   */
  live_lines?: Record<string, string>
}

export type WolvesWsPrivateState = {
  engine_seat_id: string | null
  hand: Array<{ id: string; tag: string; title: string }>
  faction: string | null
  sub_role: string | null
  pack_mates: string[]
}

export type WolvesWsSnapshot = GameRoomSnapshot<WolvesWsPublicState, WolvesWsPrivateState>

export type WolvesSocketSeed = GameRoomSeed

function humanizeWsError(detail: string): string {
  const d = detail.toLowerCase()
  if (!detail) return "Не вышло. Попробуйте ещё раз."
  if (d.includes("full") || d.includes("полн")) {
    return "Все люди заняли слоты — вы зритель, сядьте вместо бота."
  }
  if (d.includes("not found") || d.includes("не найден") || d.includes("closed")) {
    return "Стол уже закрыт или кода нет."
  }
  if (d.includes("паузе") || d.includes("pause")) {
    return "Стол на паузе — нажми «Продолжить»."
  }
  if (d.includes("phase") || d.includes("фаза")) {
    return "Сейчас нельзя: не та фаза."
  }
  if (d.includes("host") || d.includes("хост")) {
    return "Только хост может это сделать."
  }
  if (d.includes("seat") || d.includes("слот")) {
    return "Слот недоступен — возьмите бота или ждите передышку."
  }
  if (d.includes("auth") || d.includes("401") || d.includes("вход")) {
    return "Сессия истекла — обновите страницу и войдите снова."
  }
  return detail.length > 120 ? `${detail.slice(0, 117)}…` : detail
}

export function loadSeatToken(roomCode: string): string | null {
  return loadToken(STORAGE_PREFIX, roomCode)
}

export function saveSeatToken(roomCode: string, token: string) {
  saveToken(STORAGE_PREFIX, roomCode, token)
}

/**
 * Живые реплики поверх состояния: место, чья фраза уже доехала в `answers`, из «печатается»
 * убираем — иначе после применения ответа под ним ещё секунду висел бы его же черновик.
 */
export function mergeLiveLines(
  pub: WolvesWsPublicState,
  live: Record<string, string>,
): WolvesWsPublicState {
  const answers = pub.answers ?? {}
  const pending: Record<string, string> = {}
  for (const [seatId, text] of Object.entries(live)) {
    if (!text || answers[seatId]) continue
    pending[seatId] = text
  }
  return Object.keys(pending).length > 0 ? { ...pub, live_lines: pending } : pub
}

/** Стол «Хрюш и Волков»: generic-транспорт + формы и тексты этой игры. */
export class WolvesRoomSocket extends GameRoomSocket<WolvesWsPublicState, WolvesWsPrivateState> {
  /** Место → накопленный текст стрима. Живёт вне состояния: кадры идут между кадрами состояния. */
  private live: Record<string, string> = {}

  constructor(roomCode: string, seed: WolvesSocketSeed = {}) {
    super(roomCode, {
      ...seed,
      initialPublic: { phase: "lobby", slot_index: 0, slot_count: 5 },
      humanizeError: humanizeWsError,
      storagePrefix: STORAGE_PREFIX,
    })
  }

  protected override onGameFrame(msg: Record<string, unknown>): boolean {
    if (msg.type !== "line_delta") return false
    const seatId = String(msg.seat_id ?? "")
    const text = String(msg.text ?? "")
    if (!seatId) return true
    this.live = { ...this.live, [seatId]: text }
    this.setPublic(mergeLiveLines(this.snapshot.public, this.live))
    return true
  }

  protected override decoratePublic(pub: WolvesWsPublicState): WolvesWsPublicState {
    // Новый вопрос хрюши (или новый слот) — прошлые черновики больше не про эту сцену.
    if (pub.question_chip !== this.snapshot.public.question_chip) this.live = {}
    return mergeLiveLines(pub, this.live)
  }
}
