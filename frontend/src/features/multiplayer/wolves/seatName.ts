import type { WolvesWsPublicState, WolvesWsSeat } from "./wolves-ws"

/**
 * Э30.7: за столом игрока зовут ником, а не машинным `c0`. В игре про то, кто врёт, читать
 * «c3 сказал» вместо «Костя сказал» — прямая потеря смысла. Запасной вариант — сам id.
 */
export function seatName(pub: WolvesWsPublicState, seatId: string): string {
  const seat = (pub.seats ?? []).find((s) => s.id === seatId)
  return seatLabelFor(seat, seatId)
}

export function seatLabelFor(seat: WolvesWsSeat | undefined, fallbackId?: string): string {
  const id = seat?.id ?? fallbackId ?? "?"
  if (seat?.nick && seat.nick.trim()) return seat.nick.trim()
  if (seat?.is_bot) return `${id} · бот`
  return id
}
