import { describe, expect, it } from "vitest"
import type { AgentEvent, AgentRun } from "@/api/agent"
import type { RunView } from "./use-agent-runs"
import { currentActivity, planProgress, runVacancies, summarize, type VacancyRef } from "./run-summary"

function ev(id: number, type: string, payload: Record<string, unknown>): AgentEvent {
  return { id, type, payload, node: null, duration_ms: null, created_at: null }
}

const vacancies = new Map<string, VacancyRef>([
  ["demo-101", { title: "Senior Backend Engineer", company: "Northwind Labs", score: 74 }],
  ["demo-102", { title: "Python Developer", company: "Kestrel Analytics", score: 61 }],
  ["demo-103", { title: "Go Developer", company: "Umbra", score: 40 }],
])

const events = [
  ev(1, "plan_created", {}),
  ev(2, "step_started", { index: 1, step_id: "s1", title: "Найти вакансии" }),
  ev(3, "tool_called", {
    step_id: "s1",
    tool: "search_vacancies",
    ok: true,
    summary: 'search_vacancies: {"items": [{"id": "demo-101"}, {"id": "demo-102"}]}',
  }),
  ev(4, "step_started", { index: 2, step_id: "s2", title: "Проверить условия" }),
  ev(5, "tool_called", {
    step_id: "s2",
    tool: "read_work_terms",
    ok: false,
    summary: "read_work_terms: ошибка — вакансия no-such-job не найдена",
    error: "вакансия no-such-job не найдена",
  }),
  ev(6, "tool_called", {
    step_id: "s2",
    tool: "read_work_terms",
    ok: true,
    summary: 'read_work_terms: {"vacancy_id": "demo-102", "engagement": "full_time"}',
  }),
  ev(7, "tool_called", {
    step_id: "s2",
    tool: "score_vacancy",
    ok: true,
    summary: 'score_vacancy: {"vacancy_id": "demo-102", "overall_score": 88, "recommendation": "apply"}',
  }),
  ev(8, "tool_called", {
    step_id: "s2",
    tool: "task",
    subagent: "country_researcher",
    ok: true,
    summary: "task(country_researcher): налоги в Сербии",
  }),
  ev(9, "judge_verdict", { level: "final", verdict: "pass", reason: "цитаты сходятся" }),
]

describe("summarize", () => {
  it("считает вызовы по инструментам, ошибки и балл запуска", () => {
    const s = summarize(events)
    expect(s.actions).toBe(5)
    expect(s.toolErrors).toBe(1)
    expect(s.stepsTaken).toBe(2)
    expect(s.currentStepId).toBe("s2")
    const terms = s.tools.find((t) => t.key === "read_work_terms")!
    expect(terms.label).toBe("Условия найма")
    expect(terms.calls).toHaveLength(2)
    expect(terms.errors).toBe(1)
    expect(terms.calls[0]).toMatchObject({ ok: false, text: "вакансия no-such-job не найдена" })
    expect(s.tools.find((t) => t.key === "task:country_researcher")?.label).toBe(
      "Субагент · исследователь страны",
    )
    expect(s.runScores.get("demo-102")).toBe(88)
    expect(s.finalVerdict).toEqual({ verdict: "pass", reason: "цитаты сходятся" })
    // Вызовы шага s2 лежат под ним — шаг в панели раскрывается своими вызовами.
    expect(s.rowsByStep.get("s2")?.filter((r) => r.kind === "tool-error")).toHaveLength(1)
  })
})

describe("currentActivity", () => {
  it("называет действие глаголом и вакансию — компанией из базы", () => {
    expect(currentActivity(events.slice(0, 6), vacancies)).toBe("читает условия Kestrel Analytics")
    expect(currentActivity(events.slice(0, 7), vacancies)).toBe("оценивает Kestrel Analytics")
    expect(currentActivity(events.slice(0, 3), vacancies)).toBe("ищет вакансии в базе")
    expect(currentActivity(events.slice(0, 8), vacancies)).toBe("исследователь страны разбирает условия")
  })

  it("после начала шага и без событий строки нет; перед итогом — судья", () => {
    expect(currentActivity([], vacancies)).toBeNull()
    expect(currentActivity(events.slice(0, 4), vacancies)).toBeNull()
    expect(currentActivity([ev(1, "plan_changed", { action: "finish" })])).toBe(
      "судья проверяет итог по цитатам",
    )
  })
})

describe("planProgress", () => {
  const plan = [
    { id: "s1", title: "Найти вакансии", status: "done" },
    { id: "s0", title: "Старый шаг", status: "dropped" },
    { id: "s2", title: "Проверить условия", status: "pending" },
    { id: "s3", title: "Оценить", status: "pending" },
  ]

  it("снятые шаги не считаются, текущий — по последнему начатому", () => {
    expect(planProgress(plan, "s2", true)).toEqual({
      total: 3,
      done: 1,
      current: 2,
      currentTitle: "Проверить условия",
      pct: 33,
    })
  })

  it("начатый шаг уже закрыт — текущий первый незакрытый; без плана — нули", () => {
    expect(planProgress(plan, "s1", true).current).toBe(2)
    expect(planProgress(null, null, true)).toMatchObject({ total: 0, current: 0, pct: 0 })
  })
})

describe("runVacancies", () => {
  it("вакансии из событий и ответа; балл запуска важнее балла базы", () => {
    const run: AgentRun = {
      id: 1,
      goal: "цель",
      status: "done",
      session_id: 1,
      stop_reason: "answered",
      answer: "Лучшая — Go Developer в Umbra.",
      error: null,
      created_at: null,
      updated_at: null,
    }
    const view: RunView = {
      run,
      createdAtMs: 0,
      status: "done",
      answer: run.answer,
      error: null,
      card: null,
      plan: null,
      note: null,
      planChanges: [],
      pendingRebuildReason: null,
      events,
      live: false,
    }
    const items = runVacancies(view, summarize(events), vacancies)
    expect(items.map((v) => v.id)).toEqual(["demo-101", "demo-102", "demo-103"])
    expect(items.find((v) => v.id === "demo-102")).toMatchObject({ score: 88, scoredInRun: true })
    expect(items.find((v) => v.id === "demo-101")).toMatchObject({ score: 74, scoredInRun: false })
  })
})
