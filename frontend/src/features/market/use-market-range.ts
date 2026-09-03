import { usePersistedRouteState } from "@/lib/use-persisted-route-state"
import {
  clampRange,
  DEFAULT_MARKET_RANGE,
  formatRangeParam,
  parseRangeParam,
  RANGE_MAX_DAYS,
  type MarketRange,
} from "./period-range"

const DEFAULT_PARAM = formatRangeParam(DEFAULT_MARKET_RANGE)

/**
 * Единый диапазон периода для «Рынка» — `?range=` в адресе (правка 2026-08-03, заменяет
 * дискретный `?period=` из S-01). Источник истины для всех запросов страницы: каждый вызов
 * независимо читает один и тот же параметр — виджетам не нужен ни проп, ни React-контекст,
 * чтобы согласовать период между собой.
 *
 * `maxDays` — реальный домен шкалы (дата первой заскоренной вакансии, правка 2026-08-04); без
 * него клипует к фолбэку `RANGE_MAX_DAYS`, чтобы значение из `?range=`/sessionStorage не улетало
 * за реальную историю, когда она короче.
 */
export function useMarketRange(
  maxDays: number = RANGE_MAX_DAYS,
): [MarketRange, (next: MarketRange) => void] {
  const [raw, setRaw] = usePersistedRouteState<string>({
    param: "range",
    storageKey: "copilot.market.range",
    fallback: DEFAULT_PARAM,
  })
  const parsed = parseRangeParam(raw) ?? DEFAULT_MARKET_RANGE
  const range = clampRange(parsed, maxDays)
  const setRange = (next: MarketRange) => setRaw(formatRangeParam(clampRange(next, maxDays)))
  return [range, setRange]
}
