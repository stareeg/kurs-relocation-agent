// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { countUpFrame, useCountUp } from "./use-count-up"

describe("countUpFrame", () => {
  it("на старте возвращает from, в конце — to", () => {
    expect(countUpFrame(10, 50, 0, 400)).toBe(10)
    expect(countUpFrame(10, 50, 400, 400)).toBe(50)
    expect(countUpFrame(10, 50, 500, 400)).toBe(50)
  })

  it("в середине двигается к цели", () => {
    const mid = countUpFrame(0, 100, 200, 400)
    expect(mid).toBeGreaterThan(0)
    expect(mid).toBeLessThan(100)
  })
})

describe("useCountUp", () => {
  let now = 0
  let rafCb: FrameRequestCallback | null = null

  beforeEach(() => {
    now = 0
    rafCb = null
    vi.spyOn(performance, "now").mockImplementation(() => now)
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
      rafCb = cb
      return 1
    })
    vi.stubGlobal("cancelAnimationFrame", () => {
      rafCb = null
    })
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      configurable: true,
      value: () =>
        ({
          matches: false,
          media: "",
          onchange: null,
          addListener: () => {},
          removeListener: () => {},
          addEventListener: () => {},
          removeEventListener: () => {},
          dispatchEvent: () => false,
        }) as MediaQueryList,
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  function flushTo(ms: number) {
    now = ms
    act(() => {
      rafCb?.(now)
    })
  }

  it("достигает цели за 400 мс", () => {
    const { result, rerender } = renderHook(({ t }) => useCountUp(t), {
      initialProps: { t: 10 as number | null },
    })
    expect(result.current.display).toBe(10)

    rerender({ t: 50 })
    expect(result.current.flash).toBe("up")

    flushTo(200)
    expect(result.current.display).toBeGreaterThan(10)
    expect(result.current.display!).toBeLessThan(50)

    // Дожимаем кадры до конца (ease-out может не попасть ровно в to за один тик на 400).
    for (let t = 400; t <= 800; t += 50) {
      flushTo(t)
      if (result.current.display === 50) break
    }
    expect(result.current.display).toBe(50)
  })

  it("при быстрых обновлениях не дребезжит к устаревшей цели", () => {
    const { result, rerender } = renderHook(({ t }) => useCountUp(t), {
      initialProps: { t: 0 as number | null },
    })

    rerender({ t: 100 })
    flushTo(100)
    const mid = result.current.display!
    expect(mid).toBeGreaterThan(0)
    expect(mid).toBeLessThan(100)

    // Новая цель, пока идёт анимация к 100 — стартуем от текущего mid, старая цель забыта.
    now = 0
    rerender({ t: 40 })
    expect(result.current.flash).toBe(40 >= mid ? "up" : "down")

    flushTo(50)
    const afterRetarget = result.current.display!
    // Не должно скакнуть обратно к траектории на 100.
    expect(afterRetarget).toBeLessThanOrEqual(Math.max(mid, 40) + 1)

    for (let t = 400; t <= 800; t += 50) {
      flushTo(t)
      if (result.current.display === 40) break
    }
    expect(result.current.display).toBe(40)
  })

  it("null сбрасывает отображение", () => {
    const { result, rerender } = renderHook(({ t }) => useCountUp(t), {
      initialProps: { t: 12 as number | null },
    })
    expect(result.current.display).toBe(12)
    rerender({ t: null })
    expect(result.current.display).toBeNull()
    expect(result.current.flash).toBeNull()
  })
})
