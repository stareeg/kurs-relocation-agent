import { describe, expect, it } from "vitest"
import { axisLabel, sortedAxes, type AxisAlignment } from "./axis-alignment-view"

function axis(key: string, delta: number | null): AxisAlignment {
  return {
    axis: key,
    avg_responded: 10,
    avg_not_responded: 10 - (delta ?? 0),
    delta,
    inverted: (delta ?? 0) < 0,
    n_responded: 10,
    n_not_responded: 10,
  }
}

describe("axisLabel", () => {
  it("maps known axes to Russian labels", () => {
    expect(axisLabel("role_content")).toBe("Роль")
    expect(axisLabel("salary")).toBe("Зарплата")
  })

  it("falls back to the raw key for unknown axes", () => {
    expect(axisLabel("something_new")).toBe("something_new")
  })
})

describe("sortedAxes", () => {
  it("orders by |delta| descending", () => {
    const axes = [axis("company", 0.3), axis("role_content", 2.3), axis("salary", -1.0)]
    const sorted = sortedAxes(axes)
    expect(sorted.map((a) => a.axis)).toEqual(["role_content", "salary", "company"])
  })

  it("treats null delta as zero and keeps a stable tiebreak order", () => {
    const axes = [axis("company", null), axis("management", null)]
    const sorted = sortedAxes(axes)
    expect(sorted.map((a) => a.axis)).toEqual(["management", "company"])
  })
})
