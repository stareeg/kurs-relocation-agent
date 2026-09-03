// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, render, screen, within } from "@testing-library/react"
import type { CompanyRegistryItem } from "@/api/companies"
import { CompaniesBoard } from "./CompaniesBoard"

afterEach(() => {
  cleanup()
})

function item(partial: Partial<CompanyRegistryItem> & { company: string }): CompanyRegistryItem {
  return {
    vacancy_count: 1,
    avg_score: 50,
    best_stage: null,
    last_seen_at: null,
    verdict: "neutral",
    ...partial,
  }
}

describe("CompaniesBoard", () => {
  it("карточка показывает только дату последнего контакта, без служебных цифр/стадий", () => {
    render(
      <CompaniesBoard
        target={[]}
        avoid={[]}
        candidates={[
          item({
            company: "Яндекс",
            vacancy_count: 3,
            avg_score: 72.4,
            best_stage: "Скрининг",
            last_seen_at: "2026-07-12T10:00:00Z",
          }),
        ]}
        onChange={vi.fn()}
      />,
    )
    const zone = screen.getByTestId("company-zone-candidates")
    expect(within(zone).getByText("Яндекс")).toBeTruthy()
    // Только дата, без «N·M» и без названия стадии.
    expect(within(zone).getByText("12.07")).toBeTruthy()
    expect(within(zone).queryByText(/3·72/)).toBeNull()
    expect(within(zone).queryByText(/Скрининг/)).toBeNull()
  })

  it("поиск фильтрует кандидатов по подстроке имени", () => {
    render(
      <CompaniesBoard
        target={[]}
        avoid={[]}
        candidates={[item({ company: "Яндекс" }), item({ company: "Авито" })]}
        query="янд"
        onChange={vi.fn()}
      />,
    )
    const zone = screen.getByTestId("company-zone-candidates")
    expect(within(zone).getByText("Яндекс")).toBeTruthy()
    expect(within(zone).queryByText("Авито")).toBeNull()
  })

  it("поиск ищет по всем трём колонкам, не только по кандидатам", () => {
    render(
      <CompaniesBoard
        target={["Сбер"]}
        avoid={["Тинькофф"]}
        candidates={[item({ company: "Авито" }), item({ company: "Яндекс" })]}
        query="сбер"
        onChange={vi.fn()}
      />,
    )
    // Совпадение в «Целевых» остаётся, кандидаты и «Избегать» без совпадений пустеют.
    expect(within(screen.getByTestId("company-zone-target")).getByText("Сбер")).toBeTruthy()
    expect(within(screen.getByTestId("company-zone-candidates")).queryByText("Авито")).toBeNull()
    expect(within(screen.getByTestId("company-zone-candidates")).queryByText("Яндекс")).toBeNull()
    expect(within(screen.getByTestId("company-zone-avoid")).queryByText("Тинькофф")).toBeNull()
  })

  it("запрос без совпадений — подсказка «ничего не найдено», не общий пустой реестр", () => {
    render(
      <CompaniesBoard
        target={[]}
        avoid={[]}
        candidates={[item({ company: "Яндекс" })]}
        query="несуществует"
        onChange={vi.fn()}
      />,
    )
    const zone = screen.getByTestId("company-zone-candidates")
    expect(within(zone).getByText("Ничего не найдено по «несуществует»")).toBeTruthy()
  })

  it("пустой реестр — подсказка добавить компанию вручную", () => {
    render(<CompaniesBoard target={[]} avoid={[]} candidates={[]} onChange={vi.fn()} />)
    const zone = screen.getByTestId("company-zone-candidates")
    expect(within(zone).getByText(/Пока пусто/)).toBeTruthy()
  })
})
