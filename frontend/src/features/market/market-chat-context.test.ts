import { describe, expect, it } from "vitest"
import type { OfferChance } from "@/api/market"
import type { CategoryBar } from "./charts/category-bars-geometry"
import type { LineMetricInput } from "./charts/line-chart-geometry"
import type { SalaryDistributionInput } from "./charts/salary-distribution-geometry"
import {
  dropoutReasonsAskContext,
  formatsAskContext,
  funnelAskContext,
  offerChanceAskContext,
  resumeReactionAskContext,
  salaryAskContext,
} from "./market-chat-context"

describe("salaryAskContext", () => {
  it("пусто без точек", () => {
    expect(salaryAskContext({ points: [], offers: [] }, "12 вакансий · 30 дней")).toBeNull()
  })

  it("собирает медиану/квартили/цель/офферы", () => {
    const input: SalaryDistributionInput = {
      points: [300_000, 400_000],
      median: 400_000,
      p25: 350_000,
      p75: 400_000,
      targetMin: 350_000,
      targetMax: 450_000,
      offers: [{ key: "o1", company: "Сбер", value: 520_000 }],
    }
    const ctx = salaryAskContext(input, "12 вакансий · 30 дней")
    expect(ctx?.title).toBe("Зарплаты")
    expect(ctx?.body).toContain("медиана 400к")
    expect(ctx?.body).toContain("P25–P75 350к–400к")
    expect(ctx?.body).toContain("целевая вилка 350к–450к")
    expect(ctx?.body).toContain("Сбер 520к")
  })
})

describe("offerChanceAskContext", () => {
  it("нет данных → null", () => {
    expect(offerChanceAskContext(undefined)).toBeNull()
  })

  it("собирает итог и вклады факторов", () => {
    const chance: OfferChance = {
      score: 24,
      preliminary: true,
      delta: -54,
      components: [
        { key: "funnel", label: "Воронка", weight: 0.35, contribution: 7, score: 20 },
        {
          key: "resume_quality",
          label: "Качество резюме",
          weight: 0.25,
          contribution: 10,
          score: 40,
        },
      ],
    }
    const ctx = offerChanceAskContext(chance)
    expect(ctx?.title).toBe("Шанс офферов")
    expect(ctx?.body).toContain("Итог 24 из 100")
    expect(ctx?.body).toContain("предварительно")
    expect(ctx?.body).toContain("изменение за сутки -54")
    expect(ctx?.body).toContain("Воронка 7 из 35")
  })
})

describe("funnelAskContext / dropoutReasonsAskContext", () => {
  const bars: CategoryBar[] = [
    { key: "a", label: "Скрининги", value: 1 },
    { key: "b", label: "Диалоги", value: 2 },
  ]

  it("funnel: пусто → null, иначе строка с периодом", () => {
    expect(funnelAskContext([], "период")).toBeNull()
    const ctx = funnelAskContext(bars, "28.07 – 11.08")
    expect(ctx?.title).toBe("Воронка")
    expect(ctx?.body).toBe("28.07 – 11.08: Скрининги 1, Диалоги 2.")
  })

  it("dropout reasons: пусто → null, иначе строка", () => {
    expect(dropoutReasonsAskContext([])).toBeNull()
    const ctx = dropoutReasonsAskContext(bars)
    expect(ctx?.body).toBe("Пропущено вручную: Скрининги 1, Диалоги 2.")
  })
})

describe("formatsAskContext", () => {
  it("все три пустые → null", () => {
    expect(formatsAskContext([], [], [])).toBeNull()
  })

  it("собирает непустые срезы через точку с запятой", () => {
    const format: CategoryBar[] = [{ key: "remote", label: "Удалённо", value: 4 }]
    const grade: CategoryBar[] = [{ key: "senior", label: "Senior", value: 5 }]
    const ctx = formatsAskContext(format, grade, [])
    expect(ctx?.body).toBe("формат — Удалённо 4; грейд — Senior 5.")
  })
})

describe("resumeReactionAskContext", () => {
  it("нет данных → null", () => {
    const metrics: LineMetricInput[] = [
      { key: "views", label: "просмотры", points: [], days: [], latest: null, delta: null },
    ]
    expect(resumeReactionAskContext(metrics)).toBeNull()
  })

  it("собирает последние значения с дельтой", () => {
    const metrics: LineMetricInput[] = [
      { key: "views", label: "просмотры", points: [], days: [], latest: 60, delta: 5 },
      { key: "invitations", label: "приглашения", points: [], days: [], latest: 3, delta: 0 },
    ]
    const ctx = resumeReactionAskContext(metrics)
    expect(ctx?.title).toBe("Площадки")
    expect(ctx?.body).toBe("просмотры 60 (+5), приглашения 3.")
  })
})
