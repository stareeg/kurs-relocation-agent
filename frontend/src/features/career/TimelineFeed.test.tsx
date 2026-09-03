// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { afterEach, describe, expect, it, vi } from "vitest"
import type { TimelineEventView } from "@/api/career"
import { TimelineFeed } from "./TimelineFeed"

const fetchTimeline = vi.fn()
const createTimelineEntry = vi.fn()

vi.mock("@/api/career", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/career")>()
  return {
    ...actual,
    fetchTimeline: (params?: unknown) => fetchTimeline(params),
    createTimelineEntry: (body: unknown) => createTimelineEntry(body),
  }
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

function renderFeed() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <TimelineFeed />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function event(overrides: Partial<TimelineEventView> = {}): TimelineEventView {
  return {
    id: 1,
    kind: "other",
    title: "Событие",
    occurred_at: "2026-08-01T10:00:00Z",
    payload: {},
    source_ref: "",
    created_at: "2026-08-01T10:00:00Z",
    company: "",
    vacancy_title: "",
    href: null,
    ...overrides,
  }
}

describe("TimelineFeed (Этап 3-5, plans/career_redesign_2026_08_26.md)", () => {
  it("пустая лента — честное пустое состояние, чипы быстрого добавления доступны", async () => {
    fetchTimeline.mockResolvedValue([])
    renderFeed()
    await waitFor(() =>
      expect(
        screen.getByText("Отклики, этапы, офферы и события появятся здесь по мере работы с вакансиями."),
      ).toBeTruthy(),
    )
    expect(screen.getByRole("button", { name: "Повышение" })).toBeTruthy()
    expect(screen.queryByRole("button", { name: "Другое" })).toBeNull()
  })

  it("группирует события по дню и показывает заголовки", async () => {
    fetchTimeline.mockResolvedValue([
      event({ id: 1, title: "Отклик · vac-1", occurred_at: "2026-08-05T10:00:00Z" }),
      event({ id: 2, title: "Скрининг · vac-1", occurred_at: "2026-07-20T10:00:00Z" }),
    ])
    renderFeed()
    await waitFor(() => expect(screen.getByText("Отклик · vac-1")).toBeTruthy())
    expect(screen.getByText("Скрининг · vac-1")).toBeTruthy()
    expect(screen.getByText("5 авг.")).toBeTruthy()
    expect(screen.getByText("20 июл.")).toBeTruthy()
  })

  it("заголовок вакансии — company/vacancy_title вместо id, кликабельный по href", async () => {
    fetchTimeline.mockResolvedValue([
      event({
        id: 1,
        kind: "offer",
        title: "Оффер · 135822816",
        payload: { vacancy_id: "135822816" },
        company: "МТС",
        vacancy_title: "Senior AI Engineer",
        href: "/chat?vacancy=135822816",
      }),
    ])
    renderFeed()
    await waitFor(() => expect(screen.getByText("МТС, Senior AI Engineer")).toBeTruthy())
    expect(screen.queryByText("135822816")).toBeNull()
    // Клик не должен падать — навигация вне скоупа теста (MemoryRouter без ассертов по URL).
    fireEvent.click(screen.getByRole("button", { name: "МТС, Senior AI Engineer" }))
  })

  it("быстрое добавление: клик по варианту открывает комментарий, «Добавить» без текста шлёт заголовок = лейблу варианта", async () => {
    fetchTimeline.mockResolvedValue([])
    createTimelineEntry.mockResolvedValue(event({ title: "Повышение" }))
    renderFeed()
    await waitFor(() => expect(screen.getByRole("button", { name: "Повышение" })).toBeTruthy())

    expect(screen.queryByPlaceholderText("Комментарий")).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: "Повышение" }))
    expect(await screen.findByPlaceholderText("Комментарий")).toBeTruthy()

    fireEvent.click(screen.getByRole("button", { name: "Добавить" }))
    await waitFor(() =>
      expect(createTimelineEntry).toHaveBeenCalledWith({ kind: "promotion", title: "Повышение" }),
    )
  })

  it("быстрое добавление: комментарий уходит как заголовок события вместо лейбла варианта", async () => {
    fetchTimeline.mockResolvedValue([])
    createTimelineEntry.mockResolvedValue(event({ title: "Сертификат AWS SAA" }))
    renderFeed()
    await waitFor(() => expect(screen.getByRole("button", { name: "Сертификат" })).toBeTruthy())

    fireEvent.click(screen.getByRole("button", { name: "Сертификат" }))
    fireEvent.change(await screen.findByPlaceholderText("Комментарий"), {
      target: { value: "Сертификат AWS SAA" },
    })
    fireEvent.click(screen.getByRole("button", { name: "Добавить" }))

    await waitFor(() =>
      expect(createTimelineEntry).toHaveBeenCalledWith({
        kind: "certificate",
        title: "Сертификат AWS SAA",
      }),
    )
  })

  it("3+ однотипных события за день сворачиваются в одну строку с раскрытием по клику", async () => {
    fetchTimeline.mockResolvedValue([
      event({ id: 1, kind: "application", title: "Отклик · vac-1", occurred_at: "2026-08-18T09:00:00Z" }),
      event({ id: 2, kind: "application", title: "Отклик · vac-2", occurred_at: "2026-08-18T10:00:00Z" }),
      event({ id: 3, kind: "application", title: "Отклик · vac-3", occurred_at: "2026-08-18T11:00:00Z" }),
    ])
    renderFeed()

    await waitFor(() => expect(screen.getByText("3 отклика")).toBeTruthy())
    expect(screen.queryByText("Отклик · vac-1")).toBeNull()

    fireEvent.click(screen.getByRole("button", { name: /3 отклика/ }))
    await waitFor(() => expect(screen.getByText("Отклик · vac-1")).toBeTruthy())
    expect(screen.getByText("Отклик · vac-2")).toBeTruthy()
    expect(screen.getByText("Отклик · vac-3")).toBeTruthy()
  })

  it("2 однотипных события за день НЕ сворачиваются (порог — от 3)", async () => {
    fetchTimeline.mockResolvedValue([
      event({ id: 1, kind: "application", title: "Отклик · vac-1", occurred_at: "2026-08-18T09:00:00Z" }),
      event({ id: 2, kind: "application", title: "Отклик · vac-2", occurred_at: "2026-08-18T10:00:00Z" }),
    ])
    renderFeed()
    await waitFor(() => expect(screen.getByText("Отклик · vac-1")).toBeTruthy())
    expect(screen.getByText("Отклик · vac-2")).toBeTruthy()
  })

  it("по умолчанию видно 3 последних дня с событиями, без «Показать ещё» лишнего не рендерит", async () => {
    fetchTimeline.mockResolvedValue([
      event({ id: 1, title: "День 1", occurred_at: "2026-08-20T10:00:00Z" }),
      event({ id: 2, title: "День 2", occurred_at: "2026-08-19T10:00:00Z" }),
      event({ id: 3, title: "День 3", occurred_at: "2026-08-18T10:00:00Z" }),
    ])
    renderFeed()
    await waitFor(() => expect(screen.getByText("День 1")).toBeTruthy())
    expect(screen.getByText("День 2")).toBeTruthy()
    expect(screen.getByText("День 3")).toBeTruthy()
    expect(screen.queryByRole("button", { name: "Показать ещё" })).toBeNull()
  })

  it("«Показать ещё» раскрывает уже загруженные дни сверх 3 без нового запроса", async () => {
    fetchTimeline.mockResolvedValue([
      event({ id: 1, title: "День 1", occurred_at: "2026-08-20T10:00:00Z" }),
      event({ id: 2, title: "День 2", occurred_at: "2026-08-19T10:00:00Z" }),
      event({ id: 3, title: "День 3", occurred_at: "2026-08-18T10:00:00Z" }),
      event({ id: 4, title: "День 4", occurred_at: "2026-08-17T10:00:00Z" }),
    ])
    renderFeed()
    await waitFor(() => expect(screen.getByText("День 1")).toBeTruthy())
    expect(screen.queryByText("День 4")).toBeNull()

    const more = await screen.findByRole("button", { name: "Показать ещё" })
    // `fetchTimeline` — общий на весь файл vi.fn(), afterEach его не чистит (только restore,
    // а не clear) — считаем звонки дельтой от этого клика, а не абсолютным числом.
    const callsBeforeExpand = fetchTimeline.mock.calls.length
    fireEvent.click(more)

    await waitFor(() => expect(screen.getByText("День 4")).toBeTruthy())
    expect(fetchTimeline.mock.calls.length).toBe(callsBeforeExpand) // всё уже было в памяти
  })

  it("окна в 3 дня не хватает из первой страницы — доливает следующую в фоне сама", async () => {
    const firstPage = Array.from({ length: 25 }, (_, i) =>
      event({ id: 100 - i, title: `Событие ${100 - i}`, occurred_at: "2026-08-10T10:00:00Z" }),
    )
    const secondPage = [
      event({ id: 50, title: "День -1", occurred_at: "2026-08-09T10:00:00Z" }),
      event({ id: 49, title: "День -2", occurred_at: "2026-08-08T10:00:00Z" }),
    ]
    fetchTimeline.mockResolvedValueOnce(firstPage).mockResolvedValueOnce(secondPage)
    renderFeed()

    await waitFor(() =>
      expect(fetchTimeline).toHaveBeenLastCalledWith(expect.objectContaining({ beforeId: 76 })),
    )
    await waitFor(() => expect(screen.getByText("День -2")).toBeTruthy())
  })
})
