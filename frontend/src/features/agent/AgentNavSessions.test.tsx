// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { AgentNavSessions } from "./AgentNavSessions"
import { AgentSessionsProvider } from "./AgentSessionsProvider"

const SESSIONS = Array.from({ length: 10 }, (_, i) => ({
  id: i + 1,
  title: i === 1 ? "2. Ошибка инструмента" : `Диалог ${i + 1}`,
  created_at: null,
  updated_at: null,
}))

let calls: { url: string; method: string; body: unknown }[] = []

beforeEach(() => {
  calls = []
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = (init?.method ?? "GET").toUpperCase()
      const body = init?.body ? JSON.parse(String(init.body)) : null
      calls.push({ url, method, body })
      const json = (data: unknown) =>
        new Response(JSON.stringify(data), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      if (url.endsWith("/api/agent/chats") && method === "GET") return json({ items: SESSIONS })
      if (url.includes("/api/agent/chats/") && method === "PATCH") {
        return json({ ...SESSIONS[1], title: (body as { title: string }).title })
      }
      return json({})
    }),
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  localStorage.clear()
})

function renderNav(path = "/jobs") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AgentSessionsProvider>
        <AgentNavSessions />
        <Routes>
          <Route path="/chat" element={<div>экран агента</div>} />
          <Route path="/jobs" element={<div>раздел вакансий</div>} />
        </Routes>
      </AgentSessionsProvider>
    </MemoryRouter>,
  )
}

describe("AgentNavSessions — диалоги в основном меню (U-5)", () => {
  it("первые 8 диалогов и «Ещё N»; клик из другого раздела ведёт на экран агента", async () => {
    renderNav()
    expect(await screen.findByText("2. Ошибка инструмента")).toBeTruthy()
    expect(screen.queryByText("Диалог 10")).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: "Ещё 2" }))
    expect(screen.getByText("Диалог 10")).toBeTruthy()
    // В другом разделе ни один диалог не подсвечен.
    expect(screen.getByRole("button", { name: "2. Ошибка инструмента" }).getAttribute("aria-current")).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: "2. Ошибка инструмента" }))
    expect(await screen.findByText("экран агента")).toBeTruthy()
    expect(screen.getByRole("button", { name: "2. Ошибка инструмента" }).getAttribute("aria-current")).toBe(
      "page",
    )
  })

  it("переименование двойным кликом уходит PATCH-ем", async () => {
    renderNav("/chat")
    fireEvent.doubleClick(await screen.findByRole("button", { name: "2. Ошибка инструмента" }))
    const input = screen.getByRole("textbox", { name: "Название диалога" })
    fireEvent.change(input, { target: { value: "2. Ошибка" } })
    fireEvent.keyDown(input, { key: "Enter" })
    await waitFor(() =>
      expect(calls.some((c) => c.method === "PATCH" && c.url.endsWith("/api/agent/chats/2"))).toBe(true),
    )
    expect(await screen.findByText("2. Ошибка")).toBeTruthy()
  })
})
