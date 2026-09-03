import { describe, expect, it } from "vitest"
import { overlapCaption, regionFromHiringGeo } from "./work-terms-view"

describe("regionFromHiringGeo", () => {
  it("распознаёт закрытый словарь регионов", () => {
    expect(regionFromHiringGeo(["EMEA"])).toBe("EMEA")
    expect(regionFromHiringGeo(["Europe"])).toBe("EMEA")
    expect(regionFromHiringGeo(["US-West"])).toBe("US-West")
  })
  it("worldwide не угадывает регион", () => {
    expect(regionFromHiringGeo(["worldwide"])).toBeNull()
    expect(regionFromHiringGeo([])).toBeNull()
  })
})

describe("overlapCaption", () => {
  it("числом: регион, доступные часы, требуемые", () => {
    expect(
      overlapCaption(
        { hiring_geo: ["EMEA"], overlap_hours_required: 4 },
        { EMEA: 7, "US-East": 2 },
      ),
    ).toBe("EMEA 7 ч из требуемых 4")
  })
  it("без требования — только доступные часы региона", () => {
    expect(overlapCaption({ hiring_geo: ["UK"] }, { UK: 6 })).toBe("UK 6 ч")
  })
  it("нет региона — берёт максимум из overlap кандидата", () => {
    expect(
      overlapCaption({ overlap_hours_required: 4 }, { APAC: 1, EMEA: 8 }),
    ).toBe("EMEA 8 ч из требуемых 4")
  })
  it("нечего показать — пустая строка, не выдуманное число", () => {
    expect(overlapCaption({}, undefined)).toBe("")
    expect(overlapCaption({ hiring_geo: ["worldwide"] }, {})).toBe("")
  })
})
