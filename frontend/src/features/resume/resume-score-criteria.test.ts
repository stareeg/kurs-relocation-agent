import { describe, expect, it } from "vitest"
import type { ResumeData } from "@/api/resume"
import { leftPanelGaps, leftPanelReadyForScore } from "./resume-score-criteria"

describe("leftPanelReadyForScore", () => {
  it("requires role, market, niches, grade/salary, schedule", () => {
    const empty = {} as ResumeData
    expect(leftPanelReadyForScore(empty)).toBe(false)
    expect(leftPanelGaps(empty).length).toBeGreaterThan(0)
  })

  it("passes when left panel axes are filled", () => {
    const data = {
      position: {
        title: "Dev",
        grade: ["Senior"],
        schedule: ["Удалённо"],
        salary_min: 300000,
      },
      search_criteria: {
        role_kind: "hands_on",
        market_segment: "FinTech",
        niches: ["LLM"],
      },
    } as ResumeData
    expect(leftPanelReadyForScore(data)).toBe(true)
  })

  it("treats empty market_segment as «Любые» (ready)", () => {
    const data = {
      position: {
        grade: ["Senior"],
        schedule: ["Удалённо"],
        salary_min: 300000,
      },
      search_criteria: {
        role_kind: "hands_on",
        market_segment: "",
        niches: ["LLM"],
      },
    } as ResumeData
    expect(leftPanelReadyForScore(data)).toBe(true)
    expect(leftPanelGaps(data)).not.toContain("market_segment")
  })
})
