// @vitest-environment jsdom
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MemoryRouter } from "react-router-dom"
import { ChatPage } from "./ChatPage"

beforeAll(() => {
  class Observer {
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords() {
      return []
    }
  }
  Object.assign(globalThis, { ResizeObserver: Observer, IntersectionObserver: Observer })
  Element.prototype.scrollIntoView = () => {}
  Element.prototype.scrollTo = () => {}
})

afterEach(cleanup)

function json(data: unknown) {
  return new Response(JSON.stringify(data), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  })
}

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => json({})),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

function renderChat(initialEntry = "/chat") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <ChatPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe("ChatPage — главный экран «Агент» (U-5)", () => {
  it("пустой экран: приветствие, примеры, один режим ввода, панель «Ход работы» справа", async () => {
    renderChat()
    expect(screen.getByRole("heading", { name: "Агент по валютной удалёнке" })).toBeTruthy()
    expect(screen.getByPlaceholderText("Опишите задачу для агента")).toBeTruthy()
    // Переключателя «Агент / Чат», выбора модели и вложений больше нет.
    expect(screen.queryByRole("button", { name: "Чат" })).toBeNull()
    expect(screen.queryByLabelText("Модель")).toBeNull()
    expect(screen.queryByLabelText("Приложить файл")).toBeNull()
    // Колонки диалогов на экране нет (они в меню); на узком экране — кнопка «Диалоги».
    expect(screen.queryByRole("button", { name: "Новый диалог" })).toBeNull()
    expect(screen.getByRole("button", { name: /Диалоги/ })).toBeTruthy()
    // Панель открыта по умолчанию и честно пустая.
    const panel = screen.getByRole("complementary", { name: "Ход работы" })
    expect(panel.textContent).toMatch(/В этом диалоге ещё нет запусков/)
    // Примеры целей: клик подставляет цель в композер.
    screen.getByRole("button", { name: /no-such-job/ }).click()
    expect((await screen.findByDisplayValue(/no-such-job/)) as HTMLTextAreaElement).toBeTruthy()
  })

  it("панель сворачивается, состояние помнится в localStorage", () => {
    renderChat()
    fireEvent.click(screen.getByRole("button", { name: "Свернуть панель «Ход работы»" }))
    expect(screen.queryByRole("complementary", { name: "Ход работы" })).toBeNull()
    expect(localStorage.getItem("copilot.agent.work-panel")).toBe("0")
    fireEvent.click(screen.getByRole("button", { name: "Открыть панель «Ход работы»" }))
    expect(screen.getByRole("complementary", { name: "Ход работы" })).toBeTruthy()
    expect(localStorage.getItem("copilot.agent.work-panel")).toBe("1")
  })

  it("режим подтверждения у поля ввода: «Автоматически» — через подтверждение, уходит PUT-ом", async () => {
    const calls: { url: string; method: string; body: string | null }[] = []
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        const method = (init?.method ?? "GET").toUpperCase()
        calls.push({ url, method, body: init?.body ? String(init.body) : null })
        if (url.endsWith("/api/agent/settings")) {
          return json(method === "PUT" ? JSON.parse(String(init?.body)) : { confirm_mode: "ask" })
        }
        return json({})
      }),
    )
    renderChat()
    const group = await screen.findByRole("group", { name: "Подтверждение отклика" })
    expect(group).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "Автоматически" }))
    // Сначала спрашиваем: агент будет ставить отклики без «да».
    expect(await screen.findByText("Подтверждать отклики автоматически?")).toBeTruthy()
    expect(calls.some((c) => c.method === "PUT")).toBe(false)
    fireEvent.click(screen.getByRole("button", { name: "Включить" }))
    await vi.waitFor(() =>
      expect(
        calls.some(
          (c) => c.method === "PUT" && c.url.endsWith("/api/agent/settings") && c.body?.includes('"auto"'),
        ),
      ).toBe(true),
    )
  })

  it("запуск в ленте — компактная карточка, подробности — в панели", async () => {
    const goal = "Проверь условия найма вакансии no-such-job"
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.endsWith("/api/agent/chats")) {
          return json({ items: [{ id: 7, title: "2. Ошибка инструмента", created_at: null, updated_at: null }] })
        }
        if (url.includes("/api/agent/chats/7/messages")) {
          return json({
            items: [{ id: 1, session_id: 7, role: "user", content: goal, created_at: "2026-11-16T10:00:00Z" }],
          })
        }
        if (url.includes("/events/replay")) {
          return json({
            items: [
              { id: 1, type: "plan_created", payload: { plan: [{ id: "s1", title: "Прочитать условия", status: "done" }] } },
              { id: 2, type: "step_started", payload: { index: 1, step_id: "s1", title: "Прочитать условия" } },
              {
                id: 3,
                type: "tool_called",
                payload: { step_id: "s1", tool: "read_work_terms", ok: false, error: "вакансия no-such-job не найдена" },
              },
              { id: 4, type: "done", payload: { answer: "Вакансии нет в базе." } },
            ],
          })
        }
        if (url.includes("/api/agent/runs?session_id=7")) {
          return json({
            items: [
              {
                id: 11,
                goal,
                status: "done",
                session_id: 7,
                stop_reason: "answered",
                answer: "Вакансии нет в базе.",
                error: null,
                created_at: "2026-11-16T10:00:01Z",
                updated_at: "2026-11-16T10:00:30Z",
              },
            ],
          })
        }
        return json({})
      }),
    )
    renderChat()
    expect(await screen.findByText("Вакансии нет в базе.")).toBeTruthy()
    expect(screen.getAllByText("2. Ошибка инструмента").length).toBeGreaterThan(0)
    const panel = screen.getByRole("complementary", { name: "Ход работы" })
    // Ошибка инструмента видна в панели без раскрытия ленты.
    expect(panel.textContent).toMatch(/Ошибка: вакансия no-such-job не найдена/)
    expect(panel.textContent).toMatch(/Прочитать условия/)
    // Цель уже видна репликой — в карточке не дублируется.
    expect(screen.getAllByText(goal)).toHaveLength(2) // реплика + цель в шапке панели
  })

  it("старая история из localStorage переносится в серверную сессию (A-3)", { timeout: 20_000 }, async () => {
    // Первый тест экрана мог выставить флаг «уже переносили» — тест всегда с чистого листа.
    localStorage.removeItem("copilot.agent-chat.migrated-v2")
    localStorage.setItem(
      "copilot.agent-chat.messages",
      JSON.stringify([
        { id: "m1", role: "user", content: "Привет", createdAt: 1 },
        { id: "m2", role: "assistant", content: "Здравствуй", createdAt: 2 },
      ]),
    )
    const stored: { id: number; role: string; content: string; created_at: string | null }[] = []
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        const method = (init?.method ?? "GET").toUpperCase()
        if (url.endsWith("/api/agent/chats") && method === "GET") {
          return json({
            items:
              stored.length > 0
                ? [{ id: 7, title: "Диалог из этого браузера", created_at: null, updated_at: null }]
                : [],
          })
        }
        if (url.endsWith("/api/agent/chats") && method === "POST") {
          return json({ id: 7, title: "Диалог из этого браузера", created_at: null, updated_at: null })
        }
        if (url.includes("/messages") && method === "POST") {
          const body = JSON.parse(String(init?.body)) as { role: string; content: string }
          stored.push({ id: stored.length + 1, role: body.role, content: body.content, created_at: null })
          return json(stored[stored.length - 1])
        }
        if (url.includes("/messages") && method === "GET") {
          return json({ items: stored })
        }
        return json({})
      }),
    )
    renderChat()
    // Цепочка миграции — несколько серверных ходов под нагрузкой CI: даём больше секунды.
    expect(await screen.findByText("Привет", {}, { timeout: 15_000 })).toBeTruthy()
    expect(screen.getByText("Здравствуй")).toBeTruthy()
    expect(screen.getAllByText("Диалог из этого браузера").length).toBeGreaterThan(0)
  })
})
