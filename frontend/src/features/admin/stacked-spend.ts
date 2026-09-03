import type { AdminSpendRow } from "@/api/admin"
import {
  CATEGORY_BARS_VALUE_LABEL_HEIGHT,
  CATEGORY_BARS_X_AXIS_HEIGHT,
  CATEGORY_BARS_Y_AXIS_WIDTH,
  categoryBarsLayout,
  type CategoryBarLayout,
} from "@/features/market/charts"
import { seriesSlot } from "@/features/market/charts/series-tokens"
import { spendBarsInput } from "./admin-spend"

export const STACKED_FILL = ["fill-series-1", "fill-series-2", "fill-series-3"] as const
export const STACKED_SWATCH = ["bg-series-1", "bg-series-2", "bg-series-3"] as const

export type StackedSlice = {
  key: string
  y: number
  height: number
  costUsd: number
}

export function stackedFillClass(key: string, allKeys: readonly string[]): string {
  return STACKED_FILL[seriesSlot(key, allKeys)] ?? STACKED_FILL[0]
}

export function stackedSwatchClass(key: string, allKeys: readonly string[]): string {
  return STACKED_SWATCH[seriesSlot(key, allKeys)] ?? STACKED_SWATCH[0]
}

export function stackedSlices(
  bar: CategoryBarLayout,
  row: AdminSpendRow | undefined,
): StackedSlice[] {
  const segments = (row?.segments ?? []).filter((item) => item.cost_usd > 0)
  if (segments.length === 0 || bar.height <= 0 || bar.value <= 0) return []
  const total = segments.reduce((sum, item) => sum + item.cost_usd, 0)
  if (total <= 0) return []
  let top = bar.y + bar.height
  return [...segments].reverse().map((segment) => {
    const height = (segment.cost_usd / total) * bar.height
    top -= height
    return { key: segment.key, y: top, height, costUsd: segment.cost_usd }
  })
}

export function stackedSpendLayout(
  rows: readonly AdminSpendRow[],
  width: number,
  height: number,
) {
  return categoryBarsLayout(spendBarsInput(rows), width, height)
}

export { CATEGORY_BARS_VALUE_LABEL_HEIGHT, CATEGORY_BARS_X_AXIS_HEIGHT, CATEGORY_BARS_Y_AXIS_WIDTH }
