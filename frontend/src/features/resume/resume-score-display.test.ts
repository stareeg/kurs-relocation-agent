import { describe, expect, it } from "vitest"
import {
  availableSubscaleCount,
  formatSubscaleScore,
  subscaleContribution,
  subscaleWeight,
} from "./resume-score-display"

describe("subscaleWeight", () => {
  it("4 шкалы делят итог поровну", () => {
    expect(subscaleWeight(4)).toBe(25)
  })

  it("без рынка три шкалы делят итог", () => {
    expect(subscaleWeight(3)).toBe(33)
  })
})

describe("availableSubscaleCount", () => {
  it("считает рынок, только если он не null", () => {
    expect(
      availableSubscaleCount({
        structure: 100,
        market_coverage: 80,
        writing: 60,
        role_fit: 40,
      }),
    ).toBe(4)
    expect(
      availableSubscaleCount({
        structure: 100,
        market_coverage: null,
        writing: 60,
        role_fit: 40,
      }),
    ).toBe(3)
  })
})

describe("subscaleContribution", () => {
  it("84 из 100 при весе 25 → 21", () => {
    expect(subscaleContribution(84, 25)).toBe(21)
  })

  it("полная шкала даёт весь вес", () => {
    expect(subscaleContribution(100, 25)).toBe(25)
    expect(subscaleContribution(100, 33)).toBe(33)
  })
})

describe("formatSubscaleScore", () => {
  it("формат как у навыков: 21/25", () => {
    expect(formatSubscaleScore(84, 25)).toBe("21/25")
  })
})
