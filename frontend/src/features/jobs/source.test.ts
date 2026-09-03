import { describe, expect, it } from "vitest"
import type { Job } from "@/api/jobs"
import {
  countJobsBySourceGroup,
  extractSourceGroupsFromText,
  jobSourceGroup,
  listingLinkLabel,
  resolveJobListingUrl,
  resolveSourceGroup,
  sourceFilterEligible,
} from "./source"

function job(p: Partial<Job>): Job {
  return { vacancy_text: "x", ...p } as Job
}

describe("resolveSourceGroup", () => {
  it("маппит канон source", () => {
    expect(resolveSourceGroup("hh_negotiations")).toBe("hh")
    expect(resolveSourceGroup("getmatch")).toBe("getmatch")
    expect(resolveSourceGroup("habr")).toBe("habr")
    expect(resolveSourceGroup("telegram_channel")).toBe("telegram")
  })
  it("фолбэк по vacancy_id", () => {
    expect(resolveSourceGroup(null, "gm_34716")).toBe("getmatch")
    expect(resolveSourceGroup(null, "12345")).toBe("hh")
    expect(resolveSourceGroup(null, "habr_1000164602")).toBe("habr")
    expect(resolveSourceGroup(null, "tg_1_2")).toBe("telegram")
  })
})

describe("resolveJobListingUrl", () => {
  it("job.url приоритетнее", () => {
    expect(resolveJobListingUrl(job({ url: "https://custom.example/v", vacancy_id: "123" }))).toBe(
      "https://custom.example/v",
    )
  })
  it("строит getmatch, habr и hh из id", () => {
    expect(resolveJobListingUrl(job({ vacancy_id: "gm_34716" }))).toBe(
      "https://getmatch.ru/vacancies/34716",
    )
    expect(resolveJobListingUrl(job({ vacancy_id: "habr_1000164602" }))).toBe(
      "https://career.habr.com/vacancies/1000164602",
    )
    expect(resolveJobListingUrl(job({ vacancy_id: "99887766" }))).toBe(
      "https://hh.ru/vacancy/99887766",
    )
  })
  it("возвращает null для tg_* (нет каноничного URL)", () => {
    expect(resolveJobListingUrl(job({ vacancy_id: "tg_1_2" }))).toBeNull()
    expect(resolveJobListingUrl(job({ vacancy_id: "tg_abc" }))).toBeNull()
  })
  it("возвращает null для пустого и неизвестного vacancy_id", () => {
    expect(resolveJobListingUrl(job({ vacancy_id: "" }))).toBeNull()
    expect(resolveJobListingUrl(job({ vacancy_id: "   " }))).toBeNull()
    expect(resolveJobListingUrl(job({}))).toBeNull()
  })
  it("возвращает null для getmatch-id без numeric (бот-айди gm_{digest})", () => {
    // gm_abc — не gm_\d+, каноничный URL не строится (B1/GM-9).
    expect(resolveJobListingUrl(job({ vacancy_id: "gm_abc" }))).toBeNull()
    expect(resolveJobListingUrl(job({ vacancy_id: "gm_123_456" }))).toBeNull()
  })
})

describe("sourceFilterEligible", () => {
  it("false при одной группе", () => {
    const jobs = Array.from({ length: 6 }, (_, i) => job({ id: i, source: "vacancy_page" }))
    expect(sourceFilterEligible(jobs)).toBe(false)
  })
  it("true при двух группах с ≥5", () => {
    const jobs = [
      ...Array.from({ length: 5 }, (_, i) => job({ id: i, source: "serp" })),
      ...Array.from({ length: 5 }, (_, i) => job({ id: 100 + i, source: "getmatch" })),
    ]
    expect(sourceFilterEligible(jobs)).toBe(true)
    expect(countJobsBySourceGroup(jobs)).toEqual({ hh: 5, getmatch: 5, habr: 0, telegram: 0 })
  })
})

describe("jobSourceGroup", () => {
  it("читает из job", () => {
    expect(jobSourceGroup(job({ source: "getmatch", vacancy_id: "gm_1" }))).toBe("getmatch")
  })
})

describe("listingLinkLabel", () => {
  it("все лейблы lowercase (D7 — единый регистр)", () => {
    expect(listingLinkLabel("hh")).toBe("hh")
    expect(listingLinkLabel("getmatch")).toBe("getmatch")
    expect(listingLinkLabel("habr")).toBe("habr")
    expect(listingLinkLabel("telegram")).toBe("telegram")
  })
  it("не зависит от регистра входной группы (канон уже SourceGroup)", () => {
    // SourceGroup — литерал "hh"|"getmatch"|"telegram", но проверим стабильность
    expect(listingLinkLabel("hh" as const)).toMatch(/^(hh|getmatch|telegram)$/)
  })
})

describe("extractSourceGroupsFromText", () => {
  it("извлекает упоминания источников из narrative-строки", () => {
    expect(extractSourceGroupsFromText("getmatch даёт лучший конверс")).toEqual(["getmatch"])
    expect(extractSourceGroupsFromText("hh и getmatch — два основных канала")).toEqual([
      "hh",
      "getmatch",
    ])
    expect(extractSourceGroupsFromText("давить на tg-каналы и hh")).toEqual(["telegram", "hh"])
    expect(extractSourceGroupsFromText("Telegram активно отвечает")).toEqual(["telegram"])
  })
  it("не матчит подстроки (hh внутри слова, getmatch внутри строки)", () => {
    expect(extractSourceGroupsFromText("на этой неделе")).toEqual([])
    expect(extractSourceGroupsFromText("тахиcardия")).toEqual([])
  })
  it("case-insensitive и уникальные в порядке первого вхождения", () => {
    expect(extractSourceGroupsFromText("HH → hh → Hh")).toEqual(["hh"])
    expect(extractSourceGroupsFromText("getmatch, затем hh, затем getmatch")).toEqual([
      "getmatch",
      "hh",
    ])
  })
  it("пусто/null/undefined → пустой массив", () => {
    expect(extractSourceGroupsFromText("")).toEqual([])
    expect(extractSourceGroupsFromText(null)).toEqual([])
    expect(extractSourceGroupsFromText(undefined)).toEqual([])
    expect(extractSourceGroupsFromText("   ")).toEqual([])
  })
  it("нет совпадений → пустой массив", () => {
    expect(extractSourceGroupsFromText("рынок перегрет, откликов мало")).toEqual([])
  })
})
