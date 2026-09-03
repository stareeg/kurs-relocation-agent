// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { cleanup, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { AuthProvider } from "./AuthProvider"
import { useAuth } from "./auth-context"

const PERSIST_KEY = "cc-query-cache"
const ERROR_CAPTURE_KEY = "copilot.error-capture.v1"

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

const AUTHED_STATUS = {
  authed: true,
  auth_token_configured: true,
  openrouter_key_configured: true,
  extension_confirmed: true,
  bot_configured: true,
  bot_username: "copilot_bot",
  account_username: "owner",
}

function Consumer() {
  const { status, login, logout, logoutEverywhere } = useAuth()
  return (
    <div>
      <span data-testid="status">{status}</span>
      <button onClick={() => void logout()}>logout</button>
      <button onClick={() => void logoutEverywhere()}>logout-everywhere</button>
      <button onClick={() => void login("tok-1").catch(() => undefined)}>login</button>
    </div>
  )
}

function renderAuth(qc: QueryClient) {
  return render(
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <Consumer />
      </AuthProvider>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  localStorage.clear()
})

// P-10: и протухшая сессия (401), и явный логаут должны сбрасывать не только in-memory
// кэш react-query, но и то, что уже осело в localStorage — иначе следующий вход на этой же
// машине на миг гидратируется чужими/устаревшими данными раньше первого фонового refetch.
describe("AuthProvider — сброс кэша (P-10)", () => {
  beforeEach(() => {
    localStorage.setItem(
      PERSIST_KEY,
      JSON.stringify({ clientState: { queries: [], mutations: [] } }),
    )
    // Этап 2 (§3.1): буфер error-capture должен чиститься тем же жестом, что и query-кэш —
    // иначе незафлашенные ошибки аккаунта A долетают на бэк уже под сессией аккаунта B.
    localStorage.setItem(ERROR_CAPTURE_KEY, JSON.stringify([{ ts: "x", level: "ERROR" }]))
  })

  it("протухшая сессия (401 на /auth/status) чистит и qc, и persisted-кэш, и error-capture", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json({ detail: "unauthorized" }, 401)),
    )
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    qc.setQueryData(["probe"], "stale-data")

    renderAuth(qc)

    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("anon"))
    await waitFor(() => expect(localStorage.getItem(PERSIST_KEY)).toBeNull())
    expect(qc.getQueryData(["probe"])).toBeUndefined()
    expect(JSON.parse(localStorage.getItem(ERROR_CAPTURE_KEY) ?? "[]")).toEqual([])
  })

  it("логаут чистит и qc, и persisted-кэш, и error-capture", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes("/auth/logout")) return json({})
        return json(AUTHED_STATUS) // /auth/status — успех, статус "authed"
      }),
    )
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    qc.setQueryData(["probe"], "stale-data")

    renderAuth(qc)
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("authed"))

    screen.getByText("logout").click()

    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("anon"))
    await waitFor(() => expect(localStorage.getItem(PERSIST_KEY)).toBeNull())
    expect(qc.getQueryData(["probe"])).toBeUndefined()
    expect(JSON.parse(localStorage.getItem(ERROR_CAPTURE_KEY) ?? "[]")).toEqual([])
  })

  it("«Выйти на всех устройствах» чистит и qc, и persisted-кэш, и error-capture", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes("/auth/sessions/revoke-all")) return json({ revoked: 2 })
        return json(AUTHED_STATUS)
      }),
    )
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    qc.setQueryData(["probe"], "stale-data")

    renderAuth(qc)
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("authed"))

    screen.getByText("logout-everywhere").click()

    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("anon"))
    await waitFor(() => expect(localStorage.getItem(PERSIST_KEY)).toBeNull())
    expect(qc.getQueryData(["probe"])).toBeUndefined()
    expect(JSON.parse(localStorage.getItem(ERROR_CAPTURE_KEY) ?? "[]")).toEqual([])
  })
})

// AUTH-1: вход по токену из бота.
describe("AuthProvider — вход по токену", () => {
  it("authed=false в /auth/status → anon (периметр закрыт, cookie нет)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json({ ...AUTHED_STATUS, authed: false })),
    )
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    renderAuth(qc)
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("anon"))
  })

  it("успешный POST /auth/token переводит в authed и кладёт статус в кэш", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes("/auth/token")) return json(AUTHED_STATUS)
        return json({ ...AUTHED_STATUS, authed: false, auth_token_configured: true })
      }),
    )
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    renderAuth(qc)
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("anon"))

    screen.getByText("login").click()

    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("authed"))
    expect(qc.getQueryData(["auth", "status"])).toMatchObject({ authed: true })
  })

  it("неверный токен (401) не роняет в anon-цикл: статус остаётся anon, без исключений наружу", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes("/auth/token")) return json({ detail: "Токен не подходит" }, 401)
        return json({ ...AUTHED_STATUS, authed: false })
      }),
    )
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    renderAuth(qc)
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("anon"))

    screen.getByText("login").click()

    // Ошибка обрабатывается формой (catch), глобальный статус не меняется.
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("anon"))
  })
})
