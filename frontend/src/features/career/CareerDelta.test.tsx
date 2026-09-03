// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import type { CareerDelta as CareerDeltaData } from "@/api/career"
import { CareerDelta } from "./CareerDelta"

const fetchCareerDelta = vi.fn()

vi.mock("@/api/career", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/career")>()
  return {
    ...actual,
    fetchCareerDelta: () => fetchCareerDelta(),
  }
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

function renderDelta() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const { container } = render(
    <QueryClientProvider client={qc}>
      <CareerDelta />
    </QueryClientProvider>,
  )
  return container
}

function delta(overrides: Partial<CareerDeltaData> = {}): CareerDeltaData {
  return {
    window_days: 30,
    resume_score_was: 70,
    resume_score_now: 86,
    active_applications_was: 5,
    active_applications_now: 12,
    response_rate_was: 0.2,
    response_rate_now: 0.35,
    new_facts_count: 2,
    new_milestones_count: 1,
    ...overrides,
  }
}

describe("CareerDelta (Э9.5)", () => {
  it("null (меньше двух точек истории) — блок не рендерится вовсе", async () => {
    fetchCareerDelta.mockResolvedValue(null)
    const container = renderDelta()
    await waitFor(() => expect(fetchCareerDelta).toHaveBeenCalled())
    expect(container.textContent).toBe("")
  })

  it("свёрнуто по умолчанию, строки появляются после клика", async () => {
    fetchCareerDelta.mockResolvedValue(delta())
    renderDelta()
    await waitFor(() => expect(screen.getByText("Что изменилось за 30 дней")).toBeTruthy())
    expect(screen.queryByText("Балл резюме: 70 → 86")).toBeNull()

    fireEvent.click(screen.getByText("Что изменилось за 30 дней"))

    expect(screen.getByText("Балл резюме: 70 → 86")).toBeTruthy()
    expect(screen.getByText("Активные отклики: 5 → 12")).toBeTruthy()
    expect(screen.getByText("Конверсия отклик → скрининг: 20% → 35%")).toBeTruthy()
    expect(screen.getByText("Новых фактов и вех за 30 дней: 3")).toBeTruthy()
  })

  it("метрика без обеих точек не показывается, остальные — да", async () => {
    fetchCareerDelta.mockResolvedValue(
      delta({ response_rate_was: null, new_facts_count: 0, new_milestones_count: 0 }),
    )
    renderDelta()
    await waitFor(() => expect(screen.getByText("Что изменилось за 30 дней")).toBeTruthy())
    fireEvent.click(screen.getByText("Что изменилось за 30 дней"))

    expect(screen.getByText("Балл резюме: 70 → 86")).toBeTruthy()
    expect(screen.queryByText(/Конверсия/)).toBeNull()
    expect(screen.queryByText(/Новых фактов/)).toBeNull()
  })
})
