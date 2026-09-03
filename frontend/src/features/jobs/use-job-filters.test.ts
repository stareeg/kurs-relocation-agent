import { describe, expect, it } from "vitest"
import type { Job } from "@/api/jobs"
import type { components } from "@/api/schema"
import {
  DEFAULT_FILTERS,
  DEFAULT_PERIOD_DAYS,
  EMPTY_FILTERS,
  effectiveJobFilters,
  filterJobs,
  filtersActive,
  filtersFromSearchParams,
  searchActive,
  sortJobs,
  type JobFilters,
} from "./use-job-filters"

function job(p: Partial<Job>): Job {
  return { vacancy_text: "x", ...p } as Job
}

// B-03: job.score теперь типизирован полным ScoreResult — тестам нужен полный валидный объект,
// варьируется только company_type.
type ScoreResult = components["schemas"]["ScoreResult"]

function fakeScore(overrides: Partial<ScoreResult> = {}): ScoreResult {
  return {
    overall_score: 0,
    recommendation: "maybe",
    remote_abroad_compat: { level: "ok", reasoning: "" },
    grade_match: { level: "match", reasoning: "", off_profile_kind: "" },
    salary: {
      meets_min: false,
      value_or_range: "",
      estimated_range: "",
      note: "",
      confidence: "low",
      source: "none",
      estimate_pending: false,
    },
    role_content_match: { score: 0, matched_niche: [], reasoning: "" },
    burnout_risk: { level: "medium", reasoning: "" },
    company_type: "unknown",
    pros: [],
    cons: [],
    red_flags: [],
    one_line_verdict: "",
    work_city: "",
    currency_remote: false,
    weights_version: "",
    track: "primary",
    ...overrides,
  }
}
function withFilters(p: Partial<JobFilters>): JobFilters {
  return { ...EMPTY_FILTERS, ...p }
}

const SAMPLE: Job[] = [
  job({
    id: 1,
    title: "LLM Engineer",
    company: "Сбер",
    overall_score: 90,
    recommendation: "strong_apply",
    status: "Просмотр",
    scored_at: "2026-06-20T10:00:00",
    score: fakeScore({ company_type: "bank" }),
  }),
  job({
    id: 2,
    title: "ML Engineer",
    company: "Яндекс",
    overall_score: 70,
    recommendation: "apply",
    status: "Отклик",
    scored_at: "2026-06-18T10:00:00",
    score: fakeScore({ company_type: "product" }),
  }),
  job({
    id: 3,
    title: "Backend Developer",
    company: "Аутсорс ООО",
    overall_score: 40,
    recommendation: "skip",
    status: "Архив",
    scored_at: "2026-06-10T10:00:00",
    score: fakeScore({ company_type: "outsource" }),
  }),
]

describe("filtersActive", () => {
  it("дефолтные фильтры не активны", () => {
    expect(filtersActive(EMPTY_FILTERS)).toBe(false)
  })
  it("любой сужающий фильтр → активен", () => {
    expect(filtersActive(withFilters({ search: "llm" }))).toBe(true)
    expect(filtersActive(withFilters({ minScore: 60 }))).toBe(true)
    expect(filtersActive(withFilters({ statuses: ["Отклик"] }))).toBe(true)
    expect(filtersActive(withFilters({ scoredFrom: "2026-06-15" }))).toBe(true)
    expect(filtersActive(withFilters({ scoredTo: "2026-06-19" }))).toBe(true)
    expect(filtersActive(withFilters({ sources: ["getmatch"] }))).toBe(true)
    expect(filtersActive(withFilters({ ids: [1] }))).toBe(true)
    expect(filtersActive(withFilters({ track: "second_job" }))).toBe(true)
  })
})

describe("DEFAULT_FILTERS (UX3-3)", () => {
  it("период по умолчанию — последние 2 недели (включительно, сегодня — верхняя граница)", () => {
    const from = new Date(`${DEFAULT_FILTERS.scoredFrom}T00:00:00`)
    const to = new Date(`${DEFAULT_FILTERS.scoredTo}T00:00:00`)
    const today = new Date()
    today.setHours(0, 0, 0, 0)
    expect(to.getTime()).toBe(today.getTime())
    expect(today.getTime() - from.getTime()).toBe((DEFAULT_PERIOD_DAYS - 1) * 86_400_000)
    expect(DEFAULT_PERIOD_DAYS).toBe(14)
  })
  it("остальные поля как у EMPTY_FILTERS — период не тянет за собой другие фильтры", () => {
    expect(DEFAULT_FILTERS.search).toBe("")
    expect(DEFAULT_FILTERS.statuses).toEqual([])
    expect(DEFAULT_FILTERS.minScore).toBe(0)
    expect(DEFAULT_FILTERS.sources).toEqual([])
  })
})

describe("filterJobs", () => {
  it("поиск регистронезависимо по названию и компании", () => {
    expect(filterJobs(SAMPLE, withFilters({ search: "llm" })).map((j) => j.id)).toEqual([1])
    expect(filterJobs(SAMPLE, withFilters({ search: "яндекс" })).map((j) => j.id)).toEqual([2])
  })
  it("поиск по ID вакансии", () => {
    const sample = [job({ id: 5, title: "Role", vacancy_id: "12345678" })]
    expect(filterJobs(sample, withFilters({ search: "12345" })).map((j) => j.id)).toEqual([5])
  })
  it("поиск идёт по всей воронке — окно дат при непустом запросе не применяется", () => {
    // Ровно тот сценарий, из-за которого владелец каждый раз снимал фильтр по датам вручную:
    // вакансия старше окна находится по названию, но при пустом поиске остаётся скрытой.
    const stale = job({
      id: 9,
      title: "Забытая LLM-вакансия",
      company: "Acme",
      status: "Просмотр",
      scored_at: "2026-01-05T10:00:00",
      updated_at: "2026-01-05T10:00:00",
    })
    const window = { scoredFrom: "2026-06-15", scoredTo: "2026-06-20" }
    expect(filterJobs([stale], withFilters(window)).map((j) => j.id)).toEqual([])
    expect(
      filterJobs([stale], withFilters({ ...window, search: "забытая" })).map((j) => j.id),
    ).toEqual([9])
  })
  it("поиск не отменяет остальные фильтры (этап/скор сужают как раньше)", () => {
    expect(
      filterJobs(SAMPLE, withFilters({ search: "llm", statuses: ["Отклик"] })).map((j) => j.id),
    ).toEqual([])
  })
  it("searchActive — только про непустой запрос", () => {
    expect(searchActive(withFilters({ search: "  " }))).toBe(false)
    expect(searchActive(withFilters({ search: "llm" }))).toBe(true)
  })
  it("минимальный скор", () => {
    expect(filterJobs(SAMPLE, withFilters({ minScore: 60 })).map((j) => j.id)).toEqual([1, 2])
  })
  it("статус нормализуется (Архив → Отказ)", () => {
    expect(filterJobs(SAMPLE, withFilters({ statuses: ["Отказ"] })).map((j) => j.id)).toEqual([3])
    expect(filterJobs(SAMPLE, withFilters({ statuses: ["Просмотр"] })).map((j) => j.id)).toEqual([
      1,
    ])
  })
  it("статус — мультивыбор (Просмотр + Отклик)", () => {
    expect(
      filterJobs(SAMPLE, withFilters({ statuses: ["Просмотр", "Отклик"] })).map((j) => j.id),
    ).toEqual([1, 2])
  })
  it("диапазон дат — по релевантной активности (cardDateMs), границы включительно", () => {
    expect(filterJobs(SAMPLE, withFilters({ scoredFrom: "2026-06-15" })).map((j) => j.id)).toEqual([
      1, 2,
    ])
    expect(filterJobs(SAMPLE, withFilters({ scoredTo: "2026-06-18" })).map((j) => j.id)).toEqual([
      2, 3,
    ])
    expect(
      filterJobs(SAMPLE, withFilters({ scoredFrom: "2026-06-18", scoredTo: "2026-06-18" })).map(
        (j) => j.id,
      ),
    ).toEqual([2])
  })
  it("живой Скрининг со старым scored_at проходит период по updated_at (баг дефолтного окна)", () => {
    const sample = [
      job({
        id: 1,
        status: "Скрининг",
        scored_at: "2026-05-01T10:00:00",
        updated_at: "2026-06-20T12:00:00",
      }),
      job({
        id: 2,
        status: "Техничка",
        scored_at: "2026-05-01T10:00:00",
        updated_at: "2026-06-19T09:00:00",
      }),
      job({
        id: 3,
        status: "Просмотр",
        scored_at: "2026-05-01T10:00:00",
      }),
    ]
    expect(filterJobs(sample, withFilters({ scoredFrom: "2026-06-15" })).map((j) => j.id)).toEqual([
      1, 2,
    ])
  })
  it("Оффер со свежим updated_at не отсекается старым scored_at", () => {
    const sample = [
      job({
        id: 7,
        status: "Оффер",
        scored_at: "2026-01-10T10:00:00",
        updated_at: "2026-06-18T15:00:00",
      }),
    ]
    expect(
      filterJobs(sample, withFilters({ scoredFrom: "2026-06-18", scoredTo: "2026-06-18" })).map(
        (j) => j.id,
      ),
    ).toEqual([7])
  })
  it("несколько фильтров комбинируются (DoD: minScore + Просмотр)", () => {
    const res = filterJobs(SAMPLE, withFilters({ minScore: 80, statuses: ["Просмотр"] }))
    expect(res.map((j) => j.id)).toEqual([1])
  })
  it("фильтр по источнику (GM-6)", () => {
    const sample = [
      job({ id: 1, source: "serp" }),
      job({ id: 2, source: "getmatch", vacancy_id: "gm_34716" }),
    ]
    expect(filterJobs(sample, withFilters({ sources: ["getmatch"] })).map((j) => j.id)).toEqual([2])
    expect(filterJobs(sample, withFilters({ sources: ["hh"] })).map((j) => j.id)).toEqual([1])
  })
  it("рекомендованные (Шаг 10: strong_apply + apply)", () => {
    expect(filterJobs(SAMPLE, withFilters({ recommended: true })).map((j) => j.id)).toEqual([1, 2])
    expect(filterJobs(SAMPLE, withFilters({ recommended: false })).map((j) => j.id)).toEqual([1, 2, 3])
  })
  it("рекомендованные комбинируются с другими фильтрами", () => {
    const res = filterJobs(SAMPLE, withFilters({ recommended: true, minScore: 80 }))
    expect(res.map((j) => j.id)).toEqual([1])
  })
  it("точечный список id (L-01: ссылка из «Рынка»)", () => {
    expect(filterJobs(SAMPLE, withFilters({ ids: [2] })).map((j) => j.id)).toEqual([2])
    expect(filterJobs(SAMPLE, withFilters({ ids: [3, 1] })).map((j) => j.id)).toEqual([1, 3])
    expect(filterJobs(SAMPLE, withFilters({ ids: [999] })).map((j) => j.id)).toEqual([])
  })
  it("сегмент трека (Э3.1)", () => {
    const sample = [
      job({ id: 1, track: "primary", overall_score: 70 }),
      job({ id: 2, track: "second_job", overall_score: 80 }),
    ]
    expect(filterJobs(sample, withFilters({ track: "primary" })).map((j) => j.id)).toEqual([1])
    expect(filterJobs(sample, withFilters({ track: "second_job" })).map((j) => j.id)).toEqual([2])
    expect(filterJobs(sample, withFilters({ track: "" })).map((j) => j.id)).toEqual([1, 2])
  })
})

describe("filtersFromSearchParams (L-01)", () => {
  it("без поддерживаемых ключей — null, персистентные фильтры не трогаем", () => {
    expect(filtersFromSearchParams(new URLSearchParams("foo=bar"))).toBeNull()
    expect(filtersFromSearchParams(new URLSearchParams(""))).toBeNull()
  })
  it("этап + источник + скор + список id", () => {
    const partial = filtersFromSearchParams(
      new URLSearchParams("stage=Скрининг,Техничка&source=hh&minScore=60&ids=1,2,3"),
    )
    expect(partial).toEqual({
      search: "",
      statuses: ["Скрининг", "Техничка"],
      minScore: 60,
      sources: ["hh"],
      recommended: false,
      ids: [1, 2, 3],
      scoredFrom: "",
      scoredTo: "",
      track: "",
    })
  })
  it("recommended=1 → флаг рекомендованных (Шаг 10)", () => {
    expect(filtersFromSearchParams(new URLSearchParams("recommended=1"))?.recommended).toBe(true)
    expect(filtersFromSearchParams(new URLSearchParams("recommended=0"))?.recommended).toBe(false)
  })
  it("неизвестные значения этапа/источника отбрасываются, не роняют парсер", () => {
    const partial = filtersFromSearchParams(
      new URLSearchParams("stage=Bogus&source=carrier_pigeon"),
    )
    expect(partial?.statuses).toEqual([])
    expect(partial?.sources).toEqual([])
  })
  it("period=all или отсутствует → без границ периода (не дефолтные 7 дней доски)", () => {
    const withAll = filtersFromSearchParams(new URLSearchParams("stage=Скрининг&period=all"))
    expect(withAll?.scoredFrom).toBe("")
    expect(withAll?.scoredTo).toBe("")
    const withoutPeriod = filtersFromSearchParams(new URLSearchParams("stage=Скрининг"))
    expect(withoutPeriod?.scoredFrom).toBe("")
    expect(withoutPeriod?.scoredTo).toBe("")
  })
  it("period=N → последние N дней, сегодня — верхняя граница", () => {
    const partial = filtersFromSearchParams(new URLSearchParams("stage=Скрининг&period=30"))
    const to = new Date(`${partial?.scoredTo}T00:00:00`)
    const from = new Date(`${partial?.scoredFrom}T00:00:00`)
    const today = new Date()
    today.setHours(0, 0, 0, 0)
    expect(to.getTime()).toBe(today.getTime())
    expect(today.getTime() - from.getTime()).toBe(29 * 86_400_000)
  })
})

describe("sortJobs", () => {
  it("по скору ↓/↑", () => {
    expect(sortJobs(SAMPLE, "score_desc").map((j) => j.id)).toEqual([1, 2, 3])
    expect(sortJobs(SAMPLE, "score_asc").map((j) => j.id)).toEqual([3, 2, 1])
  })
  it("по дате ↓/↑ (cardDateMs / scored_at на ранних этапах)", () => {
    expect(sortJobs(SAMPLE, "date_desc").map((j) => j.id)).toEqual([1, 2, 3])
    expect(sortJobs(SAMPLE, "date_asc").map((j) => j.id)).toEqual([3, 2, 1])
  })
  it("не мутирует исходный массив", () => {
    const before = SAMPLE.map((j) => j.id)
    sortJobs(SAMPLE, "score_asc")
    expect(SAMPLE.map((j) => j.id)).toEqual(before)
  })
  it("вакансии без скора/даты уходят в хвост desc", () => {
    const withNulls = [...SAMPLE, job({ id: 9, overall_score: null, scored_at: null })]
    expect(sortJobs(withNulls, "score_desc").at(-1)?.id).toBe(9)
    expect(sortJobs(withNulls, "date_desc").at(-1)?.id).toBe(9)
  })
  it("гейт — отдельной группой: балл при дилбрейкере больше не режется", () => {
    // Этап 1 §1.4: у зарезанной сильной вакансии остаётся высокий overall_score, поэтому по
    // числу она обошла бы честную среднюю — сортировка обязана смотреть на флаг гейта.
    const gated = job({
      id: 8,
      overall_score: 95,
      recommendation: "skip",
      status: "Просмотр",
      scored_at: "2026-06-21T10:00:00",
      score: fakeScore({ overall_score: 95, gate_triggered: "Балл срезан: формат-гейт" }),
    })
    expect(sortJobs([...SAMPLE, gated], "score_desc").map((j) => j.id)).toEqual([1, 2, 3, 8])
    expect(sortJobs([...SAMPLE, gated], "score_asc").map((j) => j.id)).toEqual([8, 3, 2, 1])
  })
  it("смешанная доска при «Все»: основной трек первым, внутри — гейт затем балл (Э3.1)", () => {
    const mixed = [
      job({ id: 1, track: "second_job", overall_score: 90 }),
      job({ id: 2, track: "primary", overall_score: 70 }),
      job({
        id: 3,
        track: "primary",
        overall_score: 95,
        score: fakeScore({ gate_triggered: "Балл срезан: формат-гейт" }),
      }),
      job({ id: 4, track: "second_job", overall_score: 60 }),
    ]
    expect(sortJobs(mixed, "score_desc", { groupByTrack: true }).map((j) => j.id)).toEqual([
      2, 3, 1, 4,
    ])
  })
  it("выключенный второй трек не меняет порядок — регресс на текущий вид доски (Э3.1)", () => {
    const mixed = [
      job({ id: 1, track: "second_job", overall_score: 90 }),
      job({ id: 2, track: "primary", overall_score: 70 }),
    ]
    expect(sortJobs(mixed, "score_desc").map((j) => j.id)).toEqual([1, 2])
    expect(sortJobs(mixed, "score_desc", { groupByTrack: false }).map((j) => j.id)).toEqual([1, 2])
  })
})

describe("effectiveJobFilters (Э3.1)", () => {
  it("без второго трека сегмент не применяется", () => {
    const f = withFilters({ track: "second_job" })
    expect(effectiveJobFilters(f, false).track).toBe("")
    expect(effectiveJobFilters(f, true).track).toBe("second_job")
  })
})
