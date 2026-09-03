import { describe, expect, it } from "vitest"
import { formatDayShort } from "@/features/market/charts"
import { cacheHitLabel, orderSpendRows, spendBarsInput, spendRowLabel, spendTooltipLines, taskKindLabel, visibleSpendRows } from "./admin-spend"

describe("taskKindLabel", () => {
  it("переводит kind очереди на русский", () => {
    expect(taskKindLabel("salary_estimate")).toBe("Оценка зарплаты")
    expect(taskKindLabel("situation_refresh")).toBe("Обновление ситуации")
    expect(taskKindLabel("tg_push")).toBe("Пуш в Telegram")
  })
})

describe("spendBarsInput", () => {
  it("день — короткая дата, столбик берёт то же число, что KPI", () => {
    const input = spendBarsInput([
      { key: "2026-08-25", cost_usd: 0.75, tokens_in: 0, tokens_out: 0, calls: 3, cache_hits: 0, retries: 0 },
    ])
    expect(input.rows[0]?.value).toBe(0.75)
    expect(input.rows[0]?.label).toBe(formatDayShort("2026-08-25"))
  })

  it("модель и фича остаются подписью, длинное режется", () => {
    const input = spendBarsInput([
      { key: "openai/gpt-5.6-luna", cost_usd: 1, tokens_in: 0, tokens_out: 0, calls: 1, cache_hits: 0, retries: 0 },
      {
        key: "очень-длинное-имя-фичи-которое-не-влезает-на-ось",
        cost_usd: 2,
        tokens_in: 0,
        tokens_out: 0,
        calls: 1,
        cache_hits: 0,
        retries: 0,
      },
    ])
    expect(input.rows[0]?.label).toBe("gpt-5.6-luna")
    expect(input.rows[1]?.label.endsWith("…")).toBe(true)
  })
})

describe("cacheHitLabel", () => {
  it("нет вызовов — не врёт нулём процентов", () => {
    expect(cacheHitLabel(null, 0)).toBe("кэш: нет вызовов")
    expect(cacheHitLabel(0.34, 10)).toBe("кэш 34%")
  })
})

describe("spendTooltipLines", () => {
  it("пустые вызовы — только деньги, без нулевого кэша", () => {
    const lines = spendTooltipLines(
      { key: "2026-08-25", cost_usd: 0.5, tokens_in: 0, tokens_out: 0, calls: 0, cache_hits: 0, retries: 0 },
      "25 авг",
    )
    expect(lines).toEqual([{ label: "25 авг", value: "$0.50" }])
  })

  it("строка с вызовами показывает кэш, latency и повторы", () => {
    const lines = spendTooltipLines(
      {
        key: "openai/gpt",
        cost_usd: 1,
        tokens_in: 0,
        tokens_out: 0,
        calls: 10,
        cache_hits: 4,
        cache_hit_rate: 0.4,
        median_ms: 320,
        p95_ms: 900,
        retries: 2,
        retry_share: 0.2,
      },
      "openai/gpt",
    )
    expect(lines.map((line) => line.label)).toEqual(["openai/gpt", "кэш", "p50", "p95", "повторы"])
    expect(lines[1]?.value).toBe("40%")
    expect(lines[4]?.value).toBe("20%")
  })
})

describe("spendRowLabel: подпись дня", () => {
  it("голый ISO-день — короткая дата", () => {
    expect(spendRowLabel("2026-08-12")).toBe("12.08")
  })

  it("день с временем и зоной — тоже короткая дата, а не сырой таймстемп", () => {
    // Ровно то, что бэкенд отдавал до Этапа 1 и что ещё лежит в llm_result_cache.
    expect(spendRowLabel("2026-08-12 00:00:00+00")).toBe("12.08")
    expect(spendRowLabel("2026-08-12T00:00:00Z")).toBe("12.08")
  })

  it("фича — короткое русское имя, модель — короткий slug", () => {
    expect(spendRowLabel("openai/gpt-5.6-luna")).toBe("gpt-5.6-luna")
    expect(spendRowLabel("screening_brief")).toBe("Бриф скрининга")
  })
})

describe("orderSpendRows", () => {
  it("дни — новая дата первая, модели не трогает", () => {
    const rows = [
      { key: "2026-08-24", cost_usd: 1, tokens_in: 0, tokens_out: 0, calls: 1, cache_hits: 0, retries: 0 },
      { key: "2026-08-25", cost_usd: 2, tokens_in: 0, tokens_out: 0, calls: 1, cache_hits: 0, retries: 0 },
    ]
    expect(orderSpendRows(rows, "day").map((row) => row.key)).toEqual(["2026-08-25", "2026-08-24"])
    expect(orderSpendRows(rows, "model").map((row) => row.key)).toEqual(["2026-08-24", "2026-08-25"])
  })
})

describe("visibleSpendRows", () => {
  it("в разрезе фич прячет траты дешевле 5 центов", () => {
    const rows = [
      { key: "chat", cost_usd: 1, tokens_in: 0, tokens_out: 0, calls: 1, cache_hits: 0, retries: 0 },
      { key: "qa", cost_usd: 0.04, tokens_in: 0, tokens_out: 0, calls: 1, cache_hits: 0, retries: 0 },
    ]
    expect(visibleSpendRows(rows, "feature").map((row) => row.key)).toEqual(["chat"])
    expect(visibleSpendRows(rows, "day").map((row) => row.key)).toEqual(["chat", "qa"])
  })
})
