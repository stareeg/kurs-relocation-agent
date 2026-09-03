// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { AttachmentChips } from "./AttachmentChips"
import type { PendingAttachment } from "./use-attachment-upload"
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
    analysis_status: "pending",
    ...overrides,
  }
}

function pending(overrides: Partial<PendingAttachment> = {}): PendingAttachment {
  return {
    key: "k1",
    file: new File(["x"], "shot.png", { type: "image/png" }),
    previewUrl: "blob:preview-1",
    status: "uploading",
    attachment: null,
    errorMessage: null,
    ...overrides,
  }
}

describe("AttachmentChips", () => {
  it("пустой список — ничего не рендерит", () => {
    const { container } = render(
      <AttachmentChips items={[]} onRemove={vi.fn()} onRetry={vi.fn()} />,
    )
    expect(container.firstChild).toBeNull()
  })

  it("клик по «×» убирает конкретный чип (onRemove с его key) после схлопывания (§6.1)", () => {
    vi.useFakeTimers()
    const onRemove = vi.fn()
    render(
      <AttachmentChips
        items={[pending({ key: "a", status: "ready", attachment: attachment() })]}
        onRemove={onRemove}
        onRetry={vi.fn()}
      />,
    )
    fireEvent.click(screen.getByRole("button", { name: "Убрать" }))
    expect(onRemove).not.toHaveBeenCalled()
    vi.advanceTimersByTime(200)
    expect(onRemove).toHaveBeenCalledWith("a")
    vi.useRealTimers()
  })

  it("Backspace на сфокусированном чипе тоже убирает его (после схлопывания)", () => {
    vi.useFakeTimers()
    const onRemove = vi.fn()
    render(
      <AttachmentChips
        items={[pending({ key: "a", status: "ready", attachment: attachment() })]}
        onRemove={onRemove}
        onRetry={vi.fn()}
      />,
    )
    fireEvent.keyDown(screen.getByRole("group"), { key: "Backspace" })
    vi.advanceTimersByTime(200)
    expect(onRemove).toHaveBeenCalledWith("a")
    vi.useRealTimers()
  })

  it("prefers-reduced-motion: убирает чип сразу, без анимации схлопывания", () => {
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      configurable: true,
      value: (query: string) =>
        ({
          matches: query.includes("reduce"),
          media: query,
          onchange: null,
          addListener: () => {},
          removeListener: () => {},
          addEventListener: () => {},
          removeEventListener: () => {},
          dispatchEvent: () => false,
        }) as MediaQueryList,
    })
    const onRemove = vi.fn()
    render(
      <AttachmentChips
        items={[pending({ key: "a", status: "ready", attachment: attachment() })]}
        onRemove={onRemove}
        onRetry={vi.fn()}
      />,
    )
    fireEvent.click(screen.getByRole("button", { name: "Убрать" }))
    expect(onRemove).toHaveBeenCalledWith("a")
    Reflect.deleteProperty(window, "matchMedia")
  })

  it("чип с ошибкой — клик по чипу повторяет загрузку", () => {
    const onRetry = vi.fn()
    render(
      <AttachmentChips
        items={[pending({ key: "a", status: "error", errorMessage: "сеть недоступна" })]}
        onRemove={vi.fn()}
        onRetry={onRetry}
      />,
    )
    fireEvent.click(screen.getByRole("group"))
    expect(onRetry).toHaveBeenCalledWith("a")
  })

  it("подпись analysis.title видна только когда вложение готово", () => {
    render(
      <AttachmentChips
        items={[
          pending({
            key: "a",
            status: "ready",
            attachment: attachment({
              analysis_status: "ready",
              analysis: {
                kind: "diagram",
                title: "Схема БД",
                summary: "…",
                text: "…",
                confidence: 0.9,
              },
            }),
          }),
        ]}
        onRemove={vi.fn()}
        onRetry={vi.fn()}
      />,
    )
    expect(screen.getByText("Схема БД")).toBeTruthy()
  })

  it("кнопки кадрирования в превью-чипе нет — кадрирование доступно только из просмотрщика", () => {
    render(
      <AttachmentChips
        items={[pending({ key: "a", status: "ready", attachment: attachment() })]}
        onRemove={vi.fn()}
        onRetry={vi.fn()}
      />,
    )
    expect(screen.queryByRole("button", { name: "Кадрировать" })).toBeNull()
  })

  // Э4-3: ярлык-переключатель ветки — только в режимах-парсерах, когда передан onRouteChange.
  it("без routes/onRouteChange бейдж ветки не рисуется", () => {
    render(
      <AttachmentChips
        items={[
          pending({
            key: "a",
            status: "ready",
            attachment: attachment({ analysis_status: "ready" }),
          }),
        ]}
        onRemove={vi.fn()}
        onRetry={vi.fn()}
      />,
    )
    expect(screen.queryByRole("button", { name: /Переписка|Материал/ })).toBeNull()
  })

  it("клик по бейджу переключает ветку и зовёт onRouteChange с новым значением", () => {
    const onRouteChange = vi.fn()
    render(
      <AttachmentChips
        items={[
          pending({
            key: "a",
            status: "ready",
            attachment: attachment({ analysis_status: "ready" }),
          }),
        ]}
        onRemove={vi.fn()}
        onRetry={vi.fn()}
        routes={{ a: "correspondence" }}
        onRouteChange={onRouteChange}
      />,
    )
    fireEvent.click(screen.getByRole("button", { name: /Переписка/ }))
    expect(onRouteChange).toHaveBeenCalledWith("a", "material")
  })

  // Э5-3: распознавание упало — картинка рабочая, чип не в состоянии ошибки (нет красного кольца),
  // но подпись явно говорит "не распознал" вместо тишины.
  it("распознавание упало — чип не в состоянии ошибки, но подписан «Не распознал»", () => {
    render(
      <AttachmentChips
        items={[
          pending({
            key: "a",
            status: "ready",
            attachment: attachment({ analysis_status: "failed" }),
          }),
        ]}
        onRemove={vi.fn()}
        onRetry={vi.fn()}
      />,
    )
    expect(screen.getByText("Не распознал")).toBeTruthy()
    expect(screen.queryByRole("button", { name: "Убрать" })).toBeTruthy()
  })

  it("бейдж не рисуется, пока распознавание не готово", () => {
    render(
      <AttachmentChips
        items={[
          pending({
            key: "a",
            status: "ready",
            attachment: attachment({ analysis_status: "pending" }),
          }),
        ]}
        onRemove={vi.fn()}
        onRetry={vi.fn()}
        routes={{ a: "material" }}
        onRouteChange={vi.fn()}
      />,
    )
    expect(screen.queryByRole("button", { name: /Переписка|Материал/ })).toBeNull()
  })
})
