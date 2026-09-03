import { describe, expect, it } from "vitest"
import { formatEventLabel, formatVacancyEventAt } from "./format"

describe("formatEventLabel", () => {
  it("день недели + ДД.ММ + время по Москве", () => {
    // Понедельник 13.07.2026 15:00 МСК
    expect(formatEventLabel("2026-07-13T15:00:00+03:00")).toBe("пн 13.07 15:00")
  })

  it("не сдвигает день при UTC-сериализации того же инстанта", () => {
    // 15:00 МСК = 12:00Z — weekday всё ещё понедельник в MSK
    expect(formatEventLabel("2026-07-13T12:00:00.000Z")).toBe("пн 13.07 15:00")
  })

  it("пустая / битая строка → пусто", () => {
    expect(formatEventLabel(null)).toBe("")
    expect(formatEventLabel("")).toBe("")
    expect(formatEventLabel("not-a-date")).toBe("")
  })
})

describe("formatVacancyEventAt", () => {
  it("DD:MM HH:MM по Москве", () => {
    expect(formatVacancyEventAt("2026-08-25T14:30:00+03:00")).toBe("25:08 14:30")
  })

  it("не сдвигает день при UTC-сериализации того же инстанта", () => {
    expect(formatVacancyEventAt("2026-08-25T11:30:00.000Z")).toBe("25:08 14:30")
  })

  it("пустая / битая строка → пусто", () => {
    expect(formatVacancyEventAt(null)).toBe("")
    expect(formatVacancyEventAt("")).toBe("")
    expect(formatVacancyEventAt("not-a-date")).toBe("")
  })
})
