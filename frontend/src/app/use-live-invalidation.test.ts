import { readFileSync } from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"
import { allTrackedKeyPrefixes, EVENT_QUERY_KEYS } from "./use-live-invalidation"
import type { LiveEventPayload } from "@/api/live-events"

// F-04: эталон — FIRST_ORDER_EVENTS в core/kernel/events.py. Хардкод зеркала в тесте не держим,
// список типов вытаскиваем из исходника — рассинхрон (добавили/убрали событие на бэке) ловится
// здесь, а не тишиной в проде.
const EVENTS_PY = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../../core/kernel/events.py",
)
const eventsPySource = readFileSync(EVENTS_PY, "utf-8")

function firstOrderEventNames(source: string): string[] {
  const tupleMatch = source.match(
    /FIRST_ORDER_EVENTS:\s*tuple\[type\[DomainEvent\],\s*\.\.\.\]\s*=\s*\(([\s\S]*?)\)/,
  )
  if (!tupleMatch) throw new Error("FIRST_ORDER_EVENTS не найден в core/kernel/events.py")
  return tupleMatch[1]
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
}

const CANON_FIRST_ORDER_EVENTS = firstOrderEventNames(eventsPySource)

describe("EVENT_QUERY_KEYS покрывает FIRST_ORDER_EVENTS (F-04)", () => {
  it("нашёл события в каноне (список не пуст)", () => {
    expect(CANON_FIRST_ORDER_EVENTS.length).toBeGreaterThan(0)
  })

  for (const eventType of CANON_FIRST_ORDER_EVENTS) {
    it(`есть запись для ${eventType}`, () => {
      expect(EVENT_QUERY_KEYS[eventType]).toBeTypeOf("function")
    })
  }

  it("в карте нет лишних типов сверх канона", () => {
    expect(Object.keys(EVENT_QUERY_KEYS).sort()).toEqual([...CANON_FIRST_ORDER_EVENTS].sort())
  })
})

describe("ScreeningPackReady → screening-questions по subject", () => {
  it("subject есть — инвалидирует конкретную вакансию, не весь раздел", () => {
    const payload: LiveEventPayload = { type: "ScreeningPackReady", subject: "vac-1" }
    expect(EVENT_QUERY_KEYS.ScreeningPackReady(payload)).toEqual([["screening-questions", "vac-1"]])
  })

  it("без subject ничего не инвалидирует (не раздел целиком)", () => {
    const payload: LiveEventPayload = { type: "ScreeningPackReady" }
    expect(EVENT_QUERY_KEYS.ScreeningPackReady(payload)).toEqual([])
  })
})

describe("allTrackedKeyPrefixes (F-05): полный рефреш на реконнект", () => {
  it("покрывает префикс каждого ключа из карты, без дублей", () => {
    const prefixes = allTrackedKeyPrefixes().map((k) => k[0])
    expect(new Set(prefixes).size).toBe(prefixes.length)
    expect(prefixes).toEqual(
      expect.arrayContaining([
        "jobs",
        "vacancy-events",
        "market-pulse",
        "market-search",
        "market-calibration",
        "market-money",
        "market-chance-history",
        "companies",
        "resume",
        "screening-questions",
        "prep",
        "debrief",
        "interview-stages",
      ]),
    )
  })
})

describe("рынок: VacancyScored / ResumeUpdated инвалидируют срезы F-04", () => {
  it("VacancyScored покрывает analytics-ключи раздела", () => {
    const keys = EVENT_QUERY_KEYS.VacancyScored({ type: "VacancyScored" }).map((k) => k[0])
    expect(keys).toEqual(
      expect.arrayContaining([
        "market-pulse",
        "market-search",
        "market-calibration",
        "market-money",
        "market-chance-history",
        "companies",
      ]),
    )
  })

  it("ResumeUpdated освежает money и companies (профиль / списки), не search", () => {
    const keys = EVENT_QUERY_KEYS.ResumeUpdated({ type: "ResumeUpdated" }).map((k) => k[0])
    expect(keys).toEqual(expect.arrayContaining(["market-pulse", "market-money", "companies"]))
    expect(keys).not.toContain("market-search")
  })
})

describe("SearchModeChanged → career/search-mode (ST-01)", () => {
  it("инвалидирует ключ пилюлей режима", () => {
    expect(EVENT_QUERY_KEYS.SearchModeChanged({ type: "SearchModeChanged" })).toEqual([
      ["career", "search-mode"],
    ])
  })
})

describe("SearchTrackChanged → career/search-track (Э1)", () => {
  it("инвалидирует ключ тумблера и международный профиль", () => {
    expect(EVENT_QUERY_KEYS.SearchTrackChanged({ type: "SearchTrackChanged" })).toEqual([
      ["career", "search-track"],
      ["resume", "international"],
    ])
  })
})

describe("InterviewDebriefed → prep/debrief/interview-stages/events по subject", () => {
  it("subject есть — инвалидирует ключи конкретной вакансии", () => {
    const payload: LiveEventPayload = { type: "InterviewDebriefed", subject: "vac-2" }
    expect(EVENT_QUERY_KEYS.InterviewDebriefed(payload)).toEqual([
      ["prep", "vac-2"],
      ["debrief", "vac-2"],
      ["interview-stages", "vac-2"],
      ["vacancy-events", "vac-2"],
    ])
  })

  it("без subject ничего не инвалидирует (не раздел целиком)", () => {
    const payload: LiveEventPayload = { type: "InterviewDebriefed" }
    expect(EVENT_QUERY_KEYS.InterviewDebriefed(payload)).toEqual([])
  })
})
