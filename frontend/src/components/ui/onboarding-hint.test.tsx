// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { cleanup, render, screen, act } from "@testing-library/react"
import { OnboardingHint } from "./tooltip"
import { clearTipMemoryForTests } from "@/lib/tip-memory"

vi.stubGlobal(
  "IntersectionObserver",
  class {
    cb: IntersectionObserverCallback
    constructor(cb: IntersectionObserverCallback) {
      this.cb = cb
    }
    observe(el: Element) {
      this.cb(
        [{ isIntersecting: true, target: el } as IntersectionObserverEntry],
        this as unknown as IntersectionObserver,
      )
    }
    disconnect() {}
    unobserve() {}
  },
)

vi.stubGlobal(
  "ResizeObserver",
  class {
    observe() {}
    disconnect() {}
    unobserve() {}
  },
)

describe("OnboardingHint — once-seen", () => {
  beforeEach(() => {
    clearTipMemoryForTests()
    vi.useFakeTimers()
  })

  afterEach(() => {
    cleanup()
    clearTipMemoryForTests()
    vi.useRealTimers()
  })

  it("при показе сразу вызывает onDismiss (не ждёт таймер / уход со страницы)", () => {
    const onDismiss = vi.fn()
    render(
      <OnboardingHint open onDismiss={onDismiss} content="Подсказка">
        <button type="button">Якорь</button>
      </OnboardingHint>,
    )
    expect(screen.getByText("Якорь")).toBeTruthy()
    expect(onDismiss).toHaveBeenCalledTimes(1)
  })

  it("после onDismiss open=false не убивает текущий показ до таймера", () => {
    const onDismiss = vi.fn()
    const { rerender } = render(
      <OnboardingHint open onDismiss={onDismiss} content="Остаюсь на экране" autoHideMs={5000}>
        <button type="button">Якорь</button>
      </OnboardingHint>,
    )
    expect(onDismiss).toHaveBeenCalled()
    // Родитель сразу выключил open (shouldShow стал false) — текст ещё виден.
    rerender(
      <OnboardingHint
        open={false}
        onDismiss={onDismiss}
        content="Остаюсь на экране"
        autoHideMs={5000}
      >
        <button type="button">Якорь</button>
      </OnboardingHint>,
    )
    expect(screen.getByText("Остаюсь на экране")).toBeTruthy()

    act(() => {
      vi.advanceTimersByTime(5000)
    })
    expect(screen.queryByText("Остаюсь на экране")).toBeNull()
  })

  it("без open рендерит только children и не зовёт onDismiss", () => {
    const onDismiss = vi.fn()
    render(
      <OnboardingHint open={false} onDismiss={onDismiss} content="Раз">
        <span>Кнопка</span>
      </OnboardingHint>,
    )
    expect(screen.getByText("Кнопка")).toBeTruthy()
    expect(screen.queryByText("Раз")).toBeNull()
    expect(onDismiss).not.toHaveBeenCalled()
  })
})
