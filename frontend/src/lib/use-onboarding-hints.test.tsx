// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it } from "vitest"
import { cleanup, render, screen, act } from "@testing-library/react"
import { useOnboardingHints, ONBOARDING_HINT_IDS, hintDismissedKey } from "./use-onboarding-hints"
import { clearTipMemoryForTests } from "./tip-memory"

function Probe({ id }: { id: string }) {
  const { shouldShow, dismissHint } = useOnboardingHints()
  return (
    <div>
      <span data-testid="show">{shouldShow(id) ? "yes" : "no"}</span>
      <button type="button" onClick={() => dismissHint(id)}>
        dismiss
      </button>
    </div>
  )
}

describe("useOnboardingHints", () => {
  beforeEach(() => {
    localStorage.clear()
    clearTipMemoryForTests()
  })

  afterEach(() => {
    cleanup()
    localStorage.clear()
    clearTipMemoryForTests()
  })

  it("по умолчанию показывает", () => {
    render(<Probe id={ONBOARDING_HINT_IDS.jobsExtension} />)
    expect(screen.getByTestId("show").textContent).toBe("yes")
  })

  it("после dismiss больше не показывает", () => {
    render(<Probe id={ONBOARDING_HINT_IDS.jobsExtension} />)
    act(() => {
      screen.getByText("dismiss").click()
    })
    expect(screen.getByTestId("show").textContent).toBe("no")
    expect(localStorage.getItem(hintDismissedKey(ONBOARDING_HINT_IDS.jobsExtension))).toBe("1")
  })

  it("legacy dismissed в localStorage уважается без tip-memory", () => {
    localStorage.setItem(hintDismissedKey(ONBOARDING_HINT_IDS.resumeFillBasics), "1")
    render(<Probe id={ONBOARDING_HINT_IDS.resumeFillBasics} />)
    expect(screen.getByTestId("show").textContent).toBe("no")
  })

  it("после mark через dismiss — новый mount тоже no", () => {
    const { unmount } = render(<Probe id={ONBOARDING_HINT_IDS.jobsFirstCard} />)
    act(() => {
      screen.getByText("dismiss").click()
    })
    unmount()
    render(<Probe id={ONBOARDING_HINT_IDS.jobsFirstCard} />)
    expect(screen.getByTestId("show").textContent).toBe("no")
  })
})
