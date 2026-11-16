// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import type { AgentEvent, AgentRun } from "@/api/agent"
import { AgentRunCard } from "./AgentRunCard"
import type { RunView } from "./use-agent-runs"

afterEach(cleanup)

function ev(id: number, type: string, payload: Record<string, unknown>): AgentEvent {
  return { id, type, payload, node: null, duration_ms: null, created_at: null }
}

function makeView(over: Partial<RunView>): RunView {
  const run: AgentRun = {
    id: 1,
    goal: "Проверь условия вакансии no-such-job",
    status: "done",
    session_id: 3,
    stop_reason: "answered",
    answer: null,
    error: null,
    created_at: "2026-11-16T10:00:00Z",
    updated_at: "2026-11-16T10:00:42Z",
  }
  return {
    run,
    createdAtMs: Date.parse(run.created_at!),
    status: "done",
    answer: null,
    error: null,
    card: null,
    plan: null,
    note: null,
    planChanges: [],
    pendingRebuildReason: null,
    events: [],
    live: false,
    ...over,
  }
}

const vacancies = new Map([
  ["demo-101", { title: "Senior LLM Engineer", company: "Northwind Labs", score: 74 }],
  ["demo-102", { title: "Python Developer", company: "Kestrel Analytics", score: 61 }],
])

describe("AgentRunCard", () => {
  it("живой запуск: «Шаг 2 из 3 · читает условия …», полоса и секундомер", () => {
    const view = makeView({
      status: "running",
      live: true,
      plan: [
        { id: "s1", title: "Найти вакансии", status: "done" },
        { id: "s2", title: "Проверить условия", status: "pending" },
        { id: "s3", title: "Оценить", status: "pending" },
      ],
      events: [
        ev(1, "step_started", { index: 1, step_id: "s1", title: "Найти вакансии" }),
        ev(2, "step_started", { index: 2, step_id: "s2", title: "Проверить условия" }),
        ev(3, "tool_called", {
          step_id: "s2",
          tool: "read_work_terms",
          ok: true,
          summary: 'read_work_terms: {"vacancy_id": "demo-102"}',
        }),
      ],
    })
    render(<AgentRunCard view={view} vacancies={vacancies} onShowWork={vi.fn()} />)
    expect(screen.getByText("Шаг 2 из 3")).toBeTruthy()
    expect(screen.getByText(/читает условия Kestrel Analytics/)).toBeTruthy()
    expect(screen.getByRole("progressbar")).toBeTruthy()
    expect(screen.getByText(/^\d+:\d{2}$/)).toBeTruthy()
    // Подробностей шага в ленте нет — они в панели.
    expect(screen.queryByText("Найти вакансии")).toBeNull()
    expect(screen.queryByRole("button", { name: /Запустить заново/ })).toBeNull()
  })

  it("итог: ответ markdown-ом, судья, ошибка инструмента в шапке, «Ход работы» открывает панель", () => {
    const onShowWork = vi.fn()
    const onRetry = vi.fn()
    const view = makeView({
      plan: [{ id: "s1", title: "Прочитать условия вакансии", status: "done" }],
      answer: "**Итог:** вакансии нет, нашёл замену `demo-101`.",
      events: [
        ev(1, "step_started", { index: 1, step_id: "s1", title: "Прочитать условия вакансии" }),
        ev(2, "tool_called", {
          tool: "read_work_terms",
          ok: false,
          summary: "read_work_terms: ошибка",
          error: "вакансия no-such-job не найдена",
        }),
        ev(3, "tool_called", { tool: "search_vacancies", ok: true, summary: "найдено 3" }),
        ev(4, "judge_verdict", { level: "final", verdict: "pass" }),
      ],
    })
    render(<AgentRunCard view={view} onShowWork={onShowWork} onRetry={onRetry} />)
    expect(screen.getByText("Готово")).toBeTruthy()
    expect(screen.getByText(/1 ошибка инструмента — обработано/)).toBeTruthy()
    expect(screen.getByText("Итог:").tagName).toBe("STRONG")
    expect(screen.getByText(/Судья: итог подтверждён/)).toBeTruthy()
    // Текст ошибки — только в панели, в ленте его нет.
    expect(screen.queryByText(/вакансия no-such-job не найдена/)).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: /Ход работы · 2 действия/ }))
    expect(onShowWork).toHaveBeenCalledWith(1)
    fireEvent.click(screen.getByRole("button", { name: /Запустить заново/ }))
    expect(onRetry).toHaveBeenCalledWith("Проверь условия вакансии no-such-job")
  })

  it("карточка подтверждения: название вакансии, решение уходит один раз", () => {
    const onApprove = vi.fn()
    const onOpen = vi.fn()
    const view = makeView({
      status: "waiting_approval",
      live: true,
      plan: [{ id: "s1", title: "Поставить отклик", status: "pending" }],
      card: {
        action: "queue_application",
        params: { vacancy_id: "demo-101", cover_note: "Здравствуйте! Мне интересна вакансия…" },
      },
    })
    render(
      <AgentRunCard view={view} vacancies={vacancies} onApprove={onApprove} onOpenVacancy={onOpen} />,
    )
    expect(screen.getByText("Ждёт подтверждения")).toBeTruthy()
    expect(screen.getByText("Поставить отклик в очередь автооткликов")).toBeTruthy()
    expect(screen.getByText("Сообщение работодателю")).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "Senior LLM Engineer · Northwind Labs" }))
    expect(onOpen).toHaveBeenCalledWith("demo-101")
    fireEvent.click(screen.getByRole("button", { name: "Да, выполнить" }))
    fireEvent.click(screen.getByRole("button", { name: "Да, выполнить" }))
    expect(onApprove).toHaveBeenCalledTimes(1)
    expect(onApprove).toHaveBeenCalledWith(1, true)
  })

  it("упавший запуск: текст ошибки и «Повторить»", () => {
    const onRetry = vi.fn()
    const view = makeView({ status: "failed", error: "сбой модели", run: { ...makeView({}).run, stop_reason: "model_error" } })
    render(<AgentRunCard view={view} onRetry={onRetry} />)
    expect(screen.getByText("Ошибка")).toBeTruthy()
    expect(screen.getAllByText(/сбой модели/).length).toBeGreaterThan(0)
    fireEvent.click(screen.getByRole("button", { name: /Повторить/ }))
    expect(onRetry).toHaveBeenCalledTimes(1)
  })
})
