// @vitest-environment jsdom
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { cleanup, render, screen } from "@testing-library/react"
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

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      new Response(JSON.stringify({}), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ),
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

describe("ChatPage — главный экран «Агент»", () => {
  it("пустой экран — приветствие, композер и список серверных диалогов", async () => {
    renderChat()
    expect(screen.getByRole("heading", { name: "Агент" })).toBeTruthy()
    expect(screen.getByPlaceholderText("Спросите агента…")).toBeTruthy()
    // A-3: список диалогов теперь серверный, тумблер «Агент» рядом с композером.
    expect(await screen.findByText("Диалоги")).toBeTruthy()
    expect(screen.getByRole("button", { name: "Агент" })).toBeTruthy()
    // Переписка с HR переехала в «Вакансии»: кнопок списков и «контекстов» здесь больше нет.
    expect(screen.queryByText("Архив")).toBeNull()
    expect(screen.queryByText("Контексты")).toBeNull()
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
        console.log("FETCH", method, url)
        const json = (data: unknown) =>
          new Response(JSON.stringify(data), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          })
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
    expect(screen.getByText("Диалог из этого браузера")).toBeTruthy()
  })
})
