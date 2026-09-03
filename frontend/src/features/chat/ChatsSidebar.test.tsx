// @vitest-environment jsdom
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { ChatsSidebar, type ChatSelection } from "./ChatsSidebar"
import type { ConvThread } from "@/api/conversations"
import type { Job } from "@/api/jobs"
import type { Note } from "@/api/notes"

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

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({ reply: [], remind: [], upcoming: [], strong_unapplied: [] }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
    ),
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  localStorage.removeItem("copilot.chat-list.tab")
  localStorage.removeItem("copilot.chat-list.collapsed")
})

const context: Note = { id: 1, title: "Контекст про офферы", body: "" } as Note

const conversation: ConvThread = {
  id: 42,
  vacancy_id: "vac-1",
  last_message_at: null,
  last_hr_kind: null,
  last_hr_at: null,
  next_stage_at: null,
  pinned: false,
} as ConvThread

function renderSidebar(overrides?: Partial<React.ComponentProps<typeof ChatsSidebar>>) {
  const selection: ChatSelection = { kind: "empty" }
  const onDeleteContext = vi.fn()
  const onDeleteVacancy = vi.fn()
  const onTogglePinVacancy = vi.fn()
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <ChatsSidebar
        selection={selection}
        contexts={[context]}
        contextsLoading={false}
        conversations={[conversation]}
        onRetryConversations={vi.fn()}
        jobsByVacancyId={new Map()}
        archiveMode={false}
        onToggleArchiveMode={vi.fn()}
        onArchiveConversation={vi.fn()}
        onRestoreConversation={vi.fn()}
        onNewVacancy={vi.fn()}
        onNewContext={vi.fn()}
        onSelectContext={vi.fn()}
        onDeleteContext={onDeleteContext}
        onSelectVacancy={vi.fn()}
        onDeleteVacancy={onDeleteVacancy}
        onTogglePinVacancy={onTogglePinVacancy}
        {...overrides}
      />
    </QueryClientProvider>,
  )
  return { onDeleteContext, onDeleteVacancy, onTogglePinVacancy }
}

describe("ChatsSidebar — подтверждение удаления (F-11)", () => {
  it("не использует window.confirm", () => {
    const spy = vi.spyOn(window, "confirm")
    const { onDeleteVacancy } = renderSidebar()
    fireEvent.click(screen.getByTitle("Удалить разговор"))
    expect(spy).not.toHaveBeenCalled()
    expect(onDeleteVacancy).not.toHaveBeenCalled()
    spy.mockRestore()
  })

  it("удаление разговора требует подтверждения в диалоге", () => {
    const { onDeleteVacancy } = renderSidebar()
    fireEvent.click(screen.getByTitle("Удалить разговор"))
    expect(screen.getByText("Удалить разговор?")).toBeTruthy()
    expect(onDeleteVacancy).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole("button", { name: "Удалить" }))
    expect(onDeleteVacancy).toHaveBeenCalledWith(42)
  })

  it("отмена в диалоге не удаляет контекст", () => {
    const { onDeleteContext } = renderSidebar()
    fireEvent.click(screen.getByRole("button", { name: "Контексты" }))
    fireEvent.click(screen.getByTitle("Удалить контекст"))
    expect(screen.getByText("Удалить контекст?")).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "Отмена" }))
    expect(onDeleteContext).not.toHaveBeenCalled()
    expect(screen.queryByText("Удалить контекст?")).toBeNull()
  })
})

describe("ChatsSidebar — вкладки Вакансии/Контексты", () => {
  it("в Контекстах нет кнопки Архив", () => {
    renderSidebar()
    expect(screen.getByRole("button", { name: /Архив/i })).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "Контексты" }))
    expect(screen.queryByRole("button", { name: /Архив/i })).toBeNull()
    expect(screen.getByText("Контекст про офферы")).toBeTruthy()
  })
})

describe("ChatsSidebar — действия под строкой диалога", () => {
  it("копирование/удаление/закреп — под карточкой, не справа в pr-14", () => {
    renderSidebar()
    const copy = screen.getByRole("button", { name: "Копировать" })
    const row = screen.getByText("Вакансия vac-1").closest("li")
    expect(copy.closest("li")).toBe(row)
    expect(
      screen.getByText("Вакансия vac-1").closest("button")!.className.split(/\s+/),
    ).not.toContain("pr-14")
  })
})

describe("ChatsSidebar — первая строка диалога по вакансии", () => {
  it("обрезает длинное имя HR до 23 символов и оставляет дату в строке", () => {
    const longName = "Александра Константинопольская"
    renderSidebar({
      conversations: [
        {
          ...conversation,
          contact_name: longName,
          company: "Яндекс",
          last_message_at: "2026-08-20T10:15:00",
        },
      ],
    })
    expect(screen.getByText(`${longName.slice(0, 23)}…`)).toBeTruthy()
    expect(screen.queryByText(longName)).toBeNull()
    expect(screen.getByText("20.08")).toBeTruthy()
  })

  it("рисует скор тем же text-sm, что и название", () => {
    renderSidebar({
      jobsByVacancyId: new Map([
        ["vac-1", { overall_score: 87, vacancy_text: "x".repeat(50) } as Job],
      ]),
    })
    const score = screen.getByText("87")
    expect(score.className.split(/\s+/)).toContain("text-sm")
  })
})

describe("ChatsSidebar — закреп диалогов", () => {
  it("клик по булавке зовёт onTogglePinVacancy с инвертированным pinned", () => {
    const { onTogglePinVacancy } = renderSidebar()
    fireEvent.click(screen.getByTitle("Закрепить"))
    expect(onTogglePinVacancy).toHaveBeenCalledWith(42, true)
  })

  it("закреплённый диалог показывает «Открепить»", () => {
    renderSidebar({ conversations: [{ ...conversation, pinned: true }] })
    expect(screen.getByTitle("Открепить")).toBeTruthy()
    expect(screen.queryByTitle("Закрепить")).toBeNull()
  })

  it("закреплённые диалоги идут первыми независимо от last_message_at", () => {
    const older: ConvThread = {
      ...conversation,
      id: 1,
      vacancy_id: "vac-old",
      last_message_at: "2026-01-01T00:00:00Z",
      pinned: true,
    }
    const newer: ConvThread = {
      ...conversation,
      id: 2,
      vacancy_id: "vac-new",
      last_message_at: "2026-06-01T00:00:00Z",
      pinned: false,
    }
    renderSidebar({ conversations: [newer, older] })
    const rows = screen.getAllByTitle(/^(Закрепить|Открепить)$/).map((el) => el.closest("li"))
    expect(rows[0]?.textContent).toContain("Вакансия vac-old")
    expect(rows[1]?.textContent).toContain("Вакансия vac-new")
  })
})
