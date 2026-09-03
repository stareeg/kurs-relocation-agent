// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { cleanup, render, screen, act } from "@testing-library/react"
import type { ReactElement } from "react"
import { MemoryRouter } from "react-router-dom"
import { HelpTip } from "./help-tip"
import {
  clearTipMemoryForTests,
  HELP_TIP_COOLDOWN_MS,
  markTipShown,
  wasTipShownRecently,
} from "@/lib/tip-memory"

function renderTip(ui: ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>)
}

describe("HelpTip (hover, без тумблера)", () => {
  beforeEach(() => {
    localStorage.clear()
    clearTipMemoryForTests()
  })

  afterEach(() => {
    cleanup()
    localStorage.clear()
    clearTipMemoryForTests()
  })

  it("icon-only без showIcon не рисует маркер", () => {
    renderTip(
      <div>
        <HelpTip id="settings.openrouter-key" />
        <HelpTip id="nav.menu-toggle">
          <span>Меню</span>
        </HelpTip>
      </div>,
    )
    expect(document.querySelectorAll('[aria-label="Подсказка"]')).toHaveLength(0)
    expect(screen.getByText("Меню")).toBeTruthy()
  })

  it("showIcon рисует кнопку подсказки", () => {
    renderTip(<HelpTip id="settings.openrouter-key" showIcon />)
    expect(document.querySelectorAll('[aria-label="Подсказка"]')).toHaveLength(1)
  })

  it("без Router не падает", () => {
    render(
      <HelpTip id="resume.companies-target">
        <span>Целевые</span>
      </HelpTip>,
    )
    expect(screen.getByText("Целевые")).toBeTruthy()
  })

  it("после недавнего показа тот же id не открывается по hover", () => {
    markTipShown("help.nav.menu-toggle")
    renderTip(
      <HelpTip id="nav.menu-toggle">
        <span>Меню</span>
      </HelpTip>,
    )
    const trigger = screen.getByText("Меню")
    act(() => {
      trigger.dispatchEvent(new PointerEvent("pointermove", { bubbles: true }))
      trigger.focus()
    })
    expect(document.querySelector('[data-slot="tooltip-content"]')).toBeNull()
  })

  it("кулдаун HelpTip конечный (не навсегда как онбординг)", () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date("2026-08-26T12:00:00Z"))
    markTipShown("help.nav.menu-toggle")
    expect(wasTipShownRecently("help.nav.menu-toggle", HELP_TIP_COOLDOWN_MS)).toBe(true)
    vi.setSystemTime(Date.now() + HELP_TIP_COOLDOWN_MS + 1)
    expect(wasTipShownRecently("help.nav.menu-toggle", HELP_TIP_COOLDOWN_MS)).toBe(false)
    vi.useRealTimers()
  })
})
