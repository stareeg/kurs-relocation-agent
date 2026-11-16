// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, render, screen } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MemoryRouter } from "react-router-dom"
import type { AuthStatus } from "@/api/auth"
import { SectionRoute } from "@/app/SectionRoute"
import { homeTarget } from "./onboarding"
import { isSectionVisible } from "./sections"
import { AUTH_STATUS_KEY } from "./use-auth-status"

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const COURSE: Record<string, boolean> = {
  agent: true,
  jobs: true,
  resume: true,
  screening: false,
  tech: false,
  offers: false,
  extension_nav: false,
  market: false,
  companies: false,
  career: false,
  multiplayer: false,
  today: false,
}

function status(overrides: Partial<AuthStatus> = {}): AuthStatus {
  return {
    authed: true,
    auth_token_configured: true,
    openrouter_key_configured: true,
    server_llm_available: true,
    extension_confirmed: false,
    bot_configured: true,
    bot_username: null,
    account_username: null,
    is_admin: false,
    features: COURSE,
    ...overrides,
  } as AuthStatus
}

describe("U-0: разделы в режиме курса", () => {
  it("видимость по флагам; без флага или статуса — раздел виден", () => {
    expect(isSectionVisible(status(), "agent")).toBe(true)
    expect(isSectionVisible(status(), "market")).toBe(false)
    expect(isSectionVisible(status({ features: {} }), "market")).toBe(true)
    expect(isSectionVisible(undefined, "market")).toBe(true)
  })

  it("стартовая страница — агент, шаг расширения пропускается, если «Автоотклики» скрыты", () => {
    expect(homeTarget(status())).toBe("/chat")
    expect(homeTarget(status({ features: { ...COURSE, extension_nav: true } }))).toBe("/extension")
  })

  it("адрес скрытого раздела отдаёт «страницы нет», видимого — саму страницу", () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    qc.setQueryData(AUTH_STATUS_KEY, status())
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(status()), { status: 200 })))
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <SectionRoute section="market">
            <div>РЫНОК</div>
          </SectionRoute>
          <SectionRoute section="jobs">
            <div>ВАКАНСИИ</div>
          </SectionRoute>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(screen.queryByText("РЫНОК")).toBeNull()
    expect(screen.getByText("ВАКАНСИИ")).toBeTruthy()
  })
})
