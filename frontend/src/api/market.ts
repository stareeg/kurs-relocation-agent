import type { components } from "@/api/schema"
import { api } from "@/api/client"

export type MarketPulse = components["schemas"]["MarketPulse"]
export type MarketBucket = components["schemas"]["MarketBucket"]
export type MarketGrid = components["schemas"]["MarketGrid"]
export type MarketGridCell = components["schemas"]["MarketGridCell"]
export type SearchMetrics = components["schemas"]["SearchMetrics"]
export type CalibrationReport = components["schemas"]["CalibrationReport"]
export type SalaryBenchmarkReport = components["schemas"]["SalaryBenchmarkReport"]
export type SalaryBenchmarkSegment = components["schemas"]["SalaryBenchmarkSegment"]
export type SalaryBenchmarkPoint = components["schemas"]["SalaryBenchmarkPoint"]
export type MoneyOverview = components["schemas"]["MoneyOverview"]
export type OfferChanceHistory = components["schemas"]["OfferChanceHistory"]
export type ResumeStatsSeries = components["schemas"]["ResumeStatsSeries"]
export type MarketOverview = components["schemas"]["MarketOverview"]
export type OfferChance = components["schemas"]["OfferChance"]
export type OfferChanceComponent = components["schemas"]["OfferChanceComponent"]
export type OfferChancePoint = components["schemas"]["OfferChancePoint"]
export type MarketSupplyFacts = components["schemas"]["MarketSupplyFacts"]
export type LiveOfferPoint = components["schemas"]["LiveOfferPoint"]
export type MarketIndexPoint = components["schemas"]["MarketIndexPoint"]
export type DemandTrend = components["schemas"]["DemandTrend"]
export type DemandPoint = components["schemas"]["DemandPoint"]
export type GatesOverview = components["schemas"]["GatesOverview"]
export type KillFactor = components["schemas"]["KillFactor"]
export type GateCounterfactuals = components["schemas"]["GateCounterfactuals"]
export type SalaryGateCounterfactual = components["schemas"]["SalaryGateCounterfactual"]
export type FormatGateCounterfactual = components["schemas"]["FormatGateCounterfactual"]
export type GateCounterfactualStep = components["schemas"]["GateCounterfactualStep"]
export type StageAging = components["schemas"]["StageAging"]
export type StageAgeRow = components["schemas"]["StageAgeRow"]
export type AgeBucketCount = components["schemas"]["AgeBucketCount"]
export type StalledJob = components["schemas"]["StalledJob"]
export type FunnelLevel = components["schemas"]["FunnelLevel"]
export type FunnelLevelSegment = components["schemas"]["FunnelLevelSegment"]
export type SkipReasonCount = components["schemas"]["SkipReasonCount"]

export function fetchPulse() {
  return api.get<MarketPulse>(`/api/analytics/pulse`)
}

/** GET /api/analytics/search-metrics — воронка, источники, пропуски (B-01). */
export function fetchSearchMetrics() {
  return api.get<SearchMetrics>(`/api/analytics/search-metrics`)
}

/** GET /api/analytics/calibration — «Скоринг не врёт?» (B-02). */
export function fetchCalibration() {
  return api.get<CalibrationReport>(`/api/analytics/calibration`)
}

/** GET /api/analytics/money — две шкалы + планка + форматы (B-03). */
export function fetchMoneyOverview() {
  return api.get<MoneyOverview>(`/api/analytics/money`)
}

/** GET /api/analytics/offer-chance-history — спарклайн шанса офферов (B-04).
 *  `fromDays`/`toDays` — обе границы шкалы периода (план 2026-08-03), «дней назад от сегодня». */
export function fetchOfferChanceHistory(fromDays = 30, toDays = 0) {
  return api.get<OfferChanceHistory>(
    `/api/analytics/offer-chance-history?from_days=${fromDays}&to_days=${toDays}`,
  )
}

/** GET /api/resume-stats — показы/просмотры/приглашения за окно (W-09). */
export function fetchResumeStats(fromDays = 90, toDays = 0) {
  return api.get<ResumeStatsSeries>(`/api/resume-stats?from_days=${fromDays}&to_days=${toDays}`)
}

/** GET /api/market/overview — единый ответ «Рынка» (D-01), в т.ч. индекс рынка (E-03). */
export function fetchMarketOverview(fromDays = 14, toDays = 0) {
  return api.get<MarketOverview>(`/api/market/overview?from_days=${fromDays}&to_days=${toDays}`)
}
