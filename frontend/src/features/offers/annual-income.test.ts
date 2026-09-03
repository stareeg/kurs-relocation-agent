import { describe, expect, it } from "vitest"
import type { OfferRecord } from "@/api/offers"
import { computeAnnualIncome } from "./annual-income"

function offer(p: Partial<OfferRecord>): OfferRecord {
  return {
    vacancy_id: "v1",
    company: "",
    position: "",
    base_salary_currency: "RUB",
    base_salary_period: "month",
    bonus: "",
    equity: "",
    notice_period: "",
    relocation_package: "",
    work_format: "unknown",
    location: "",
    base_salary_tax_basis: "gross",
    bonus_type: "none",
    bonus_types: [],
    contract_type: "employment",
    location_country: "",
    ...p,
  } as OfferRecord
}

describe("computeAnnualIncome", () => {
  it("нет оклада — null", () => {
    expect(computeAnnualIncome(offer({ base_salary: null }))).toBeNull()
    expect(computeAnnualIncome(offer({ base_salary: 0 }))).toBeNull()
  })

  it("месячный оклад приводится к году", () => {
    const res = computeAnnualIncome(offer({ base_salary: 500_000, base_salary_period: "month" }))
    expect(res).toEqual({ total: 6_000_000, currency: "₽", hasSignon: false })
  })

  it("годовой оклад берётся как есть", () => {
    const res = computeAnnualIncome(offer({ base_salary: 6_000_000, base_salary_period: "year" }))
    expect(res?.total).toBe(6_000_000)
  })

  it("добавляет годовую премию из помесячного эквивалента", () => {
    const res = computeAnnualIncome(
      offer({ base_salary: 500_000, bonus_type: "annual", bonus_monthly_equiv: 100_000 }),
    )
    expect(res?.total).toBe(500_000 * 12 + 100_000 * 12)
  })

  it("годовая премия из процента — добавка к окладу, не вместо него", () => {
    const base = offer({ base_salary: 500_000, base_salary_period: "month" })
    const withBonus = offer({
      base_salary: 500_000,
      base_salary_period: "month",
      bonus_types: ["annual"],
      bonus_type: "annual",
      annual_bonus_pct: 10,
    })
    const before = computeAnnualIncome(base)?.total ?? 0
    const after = computeAnnualIncome(withBonus)?.total ?? 0
    expect(after).toBe(6_600_000)
    expect(after).toBeGreaterThan(before)
  })

  it("процент побеждает устаревший помесячный эквивалент", () => {
    const res = computeAnnualIncome(
      offer({
        base_salary: 500_000,
        bonus_types: ["annual"],
        bonus_type: "annual",
        annual_bonus_pct: 10,
        // легаси: весь оклад ошибочно записан как «премия» — раньше это раздувало
        // итог, а при пересчёте на 10% сумма падала
        bonus_monthly_equiv: 500_000,
      }),
    )
    expect(res?.total).toBe(6_600_000)
  })

  it("квартальная 20% от квартала = 20% годового оклада сверху", () => {
    const res = computeAnnualIncome(
      offer({
        base_salary: 500_000,
        bonus_types: ["quarterly"],
        bonus_type: "quarterly",
        quarterly_bonus_pct: 20,
      }),
    )
    expect(res?.total).toBe(7_200_000)
  })

  it("годовая и квартальная складываются", () => {
    const res = computeAnnualIncome(
      offer({
        base_salary: 500_000,
        bonus_types: ["annual", "quarterly"],
        bonus_type: "annual",
        annual_bonus_pct: 10,
        quarterly_bonus_pct: 10,
      }),
    )
    expect(res?.total).toBe(7_200_000)
  })

  it("добавляет welcome-бонус разово и помечает hasSignon", () => {
    const res = computeAnnualIncome(offer({ base_salary: 500_000, signon: 300_000 }))
    expect(res?.total).toBe(500_000 * 12 + 300_000)
    expect(res?.hasSignon).toBe(true)
  })

  it("валюта офера отражается в результате", () => {
    const res = computeAnnualIncome(
      offer({ base_salary: 5_000, base_salary_currency: "USD", work_format: "currency" }),
    )
    expect(res?.currency).toBe("$")
  })
})
