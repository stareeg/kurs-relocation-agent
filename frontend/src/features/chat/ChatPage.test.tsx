// @vitest-environment jsdom
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
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
})

afterEach(cleanup)

beforeEach(() => {
  // Пустые списки — иначе ChatPage падает без бэкенда.
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      const json = (body: unknown) =>
        new Response(JSON.stringify(body), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      if (url.includes("/api/conversations/attention")) {
        return json({ reply: [], remind: [], upcoming: [], strong_unapplied: [] })
      }
      if (url.includes("/api/conversations/active-count")) {
        return json({ count: 0 })
      }
      if (url.includes("/api/conversations")) {
        return json({ items: [] })
      }
      if (url.includes("/api/jobs")) {
        return json({ jobs: [], next_cursor: null, column_counts: {} })
      }
      if (url.includes("/api/notes")) {
        return json([])
      }
      return json({})
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
  sessionStorage.clear()
  localStorage.removeItem("copilot.chat-list.tab")
  localStorage.removeItem("copilot.chat-list.collapsed")
})

function renderChat() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/chat"]}>
        <ChatPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe("ChatPage — раздел «Чаты»", () => {
  it("по умолчанию показывает пустое состояние, не свободный чат", async () => {
    renderChat()
    await waitFor(() => {
      expect(screen.getByText("Выберите диалог")).toBeTruthy()
    })
    expect(screen.queryByText("Чат копайлота")).toBeNull()
  })

  it("«Новая вакансия» открывает форму создания с полями друг под другом", async () => {
    renderChat()
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Новая вакансия/i })).toBeTruthy()
    })
    fireEvent.click(screen.getByRole("button", { name: /Новая вакансия/i }))
    expect(screen.getByPlaceholderText("Компания")).toBeTruthy()
    expect(screen.getByPlaceholderText("Должность")).toBeTruthy()
    expect(screen.getByPlaceholderText("Telegram HR — @username или t.me/…")).toBeTruthy()
    expect(screen.getByRole("button", { name: /Добавить вакансию/i })).toBeTruthy()
  })
})
