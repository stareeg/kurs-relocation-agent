import { describe, expect, it } from "vitest"
import { isResumeSectionComplete } from "./resume-filled"

const empty = {
  personal: { full_name: "", city: "" },
  contacts: { phone: "", email: "" },
  position: {
    title: "",
    categories: [] as string[],
  },
  search_criteria: {
    market_segment: "",
    niches: [] as string[],
    dealbreakers: [] as string[],
  },
  experience: [] as Array<{
    company: string
    position: string
    start: string
    end: string
    current: boolean
    description: string
  }>,
  education: [] as Array<{ institution: string }>,
  key_skills: [] as string[],
  languages: [] as Array<{ name: string; level: string }>,
  about: "",
}

describe("isResumeSectionComplete", () => {
  it("personal: требует профессию, специальности, ФИО, город — страну не требует", () => {
    expect(isResumeSectionComplete("personal", empty)).toBe(false)
    const filled = {
      ...empty,
      personal: { full_name: "Иванов", city: "Москва" },
      position: { title: "Инженер", categories: ["Backend"] },
    }
    expect(isResumeSectionComplete("personal", filled)).toBe(true)
    // Без страны блок полный: страна выводится из города.
    expect(
      isResumeSectionComplete("personal", {
        ...filled,
        personal: { full_name: "Иванов", city: "Хогвартс" },
      }),
    ).toBe(true)
    // Специальности переехали в «Профиль» вместе с профессией — без них блок неполный.
    expect(
      isResumeSectionComplete("personal", {
        ...filled,
        position: { ...filled.position, categories: [] },
      }),
    ).toBe(false)
  })


  it("search: достаточно приоритетов (отрасль «Любые» = пустая строка)", () => {
    expect(isResumeSectionComplete("search", empty)).toBe(false)
    expect(
      isResumeSectionComplete("search", {
        ...empty,
        search_criteria: {
          market_segment: "",
          niches: ["Python"],
          dealbreakers: [],
        },
      }),
    ).toBe(true)
    expect(
      isResumeSectionComplete("search", {
        ...empty,
        search_criteria: {
          market_segment: "IT",
          niches: ["Python"],
          dealbreakers: [],
        },
      }),
    ).toBe(true)
  })

  it("experience: все обязательные поля в каждой записи", () => {
    expect(
      isResumeSectionComplete("experience", {
        ...empty,
        experience: [
          {
            company: "Acme",
            position: "Dev",
            start: "2020-01",
            end: "",
            current: true,
            description: "Делал вещи",
          },
        ],
      }),
    ).toBe(true)
    expect(
      isResumeSectionComplete("experience", {
        ...empty,
        experience: [
          {
            company: "Acme",
            position: "Dev",
            start: "2020-01",
            end: "",
            current: false,
            description: "Делал вещи",
          },
        ],
      }),
    ).toBe(false)
  })
})
