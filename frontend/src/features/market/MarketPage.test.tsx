// @vitest-environment jsdom
/**
 * F-05 (редизайн 2026-08-09, правка 2026-08-09): лейаут «Рынка» читается тремя рядами —
 * Где стою (зарплаты | шанс офферов) / Поток (воронка | что режет поток) / Реакция рынка
 * (форматы | отклик резюме во времени). Под ними чат по ситуации. Все карточки грузятся
 * независимо. Гистограммы CategoryBars вместо полос сегментами; блок «Зарплатная планка»
 * (контрфакты-ступени) удалён.
 */
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { cleanup, render, screen } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MemoryRouter } from "react-router-dom"
import { MarketPage } from "./MarketPage"

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

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      const json = (body: unknown) =>
        new Response(JSON.stringify(body), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      // Все ручки возвращают пустой/недоступный ответ — карточки показывают empty/loading,
      // но скелет страницы рисуется, чат доступен.
      if (url.includes("/api/market/overview")) return json({ available: false })
      if (url.includes("/api/career/track"))
        return json({ tracks: ["primary"], labels: ["Основная"], second_job_enabled: false })
      if (url.includes("/api/market/chat")) return json({ items: [] })
      if (url.includes("/api/analytics/offer-chance-history"))
        return json({ available: false, points: [] })
      if (url.includes("/api/resume-stats")) return json({ available: false, points: [] })
      return json({})
    }),
  )
})

function renderMarket() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/market"]}>
        <MarketPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe("MarketPage двухколоночный лейаут (F-05)", () => {
  it("рендерит карточки левой и правой колонок + чат по ситуации", () => {
    renderMarket()
    // Левые (гистограммы/сегментные бары).
    expect(screen.getByRole("region", { name: "Зарплаты" })).toBeTruthy()
    expect(screen.getByRole("region", { name: "Воронка" })).toBeTruthy()
    expect(screen.getByRole("region", { name: "Причины в пропуске" })).toBeTruthy()
    expect(screen.getByRole("region", { name: "Условия" })).toBeTruthy()
    // Правые (линейные графики во времени).
    expect(screen.getByRole("region", { name: "Шанс офферов" })).toBeTruthy()
    expect(screen.getByRole("region", { name: "Площадки" })).toBeTruthy()
  })

  it("поле ввода чата по ситуации доступно на старте", () => {
    renderMarket()
    const textarea = screen.getByPlaceholderText(/ситуацию на рынке/i)
    expect(textarea).toBeTruthy()
  })

  it("блок «Что сделать» удалён (заменён чатом)", () => {
    renderMarket()
    expect(screen.queryByRole("region", { name: "Что сделать" })).toBeNull()
  })
})
