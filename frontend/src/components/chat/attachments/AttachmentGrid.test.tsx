// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { AttachmentGrid } from "./AttachmentGrid"
import type { AttachmentOut } from "@/api/attachments"

afterEach(() => cleanup())

function attachment(overrides: Partial<AttachmentOut> = {}): AttachmentOut {
  return {
    id: 1,
    mime: "image/png",
    width: 800,
    height: 600,
    bytes: 1000,
    thumb_width: 200,
    thumb_height: 150,
    url: "/api/attachments/1",
    thumb_url: "/api/attachments/1/thumb",
    analysis_status: "ready",
    ...overrides,
  }
}

function renderGrid(attachments: AttachmentOut[]) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <AttachmentGrid attachments={attachments} />
    </QueryClientProvider>,
  )
}

// Э5-3: битый блоб (нет PG, GC снёс, сетевой сбой на /thumb) не должен рисовать нативную "битую
// картинку" браузера — вместо неё плитка с явным поводом и повтором.
describe("AttachmentGrid — состояния отказа (Э5-3)", () => {
  it("ошибка загрузки миниатюры — плитка «картинка не открылась» вместо <img>", () => {
    renderGrid([attachment()])
    const img = document.querySelector("img") as HTMLImageElement
    fireEvent.error(img)
    expect(screen.getByText("Картинка не открылась")).toBeTruthy()
    expect(document.querySelector("img")).toBeNull()
  })

  it("«Повторить» возвращает <img> с новым src, чтобы обойти закэшированный отказ", () => {
    renderGrid([attachment()])
    fireEvent.error(document.querySelector("img") as HTMLImageElement)
    fireEvent.click(screen.getByRole("button", { name: "Повторить" }))
    const retried = document.querySelector("img") as HTMLImageElement
    expect(retried).toBeTruthy()
    expect(retried.src).toContain("retry=1")
  })
})

describe("AttachmentGrid — документы (txt/md/pdf/docx, 2026-08-11)", () => {
  function doc(overrides: Partial<AttachmentOut> = {}): AttachmentOut {
    return attachment({
      id: 2,
      mime: "application/pdf",
      width: 0,
      height: 0,
      thumb_width: 0,
      thumb_height: 0,
      url: "/api/attachments/2",
      analysis: {
        kind: "document",
        title: "resume.pdf",
        summary: "",
        text: "текст резюме",
        confidence: 1,
      },
      ...overrides,
    })
  }

  it("только документ — ссылка со скачиванием, без <img>/сетки", () => {
    renderGrid([doc()])
    expect(document.querySelector("img")).toBeNull()
    const link = screen.getByRole("link", { name: /resume\.pdf/ })
    expect(link.getAttribute("href")).toBe("/api/attachments/2")
  })

  it("картинка + документ — оба рендерятся, документ не попадает в сетку картинок", () => {
    renderGrid([attachment({ id: 1 }), doc()])
    expect(document.querySelectorAll("img")).toHaveLength(1)
    expect(screen.getByRole("link", { name: /resume\.pdf/ })).toBeTruthy()
  })

  it("несколько документов без картинок — список ссылок", () => {
    renderGrid([
      doc({
        id: 2,
        analysis: { kind: "document", title: "a.txt", summary: "", text: "x", confidence: 1 },
      }),
      doc({
        id: 3,
        mime: "text/markdown",
        analysis: { kind: "document", title: "b.md", summary: "", text: "y", confidence: 1 },
      }),
    ])
    expect(screen.getByRole("link", { name: /a\.txt/ })).toBeTruthy()
    expect(screen.getByRole("link", { name: /b\.md/ })).toBeTruthy()
  })
})
