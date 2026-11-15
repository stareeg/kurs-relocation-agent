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
  it("пустой экран — приветствие и композер свободного чата, без списка диалогов", () => {
    renderChat()
    expect(screen.getByText("Агент")).toBeTruthy()
    expect(screen.getByPlaceholderText("Спросите агента…")).toBeTruthy()
    // Переписка с HR переехала в «Вакансии»: кнопок списков и «контекстов» здесь больше нет.
    expect(screen.queryByText("Архив")).toBeNull()
    expect(screen.queryByText("Контексты")).toBeNull()
  })

  it("история из localStorage рисуется лентой (персист свободного чата)", () => {
    localStorage.setItem(
      "copilot.agent-chat.messages",
      JSON.stringify([
        { id: "m1", role: "user", content: "Привет", createdAt: 1 },
        { id: "m2", role: "assistant", content: "Здравствуй", createdAt: 2 },
      ]),
    )
    renderChat()
    expect(screen.getByText("Привет")).toBeTruthy()
    expect(screen.getByText("Здравствуй")).toBeTruthy()
  })
})
