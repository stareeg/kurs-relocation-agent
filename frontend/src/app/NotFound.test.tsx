// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest"
import { cleanup, render, screen } from "@testing-library/react"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { NotFound } from "./NotFound"

// Этап 1.6 плана `plans/ui_slop_cleanup_2026_08_25.md`: неизвестный адрес больше не уводит молча
// на доску. Опечатка в ссылке выглядела как «раздел удалили» — теперь экран честно называет
// адрес, по которому пришли, и оставляет выход.

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="*" element={<NotFound />} />
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(cleanup)

describe("NotFound", () => {
  it("называет, что страницы нет, и показывает запрошенный адрес", () => {
    renderAt("/nonexistent")
    expect(screen.getByText("Такой страницы нет")).toBeTruthy()
    expect(screen.getByText(/\/nonexistent/)).toBeTruthy()
  })

  it("даёт выход на доску вакансий", () => {
    renderAt("/jobs-old")
    const link = screen.getByRole("link", { name: "На доску вакансий" })
    expect(link.getAttribute("href")).toBe("/jobs")
  })

  it("подставляет именно текущий путь, а не заглушку", () => {
    renderAt("/market/legacy-report")
    expect(screen.getByText(/\/market\/legacy-report/)).toBeTruthy()
  })
})
