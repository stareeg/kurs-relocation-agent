// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import {
  clearTipMemoryForTests,
  HELP_TIP_COOLDOWN_MS,
  isOnboardingGapActive,
  markTipShown,
  ONBOARDING_GLOBAL_GAP_MS,
  ONBOARDING_SEEN_MS,
  wasTipShownRecently,
} from "./tip-memory"

describe("tip-memory", () => {
  beforeEach(() => {
    clearTipMemoryForTests()
    vi.useFakeTimers()
    vi.setSystemTime(new Date("2026-08-26T12:00:00Z"))
  })

  afterEach(() => {
    clearTipMemoryForTests()
    vi.useRealTimers()
  })

  it("wasTipShownRecently: false до первого показа", () => {
    expect(wasTipShownRecently("help.jobs.card-score", HELP_TIP_COOLDOWN_MS)).toBe(false)
  })

  it("после markTipShown — недавно, после кулдауна — снова можно", () => {
    markTipShown("help.jobs.card-score")
    expect(wasTipShownRecently("help.jobs.card-score", HELP_TIP_COOLDOWN_MS)).toBe(true)

    vi.setSystemTime(Date.now() + HELP_TIP_COOLDOWN_MS + 1)
    expect(wasTipShownRecently("help.jobs.card-score", HELP_TIP_COOLDOWN_MS)).toBe(false)
  })

  it("онбординг с ONBOARDING_SEEN_MS — раз показали, навсегда", () => {
    markTipShown("onboarding.jobs.extension")
    expect(wasTipShownRecently("onboarding.jobs.extension", ONBOARDING_SEEN_MS)).toBe(true)

    vi.setSystemTime(Date.now() + 365 * 24 * 60 * 60 * 1000)
    expect(wasTipShownRecently("onboarding.jobs.extension", ONBOARDING_SEEN_MS)).toBe(true)
  })

  it("разные ключи не мешают друг другу", () => {
    markTipShown("help.a")
    expect(wasTipShownRecently("help.a", HELP_TIP_COOLDOWN_MS)).toBe(true)
    expect(wasTipShownRecently("help.b", HELP_TIP_COOLDOWN_MS)).toBe(false)
  })

  it("isOnboardingGapActive после любого показа", () => {
    expect(isOnboardingGapActive()).toBe(false)
    markTipShown("help.x")
    expect(isOnboardingGapActive(ONBOARDING_GLOBAL_GAP_MS)).toBe(true)
    vi.setSystemTime(Date.now() + ONBOARDING_GLOBAL_GAP_MS + 1)
    expect(isOnboardingGapActive(ONBOARDING_GLOBAL_GAP_MS)).toBe(false)
  })
})
