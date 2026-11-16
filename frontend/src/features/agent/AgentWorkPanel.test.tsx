// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import type { AgentEvent, AgentRun } from "@/api/agent"
import { AgentWorkPanel } from "./AgentWorkPanel"
import type { RunView } from "./use-agent-runs"

afterEach(cleanup)

function ev(id: number, type: string, payload: Record<string, unknown>): AgentEvent {
  return { id, type, payload, node: null, duration_ms: null, created_at: null }
}

const run: AgentRun = {
  id: 5,
  goal: "Проверь условия найма вакансии no-such-job; если её нет в базе, найди похожую и оцени",
  status: "done",
  session_id: 3,
  stop_reason: "answered",
  answer: "Нашёл замену: Python Developer.",
  error: null,
  created_at: "2026-11-16T10:00:00Z",
  updated_at: "2026-11-16T10:00:42Z",
}

const view: RunView = {
  run,
  createdAtMs: Date.parse(run.created_at!),
  status: "done",
  answer: run.answer,
  error: null,
  card: null,
  plan: [
    { id: "s1", title: "Прочитать условия no-such-job", status: "done" },
    { id: "s0", title: "Откликнуться сразу", status: "dropped" },
    { id: "s2", title: "Найти похожую и оценить", status: "done" },
  ],
  note: null,
  planChanges: [
    { id: 9, action: "continue", reason: "вакансии нет в базе", changes: ["- s0: Откликнуться сразу"] },
  ],
  pendingRebuildReason: null,
  events: [
    ev(1, "plan_created", { note: "проверить вакансию, при отсутствии — найти замену" }),
    ev(2, "step_started", { index: 1, step_id: "s1", title: "Прочитать условия no-such-job" }),
    ev(3, "tool_called", {
      step_id: "s1",
      tool: "read_work_terms",
      ok: false,
      summary: "read_work_terms: ошибка — вакансия no-such-job не найдена",
      error: "вакансия no-such-job не найдена",
    }),
    ev(4, "step_started", { index: 2, step_id: "s2", title: "Найти похожую и оценить" }),
    ev(5, "tool_called", {
      step_id: "s2",
      tool: "search_vacancies",
      ok: true,
      summary: 'search_vacancies: {"items": [{"id": "demo-102"}]}',
    }),
    ev(6, "tool_called", {
      step_id: "s2",
      tool: "score_vacancy",
      ok: true,
      summary: 'score_vacancy: {"vacancy_id": "demo-102", "overall_score": 88}',
    }),
    ev(7, "judge_verdict", { level: "final", verdict: "pass" }),
  ],
  live: false,
}

const vacancies = new Map([
  ["demo-102", { title: "Python Developer", company: "Kestrel Analytics", score: 61 }],
  ["demo-105", { title: "Не из этого запуска", company: null, score: 10 }],
])

describe("AgentWorkPanel", () => {
  it("план с прогрессом и снятым шагом, шаг раскрывается своими вызовами", () => {
    render(<AgentWorkPanel view={view} vacancies={vacancies} runIndex={2} runCount={2} />)
    expect(screen.getByText("2 из 2")).toBeTruthy()
    expect(screen.getByText(/запуск 2 из 2/)).toBeTruthy()
    expect(screen.getByText(/при отсутствии — найти замену/)).toBeTruthy()
    expect(screen.getByText(/Откликнуться сразу \(снят\)/)).toBeTruthy()
    expect(screen.getByText(/вакансии нет в базе/)).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: /Прочитать условия no-such-job/ }))
    expect(screen.getByText("Ошибка · Условия найма")).toBeTruthy()
  })

  it("инструменты: число вызовов, упавший раскрыт с текстом ошибки", () => {
    render(<AgentWorkPanel view={view} vacancies={vacancies} />)
    expect(screen.getByText("3 · 1 ошибка")).toBeTruthy()
    const terms = screen.getByRole("button", { name: /Условия найма/ })
    expect(terms.getAttribute("aria-expanded")).toBe("true")
    expect(screen.getByText("вакансия no-such-job не найдена")).toBeTruthy()
    expect(screen.getByRole("button", { name: /Поиск вакансий/ }).getAttribute("aria-expanded")).toBe(
      "false",
    )
  })

  it("вакансии запуска с баллом агента, клик открывает карточку; память — пустая с нулём", () => {
    const onOpen = vi.fn()
    render(<AgentWorkPanel view={view} vacancies={vacancies} onOpenVacancy={onOpen} />)
    expect(screen.queryByText("Не из этого запуска")).toBeNull()
    expect(screen.getByText("88")).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: /Python Developer/ }))
    expect(onOpen).toHaveBeenCalledWith("demo-102")
    expect(screen.getByText(/Агент пока не запоминает факты/)).toBeTruthy()
  })

  it("расход: шаги, вызовы и токены из пределов, цена с условной частью GLM", () => {
    const withUsage: RunView = {
      ...view,
      limits: { max_steps: 8, max_model_calls: 40, max_tokens: 200_000 },
      usage: {
        model_calls: 17,
        tokens_in: 48_100,
        tokens_out: 4_200,
        cost_usd: 0.0042,
        cost_self_hosted_usd: 0.0024,
        by_group: {
          agent: { calls: 11, tokens_in: 40_000, tokens_out: 3_500, cost_usd: 0.0024 },
          judge: { calls: 4, tokens_in: 6_100, tokens_out: 500, cost_usd: 0.0018 },
          tools: { calls: 2, tokens_in: 2_000, tokens_out: 200, cost_usd: 0 },
        },
      },
    }
    render(<AgentWorkPanel view={withUsage} vacancies={vacancies} />)
    expect(screen.getByLabelText("Шаги: 2 из 8")).toBeTruthy()
    expect(screen.getByLabelText("Вызовы модели: 17 из 40")).toBeTruthy()
    expect(screen.getByLabelText(/^Токены: 52\s300 из 200\s000$/)).toBeTruthy()
    expect(screen.getByText(/прочитал 48\s100 · написал 4\s200/)).toBeTruthy()
    expect(screen.getAllByText("$0.0042").length).toBeGreaterThan(0)
    expect(screen.getByText(/Из неё \$0\.0024 условно: GLM работает на нашей ВМ/)).toBeTruthy()
    expect(screen.getByText(/Оплачено в OpenRouter: \$0\.0018/)).toBeTruthy()
    expect(screen.getByText("судья 4")).toBeTruthy()
  })

  it("запуск до учёта расхода: честное «не записаны», цена — тире", () => {
    render(<AgentWorkPanel view={view} vacancies={vacancies} />)
    expect(screen.getByText(/Токены и цена этого запуска не записаны/)).toBeTruthy()
  })

  it("без запуска — пустое состояние, секции с нулём; свернуть панель", () => {
    const onClose = vi.fn()
    render(<AgentWorkPanel view={null} onClose={onClose} />)
    expect(screen.getByText(/В этом диалоге ещё нет запусков/)).toBeTruthy()
    expect(screen.getByText("Агент ещё не открывал вакансии.")).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "Свернуть панель «Ход работы»" }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
