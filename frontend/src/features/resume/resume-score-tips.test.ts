import { describe, expect, it } from "vitest"
import {
  formatWritingTip,
  normalizeScoreTip,
  roleFitTipsFromScore,
  writingTipsFromScore,
} from "./resume-score-tips"

describe("normalizeScoreTip", () => {
  it("убирает slop-префиксы", () => {
    expect(normalizeScoreTip("Слабый: нет метрик")).toBe("добавьте метрики")
  })
})

describe("formatWritingTip", () => {
  it("одна строка с местом и цитатой", () => {
    const line = formatWritingTip("Сбер — Lead", "Занимался развитием", "нет результата")
    expect(line).toContain("Сбер — Lead")
    expect(line).toContain("«Занимался развитием»")
    expect(line).toContain("добавьте результат")
  })
})

describe("writingTipsFromScore", () => {
  it("берёт weak_bullets", () => {
    const tips = writingTipsFromScore({
      total: 50,
      structure: 80,
      market_coverage: null,
      writing: 40,
      role_fit: 50,
      weak_bullets: [{ section: "about", ref: "Обо мне", text: "Общие слова", reason: "нет действия" }],
    })
    expect(tips).toHaveLength(1)
    expect(tips[0]).toContain("Обо мне")
  })
})

describe("roleFitTipsFromScore", () => {
  it("нормализует notes", () => {
    const tips = roleFitTipsFromScore({
      total: 50,
      structure: 80,
      market_coverage: null,
      writing: 60,
      role_fit: 40,
      role_fit_notes: ["Рекомендуется добавить LLM в навыки"],
    })
    expect(tips[0]).toBe("добавить LLM в навыки")
  })
})
