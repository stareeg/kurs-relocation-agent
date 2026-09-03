/**
 * Aggregator for Market page queries (F-04).
 *
 * One module owns every fetch the section needs so widgets share staleTime /
 * live-channel polling fallback and the same query keys as EVENT_QUERY_KEYS.
 */
import { useQuery } from "@tanstack/react-query"
import { fetchCompanies } from "@/api/companies"
import {
  fetchCalibration,
  fetchMarketOverview,
  fetchMoneyOverview,
  fetchOfferChanceHistory,
  fetchPulse,
  fetchResumeStats,
  fetchSearchMetrics,
} from "@/api/market"
import { useLiveEventsConnected } from "@/app/use-live-invalidation"
import type { MarketRange } from "./period-range"
import { useMarketRange } from "./use-market-range"

/** Shared with live-invalidation and reconnect refresh. */
export const MARKET_QUERY_KEYS = {
  pulse: ["market-pulse"] as const,
  search: ["market-search"] as const,
  calibration: ["market-calibration"] as const,
  money: ["market-money"] as const,
  chanceHistory: ["market-chance-history"] as const,
  overview: ["market-overview"] as const,
  resumeStats: ["resume-stats"] as const,
  companies: ["companies"] as const,
}

const STALE_MS = 30_000
const POLL_MS = 60_000

/** Polling only while `/api/events/stream` is down — same fallback as the old grid hook. */
function useMarketLiveQueryOptions() {
  const liveConnected = useLiveEventsConnected()
  return {
    staleTime: STALE_MS,
    refetchInterval: liveConnected ? (false as const) : POLL_MS,
  }
}

export function useMarketPulse() {
  const live = useMarketLiveQueryOptions()
  return useQuery({
    queryKey: MARKET_QUERY_KEYS.pulse,
    queryFn: fetchPulse,
    ...live,
    refetchOnWindowFocus: false,
  })
}

export function useMarketSearch() {
  const live = useMarketLiveQueryOptions()
  return useQuery({
    queryKey: MARKET_QUERY_KEYS.search,
    queryFn: fetchSearchMetrics,
    ...live,
  })
}

export function useMarketCalibration() {
  const live = useMarketLiveQueryOptions()
  return useQuery({
    queryKey: MARKET_QUERY_KEYS.calibration,
    queryFn: fetchCalibration,
    ...live,
  })
}

export function useMarketMoney() {
  const live = useMarketLiveQueryOptions()
  return useQuery({
    queryKey: MARKET_QUERY_KEYS.money,
    queryFn: fetchMoneyOverview,
    ...live,
  })
}

/** Без явного `range` берёт диапазон из шкалы периода над секциями — как `useMarketOverview`. */
export function useMarketChanceHistory(range?: MarketRange) {
  const [pageRange] = useMarketRange()
  const effective = range ?? pageRange
  const live = useMarketLiveQueryOptions()
  return useQuery({
    queryKey: [...MARKET_QUERY_KEYS.chanceHistory, effective.fromDays, effective.toDays] as const,
    queryFn: () => fetchOfferChanceHistory(effective.fromDays, effective.toDays),
    ...live,
  })
}

/**
 * E-03: индекс рынка живёт внутри `/api/market/overview` — своя часть кэша тем же ключом.
 * Без явного `range` берёт диапазон из шкалы периода над секциями (`?range=`) — одна шкала
 * скоупит весь контракт `overview`.
 */
export function useMarketOverview(range?: MarketRange) {
  const [pageRange] = useMarketRange()
  const effective = range ?? pageRange
  const live = useMarketLiveQueryOptions()
  return useQuery({
    queryKey: [...MARKET_QUERY_KEYS.overview, effective.fromDays, effective.toDays] as const,
    queryFn: () => fetchMarketOverview(effective.fromDays, effective.toDays),
    ...live,
  })
}

/** Без явного `range` берёт диапазон из шкалы периода над секциями — как `useMarketOverview`. */
export function useResumeStats(range?: MarketRange) {
  const [pageRange] = useMarketRange()
  const effective = range ?? pageRange
  const live = useMarketLiveQueryOptions()
  return useQuery({
    queryKey: [...MARKET_QUERY_KEYS.resumeStats, effective.fromDays, effective.toDays] as const,
    queryFn: () => fetchResumeStats(effective.fromDays, effective.toDays),
    ...live,
  })
}

export function useMarketCompanies() {
  const live = useMarketLiveQueryOptions()
  return useQuery({
    queryKey: MARKET_QUERY_KEYS.companies,
    queryFn: fetchCompanies,
    ...live,
  })
}
