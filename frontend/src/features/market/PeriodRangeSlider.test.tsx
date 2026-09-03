// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { MemoryRouter, useSearchParams } from "react-router-dom"
import { afterEach, describe, expect, it, vi } from "vitest"
import { PeriodRangeSlider } from "./PeriodRangeSlider"

vi.mock("@/api/market", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/market")>()
  return {
    ...actual,
    fetchOfferChanceHistory: vi.fn().mockResolvedValue({ available: false, points: [] }),
  }
})

afterEach(() => {
  cleanup()
  sessionStorage.clear()
  vi.restoreAllMocks()
})

function CurrentRange() {
  const [searchParams] = useSearchParams()
  return <span data-testid="range">{searchParams.get("range") ?? "none"}</span>
}

function renderSlider(initialEntries: string[]) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={initialEntries}>
        <PeriodRangeSlider />
        <CurrentRange />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function valueNow(el: HTMLElement): string | null {
  return el.getAttribute("aria-valuenow")
}

describe("PeriodRangeSlider (правка 2026-08-03)", () => {
  it("без параметра в адресе — 14 дней назад по сегодня", () => {
    renderSlider(["/market"])
    expect(valueNow(screen.getByRole("slider", { name: "Начало периода" }))).toBe("14")
    expect(valueNow(screen.getByRole("slider", { name: "Конец периода" }))).toBe("0")
  })

  it("читает диапазон из ?range=", () => {
    renderSlider(["/market?range=30-5"])
    expect(valueNow(screen.getByRole("slider", { name: "Начало периода" }))).toBe("30")
    expect(valueNow(screen.getByRole("slider", { name: "Конец периода" }))).toBe("5")
  })

  it("стрелка влево на левой границе отодвигает её ещё дальше в прошлое и пишет в адрес", () => {
    renderSlider(["/market?range=14-0"])
    const fromHandle = screen.getByRole("slider", { name: "Начало периода" })
    fireEvent.keyDown(fromHandle, { key: "ArrowLeft" })
    expect(valueNow(fromHandle)).toBe("15")
    expect(screen.getByTestId("range").textContent).toBe("15-0")
  })

  it("стрелка вправо на правой границе не уходит правее сегодняшнего дня", () => {
    renderSlider(["/market?range=14-0"])
    const toHandle = screen.getByRole("slider", { name: "Конец периода" })
    fireEvent.keyDown(toHandle, { key: "ArrowRight" })
    expect(valueNow(toHandle)).toBe("0")
  })

  it("Shift+стрелка двигает границу на неделю", () => {
    renderSlider(["/market?range=30-0"])
    const fromHandle = screen.getByRole("slider", { name: "Начало периода" })
    fireEvent.keyDown(fromHandle, { key: "ArrowLeft", shiftKey: true })
    expect(valueNow(fromHandle)).toBe("37")
  })

  it("правая граница останавливается у левой с зазором в сутки, не сдвигая её", () => {
    renderSlider(["/market?range=10-0"])
    const toHandle = screen.getByRole("slider", { name: "Конец периода" })
    const fromHandle = screen.getByRole("slider", { name: "Начало периода" })
    fireEvent.keyDown(toHandle, { key: "ArrowLeft", shiftKey: true })
    expect(valueNow(toHandle)).toBe("7")
    // Ещё неделя упёрлась бы в 14, но левее 9 (from - 1) конец уйти не может.
    fireEvent.keyDown(toHandle, { key: "ArrowLeft", shiftKey: true })
    expect(valueNow(toHandle)).toBe("9")
    expect(valueNow(fromHandle)).toBe("10")
  })
})
