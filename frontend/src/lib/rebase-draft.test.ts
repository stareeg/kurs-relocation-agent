import { describe, expect, it } from "vitest"
import { rebaseDraft } from "./rebase-draft"

// Форма «Резюме» в миниатюре: вложенные объекты + список строк с клиентским `_uid`.
type Form = {
  position: { title: string; salary_basis: string; salary_min: number | null }
  search_criteria: { role_kind: string; niches: string[] }
  about: string
  experience: { _uid: string; company: string }[]
}

const NESTED = ["position", "search_criteria"] as const

function stripUid(value: unknown): unknown {
  if (!Array.isArray(value)) return value
  return value.map((row) =>
    row && typeof row === "object" && "_uid" in row
      ? Object.fromEntries(Object.entries(row).filter(([k]) => k !== "_uid"))
      : row,
  )
}

function rebase(draft: Form, prev: Form, next: Form): Form {
  return rebaseDraft(draft, prev, next, { nestedKeys: NESTED, normalize: stripUid })
}

function form(overrides: Partial<Form> = {}): Form {
  return {
    position: { title: "AI-инженер", salary_basis: "На руки", salary_min: 300000 },
    search_criteria: { role_kind: "", niches: ["LLM"] },
    about: "текст о себе",
    experience: [{ _uid: "u1", company: "Дневник.ру" }],
    ...overrides,
  }
}

describe("rebaseDraft", () => {
  it("применяет чужой автосейв, когда черновик это поле не трогал", () => {
    const base = form()
    const draft = form()
    const next = form({ position: { ...base.position, salary_basis: "Гросс" } })

    const out = rebase(draft, base, next)

    expect(out.position.salary_basis).toBe("Гросс")
  })

  it("не затирает несохранённый ввод владельца", () => {
    const base = form()
    const draft = form({ about: "мой новый текст" })
    const next = form({ about: "текст с бэкенда" })

    const out = rebase(draft, base, next)

    expect(out.about).toBe("мой новый текст")
  })

  it("правка соседнего под-поля не блокирует автосейв в том же объекте", () => {
    const base = form()
    const draft = form({ position: { ...base.position, title: "Lead LLM Engineer" } })
    const next = form({ position: { ...base.position, salary_basis: "Гросс" } })

    const out = rebase(draft, base, next)

    expect(out.position.title).toBe("Lead LLM Engineer")
    expect(out.position.salary_basis).toBe("Гросс")
  })

  it("после ребейза черновик равен новой базе, если владелец ничего не правил", () => {
    const base = form()
    const draft = form()
    const next = form({
      position: { ...base.position, salary_basis: "Гросс" },
      search_criteria: { role_kind: "hands_on", niches: ["LLM"] },
    })

    const out = rebase(draft, base, next)

    expect(stripUid(out.experience)).toEqual(stripUid(next.experience))
    expect(out.position).toEqual(next.position)
    expect(out.search_criteria).toEqual(next.search_criteria)
  })

  it("не перемонтирует строки списка, если по сути они не изменились", () => {
    const base = form()
    const draft = form()
    // normalize() на бэкенд-данных выдаёт свежие `_uid` — по сути это тот же список.
    const next = form({ experience: [{ _uid: "u-fresh", company: "Дневник.ру" }] })

    const out = rebase(draft, base, next)

    expect(out.experience[0]!._uid).toBe("u1")
  })

  it("подхватывает изменившийся список, которого черновик не касался", () => {
    const base = form()
    const draft = form()
    const next = form({ experience: [{ _uid: "u2", company: "РСХБ-Интех" }] })

    const out = rebase(draft, base, next)

    expect(out.experience[0]!.company).toBe("РСХБ-Интех")
  })

  it("возвращает тот же объект, если менять нечего", () => {
    const base = form()
    const draft = form()
    const next = form()
    expect(rebase(draft, base, next)).toBe(draft)
  })
})
