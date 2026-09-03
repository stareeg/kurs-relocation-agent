import { describe, expect, it } from "vitest"
import { toggleSelected, withSelected } from "./use-message-selection"

describe("toggleSelected", () => {
  it("добавляет отсутствующий id", () => {
    const next = toggleSelected(new Set([1]), 2)
    expect([...next].sort()).toEqual([1, 2])
  })

  it("убирает уже выделенный id", () => {
    const next = toggleSelected(new Set([1, 2]), 2)
    expect([...next]).toEqual([1])
  })

  it("не мутирует исходное множество", () => {
    const original = new Set([1])
    toggleSelected(original, 2)
    expect([...original]).toEqual([1])
  })
})

describe("withSelected", () => {
  it("добавляет id, если его ещё нет", () => {
    const next = withSelected(new Set([1]), 2)
    expect([...next].sort()).toEqual([1, 2])
  })

  it("возвращает тот же Set, если id уже выделен (не дёргает рендер)", () => {
    const original = new Set([1, 2])
    expect(withSelected(original, 1)).toBe(original)
  })
})
