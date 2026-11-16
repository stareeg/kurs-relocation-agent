// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import type { AgentEvent, AgentRun } from "@/api/agent"
import { AgentRunView } from "./AgentRunView"
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

describe("AgentRunView", () => {
  it("показывает ошибку инструмента в ходе работы и ответ markdown-ом", () => {
    const view = makeView({
      plan: [
        { id: "s1", title: "Прочитать условия вакансии", status: "done" },
        { id: "s2", title: "Найти похожую", status: "done" },
      ],
      answer: "**Итог:** вакансии нет, нашёл замену `demo-101`.",
      events: [
        ev(1, "plan_created", {}),
        ev(2, "step_started", { index: 1, step_id: "s1", title: "Прочитать условия вакансии" }),
        ev(3, "tool_called", {
          tool: "read_work_terms",
          ok: false,
          summary: "read_work_terms: ошибка",
          error: "вакансия no-such-job не найдена",
        }),
        ev(4, "step_started", { index: 2, step_id: "s2", title: "Найти похожую" }),
        ev(5, "tool_called", { tool: "search_vacancies", ok: true, summary: "search_vacancies: найдено 3" }),
        ev(6, "judge_verdict", { level: "final", verdict: "pass" }),
      ],
    })
    render(<AgentRunView view={view} />)
    expect(screen.getByText(/1 ошибка инструмента — обработано/)).toBeTruthy()
    expect(screen.getByText("Итог:").tagName).toBe("STRONG")
    expect(screen.getByText(/Судья: итог подтверждён/)).toBeTruthy()
    // Ход работы у завершённого запуска свёрнут — раскрываем.
    fireEvent.click(screen.getByRole("button", { name: /Ход работы/ }))
    expect(screen.getByText("Ошибка инструмента · Условия найма")).toBeTruthy()
    expect(screen.getByText(/вакансия no-such-job не найдена/)).toBeTruthy()
    expect(screen.getByText(/найдено 3/)).toBeTruthy()
  })

  it("карточка подтверждения: человеческие подписи и решение уходит один раз", () => {
    const onApprove = vi.fn()
    const view = makeView({
      status: "waiting_approval",
      live: true,
      card: {
        action: "queue_application",
        params: { vacancy_id: "demo-101", cover_note: "Здравствуйте! Мне интересна вакансия…" },
      },
    })
    render(<AgentRunView view={view} onApprove={onApprove} />)
    expect(screen.getByText("Поставить отклик в очередь автооткликов")).toBeTruthy()
    expect(screen.getByText("Вакансия")).toBeTruthy()
    expect(screen.getByText("Сообщение работодателю")).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "Да, выполнить" }))
    fireEvent.click(screen.getByRole("button", { name: "Да, выполнить" }))
    expect(onApprove).toHaveBeenCalledTimes(1)
    expect(onApprove).toHaveBeenCalledWith(1, true)
  })
})
