import { describe, expect, it } from "vitest"
import {
  formatCellDelta,
  formatCellValue,
  formatFxRate,
  ratioPct,
  unitSuffix,
} from "./format"

describe("formatCellValue", () => {
  it("formats pct with one decimal", () => {
    expect(formatCellValue(12.34, "pct")).toBe("12.3")
    expect(formatCellValue(12, "pct")).toBe("12")
  })

  it("formats count and score as integers", () => {
    expect(formatCellValue(128.7, "count")).toBe("129")
    expect(formatCellValue(71.2, "score")).toBe("71")
  })

  it("passes money strings through", () => {
    expect(formatCellValue("450-520к", "money")).toBe("450-520к")
  })

  it("empty values become dash", () => {
    expect(formatCellValue(null, "count")).toBe("—")
  })
})

describe("formatCellDelta", () => {
  it("uses signed number without unit suffix", () => {
    expect(formatCellDelta(3, "pct")).toBe("+3")
    expect(formatCellDelta(-1.5, "pct")).toBe("-1.5")
  })

  it("uses signed number for count", () => {
    expect(formatCellDelta(2, "count")).toBe("+2")
  })
})

describe("unitSuffix", () => {
  it("maps units", () => {
    expect(unitSuffix("count")).toBe("шт")
    expect(unitSuffix("pct")).toBe("%")
    expect(unitSuffix("money")).toBe("₽")
  })
})

describe("formatFxRate (Э3.3)", () => {
  it("hourly stays a raw number, monthly abbreviates", () => {
    expect(formatFxRate(45, "USD", "hour")).toBe("$45/ч")
    expect(formatFxRate(8000, "USD", "month")).toBe("$8к/мес")
    expect(formatFxRate(40, "EUR", "hour")).toBe("€40/ч")
  })
  it("unknown currency uses the code, not a made-up symbol", () => {
    expect(formatFxRate(100, "CHF", "day")).toBe("CHF 100/день")
  })
})

describe("ratioPct", () => {
  it("computes percent with one decimal", () => {
    expect(ratioPct(1, 4)).toBe(25)
    expect(ratioPct(1, 3)).toBe(33.3)
  })

  it("returns null when base is zero or missing", () => {
    expect(ratioPct(5, 0)).toBeNull()
    expect(ratioPct(5, null)).toBeNull()
  })
})
