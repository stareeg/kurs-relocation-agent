import type { SparklinePoint } from "./sparkline-geometry"
import { normalizePoints, sparklineLayout } from "./sparkline-geometry"
import { ChartTooltip } from "./ChartTooltip"
import { useNearest } from "./chart-hover"
import { cn } from "@/lib/utils"

export type { SparklinePoint }

/**
 * Минимальный SVG-спарклайн (V-07, план market_redesign_v3 п. 4.1/4.3). Пусто → null; одна
 * точка → точка; 2+ → линия с визиром: вертикальная линия липнет к ближайшей точке под
 * курсором/пальцем и несёт тултип со значением (визир и тултип — общий слой `chart-hover` /
 * `ChartTooltip`, V-08). То же самое доступно с клавиатуры (стрелки двигают точку, фокус сам
 * ставит визир на последнюю) — наведение не единственный путь к числу (план п. 4.3).
 */
export function Sparkline({
  points,
  width = 120,
  height = 32,
  className,
  stroke = "currentColor",
  formatValue = (point) => `${point.y}`,
  formatLabel,
  onSelect,
}: {
  points: readonly SparklinePoint[] | readonly number[]
  width?: number
  height?: number
  className?: string
  stroke?: string
  /** Значение в тултипе (крупным) и в aria-label — план п. 4.3. */
  formatValue?: (point: { x: number; y: number }, index: number) => string
  /** Подпись точки в тултипе (мельче значения), например дата. */
  formatLabel?: (point: { x: number; y: number }, index: number) => string
  /** Выбор точки — клик, либо Enter/Space когда точка под визиром с клавиатуры. */
  onSelect?: (point: { x: number; y: number }, index: number) => void
}) {
  const normalized = normalizePoints(points)
  const { coords } = sparklineLayout(normalized, width, height)

  const nearest = useNearest<SVGSVGElement>(coords, width, (index) => {
    onSelect?.(normalized[index]!, index)
  })

  if (normalized.length === 0) return null

  const lastIndex = normalized.length - 1

  if (normalized.length === 1) {
    const p = normalized[0]!
    const c = coords[0]!
    return (
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        className={cn("shrink-0 overflow-visible", className)}
        role="img"
        aria-label={formatValue(p, 0)}
      >
        <title>{formatValue(p, 0)}</title>
        <circle cx={c.cx} cy={c.cy} r={1.5} fill={stroke} />
      </svg>
    )
  }

  const d = coords
    .map((c, i) => `${i === 0 ? "M" : "L"}${c.cx.toFixed(2)} ${c.cy.toFixed(2)}`)
    .join(" ")

  const { activeIndex, containerRef, handlers } = nearest
  const active =
    activeIndex != null
      ? { index: activeIndex, coord: coords[activeIndex]!, point: normalized[activeIndex]! }
      : null

  const summary = `ряд из ${normalized.length} значений, последнее ${formatValue(normalized[lastIndex]!, lastIndex)}`

  return (
    <div className={cn("relative inline-block shrink-0", className)}>
      <svg
        ref={containerRef}
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        className="block overflow-visible"
        role="img"
        aria-label={summary}
        tabIndex={0}
        onPointerMove={handlers.onPointerMove}
        onPointerLeave={handlers.onPointerLeave}
        onClick={handlers.onClick}
        onFocus={handlers.onFocus}
        onBlur={handlers.onBlur}
        onKeyDown={handlers.onKeyDown}
      >
        <title>{summary}</title>
        <path
          d={d}
          fill="none"
          stroke={stroke}
          strokeWidth={1.5}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        {active ? (
          <>
            <line
              x1={active.coord.cx}
              x2={active.coord.cx}
              y1={0}
              y2={height}
              stroke="currentColor"
              strokeWidth={1}
              className="text-slate-300"
            />
            <circle
              cx={active.coord.cx}
              cy={active.coord.cy}
              r={2.5}
              fill={stroke}
              stroke="white"
              strokeWidth={1}
            />
          </>
        ) : null}
      </svg>
      {active ? (
        <ChartTooltip
          x={active.coord.cx}
          y={Math.max(0, active.coord.cy - 6)}
          heading={formatLabel ? formatLabel(active.point, active.index) : undefined}
          rows={[{ value: formatValue(active.point, active.index) }]}
        />
      ) : null}
    </div>
  )
}
