/**
 * Гистограмма «Зарплаты» (редизайн 2026-08-11): настоящий bar chart на SVG — ось X
 * (зарплатные корзины, урезаны по P5–P95), ось Y (количество вакансий), тонкая линия
 * медианы, короткие незаподписанные насечки P25/P75, скобка целевой вилки под осью, точки
 * офферов. Тултип при наведении на столбик.
 *
 * Числа медианы/P25/P75 живут в текстовой строке НАД графиком (обычный текст, не SVG) —
 * так они не наезжают друг на друга и не соревнуются с осями за внимание; в SVG эти
 * маркеры остаются чисто позиционными ориентирами.
 *
 * Геометрия — в `salary-distribution-geometry.ts`, чистая и тестируемая отдельно.
 */
import { useState } from "react"
import { cn } from "@/lib/utils"
import { useContainerWidth } from "@/lib/use-container-width"
import { ChartTooltip } from "./ChartTooltip"
import {
  formatMoneyFull,
  salaryDistributionLayout,
  type SalaryDistributionInput,
} from "./salary-distribution-geometry"

const Y_AXIS_WIDTH = 32
const X_AXIS_HEIGHT = 18
const BRACKET_AREA_HEIGHT = 22
const QUARTILE_TICK_HALF = 3

export type SalaryDistributionProps = {
  input: SalaryDistributionInput
  /** Ширина в px; по умолчанию — ширина контейнера (заполняет ячейку, без пустоты справа). */
  width?: number
  height?: number
  className?: string
}

export function SalaryDistribution({
  input,
  width,
  height = 180,
  className,
}: SalaryDistributionProps) {
  const [activeBar, setActiveBar] = useState<number | null>(null)
  const { ref, width: containerWidth } = useContainerWidth<HTMLDivElement>(560)
  const effectiveWidth = width ?? containerWidth

  const chartW = effectiveWidth - Y_AXIS_WIDTH
  const chartH = height - X_AXIS_HEIGHT
  const layout = salaryDistributionLayout(input, chartW, chartH)

  if (!layout) return null

  const offerLaneCount = new Set(layout.offerMarkers.map((m) => m.lane)).size
  const bracketH = layout.targetBracket ? BRACKET_AREA_HEIGHT : 0
  const totalH =
    chartH + X_AXIS_HEIGHT + bracketH + layout.offerLaneHeight * Math.max(1, offerLaneCount)
  const svgH = totalH

  // Медиана — в шапке блока (`MarketSection` meta, `MarketPage.tsx`); P25/P75 остались только
  // как незаподписанные насечки на оси (в самом SVG) — без отдельной текстовой подписи.
  return (
    <div ref={ref} className={cn("min-w-0", className)} data-testid="salary-distribution">
      <div className="relative min-w-0">
        <svg
          width={effectiveWidth}
          height={svgH}
          viewBox={`0 0 ${effectiveWidth} ${svgH}`}
          className="block overflow-visible"
          role="img"
          aria-label="Распределение зарплат на рынке"
        >
          <g transform={`translate(${Y_AXIS_WIDTH} 0)`}>
            {/* Сетка + тики оси Y. */}
            {layout.gridLines.map((line, i) => (
              <line
                key={`grid-${i}`}
                x1={0}
                x2={chartW}
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

            {/* Столбики. */}
            {layout.bars.map((bar, i) => (
              <rect
                key={bar.key}
                x={bar.x}
                y={bar.y}
                width={bar.width}
                height={bar.height}
                rx={Math.min(2, bar.width / 2)}
                className={cn(
                  "fill-slate-300 transition-colors",
                  activeBar === i ? "fill-slate-400" : null,
                )}
                onMouseEnter={() => setActiveBar(i)}
                onMouseLeave={() => setActiveBar((v) => (v === i ? null : v))}
              />
            ))}

            {/* Медиана — тонкая линия во всю высоту + каретка сверху (без текста, число — в
                строке над графиком). */}
            {layout.medianMarker ? (
              <g className="text-series-1">
                <line
                  x1={layout.medianMarker.x}
                  x2={layout.medianMarker.x}
                  y1={0}
                  y2={chartH}
                  stroke="currentColor"
                  strokeWidth={1.5}
                  opacity={0.6}
                />
                <path
                  d={`M ${layout.medianMarker.x - 4} 0 L ${layout.medianMarker.x + 4} 0 L ${layout.medianMarker.x} 6 Z`}
                  fill="currentColor"
                />
              </g>
            ) : null}

            {/* P25/P75 — короткие незаподписанные насечки на оси. */}
            {layout.quartileTicks.map((t) => (
              <line
                key={`qtick-${t.key}`}
                x1={t.x}
                x2={t.x}
                y1={chartH - QUARTILE_TICK_HALF}
                y2={chartH + QUARTILE_TICK_HALF}
                className="text-slate-400"
                stroke="currentColor"
                strokeWidth={1.5}
              />
            ))}

            {/* Ось X. */}
            <line
              x1={0}
              x2={chartW}
              y1={chartH}
              y2={chartH}
              className="text-slate-300"
              stroke="currentColor"
              strokeWidth={1}
            />
            {layout.xTicks.map((tick, i) => (
              <text
                key={`xtick-${i}-${tick.label}`}
                x={tick.x}
                y={chartH + 12}
                textAnchor={
                  tick.anchor === "start" ? "start" : tick.anchor === "end" ? "end" : "middle"
                }
                className="fill-slate-400 text-[10px] tabular-nums"
              >
                {tick.label}
              </text>
            ))}

            {/* Скобка целевой вилки — тонкая линия с засечками, без заливки на всю высоту. */}
            {layout.targetBracket ? (
              <g
                transform={`translate(0 ${chartH + X_AXIS_HEIGHT + BRACKET_AREA_HEIGHT / 2})`}
                className="text-status-good-fg"
              >
                <line
                  x1={layout.targetBracket.x}
                  x2={layout.targetBracket.x + layout.targetBracket.width}
                  y1={0}
                  y2={0}
                  stroke="currentColor"
                  strokeWidth={1.5}
                />
                <line
                  x1={layout.targetBracket.x}
                  x2={layout.targetBracket.x}
                  y1={-3}
                  y2={3}
                  stroke="currentColor"
                  strokeWidth={1.5}
                />
                <line
                  x1={layout.targetBracket.x + layout.targetBracket.width}
                  x2={layout.targetBracket.x + layout.targetBracket.width}
                  y1={-3}
                  y2={3}
                  stroke="currentColor"
                  strokeWidth={1.5}
                />
                <text
                  x={layout.targetBracket.x + layout.targetBracket.width / 2}
                  y={-7}
                  textAnchor={
                    layout.targetBracket.labelAnchor === "start"
                      ? "start"
                      : layout.targetBracket.labelAnchor === "end"
                        ? "end"
                        : "middle"
                  }
                  className="fill-status-good-fg text-[10px]"
                >
                  {layout.targetBracket.label}
                </text>
              </g>
            ) : null}

            {/* Точки офферов под осью X (ниже скобки цели, если она есть). */}
            {layout.offerMarkers.map((m) => {
              const laneTop = chartH + X_AXIS_HEIGHT + bracketH
              const offY = laneTop + m.lane * layout.offerLaneHeight
              return (
                <g key={`offer-${m.key}`}>
                  <line
                    x1={m.x}
                    x2={m.x}
                    y1={chartH}
                    y2={offY}
                    className="text-status-strong-dot/40"
                    stroke="currentColor"
                    strokeWidth={1}
                  />
                  <circle cx={m.x} cy={chartH} r={3} className="fill-status-strong-dot" />
                  <text
                    x={m.x}
                    y={offY + 8}
                    textAnchor="middle"
                    className="fill-status-strong-fg text-[10px]"
                  >
                    {m.label}
                  </text>
                </g>
              )
            })}
          </g>
        </svg>

        {/* Тултип активного столбика. */}
        {activeBar != null ? (
          <ChartTooltip
            x={Y_AXIS_WIDTH + layout.bars[activeBar]!.x + layout.bars[activeBar]!.width / 2}
            y={layout.bars[activeBar]!.y}
            rows={[
              {
                label: formatMoneyFull(layout.bars[activeBar]!.mid),
                value: `${layout.bars[activeBar]!.count} вак.`,
              },
            ]}
          />
        ) : null}
      </div>
    </div>
  )
}
