/** REST лобби «Хрюши и Волки». Типы зеркалят домен multiplayer. */

import { api } from "@/api/client"

export type RoomMode = "solo" | "friends"
export type RoomStatus = "open" | "playing" | "closed"
export type SeatKind = "hr" | "candidate" | "spectator"
export type JoinAs = "player" | "spectator"

export type RoomSeatView = {
  id: number
  seat_kind: SeatKind
  seat_index: number
  account_id: number | null
  role_public: string
  is_bot: boolean
  nick?: string | null
}

export type RoomSettings = {
  candidate_slots: number
  match_slots: number
  friends_only?: boolean
  /** ISO date of daily table (Э12); badge «День #N». */
  daily_day?: string | null
  /** account_id → nick за столом */
  nicks?: Record<string, string>
}

export type RoomOut = {
  id: number
  code: string
  name: string
  host_account_id: number
  status: RoomStatus
  mode: RoomMode
  has_pin: boolean
  phase_label: string
  seats_total: number
  seats_free: number
  seats_taken: number
  candidate_slots: number
  settings: RoomSettings
  seats: RoomSeatView[]
  my_seat_id: number | null
  my_seat_kind: SeatKind | null
}

export type CreateRoomBody = {
  name?: string
  slots?: number
  mode?: RoomMode
  pin?: string | null
  friends_only?: boolean
  daily?: boolean
  nick?: string
}

export type JoinRoomBody = {
  as?: JoinAs
  pin?: string | null
  nick?: string
}

/** Deep-link приглашения за стол (Э11). */
export function wolvesInviteUrl(code: string): string {
  const origin = typeof window !== "undefined" ? window.location.origin : ""
  return `${origin}/multiplayer?join=${encodeURIComponent(code.trim().toUpperCase())}`
}

/** GET /api/multiplayer/wolves/rooms — открытые столы. */
export function listWolvesRooms() {
  return api.get<RoomOut[]>("/api/multiplayer/wolves/rooms")
}

/** POST /api/multiplayer/wolves/rooms — создать стол. */
export function createWolvesRoom(body: CreateRoomBody) {
  return api.post<RoomOut>("/api/multiplayer/wolves/rooms", body)
}

/** GET /api/multiplayer/wolves/rooms/{code} */
export function fetchWolvesRoom(code: string) {
  return api.get<RoomOut>(`/api/multiplayer/wolves/rooms/${encodeURIComponent(code)}`)
}

/** POST /api/multiplayer/wolves/rooms/{code}/join */
export function joinWolvesRoom(code: string, body: JoinRoomBody = {}) {
  return api.post<RoomOut>(`/api/multiplayer/wolves/rooms/${encodeURIComponent(code)}/join`, body)
}

/** POST /api/multiplayer/wolves/rooms/{code}/close — хост завершает стол. */
export function closeWolvesRoom(code: string) {
  return api.post<RoomOut>(`/api/multiplayer/wolves/rooms/${encodeURIComponent(code)}/close`, {})
}
