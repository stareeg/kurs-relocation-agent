import { api } from "@/api/client"
import type { components } from "@/api/schema"

export type MetricsResponse = components["schemas"]["MetricsResponse"]
export type TierTokenTotals = components["schemas"]["TierTokenTotals"]

export function fetchMetrics() {
  return api.get<MetricsResponse>("/api/metrics")
}

/** Токены по тирам (базовые/продвинутые) — сегодня и за 30 дней (таблица llm_usage). */
export function tokenStatsFromMetrics(m: MetricsResponse): {
  todayBasic: TierTokenTotals
  todayAdvanced: TierTokenTotals
  monthBasic: TierTokenTotals
  monthAdvanced: TierTokenTotals
} {
  const empty: TierTokenTotals = { tokens_in: 0, tokens_out: 0 }
  return {
    todayBasic: m.token_stats?.today_basic ?? empty,
    todayAdvanced: m.token_stats?.today_advanced ?? empty,
    monthBasic: m.token_stats?.month_basic ?? empty,
    monthAdvanced: m.token_stats?.month_advanced ?? empty,
  }
}
