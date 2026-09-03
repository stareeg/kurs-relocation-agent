import { describe, expect, it } from "vitest"
import { buildWhatNextGuidance, screenLabel } from "./what-next"

const base = {
  activeJobsCount: 0,
  activeChatsCount: 0,
  offersCount: 0,
  resumeReady: true,
  hasOpenRouterKey: true,
}

describe("buildWhatNextGuidance", () => {
  it("без ключа — следующий шаг про OpenRouter", () => {
    const g = buildWhatNextGuidance({
      ...base,
      pathname: "/jobs",
      hasOpenRouterKey: false,
      resumeReady: false,
    })
    expect(g.last.title).toContain("Вакансии")
    expect(g.next.title).toMatch(/OpenRouter|ключ/i)
    expect(g.next.href).toBe("/settings")
  })

  it("ключ есть, резюме слабое — про критерии", () => {
    const g = buildWhatNextGuidance({
      ...base,
      pathname: "/jobs",
      resumeReady: false,
    })
    expect(g.next.title).toMatch(/критерии/i)
    expect(g.next.href).toBe("/resume")
  })

  it("всё готово, 0 вакансий — про расширение", () => {
    const g = buildWhatNextGuidance({
      ...base,
      pathname: "/chat",
      activeJobsCount: 0,
    })
    expect(g.next.title).toMatch(/расширен/i)
    expect(g.next.href).toBe("/extension")
  })

  it("экран офферов пуст — занести оффер", () => {
    const g = buildWhatNextGuidance({
      ...base,
      pathname: "/offers",
      activeJobsCount: 5,
      offersCount: 0,
    })
    expect(g.last.title).toContain("Офферы")
    expect(g.next.title).toMatch(/оффер/i)
  })

  it("карточка вакансии — last про карточку, next про площадку", () => {
    const g = buildWhatNextGuidance({
      ...base,
      pathname: "/jobs/abc-123",
      activeJobsCount: 5,
    })
    expect(g.last.title).toMatch(/карточк/i)
    expect(g.next.body.length).toBeGreaterThan(20)
  })

  it("не упоминает «Сегодня» и срочные дела", () => {
    const g = buildWhatNextGuidance({
      ...base,
      pathname: "/market",
      activeJobsCount: 12,
    })
    const blob = `${g.last.title} ${g.last.body} ${g.next.title} ${g.next.body}`
    expect(blob.toLowerCase()).not.toMatch(/сегодня|срочн/)
  })
})

describe("screenLabel", () => {
  it("режет вложенный путь вакансии", () => {
    expect(screenLabel("/jobs/abc")).toBe("Вакансии")
  })
})
