// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { afterEach, describe, expect, it, vi } from "vitest"
import type { CareerSnapshot } from "@/api/career"
import { CareerSnapshotStrip } from "./CareerSnapshotStrip"

const fetchCareerSnapshot = vi.fn()

vi.mock("@/api/career", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/career")>()
  return {
    ...actual,
    fetchCareerSnapshot: () => fetchCareerSnapshot(),
  }
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

function renderStrip() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <CareerSnapshotStrip />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function snapshot(overrides: Partial<CareerSnapshot> = {}): CareerSnapshot {
  return {
    employment: "unknown",
    search_mode_label: "",
    market_scope_label: "",
    tracks: [],
    days_active: null,
    active_applications: 0,
    stalled: 0,
    resume_score: null,
    ...overrides,
  }
}

describe("CareerSnapshotStrip (Э9.2)", () => {
  it("свежий аккаунт — честное пустое состояние, не нули", async () => {
    fetchCareerSnapshot.mockResolvedValue(snapshot())
    renderStrip()
    await waitFor(() => expect(screen.getByText("Ещё ничего не оценивали")).toBeTruthy())
    expect(screen.queryByText(/активных откликов/)).toBeNull()
  })

  it("собирает заголовок из занятости, режима, рынка и дней", async () => {
    fetchCareerSnapshot.mockResolvedValue(
      snapshot({
        employment: "employed",
        search_mode_label: "Активно ищу",
        market_scope_label: "Только РФ",
        days_active: 47,
      }),
    )
    renderStrip()
    await waitFor(() =>
      expect(
        screen.getByText("Работаю · Активно ищу · Только РФ · 47 дн."),
      ).toBeTruthy(),
    )
  })

  it("показывает «без движения» только когда застрявшие есть", async () => {
    fetchCareerSnapshot.mockResolvedValue(
      snapshot({ days_active: 10, active_applications: 12, stalled: 3, resume_score: 86 }),
    )
    renderStrip()
    await waitFor(() => expect(screen.getByText("12")).toBeTruthy())
    expect(screen.getByText("3")).toBeTruthy()
    expect(screen.getByText("без движения")).toBeTruthy()
    expect(screen.getByText("86")).toBeTruthy()
  })

  it("не показывает «без движения», когда застрявших нет", async () => {
    fetchCareerSnapshot.mockResolvedValue(
      snapshot({ days_active: 10, active_applications: 5, stalled: 0 }),
    )
    renderStrip()
    await waitFor(() => expect(screen.getByText("5")).toBeTruthy())
    expect(screen.queryByText("без движения")).toBeNull()
  })

  it("второй трек попадает в заголовок только когда их больше одного", async () => {
    fetchCareerSnapshot.mockResolvedValue(
      snapshot({
        days_active: 1,
        tracks: ["Основная работа", "Вторая работа"],
        search_mode_label: "Активно ищу",
      }),
    )
    renderStrip()
    await waitFor(() =>
      expect(screen.getByText(/Основная работа \+ Вторая работа/)).toBeTruthy(),
    )
  })
})
