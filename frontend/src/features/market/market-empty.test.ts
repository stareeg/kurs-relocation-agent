import { describe, expect, it } from "vitest"
import { resolveEmptyReason, SECTION_EMPTY_FALLBACKS, shouldHideEmptyBlock } from "./market-empty"
import { MARKET_SECTIONS } from "./market-sections"

describe("resolveEmptyReason (F-06)", () => {
  it("предпочитает note бэка запасной формулировке", () => {
    expect(resolveEmptyReason("  Нужно ещё 3 ответа HR.  ", "voronka")).toBe(
      "Нужно ещё 3 ответа HR.",
    )
  })

  it("пустой/пробельный note → fallback секции", () => {
    expect(resolveEmptyReason(null, "voronka")).toBe(SECTION_EMPTY_FALLBACKS.voronka)
    expect(resolveEmptyReason("   ", "voronka")).toBe(SECTION_EMPTY_FALLBACKS.voronka)
  })

  it("у каждой секции своя причина, не общая отписка и не прочерк-заглушка", () => {
    const reasons = MARKET_SECTIONS.map((s) => resolveEmptyReason(undefined, s.id))
    expect(new Set(reasons).size).toBe(MARKET_SECTIONS.length)
    for (const reason of reasons) {
      expect(reason.toLowerCase()).not.toMatch(/нет данных|n\/a|прочерк/)
      // Прочерк как единственный ответ («—»), не тире в предложении.
      expect(reason.trim()).not.toBe("—")
      expect(reason.trim()).not.toBe("-")
    }
  })

  it("fallback-тексты совпадают с примерами плана (воронка) и новых секций (formats/shans-offera)", () => {
    expect(SECTION_EMPTY_FALLBACKS.voronka).toMatch(/откликов/i)
    expect(SECTION_EMPTY_FALLBACKS.formats).toMatch(/форматы/i)
    expect(SECTION_EMPTY_FALLBACKS["shans-offera"]).toMatch(/шанс офферов/i)
  })
})

describe("shouldHideEmptyBlock (F-06)", () => {
  it("прячет при available=false или enoughData=false", () => {
    expect(shouldHideEmptyBlock({ available: false })).toBe(true)
    expect(shouldHideEmptyBlock({ available: true, enoughData: false })).toBe(true)
    expect(shouldHideEmptyBlock({ available: true, enoughData: true })).toBe(false)
    expect(shouldHideEmptyBlock({})).toBe(false)
  })
})
