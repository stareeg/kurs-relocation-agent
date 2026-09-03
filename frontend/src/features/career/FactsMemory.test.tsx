// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import type { CareerFact, PortfolioItem } from "@/api/career"
import { FactsMemory } from "./FactsMemory"

const fetchFacts = vi.fn()
const patchFact = vi.fn()
const deleteFact = vi.fn()
const listPortfolioItems = vi.fn()
const deletePortfolioItem = vi.fn()

vi.mock("@/api/career", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/career")>()
  return {
    ...actual,
    fetchFacts: () => fetchFacts(),
    patchFact: (id: number, body: unknown) => patchFact(id, body),
    deleteFact: (id: number) => deleteFact(id),
    listPortfolioItems: () => listPortfolioItems(),
    deletePortfolioItem: (id: number) => deletePortfolioItem(id),
  }
})

vi.mock("@/features/jobs/use-jobs", () => ({ useJobs: () => ({ data: [] }) }))
vi.mock("@/features/tech/use-debrief", () => ({ useDebriefHistory: () => ({ data: undefined }) }))
vi.mock("@/features/offers/use-offers", () => ({ useOffers: () => ({ data: [] }) }))

const writeText = vi.fn().mockResolvedValue(undefined)
Object.assign(navigator, { clipboard: { writeText } })

beforeEach(() => {
  fetchFacts.mockResolvedValue([])
  listPortfolioItems.mockResolvedValue([])
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  writeText.mockClear()
})

function renderMemory() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <FactsMemory />
    </QueryClientProvider>,
  )
}

function fact(overrides: Partial<CareerFact> = {}): CareerFact {
  return {
    id: 1,
    fact: "Подтянуть: System Design",
    fact_type: "skill_gap",
    source_kind: "debrief",
    source_ref: "vac-1",
    confidence: 0.75,
    recorded_at: "2026-08-01T10:00:00Z",
    expires_at: "2027-02-01T10:00:00Z",
    payload: {},
    created_at: "2026-08-01T10:00:00Z",
    ...overrides,
  }
}

function portfolioItem(overrides: Partial<PortfolioItem> = {}): PortfolioItem {
  return {
    id: 1,
    project: "ООО «ВебПродукт»",
    role: "Senior Frontend Developer",
    outcome: "Ускорил сборку на 30%",
    artifact_url: "",
    source_ref: "",
    notes: "",
    created_at: "2026-08-01T10:00:00Z",
    ...overrides,
  }
}

async function openAddMenu() {
  fireEvent.keyDown(screen.getByRole("button", { name: "Добавить" }), { key: "Enter" })
}

describe("FactsMemory (правка 2026-08-26: Достижения+Пробелы, без Заметок)", () => {
  it("пустая память — честное пустое состояние в обеих колонках, но кнопка «Добавить» доступна", async () => {
    renderMemory()
    await waitFor(() => expect(screen.getByText("Достижений пока нет")).toBeTruthy())
    expect(screen.getByText("Пробелов нет")).toBeTruthy()
    expect(screen.getByRole("button", { name: "Добавить" })).toBeTruthy()
  })

  it("сильные стороны и портфолио уходят в «Достижения», пробелы — в «Пробелы»", async () => {
    fetchFacts.mockResolvedValue([
      fact({ id: 1, fact_type: "strength", fact: "Сильный ответ про архитектуру" }),
      fact({ id: 2, fact_type: "skill_gap", fact: "Подтянуть System Design" }),
    ])
    renderMemory()
    await waitFor(() => expect(screen.getByText("Достижения")).toBeTruthy())
    expect(screen.getByText("Пробелы")).toBeTruthy()
    expect(screen.getByText("Сильный ответ про архитектуру")).toBeTruthy()
    expect(screen.getByText("Подтянуть System Design")).toBeTruthy()
  })

  it("«Заметки» больше не показываются вообще", async () => {
    fetchFacts.mockResolvedValue([fact({ id: 1, fact_type: "note", fact: "Случайная заметка" })])
    renderMemory()
    await waitFor(() => expect(screen.getByText(/1 активных/)).toBeTruthy())
    expect(screen.queryByText("Заметки")).toBeNull()
    expect(screen.queryByText("Случайная заметка")).toBeNull()
  })

  it("достижения из портфолио и сильных сторон объединены в одном списке", async () => {
    fetchFacts.mockResolvedValue([fact({ id: 1, fact_type: "strength", fact: "Сильный ответ" })])
    listPortfolioItems.mockResolvedValue([portfolioItem()])
    renderMemory()
    await waitFor(() => expect(screen.getByText("Сильный ответ")).toBeTruthy())
    expect(screen.getByText("ООО «ВебПродукт»")).toBeTruthy()
  })

  it("копирует проект + роль + результат достижения из портфолио", async () => {
    listPortfolioItems.mockResolvedValue([portfolioItem()])
    renderMemory()
    await waitFor(() => expect(screen.getByText("ООО «ВебПродукт»")).toBeTruthy())

    fireEvent.click(screen.getByText("Копировать"))

    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith(
        "ООО «ВебПродукт» — Senior Frontend Developer\nУскорил сборку на 30%",
      ),
    )
  })

  it("удаление достижения-портфолио зовёт deletePortfolioItem с нужным id", async () => {
    listPortfolioItems.mockResolvedValue([portfolioItem({ id: 5 })])
    deletePortfolioItem.mockResolvedValue(undefined)
    renderMemory()
    await waitFor(() => expect(screen.getByTitle("Удалить")).toBeTruthy())

    fireEvent.click(screen.getByTitle("Удалить"))
    await waitFor(() => expect(deletePortfolioItem).toHaveBeenCalledWith(5))
  })

  it("кнопка добавления называется «Добавить», а не «Добавить достижение»", async () => {
    renderMemory()
    await waitFor(() => expect(screen.getByRole("button", { name: "Добавить" })).toBeTruthy())
  })

  it("три формы схлопнуты за кнопку «Добавить» — по умолчанию форм не видно", async () => {
    renderMemory()
    await waitFor(() => expect(screen.getByRole("button", { name: "Добавить" })).toBeTruthy())
    expect(screen.queryByPlaceholderText("Проект/компания")).toBeNull()
    expect(screen.queryByText("Вакансия с разбором")).toBeNull()
  })

  it("пункт меню «Вручную» раскрывает форму ручного добавления", async () => {
    renderMemory()
    await waitFor(() => expect(screen.getByRole("button", { name: "Добавить" })).toBeTruthy())

    await openAddMenu()
    fireEvent.click(await screen.findByText("Вручную"))

    expect(await screen.findByPlaceholderText("Проект/компания")).toBeTruthy()
  })

  it("пункт меню «Из разбора» раскрывает форму разбора, «Отмена» её скрывает", async () => {
    renderMemory()
    await waitFor(() => expect(screen.getByRole("button", { name: "Добавить" })).toBeTruthy())

    await openAddMenu()
    fireEvent.click(await screen.findByText("Из разбора"))
    expect(await screen.findByText("Вакансия с разбором")).toBeTruthy()

    fireEvent.click(screen.getByRole("button", { name: "Отмена" }))
    await waitFor(() => expect(screen.queryByText("Вакансия с разбором")).toBeNull())
  })

  it("в строках «Достижения»/«Пробелы» нет строки источника и кнопки «Поправить»", async () => {
    fetchFacts.mockResolvedValue([
      fact({ id: 1, fact_type: "strength", fact: "Сильный ответ", source_kind: "debrief" }),
      fact({ id: 2, fact_type: "skill_gap", fact: "Пробел в знаниях", source_kind: "debrief" }),
    ])
    renderMemory()
    await waitFor(() => expect(screen.getByText("Сильный ответ")).toBeTruthy())

    expect(screen.queryByText("разбор собеседования")).toBeNull()
    expect(screen.queryByTitle("Поправить")).toBeNull()
  })

  it("в строке остальных типов факта (не Достижения/Пробелы) «Поправить» остаётся", async () => {
    fetchFacts.mockResolvedValue([fact({ id: 1, fact_type: "preference", fact: "Удалёнка" })])
    renderMemory()
    await waitFor(() => expect(screen.getByText("Удалёнка")).toBeTruthy())
    expect(screen.getByTitle("Поправить")).toBeTruthy()
  })

  it("правка текста работает для остальных типов факта (не Достижения/Пробелы)", async () => {
    fetchFacts.mockResolvedValue([fact({ id: 7, fact_type: "preference", fact: "Старый текст" })])
    patchFact.mockResolvedValue(fact({ id: 7, fact: "Новый текст" }))
    renderMemory()
    await waitFor(() => expect(screen.getByText("Старый текст")).toBeTruthy())

    fireEvent.click(screen.getByTitle("Поправить"))
    const textarea = screen.getByDisplayValue("Старый текст")
    fireEvent.change(textarea, { target: { value: "Новый текст" } })
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }))

    await waitFor(() => expect(patchFact).toHaveBeenCalledWith(7, { fact: "Новый текст" }))
  })

  it("дата факта в «Пробелах» показана слева (короткая дата не сегодняшнего дня)", async () => {
    fetchFacts.mockResolvedValue([fact({ id: 1, recorded_at: "2026-08-01T10:00:00Z" })])
    renderMemory()
    await waitFor(() => expect(screen.getByText(/авг/)).toBeTruthy())
  })

  it("закреплённый факт в «Пробелах» помечен и без кнопки «Закрепить»", async () => {
    fetchFacts.mockResolvedValue([fact({ id: 1, expires_at: null })])
    renderMemory()
    await waitFor(() => expect(screen.getByText("Закреплено")).toBeTruthy())
    expect(screen.queryByTitle("Закрепить")).toBeNull()
  })

  it("клик «Закрепить» в «Пробелах» шлёт pinned: true для нужного id", async () => {
    fetchFacts.mockResolvedValue([fact({ id: 42 })])
    patchFact.mockResolvedValue(fact({ id: 42, expires_at: null }))
    renderMemory()
    await waitFor(() => expect(screen.getByTitle("Закрепить")).toBeTruthy())

    fireEvent.click(screen.getByTitle("Закрепить"))
    await waitFor(() => expect(patchFact).toHaveBeenCalledWith(42, { pinned: true }))
  })

  it("удаление в «Пробелах» зовёт deleteFact с нужным id", async () => {
    fetchFacts.mockResolvedValue([fact({ id: 3 })])
    deleteFact.mockResolvedValue(undefined)
    renderMemory()
    await waitFor(() => expect(screen.getByTitle("Удалить")).toBeTruthy())

    fireEvent.click(screen.getByTitle("Удалить"))
    await waitFor(() => expect(deleteFact).toHaveBeenCalledWith(3))
  })

  it("процент уверенности на строке не показывается", async () => {
    fetchFacts.mockResolvedValue([fact({ id: 1, confidence: 0.75 })])
    renderMemory()
    await waitFor(() => expect(screen.getByText("Подтянуть: System Design")).toBeTruthy())
    expect(screen.queryByText("75%")).toBeNull()
  })

  it("заголовок секции считает активные и закреплённые факты", async () => {
    fetchFacts.mockResolvedValue([
      fact({ id: 1, expires_at: "2027-01-01T00:00:00Z" }),
      fact({ id: 2, expires_at: null }),
    ])
    renderMemory()
    await waitFor(() => expect(screen.getByText(/2 активных/)).toBeTruthy())
    expect(screen.getByText(/1 закреплены/)).toBeTruthy()
  })

  it("«Пробелы» с более чем 6 фактами сворачиваются за «Показать все N»", async () => {
    const items = Array.from({ length: 8 }, (_, i) =>
      fact({ id: i + 1, fact: `Пробел номер ${i + 1}` }),
    )
    fetchFacts.mockResolvedValue(items)
    renderMemory()
    await waitFor(() => expect(screen.getByText("Пробел номер 1")).toBeTruthy())

    expect(screen.queryByText("Пробел номер 7")).toBeNull()
    expect(screen.getByRole("button", { name: "Показать все 8" })).toBeTruthy()

    fireEvent.click(screen.getByRole("button", { name: "Показать все 8" }))
    expect(screen.getByText("Пробел номер 7")).toBeTruthy()
  })

  it("длинный факт клипается и разворачивается по «Показать полностью»", async () => {
    const long = "Очень подробный разбор ".repeat(10).trim()
    fetchFacts.mockResolvedValue([fact({ id: 1, fact: long })])
    renderMemory()
    await waitFor(() => expect(screen.getByText("Показать полностью")).toBeTruthy())

    fireEvent.click(screen.getByText("Показать полностью"))
    expect(screen.getByText("Свернуть")).toBeTruthy()
  })

  it("остальные типы факта (например «Предпочтения») по-прежнему группируются под своим заголовком", async () => {
    fetchFacts.mockResolvedValue([fact({ id: 1, fact_type: "preference", fact: "Удалёнка" })])
    renderMemory()
    await waitFor(() => expect(screen.getByText("Предпочтения")).toBeTruthy())
    expect(screen.getByText("Удалёнка")).toBeTruthy()
  })
})
