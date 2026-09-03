import { describe, expect, it } from "vitest"
import { formatRecentAction } from "./recent-actions"

describe("formatRecentAction", () => {
  it("мапит путь раздела и фичу", () => {
    expect(formatRecentAction({ kind: "nav", label: "/jobs" })).toBe("Раздел · Вакансии")
    expect(formatRecentAction({ kind: "feature", label: "qa_vacancy" })).toBe(
      "Фича · Чат по вакансии",
    )
  })
})
