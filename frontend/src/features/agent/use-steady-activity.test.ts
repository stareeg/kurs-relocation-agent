// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, renderHook } from "@testing-library/react"
import { ACTIVITY_HOLD_MS, ACTIVITY_MIN_MS, useSteadyActivity } from "./use-steady-activity"

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

type Props = { activity: string | null; working: boolean; runId: number }

function setup(initial: Props) {
  return renderHook((p: Props) => useSteadyActivity(p.activity, p.working, p.runId), {
    initialProps: initial,
  })
}

describe("useSteadyActivity", () => {
  it("каждое действие видно не меньше 1,5 с, затем показывается последнее", () => {
    const { result, rerender } = setup({ activity: "читает профиль", working: true, runId: 1 })
    expect(result.current).toBe("читает профиль")
    rerender({ activity: "ищет вакансии в базе", working: true, runId: 1 })
    rerender({ activity: "оценивает Umbra", working: true, runId: 1 })
    expect(result.current).toBe("читает профиль")
    act(() => {
      vi.advanceTimersByTime(ACTIVITY_MIN_MS)
    })
    expect(result.current).toBe("оценивает Umbra")
  })

  it("после конца шага строка держится ещё 3 с и пропадает", () => {
    const { result, rerender } = setup({ activity: "читает профиль", working: true, runId: 1 })
    rerender({ activity: null, working: true, runId: 1 })
    act(() => {
      vi.advanceTimersByTime(ACTIVITY_HOLD_MS - 100)
    })
    expect(result.current).toBe("читает профиль")
    act(() => {
      vi.advanceTimersByTime(200)
    })
    expect(result.current).toBeNull()
  })

  it("законченная работа снимает строку сразу", () => {
    const { result, rerender } = setup({ activity: "читает профиль", working: true, runId: 1 })
    rerender({ activity: "читает профиль", working: false, runId: 1 })
    expect(result.current).toBeNull()
  })
})
