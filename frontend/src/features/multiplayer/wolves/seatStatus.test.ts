import { describe, expect, it } from "vitest"
import { isSeatActiveTurn, seatStatusLabel } from "./seatStatus"
import type { WolvesWsPublicState, WolvesWsSeat } from "./wolves-ws"

function seat(over: Partial<WolvesWsSeat> = {}): WolvesWsSeat {
  return {
    id: "c0",
    kind: "candidate",
    public_status: "waiting",
    filled: true,
    is_bot: true,
    played: [],
    ...over,
  }
}

function pub(over: Partial<WolvesWsPublicState> = {}): WolvesWsPublicState {
  return {
    phase: "play",
    slot_index: 0,
    slot_count: 5,
    seats: [seat()],
    ...over,
  }
}

describe("seatStatus", () => {
  it("seatStatusLabel — штамп важнее public_status", () => {
    expect(seatStatusLabel("waiting", { stamped: "offer" })).toBe("оффер")
    expect(seatStatusLabel("interview", { stamped: "probe" })).toBe("проверка")
  })

  it("isSeatActiveTurn — play без карты", () => {
    const s = seat({ played: [] })
    expect(isSeatActiveTurn(s, pub({ phase: "play" }), false)).toBe(true)
    expect(
      isSeatActiveTurn(seat({ played: [{ id: "1", tag: "soft", title: "x" }] }), pub(), false),
    ).toBe(false)
  })
})
