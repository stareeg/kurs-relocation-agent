import { describe, expect, it } from "vitest"
import {
  clampRange,
  daysToPct,
  DEFAULT_FROM_DAYS,
  DEFAULT_MARKET_RANGE,
  DEFAULT_TO_DAYS,
  formatBoundaryDate,
  formatRangeParam,
  MIN_SPAN_DAYS,
  moveHandle,
  parseRangeParam,
  pctToDays,
  RANGE_MAX_DAYS,
  rangeSpanDays,
} from "./period-range"

describe("clampRange (шкала периода 2026-08-03)", () => {
  it("значения внутри домена не меняются", () => {
    expect(clampRange({ fromDays: 14, toDays: 0 })).toEqual({ fromDays: 14, toDays: 0 })
  })

  it("клипует за пределы домена 0..RANGE_MAX_DAYS", () => {
    expect(clampRange({ fromDays: 999, toDays: -5 })).toEqual({
      fromDays: RANGE_MAX_DAYS,
      toDays: 0,
    })
  })

  it("не даёт границам сомкнуться — раздвигает на минимальный зазор", () => {
    const result = clampRange({ fromDays: 10, toDays: 10 })
    expect(result.fromDays - result.toDays).toBeGreaterThanOrEqual(MIN_SPAN_DAYS)
  })

  it("раздвигание у правого края домена уходит влево, не за границу", () => {
    const result = clampRange({ fromDays: RANGE_MAX_DAYS, toDays: RANGE_MAX_DAYS })
    expect(result.fromDays).toBeLessThanOrEqual(RANGE_MAX_DAYS)
    expect(result.fromDays - result.toDays).toBeGreaterThanOrEqual(MIN_SPAN_DAYS)
  })

  it("нечисловые значения приводятся к минимуму домена", () => {
    expect(clampRange({ fromDays: Number.NaN, toDays: 0 }).fromDays).toBe(MIN_SPAN_DAYS)
  })
})

describe("moveHandle — двигает одну границу, не трогая соседнюю", () => {
  it("свободное движение внутри домена", () => {
    expect(moveHandle({ fromDays: 30, toDays: 0 }, "from", 20)).toEqual({
      fromDays: 20,
      toDays: 0,
    })
    expect(moveHandle({ fromDays: 30, toDays: 0 }, "to", 10)).toEqual({
      fromDays: 30,
      toDays: 10,
    })
  })

  it("`from` не может подойти к `to` ближе минимального зазора — сама останавливается", () => {
    const result = moveHandle({ fromDays: 30, toDays: 10 }, "from", 5)
    expect(result).toEqual({ fromDays: 11, toDays: 10 })
  })

  it("`to` не может обогнать `from` — сама останавливается, `from` не двигается", () => {
    const result = moveHandle({ fromDays: 30, toDays: 10 }, "to", 40)
    expect(result).toEqual({ fromDays: 30, toDays: 29 })
  })

  it("клипует за пределы домена 0..RANGE_MAX_DAYS", () => {
    expect(moveHandle({ fromDays: 30, toDays: 0 }, "from", 999).fromDays).toBe(RANGE_MAX_DAYS)
    expect(moveHandle({ fromDays: 30, toDays: 10 }, "to", -50).toDays).toBe(0)
  })
})

describe("formatRangeParam / parseRangeParam", () => {
  it("сериализация и разбор — круговая совместимость", () => {
    const range = { fromDays: 30, toDays: 5 }
    expect(parseRangeParam(formatRangeParam(range))).toEqual(range)
  })

  it("пусто/null → null (вызывающий берёт дефолт)", () => {
    expect(parseRangeParam(null)).toBeNull()
    expect(parseRangeParam("")).toBeNull()
  })

  it("незнакомый формат → null, а не NaN", () => {
    expect(parseRangeParam("тридцать")).toBeNull()
    expect(parseRangeParam("30")).toBeNull()
  })

  it("разобранное значение проходит через clampRange", () => {
    expect(parseRangeParam("9999-9999")).toEqual({
      fromDays: RANGE_MAX_DAYS,
      toDays: RANGE_MAX_DAYS - MIN_SPAN_DAYS,
    })
  })
})

describe("rangeSpanDays", () => {
  it("ширина окна = from - to", () => {
    expect(rangeSpanDays({ fromDays: 14, toDays: 0 })).toBe(14)
  })

  it("не бывает меньше MIN_SPAN_DAYS", () => {
    expect(rangeSpanDays({ fromDays: 5, toDays: 5 })).toBe(MIN_SPAN_DAYS)
  })
})

describe("daysToPct / pctToDays", () => {
  it("сегодня (0 дней) — правый край шкалы (100%)", () => {
    expect(daysToPct(0)).toBe(100)
  })

  it("самая старая дата домена — левый край (0%)", () => {
    expect(daysToPct(RANGE_MAX_DAYS)).toBe(0)
  })

  it("обратное преобразование восстанавливает исходное значение", () => {
    const days = 14
    expect(pctToDays(daysToPct(days))).toBe(days)
  })
})

describe("formatBoundaryDate", () => {
  it("день.месяц с ведущими нулями", () => {
    const now = new Date(Date.UTC(2026, 7, 3)) // 3 августа 2026
    expect(formatBoundaryDate(0, now)).toBe("03.08")
    expect(formatBoundaryDate(14, now)).toBe("20.07")
  })
})

describe("дефолты", () => {
  it("правая граница — сегодня, левая — 14 дней назад", () => {
    expect(DEFAULT_TO_DAYS).toBe(0)
    expect(DEFAULT_FROM_DAYS).toBe(14)
    expect(DEFAULT_MARKET_RANGE).toEqual({ fromDays: 14, toDays: 0 })
  })
})
