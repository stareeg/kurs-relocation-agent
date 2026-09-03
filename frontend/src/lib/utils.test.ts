// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { MOTION_POP, usePopMotion, useListAppearMotion } from "./utils"

describe("useListAppearMotion", () => {
  it("первый непустой состав — rise, appearKey не меняется", () => {
    const { result, rerender } = renderHook(({ sig }) => useListAppearMotion(sig), {
      initialProps: { sig: "a\0b" },
    })
    expect(result.current.mode).toBe("rise")
    expect(result.current.appearKey).toBe(0)

    rerender({ sig: "a\0b" })
    expect(result.current.mode).toBe("rise")
    expect(result.current.appearKey).toBe(0)
  })

  it("смена состава после первого показа — fade, appearKey увеличивается", () => {
    const { result, rerender } = renderHook(({ sig }) => useListAppearMotion(sig), {
      initialProps: { sig: "a\0b" },
    })

    rerender({ sig: "a\0c" })
    expect(result.current.mode).toBe("fade")
    expect(result.current.appearKey).toBe(1)

    // Повторный рендер с той же сигнатурой не должен снова бампать ключ.
    rerender({ sig: "a\0c" })
    expect(result.current.appearKey).toBe(1)
  })

  it("itemClass даёт rise+stagger в режиме rise и fade без каскада в режиме fade", () => {
    const { result, rerender } = renderHook(({ sig }) => useListAppearMotion(sig), {
      initialProps: { sig: "a" },
    })
    expect(result.current.itemClass(0)).toContain("motion-rise")
    expect(result.current.itemClass(0)).toContain("motion-stagger-0")

    rerender({ sig: "b" })
    expect(result.current.itemClass(0)).toBe("motion-fade")
  })
})

describe("usePopMotion", () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it("classFor отдаёт motion-pop только для только что триггернутого id, иначе — fallback", () => {
    const { result } = renderHook(() => usePopMotion(100))

    expect(result.current.classFor("job-1", "fallback")).toBe("fallback")

    act(() => {
      result.current.trigger("job-1")
    })
    expect(result.current.classFor("job-1", "fallback")).toBe(MOTION_POP)
    expect(result.current.classFor("job-2", "fallback")).toBe("fallback")
  })

  it("автосброс через ms — pop-класс перестаёт применяться", () => {
    const { result } = renderHook(() => usePopMotion(100))

    act(() => {
      result.current.trigger("job-1")
    })
    expect(result.current.classFor("job-1")).toBe(MOTION_POP)

    act(() => {
      vi.advanceTimersByTime(100)
    })
    expect(result.current.classFor("job-1")).toBe("")
  })
})
