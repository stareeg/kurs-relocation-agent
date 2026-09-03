import { describe, expect, it } from "vitest"
import type { ResumeData } from "@/api/resume"
import { applyResumePatch, patchTouchesSkillCorpus } from "./apply-resume-patch"

function resume(overrides: Partial<ResumeData> = {}): ResumeData {
  return {
    personal: {
      full_name: "Иван",
      gender: "male",
      birth_date: "",
      city: "Москва",
      work_countries: [],
      relocation: "",
    },
    position: {
      title: "Backend-разработчик",
      salary_currency: "RUB",
      salary_basis: "gross",
      employment: "full",
      grade: ["middle"],
    },
    search_criteria: {
      role_kind: "hands_on",
      market_segment: "",
      market_scope: "",
      target_companies: ["Яндекс"],
      avoid_companies: [],
      notes: "",
    },
    experience_total: "3 года",
    education_level: "higher",
    education: [],
    key_skills: ["python"],
    languages: [],
    about: "",
    ...overrides,
  }
}

describe("applyResumePatch", () => {
  it("merges search_criteria by key, keeping fields the patch didn't touch", () => {
    const current = resume()
    const next = applyResumePatch(current, {
      search_criteria: { target_companies: ["Яндекс", "Т-Банк"] },
    })
    expect(next.search_criteria?.target_companies).toEqual(["Яндекс", "Т-Банк"])
    expect(next.search_criteria?.role_kind).toBe("hands_on")
    expect(next.search_criteria?.avoid_companies).toEqual([])
  })

  it("does not mutate the source object", () => {
    const current = resume()
    applyResumePatch(current, { search_criteria: { avoid_companies: ["Газпром"] } })
    expect(current.search_criteria?.avoid_companies).toEqual([])
  })

  it("merges personal and position independently", () => {
    const current = resume()
    const next = applyResumePatch(current, { personal: { relocation: "готов" } })
    expect(next.personal?.relocation).toBe("готов")
    expect(next.personal?.full_name).toBe("Иван")
    expect(next.position).toBe(current.position)
  })

  it("replaces array fields wholesale (education/languages/key_skills)", () => {
    const current = resume()
    const next = applyResumePatch(current, { key_skills: ["python", "sql"] })
    expect(next.key_skills).toEqual(["python", "sql"])
  })

  it("ignores untouched top-level fields", () => {
    const current = resume()
    const next = applyResumePatch(current, {})
    expect(next).toEqual(current)
  })
})

describe("patchTouchesSkillCorpus", () => {
  it("пол/релокация не трогают снимок навыков", () => {
    expect(patchTouchesSkillCorpus({ personal: { gender: "Мужчина" } })).toBe(false)
  })

  it("специальности и ключевые навыки — да", () => {
    expect(patchTouchesSkillCorpus({ position: { categories: ["Backend"] } })).toBe(true)
    expect(patchTouchesSkillCorpus({ key_skills: ["python"] })).toBe(true)
  })
})
