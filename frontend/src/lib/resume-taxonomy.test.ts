import { describe, expect, it } from "vitest"
import {
  EXPERIENCE_INDUSTRY_OPTIONS,
  EXPERIENCE_INDUSTRY_OTHER,
  MARKET_SEGMENT_SUGGESTIONS,
  RESUME_CATEGORIES,
  experienceIndustrySelectValue,
  normalizeCategories,
} from "./resume-taxonomy"

describe("experience industry", () => {
  it("тот же справочник, что отрасли поиска, без «Любые» и с «Другое»", () => {
    expect(EXPERIENCE_INDUSTRY_OPTIONS).not.toContain("Любые")
    expect(EXPERIENCE_INDUSTRY_OPTIONS).toContain(EXPERIENCE_INDUSTRY_OTHER)
    expect(EXPERIENCE_INDUSTRY_OPTIONS.at(-1)).toBe(EXPERIENCE_INDUSTRY_OTHER)
    const searchOnly = MARKET_SEGMENT_SUGGESTIONS.filter((s) => s !== "Любые")
    expect(EXPERIENCE_INDUSTRY_OPTIONS.slice(0, -1)).toEqual(searchOnly)
  })

  it("пустое → placeholder, канон как есть, неизвестное и «Любые» → «Другое»", () => {
    expect(experienceIndustrySelectValue("")).toBeUndefined()
    expect(experienceIndustrySelectValue("  ")).toBeUndefined()
    expect(experienceIndustrySelectValue("IT")).toBe("IT")
    expect(experienceIndustrySelectValue("банки / финтех")).toBe("Банки / Финтех")
    expect(experienceIndustrySelectValue("Любые")).toBe(EXPERIENCE_INDUSTRY_OTHER)
    expect(experienceIndustrySelectValue("непонятная ниша")).toBe(EXPERIENCE_INDUSTRY_OTHER)
  })
})

describe("RESUME_CATEGORIES", () => {
  it("18 IT и около-IT специальностей, по 9 в колонке", () => {
    expect(RESUME_CATEGORIES).toHaveLength(18)
    const values = RESUME_CATEGORIES.map((c) => c.value)
    expect(new Set(values).size).toBe(18)
    expect(values).toContain("Project Management")
    expect(values).toContain("Product Management")
    expect(values).toContain("Системный анализ")
    expect(values).toContain("Аналитика / Data")
    expect(values).toContain("ML / DS / AI")
    expect(values).toContain("КиберБез")
    expect(values).toContain("Fullstack")
    expect(values).not.toContain("Product/Project/Architecture")
    expect(values).not.toContain("Technical Engineering")
    expect(values).not.toContain("1С")
    expect(values).not.toContain("HR / рекрутинг")
    expect(values).not.toContain("Продажи")
    expect(values).not.toContain("Data / ML")
    expect(values).not.toContain("Аналитика")
    expect(values).not.toContain("Информационная безопасность")
  })

  it("мапит старые getmatch-слаги на канон и схлопывает дубли", () => {
    expect(normalizeCategories(["Project Manager", "QA", "Backend"])).toEqual([
      "Project Management",
      "QA / тестирование",
      "Backend",
    ])
    expect(
      normalizeCategories(["Design & UX", "UX & Tech Writers", "неизвестная ниша"]),
    ).toEqual(["Дизайн / UX"])
    expect(normalizeCategories(["Data / ML", "Аналитика", "Информационная безопасность"])).toEqual([
      "ML / DS / AI",
      "Аналитика / Data",
      "КиберБез",
    ])
    expect(normalizeCategories(["1С", "HR / рекрутинг", "Продажи", "Backend"])).toEqual(["Backend"])
    expect(normalizeCategories([])).toEqual([])
  })
})
