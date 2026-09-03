import { describe, expect, it } from "vitest"
import { mapChainStageToPrepStage, preferUniqueHrScreeningStages } from "./stages"

describe("preferUniqueHrScreeningStages", () => {
  it("не трогает цепочку без дублей HR", () => {
    const stages = [
      { id: 1, stage_type: "hr_screening", status: "completed", position: 0 },
      { id: 2, stage_type: "live_coding", status: "scheduled", position: 1 },
    ]
    expect(preferUniqueHrScreeningStages(stages)).toEqual(stages)
  })

  it("оставляет один HR-скрининг — completed предпочтительнее scheduled", () => {
    const stages = [
      { id: 1, stage_type: "hr_screening", status: "completed", position: 0 },
      { id: 2, stage_type: "live_coding", status: "scheduled", position: 1 },
      { id: 3, stage_type: "final", status: "scheduled", position: 2 },
      { id: 4, stage_type: "hr_screening", status: "scheduled", position: 3 },
    ]
    expect(preferUniqueHrScreeningStages(stages).map((s) => s.id)).toEqual([1, 2, 3])
  })

  it("при двух scheduled оставляет с меньшим position", () => {
    const stages = [
      { id: 10, stage_type: "hr_screening", status: "scheduled", position: 2 },
      { id: 5, stage_type: "hr_screening", status: "scheduled", position: 0 },
    ]
    expect(preferUniqueHrScreeningStages(stages).map((s) => s.id)).toEqual([5])
  })
})

// Унификация HR-скрининга в Техичках: stage="hr_screening" — внутренний флаг TechPage для
// UI-ветвления, но к бэкенду (prep/debrief) уходит нормализованный genStage="screening".
// mapChainStageToPrepStage(hr_screening) фолбэчит на "theory" (нет записи в CHAIN_STAGE_TO_PREP_STAGE),
// поэтому candidateDebriefStages для HR-скрининга фильтрует по stage_type === "hr_screening" явно,
// а не через этот маппинг — иначе HR-этап цепочки не нашёлся бы и разбор не привязался бы к нему.
describe("mapChainStageToPrepStage — инварианты для HR-скрининга", () => {
  it("hr_screening фолбэчит на theory (не screening)", () => {
    expect(mapChainStageToPrepStage("hr_screening")).toBe("theory")
  })

  it("технические этапы маппятся в свои PrepStage", () => {
    expect(mapChainStageToPrepStage("system_design")).toBe("system_design")
    expect(mapChainStageToPrepStage("live_coding")).toBe("live_coding")
    expect(mapChainStageToPrepStage("final")).toBe("final")
  })
})
