import { describe, expect, it } from "vitest"
import {
  BONUS_PCT_STEPS,
  bonusPctIndex,
  hasBonusKind,
  offerBonusTypes,
  snapBonusPct,
} from "./bonus"
import { isOfferRowVisible, ROWS } from "./rows"

describe("bonus pct scale", () => {
  it("snaps to the nearest exponential step", () => {
    expect(snapBonusPct(18)).toBe(20)
    expect(snapBonusPct(5)).toBe(5)
    expect(snapBonusPct(0)).toBeNull()
    expect(snapBonusPct(null)).toBeNull()
  })

  it("indexes the default when empty", () => {
    expect(bonusPctIndex(null)).toBe(BONUS_PCT_STEPS.indexOf(10))
    expect(bonusPctIndex(50)).toBe(BONUS_PCT_STEPS.indexOf(50))
  })
})

describe("offerBonusTypes", () => {
  it("prefers the array and falls back to the singular field", () => {
    expect(offerBonusTypes({ bonus_types: ["kpi", "annual"] })).toEqual(["annual", "kpi"])
    expect(offerBonusTypes({ bonus_type: "quarterly" })).toEqual(["quarterly"])
    expect(offerBonusTypes({ bonus_type: "none" })).toEqual([])
  })
})

describe("isOfferRowVisible", () => {
  const byKey = Object.fromEntries(ROWS.map((r) => [r.key, r]))

  it("hides period/KPI/welcome/equity fields until that type is selected", () => {
    const none = { bonus_types: [] as string[], bonus_type: "none", work_format: "remote" }
    expect(isOfferRowVisible(byKey.annual_bonus_pct, none)).toBe(false)
    expect(isOfferRowVisible(byKey.quarterly_bonus_pct, none)).toBe(false)
    expect(isOfferRowVisible(byKey.bonus, none)).toBe(false)
    expect(isOfferRowVisible(byKey.signon, none)).toBe(false)
    expect(isOfferRowVisible(byKey.equity, none)).toBe(false)
  })

  it("shows only the fields for selected kinds", () => {
    const offer = {
      bonus_types: ["annual", "welcome", "equity"],
      bonus_type: "annual",
      work_format: "remote",
    }
    expect(isOfferRowVisible(byKey.annual_bonus_pct, offer)).toBe(true)
    expect(isOfferRowVisible(byKey.quarterly_bonus_pct, offer)).toBe(false)
    expect(isOfferRowVisible(byKey.bonus, offer)).toBe(false)
    expect(isOfferRowVisible(byKey.signon, offer)).toBe(true)
    expect(isOfferRowVisible(byKey.equity, offer)).toBe(true)
  })

  it("shows KPI details only for kpi", () => {
    const offer = { bonus_types: ["kpi"], bonus_type: "kpi", work_format: "office" }
    expect(isOfferRowVisible(byKey.bonus, offer)).toBe(true)
    expect(isOfferRowVisible(byKey.annual_bonus_pct, offer)).toBe(false)
    expect(hasBonusKind(offer, "kpi")).toBe(true)
  })
})
