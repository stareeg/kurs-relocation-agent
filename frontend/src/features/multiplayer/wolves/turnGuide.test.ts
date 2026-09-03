import { describe, expect, it } from "vitest"
import { turnGuide } from "./turnGuide"

describe("turnGuide", () => {
  it("хрюше в штампе считает, сколько кандидатов осталось", () => {
    const g = turnGuide({ phase: "stamp", role: "hr", toStamp: 2 })
    expect(g).toEqual({ text: "Штампуй кандидатов — осталось 2", waiting: false })
  })

  it("хрюша ждёт, когда штамповать больше некого", () => {
    expect(turnGuide({ phase: "stamp", role: "hr", toStamp: 0 }).waiting).toBe(true)
  })

  it("кандидату в play говорит выложить карты, а после выкладки — ждать", () => {
    expect(turnGuide({ phase: "play", role: "candidate", cardsToPlay: 2 })).toEqual({
      text: "Выложи 2 карты опыта",
      waiting: false,
    })
    expect(turnGuide({ phase: "play", role: "candidate", iPlayed: true }).waiting).toBe(true)
  })

  it("кандидат в lines: сперва ждёт вопрос, потом отвечает, потом ждёт", () => {
    expect(turnGuide({ phase: "lines", role: "candidate", questionAsked: false }).waiting).toBe(
      true,
    )
    expect(
      turnGuide({ phase: "lines", role: "candidate", questionAsked: true }).waiting,
    ).toBe(false)
    expect(
      turnGuide({ phase: "lines", role: "candidate", questionAsked: true, iAnswered: true })
        .waiting,
    ).toBe(true)
  })

  it("хрюша в play видит прогресс подачи карт", () => {
    expect(
      turnGuide({ phase: "play", role: "hr", playedCount: 1, candidateCount: 3 }).text,
    ).toBe("Ждёшь карты кандидатов — выложили 1 из 3")
  })

  it("зритель между слотами может сесть вместо бота", () => {
    expect(turnGuide({ phase: "between", role: "spectator", canSit: true }).waiting).toBe(false)
    expect(turnGuide({ phase: "between", role: "spectator", canSit: false }).waiting).toBe(true)
  })

  it("иск подан — хрюше остаётся дойти до суда, а не собирать улики", () => {
    expect(turnGuide({ phase: "inspect", role: "hr", claimFiled: true }).text).toBe(
      "Иск подан — жми «К суду»",
    )
  })
})
