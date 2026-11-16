// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import type { AgentEvent, AgentRun } from "@/api/agent"
import { AgentRunCard } from "./AgentRunCard"
import type { RunView } from "./use-agent-runs"
import type { VacancyRef } from "./run-summary"

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
    expect(onApprove).toHaveBeenCalledWith(1, true, undefined)
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

describe("AgentRunCard — U-1: правка письма, автоподтверждение, цитаты", () => {
  const card = {
    action: "queue_application",
    params: { vacancy_id: "demo-101", cover_note: "Здравствуйте! Пять лет пишу backend на Python и агентов." },
  }

  it("«Изменить текст»: правка в пределах 40–600 знаков уходит вместе с «да»", () => {
    const onApprove = vi.fn()
    const view = makeView({ status: "waiting_approval", live: true, card })
    render(<AgentRunCard view={view} vacancies={vacancies} onApprove={onApprove} />)
    fireEvent.click(screen.getByRole("button", { name: "Изменить текст" }))
    const box = screen.getByLabelText("Сообщение работодателю") as HTMLTextAreaElement
    expect(box.value).toBe(card.params.cover_note)
    fireEvent.change(box, { target: { value: "Коротко" } })
    expect(screen.getByText(/не короче 40/)).toBeTruthy()
    expect((screen.getByRole("button", { name: /Да, с этим текстом/ }) as HTMLButtonElement).disabled).toBe(true)
    const edited = "Здравствуйте! Текст поправлен вручную: опыт с LLM-агентами и Postgres."
    fireEvent.change(box, { target: { value: edited } })
    fireEvent.click(screen.getByRole("button", { name: /Да, с этим текстом/ }))
    expect(onApprove).toHaveBeenCalledWith(1, true, { cover_note: edited })
  })

  it("«Вернуть текст агента» отменяет правку; «Отклонить» уходит без правки", () => {
    const onApprove = vi.fn()
    const view = makeView({ status: "waiting_approval", live: true, card })
    render(<AgentRunCard view={view} vacancies={vacancies} onApprove={onApprove} />)
    fireEvent.click(screen.getByRole("button", { name: "Изменить текст" }))
    fireEvent.change(screen.getByLabelText("Сообщение работодателю"), {
      target: { value: "Совсем другой текст письма, длиннее сорока знаков точно." },
    })
    fireEvent.click(screen.getByRole("button", { name: "Вернуть текст агента" }))
    expect(screen.getByText(card.params.cover_note)).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "Отклонить" }))
    expect(onApprove).toHaveBeenCalledWith(1, false, undefined)
  })

  it("действие без вопроса видно строкой в ленте", () => {
    const view = makeView({
      answer: "Отклик поставлен.",
      events: [
        ev(1, "run_started", { auto_confirm: true }),
        ev(2, "confirmation_resolved", { approved: true, auto: true, card }),
      ],
    })
    render(<AgentRunCard view={view} vacancies={vacancies} />)
    expect(
      screen.getByText(
        "Подтверждено автоматически: Поставить отклик в очередь автооткликов · Senior LLM Engineer · Northwind Labs",
      ),
    ).toBeTruthy()
  })

  it("цитата из ответа кликается и открывает вакансию, где она стоит", () => {
    const onOpen = vi.fn()
    const withText = new Map<string, VacancyRef>([
      ...vacancies,
      [
        "demo-101",
        {
          title: "Senior LLM Engineer",
          company: "Northwind Labs",
          score: 74,
          text: "Формат: Удалённо   из любой точки мира. Найм через EOR.",
        },
      ],
    ])
    const view = makeView({
      answer: "Подходит: «удалённо из любой точки мира». Не нашлось: «офис в Берлине обязателен».",
    })
    render(<AgentRunCard view={view} vacancies={withText} onOpenVacancy={onOpen} />)
    fireEvent.click(screen.getByRole("button", { name: "«удалённо из любой точки мира»" }))
    expect(onOpen).toHaveBeenCalledWith("demo-101", "удалённо из любой точки мира")
    // Цитаты, которой нет ни в одном тексте, — просто текст.
    expect(screen.queryByRole("button", { name: /офис в Берлине/ })).toBeNull()
    expect(screen.getByText(/офис в Берлине обязателен/)).toBeTruthy()
  })
})

describe("AgentRunCard — A-9: «Стоп»", () => {
  it("у живого запуска «Стоп» уходит один раз; у завершённого кнопки нет", () => {
    const onStop = vi.fn(() => new Promise<void>(() => {}))
    const live = makeView({ status: "running", live: true })
    const { unmount } = render(<AgentRunCard view={live} onStop={onStop} />)
    fireEvent.click(screen.getByRole("button", { name: "Остановить запуск" }))
    fireEvent.click(screen.getByRole("button", { name: "Остановить запуск" }))
    expect(onStop).toHaveBeenCalledTimes(1)
    expect(onStop).toHaveBeenCalledWith(1)
    unmount()
    render(<AgentRunCard view={makeView({})} onStop={onStop} />)
    expect(screen.queryByRole("button", { name: "Остановить запуск" })).toBeNull()
  })

  it("остановленный запуск: «Остановлено», частичный итог и «Повторить»", () => {
    const onRetry = vi.fn()
    const view = makeView({
      status: "cancelled",
      answer: "Не удалось закончить цель: запуск остановлен человеком кнопкой «Стоп».",
      run: { ...makeView({}).run, status: "cancelled", stop_reason: "cancelled" },
      events: [ev(1, "cancelled", { stop_reason: "cancelled" })],
    })
    render(<AgentRunCard view={view} onRetry={onRetry} />)
    expect(screen.getByText("Остановлено")).toBeTruthy()
    expect(screen.queryByText(/· cancelled/)).toBeNull()
    expect(screen.getByText(/запуск остановлен человеком/)).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: /Повторить/ }))
    expect(onRetry).toHaveBeenCalledTimes(1)
  })
})
