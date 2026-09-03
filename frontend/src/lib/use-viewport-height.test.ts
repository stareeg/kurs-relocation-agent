// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { syncViewportUnits, useViewportHeight } from "./use-viewport-height"

describe("useViewportHeight", () => {
  const realVV = (window as unknown as { visualViewport?: VisualViewport }).visualViewport

  beforeEach(() => {
    Object.defineProperty(window, "innerHeight", { configurable: true, value: 800 })
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 1200 })
  })

  afterEach(() => {
    if (realVV) (window as unknown as { visualViewport?: VisualViewport }).visualViewport = realVV
    else delete (window as unknown as { visualViewport?: VisualViewport }).visualViewport
  })

  it("на старте возвращает visualViewport.height, если он задан", () => {
    ;(window as unknown as { visualViewport: VisualViewport }).visualViewport = {
      height: 640,
      width: 1200,
      offsetTop: 0,
      offsetLeft: 0,
      pageLeft: 0,
      pageTop: 0,
      scale: 1,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    } as unknown as VisualViewport
    const { result } = renderHook(() => useViewportHeight())
    expect(result.current).toBe(640)
  })

  it("падает на window.innerHeight, если visualViewport недоступен", () => {
    delete (window as unknown as { visualViewport?: VisualViewport }).visualViewport
    const { result } = renderHook(() => useViewportHeight())
    expect(result.current).toBe(800)
  })

  it("реагирует на resize visualViewport (имитация появления клавиатуры)", () => {
    const listeners: Record<string, EventListener> = {}
    const fakeVV = {
      height: 800,
      width: 1200,
      offsetTop: 0,
      offsetLeft: 0,
      pageLeft: 0,
      pageTop: 0,
      scale: 1,
      addEventListener: vi.fn((type: string, cb: EventListener) => {
        listeners[type] = cb
      }),
      removeEventListener: vi.fn((type: string) => {
        delete listeners[type]
      }),
    }
    ;(window as unknown as { visualViewport: VisualViewport }).visualViewport =
      fakeVV as unknown as VisualViewport

    const { result } = renderHook(() => useViewportHeight())
    expect(result.current).toBe(800)

    act(() => {
      fakeVV.height = 400
      listeners.resize?.(new Event("resize"))
    })
    expect(result.current).toBe(400)
  })
})

describe("syncViewportUnits", () => {
  it("записывает --mp-vh и --mp-vw на хост", () => {
    const host = document.createElement("div")
    document.body.appendChild(host)
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 1280 })
    syncViewportUnits(host, 720)
    expect(host.style.getPropertyValue("--mp-vh")).toBe("720px")
    expect(host.style.getPropertyValue("--mp-vw")).toBe("1280px")
    document.body.removeChild(host)
  })

  it("ничего не делает, если хоста нет", () => {
    expect(() => syncViewportUnits(null, 100)).not.toThrow()
  })

  it("не пишет --mp-vh при нулевой высоте", () => {
    const host = document.createElement("div")
    document.body.appendChild(host)
    syncViewportUnits(host, 0)
    expect(host.style.getPropertyValue("--mp-vh")).toBe("")
    document.body.removeChild(host)
  })
})
