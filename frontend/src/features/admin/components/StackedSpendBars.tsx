import { useState } from "react"
import type { AdminSpendRow } from "@/api/admin"
import { ChartTooltip } from "@/features/market/charts"
import { useContainerWidth } from "@/lib/use-container-width"
import { cn } from "@/lib/utils"
import { findSpendRow, shortModelSlug, spendTooltipLines } from "@/features/admin/admin-spend"
import {
  CATEGORY_BARS_VALUE_LABEL_HEIGHT,
  CATEGORY_BARS_Y_AXIS_WIDTH,
  stackedFillClass,
  stackedSlices,
  stackedSpendLayout,
  stackedSwatchClass,
} from "@/features/admin/stacked-spend"

/**
 * Столбик дня складывается из моделей — как Activity у OpenRouter.
 */
export function StackedSpendBars({
  rows,
  modelKeys,
  height = 160,
}: {
  rows: readonly AdminSpendRow[]
  modelKeys: readonly string[]
  height?: number
}) {
  const [hover, setHover] = useState<number | null>(null)
  const { ref, width } = useContainerWidth<HTMLDivElement>(560)
  const layout = stackedSpendLayout(rows, width, height)
  if (!layout) return null

  const xLabelLineH = layout.xLabelMode === "rotated" ? 28 : 14
  const totalH =
    layout.chartH + CATEGORY_BARS_VALUE_LABEL_HEIGHT + 16 + xLabelLineH

  return (
    <div ref={ref} className="relative min-w-0" data-testid="stacked-spend-bars">
      <svg
        width={width}
        height={totalH}
        viewBox={`0 0 ${width} ${totalH}`}
        className="block overflow-visible"
        role="img"
        aria-label="Расход по дням и моделям"
      >
        <g transform={`translate(${CATEGORY_BARS_Y_AXIS_WIDTH} ${CATEGORY_BARS_VALUE_LABEL_HEIGHT})`}>
          {layout.gridLines.map((line, i) => (
            <line
              key={`grid-${i}`}
              x1={0}
              x2={layout.chartW}
              y1={line.y}
              y2={line.y}
              className="text-slate-100"
              stroke="currentColor"
              strokeWidth={1}
            />
          ))}
          {layout.yTicks.map((tick) => (
            <text
              key={`ytick-${tick.label}`}
              x={-8}
              y={tick.y + 3}
              textAnchor="end"
              className="fill-slate-400 text-[10px] tabular-nums"
            >
              {tick.label}
            </text>
          ))}
          {layout.rows.map((bar, i) => {
            const row = findSpendRow(rows, bar.key)
            const slices = stackedSlices(bar, row)
            return (
              <g
                key={bar.key}
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover((cur) => (cur === i ? null : cur))}
              >
                {slices.length > 0 ? (
                  slices.map((slice) => (
                    <rect
                      key={slice.key}
                      x={bar.x}
                      y={slice.y}
                      width={bar.width}
                      height={Math.max(slice.height, 0)}
                      className={cn("transition-opacity", stackedFillClass(slice.key, modelKeys))}
                    />
                  ))
                ) : (
                  <rect
                    x={bar.x}
                    y={bar.y}
                    width={bar.width}
                    height={bar.height}
                    className="fill-slate-200"
                  />
                )}
                {bar.value > 0 ? (
                  <text
                    x={bar.x + bar.width / 2}
                    y={bar.y - 4}
                    textAnchor="middle"
                    className="fill-slate-600 text-[10px] tabular-nums"
                  >
                    {bar.valueLabel}
                  </text>
                ) : null}
                {layout.xLabelMode === "rotated" ? (
                  <text
                    x={bar.x + bar.width / 2}
                    y={layout.chartH + 12}
                    textAnchor="end"
                    className="fill-slate-500 text-[10px]"
                    transform={`rotate(-45 ${bar.x + bar.width / 2} ${layout.chartH + 12})`}
                  >
                    {bar.xLabel}
                  </text>
                ) : (
                  <text
                    x={bar.x + bar.width / 2}
                    y={layout.chartH + 12}
                    textAnchor={bar.xLabelAnchor}
                    className="fill-slate-500 text-[10px]"
                  >
                    {bar.xLabel}
                  </text>
                )}
              </g>
            )
          })}
          <line
            x1={0}
            x2={layout.chartW}
            y1={layout.chartH}
            y2={layout.chartH}
            className="text-slate-300"
            stroke="currentColor"
            strokeWidth={1}
          />
        </g>
      </svg>
      {hover != null && layout.rows[hover] ? (
        <ChartTooltip
          x={CATEGORY_BARS_Y_AXIS_WIDTH + layout.rows[hover]!.x + layout.rows[hover]!.width / 2}
          y={CATEGORY_BARS_VALUE_LABEL_HEIGHT + layout.rows[hover]!.y}
          rows={spendTooltipLines(
            findSpendRow(rows, layout.rows[hover]!.key),
            layout.rows[hover]!.label,
          )}
        />
      ) : null}
      {modelKeys.length > 0 ? (
        <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-500">
          {modelKeys.map((key) => (
            <li key={key} className="inline-flex items-center gap-1.5">
              <span className={cn("size-2 rounded-sm", stackedSwatchClass(key, modelKeys))} />
              <span>{shortModelSlug(key)}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
