// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { useBufferedValue } from "./use-buffered-field"

describe("useBufferedValue", () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it("не зовёт onCommit на каждый символ — только после delayMs", () => {
    const onCommit = vi.fn()
    const { result, rerender } = renderHook(
      ({ external }) => useBufferedValue(external, onCommit, 300),
      { initialProps: { external: "" } },
    )

    act(() => result.current.onChange("И"))
    act(() => result.current.onChange("Ив"))
    expect(onCommit).not.toHaveBeenCalled()
    expect(result.current.value).toBe("Ив")

    act(() => {
      vi.advanceTimersByTime(300)
    })
    expect(onCommit).toHaveBeenCalledTimes(1)
    expect(onCommit).toHaveBeenCalledWith("Ив")

    rerender({ external: "Ив" })
  })

  it("на blur сразу сбрасывает хвост, не дожидаясь таймера", () => {
    const onCommit = vi.fn()
    const { result } = renderHook(() => useBufferedValue("", onCommit, 300))

    act(() => {
      result.current.onFocus()
      result.current.onChange("А")
      result.current.onBlur()
    })
    expect(onCommit).toHaveBeenCalledWith("А")
  })

  it("delayMs: false — не коммитит, пока поле в фокусе", () => {
    const onCommit = vi.fn()
    const { result } = renderHook(() => useBufferedValue("", onCommit, false))

    act(() => {
      result.current.onFocus()
      result.current.onChange("Мо")
      result.current.onChange("Мос")
      vi.advanceTimersByTime(10_000)
    })
    expect(onCommit).not.toHaveBeenCalled()
    expect(result.current.value).toBe("Мос")

    act(() => result.current.onBlur())
    expect(onCommit).toHaveBeenCalledTimes(1)
    expect(onCommit).toHaveBeenCalledWith("Мос")
  })
})
