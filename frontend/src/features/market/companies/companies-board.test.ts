import { describe, expect, it } from "vitest"
import {
  MAX_TARGET,
  addCompany,
  canAccept,
  filterCandidates,
  formatLastSeen,
  matchesCompanyQuery,
  moveCompany,
  zoneOf,
  type CompanyBoardState,
} from "./companies-board"

function state(partial?: Partial<CompanyBoardState>): CompanyBoardState {
  return { target: [], avoid: [], ...partial }
}

describe("moveCompany (K-01)", () => {
  it("не кладёт компанию в два списка сразу", () => {
    const next = moveCompany(state({ avoid: ["Яндекс"] }), "Яндекс", "target")
    expect(next).toEqual({ target: ["Яндекс"], avoid: [] })
  })

  it("переезд target → avoid снимает из целевых", () => {
    const next = moveCompany(state({ target: ["Авито", "VK"] }), "Авито", "avoid")
    expect(next).toEqual({ target: ["VK"], avoid: ["Авито"] })
  })

  it("возврат в «Кандидаты» удаляет из обоих", () => {
    expect(moveCompany(state({ target: ["А"] }), "А", "candidates")).toEqual({
      target: [],
      avoid: [],
    })
    expect(moveCompany(state({ avoid: ["Б"] }), "Б", "candidates")).toEqual({
      target: [],
      avoid: [],
    })
  })

  it("не превышает MAX_TARGET", () => {
    const fullTarget = state({ target: Array.from({ length: MAX_TARGET }, (_, i) => `T${i}`) })
    expect(moveCompany(fullTarget, "Новая", "target")).toBeNull()
    expect(canAccept(fullTarget, "target")).toBe(false)
  })

  it("«Избегать» без лимита: всегда принимает", () => {
    const big = state({ avoid: Array.from({ length: 50 }, (_, i) => `A${i}`) })
    expect(canAccept(big, "avoid")).toBe(true)
    const next = moveCompany(big, "Новая", "avoid")
    expect(next?.avoid).toHaveLength(51)
    expect(next?.avoid.at(-1)).toBe("Новая")
  })

  it("лимит не мешает переезду внутри заполненной зоны (no-op) и принимает candidates", () => {
    const fullTarget = state({ target: Array.from({ length: MAX_TARGET }, (_, i) => `T${i}`) })
    expect(moveCompany(fullTarget, "T0", "target")).toBeNull()
    expect(canAccept(fullTarget, "candidates")).toBe(true)
    expect(moveCompany(fullTarget, "T0", "candidates")).toEqual({
      target: fullTarget.target.slice(1),
      avoid: [],
    })
  })

  it("та же зона и пустое имя → null", () => {
    expect(moveCompany(state({ target: ["X"] }), "X", "target")).toBeNull()
    expect(moveCompany(state(), "  ", "target")).toBeNull()
    expect(moveCompany(state(), "Y", "candidates")).toBeNull()
  })

  it("addCompany делегирует moveCompany", () => {
    expect(addCompany(state({ avoid: ["X"] }), "X", "target")).toEqual({
      target: ["X"],
      avoid: [],
    })
  })

  it("zoneOf и filterCandidates согласованы со списками", () => {
    const s = state({ target: ["A"], avoid: ["B"] })
    expect(zoneOf(s, "A")).toBe("target")
    expect(zoneOf(s, "B")).toBe("avoid")
    expect(zoneOf(s, "C")).toBe("candidates")
    expect(
      filterCandidates([{ company: "A" }, { company: "B" }, { company: "C" }], s).map(
        (c) => c.company,
      ),
    ).toEqual(["C"])
  })
})

describe("matchesCompanyQuery (K-04)", () => {
  it("пустой запрос совпадает со всем", () => {
    expect(matchesCompanyQuery("Яндекс", "")).toBe(true)
    expect(matchesCompanyQuery("Яндекс", "   ")).toBe(true)
  })

  it("регистронезависимая подстрока", () => {
    expect(matchesCompanyQuery("Яндекс Такси", "такси")).toBe(true)
    expect(matchesCompanyQuery("Яндекс Такси", "ЯНДЕКС")).toBe(true)
    expect(matchesCompanyQuery("Авито", "вк")).toBe(false)
  })
})

describe("formatLastSeen (K-04)", () => {
  it("форматирует ISO-дату как ДД.ММ без года", () => {
    // Дата строится из локальных компонент (полдень — подальше от полуночи), чтобы тест не
    // зависел от TZ окружения при переводе через toISOString/parse.
    const iso = new Date(2026, 6, 5, 12, 0, 0).toISOString()
    expect(formatLastSeen(iso)).toBe("05.07")
  })

  it("пусто/некорректная дата → null", () => {
    expect(formatLastSeen(null)).toBeNull()
    expect(formatLastSeen(undefined)).toBeNull()
    expect(formatLastSeen("не дата")).toBeNull()
  })
})
