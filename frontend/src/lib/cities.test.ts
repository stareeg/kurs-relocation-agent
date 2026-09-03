import { describe, expect, it } from "vitest"
import { COUNTRIES } from "./countries"
import {
  CURATED_CITIES,
  UNKNOWN_CITY_HINT,
  formatCityDerivedLine,
  lookupCity,
  mergeCitySuggestions,
  mergeDerivedCountries,
} from "./cities"

describe("city suggestions", () => {
  it("lookup: Москва и алиас Moscow", () => {
    expect(lookupCity("Москва")?.country).toBe("Россия")
    expect(lookupCity("moscow")?.city).toBe("Москва")
    expect(lookupCity("Хогвартс")).toBeUndefined()
  })

  it("merge: пустой API даёт только курируемый список, без падения", () => {
    const merged = mergeCitySuggestions([])
    expect(merged[0]?.city).toBe("Москва")
    expect(merged.length).toBe(CURATED_CITIES.length)
  })

  it("merge: свои данные и опыт встают раньше справочника, дубликаты схлопываются", () => {
    const merged = mergeCitySuggestions(
      [{ city: "Тбилиси", country: "Грузия", source: "jobs" }],
      ["Москва", "Хогвартс"],
    )
    expect(merged[0]?.city).toBe("Тбилиси")
    expect(merged[0]?.source).toBe("jobs")
    expect(merged.some((c) => c.city === "Хогвартс")).toBe(true)
    expect(merged.filter((c) => c.city === "Москва")).toHaveLength(1)
  })

  it("mergeDerivedCountries не затирает второе резидентство", () => {
    expect(mergeDerivedCountries(["Грузия"], "Россия")).toEqual(["Россия", "Грузия"])
    expect(mergeDerivedCountries(["Россия"], "Россия")).toEqual(["Россия"])
    expect(mergeDerivedCountries(["Грузия"])).toEqual(["Грузия"])
  })

  it("часовой пояс рядом с городом: UTC+N или честный отказ", () => {
    expect(formatCityDerivedLine("")).toBe("")
    expect(formatCityDerivedLine("Хогвартс")).toBe(UNKNOWN_CITY_HINT)
    expect(formatCityDerivedLine("Москва")).toBe("UTC+3")
  })

  it("страны курируемых городов совпадают со справочником COUNTRIES", () => {
    const labels = new Set(COUNTRIES.map((c) => c.label))
    for (const item of CURATED_CITIES) {
      expect(labels.has(item.country ?? ""), item.city).toBe(true)
    }
  })
})
