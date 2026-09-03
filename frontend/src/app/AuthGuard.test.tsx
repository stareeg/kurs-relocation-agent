// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type { AuthStatus } from "@/api/auth"
import { AuthProvider } from "@/features/auth/AuthProvider"
import { AuthGuard } from "./AuthGuard"

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

function authStatus(overrides: Partial<AuthStatus> = {}): AuthStatus {
  return {
    authed: false,
    auth_token_configured: false,
    openrouter_key_configured: false,
    extension_confirmed: false,
    bot_configured: false,
    bot_username: null,
    account_username: null,
    is_admin: false,
    ...overrides,
  }
}

function stubStatusFetch(payload: AuthStatus) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes("/auth/status")) return json(payload)
      return json({})
    }),
  )
}

function renderAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <AuthProvider>
          <Routes>
            <Route element={<AuthGuard />}>
              <Route path="/jobs" element={<div>JOBS</div>} />
              <Route path="/extension" element={<div>EXTENSION</div>} />
              <Route path="/settings" element={<div>SETTINGS</div>} />
            </Route>
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  localStorage.clear()
})

// AUTH-1: гейт разделов — прямые URL не обходят онбординг, «Параметры» доступны всегда.
describe("AuthGuard — гейт онбординга", () => {
  it("онбординг не завершён (нет токена) → любой раздел редиректит в Параметры", async () => {
    stubStatusFetch(authStatus({ authed: true })) // bootstrap: периметр открыт, токена нет
    renderAt("/jobs")
    await waitFor(() => expect(screen.getByText("SETTINGS")).toBeTruthy())
    expect(screen.queryByText("JOBS")).toBeNull()
  })

  it("гейт закрыт → даже Расширение недоступно до токена и ключа", async () => {
    stubStatusFetch(authStatus({ authed: true, openrouter_key_configured: true }))
    renderAt("/extension")
    await waitFor(() => expect(screen.getByText("SETTINGS")).toBeTruthy())
  })

  it("anon (токен выпущен, cookie нет) → Параметры рендерятся без цикла редиректов", async () => {
    stubStatusFetch(authStatus({ auth_token_configured: true }))
    renderAt("/settings")
    await waitFor(() => expect(screen.getByText("SETTINGS")).toBeTruthy())
  })

  it("anon на защищённом разделе → в Параметры", async () => {
    stubStatusFetch(authStatus({ auth_token_configured: true, openrouter_key_configured: true }))
    renderAt("/jobs")
    await waitFor(() => expect(screen.getByText("SETTINGS")).toBeTruthy())
  })

  it("онбординг завершён → раздел открывается", async () => {
    stubStatusFetch(
      authStatus({
        authed: true,
        auth_token_configured: true,
        openrouter_key_configured: true,
        extension_confirmed: true,
      }),
    )
    renderAt("/jobs")
    await waitFor(() => expect(screen.getByText("JOBS")).toBeTruthy())
  })

  it("гейт открыт без подтверждения расширения → разделы уже доступны (кнопка не блокирует)", async () => {
    stubStatusFetch(
      authStatus({
        authed: true,
        auth_token_configured: true,
        openrouter_key_configured: true,
        extension_confirmed: false,
      }),
    )
    renderAt("/jobs")
    await waitFor(() => expect(screen.getByText("JOBS")).toBeTruthy())
  })
})
