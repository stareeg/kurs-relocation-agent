import { describe, expect, it } from "vitest"
import {
  deriveSlotOutcome,
  slotOutcomeGlyph,
  slotOutcomeTitle,
} from "./slotOutcomes"

describe("slotOutcomes", () => {
  it("deriveSlotOutcome — приоритет offer > reject > interview", () => {
    expect(deriveSlotOutcome({ c0: "offer", c1: "reject" }).tone).toBe("offer")
    expect(deriveSlotOutcome({ c0: "reject", c1: "reject" }).tone).toBe("reject")
    expect(deriveSlotOutcome({ c0: "interview" }).tone).toBe("interview")
    expect(deriveSlotOutcome({ c0: "probe" }).tone).toBe("interview")
    expect(deriveSlotOutcome({ c0: "reject", c1: "interview" }).tone).toBe("mixed")
    expect(deriveSlotOutcome({}).tone).toBe("quiet")
  })

  it("slotOutcomeTitle — счётчики и заголовок газеты", () => {
    const o = deriveSlotOutcome({ c0: "offer" }, "Стая в шоке")
    expect(slotOutcomeTitle(o)).toBe("1 оффер · Стая в шоке")
    expect(slotOutcomeGlyph(o.tone)).toBe("★")
  })
})
