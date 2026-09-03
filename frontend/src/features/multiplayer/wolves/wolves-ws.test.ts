import { describe, expect, it } from "vitest"
import { mergeLiveLines, type WolvesWsPublicState } from "./wolves-ws"

const base: WolvesWsPublicState = { phase: "lines", slot_index: 0, slot_count: 5 }

describe("mergeLiveLines", () => {
  it("показывает реплики, которые ещё печатаются", () => {
    const out = mergeLiveLines(base, { c0: "Уронил прод в пят" })
    expect(out.live_lines).toEqual({ c0: "Уронил прод в пят" })
  })

  it("убирает черновик места, чей ответ уже доехал в состоянии", () => {
    // Иначе под применённой репликой ещё секунду висел бы её же незаконченный текст.
    const pub = { ...base, answers: { c0: "Уронил прод в пятницу." } }
    const out = mergeLiveLines(pub, { c0: "Уронил прод в пят", c1: "Кафку в проде" })
    expect(out.live_lines).toEqual({ c1: "Кафку в проде" })
  })

  it("не трогает состояние, когда печатать нечего", () => {
    const pub = { ...base, answers: { c0: "Готово." } }
    expect(mergeLiveLines(pub, { c0: "Гото" })).toBe(pub)
    expect(mergeLiveLines(pub, {})).toBe(pub)
  })
})
