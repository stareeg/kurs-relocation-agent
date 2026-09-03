/**
 * Вертикальная гистограмма по категориям (редизайн «Рынка» 2026-08-09): заменяет все бывшие
 * «полосы из кусков» (SegmentedBar) в воронке / что режет поток / форматах / вкладах шанса
 * оффера. Категории по X, значения по Y, оси с тиками, тултип при наведении на столбец.
 *
 * Подписи значений — над каждым столбцом, подписи категорий — под осью X (горизонтально или
 * повёрнутые на 45° при тесноте). Никаких сегментов внутри столбца, никаких подписей под
 * полосой, которые наезжали друг на друга.
 *
 * Геометрия — в `category-bars-geometry.ts`, чистая и тестируемая отдельно.
 */
import { useState } from "react"
import { cn } from "@/lib/utils"
import { useContainerWidth } from "@/lib/use-container-width"
import { ChartTooltip } from "./ChartTooltip"
import {
  CATEGORY_BARS_VALUE_LABEL_HEIGHT,
  CATEGORY_BARS_X_AXIS_HEIGHT,
  CATEGORY_BARS_Y_AXIS_WIDTH,
  categoryBarsLayout,
  type CategoryBar,
  type CategoryBarsInput,
} from "./category-bars-geometry"

export type { CategoryBar, CategoryBarsInput }

/** Класс заливки столбца: статический (один для всех) или по ключу столбца. */
export type BarClassName = string | ((bar: CategoryBar) => string)

function resolveBarClass(fn: BarClassName, bar: CategoryBar): string {
  return typeof fn === "function" ? fn(bar) : fn
}

export function CategoryBars({
  input,
  width,
  height = 180,
  className,
  barClassName = "fill-slate-400",
  hoveredBarClassName = "fill-slate-600",
  formatTooltip,
}: {
  input: CategoryBarsInput
  /** Ширина в px; по умолчанию — ширина контейнера (заполняет ячейку). */
  width?: number
  height?: number
  className?: string
  /** Класс заливки столбца (Tailwind fill-*) — строка или функция от столбца. */
  barClassName?: BarClassName
  /** Класс заливки наведённого столбца — строка или функция от столбца. */
  hoveredBarClassName?: BarClassName
  /** Свои строки тултипа; по умолчанию — «категория · значение [unit]». */
  formatTooltip?: (bar: CategoryBar) => { label?: string; value: string }[]
}) {
  const [hover, setHover] = useState<number | null>(null)
  const { ref, width: containerWidth } = useContainerWidth<HTMLDivElement>(560)
  const effectiveWidth = width ?? containerWidth

  const layout = categoryBarsLayout(input, effectiveWidth, height)
  if (!layout) return null

  const xLabelLineH = layout.xLabelMode === "rotated" ? 28 : 14
  const totalH =
    layout.chartH + CATEGORY_BARS_VALUE_LABEL_HEIGHT + CATEGORY_BARS_X_AXIS_HEIGHT + xLabelLineH

  return (
    <div ref={ref} className={cn("relative min-w-0", className)} data-testid="category-bars">
      <svg
        width={effectiveWidth}
        height={totalH}
        viewBox={`0 0 ${effectiveWidth} ${totalH}`}
        className="block overflow-visible"
        role="img"
        aria-label="Гистограмма по категориям"
      >
        {/* Chart area сдвинута вправо под ось Y, вниз под подпись значения над первым рядом. */}
        <g
          transform={`translate(${CATEGORY_BARS_Y_AXIS_WIDTH} ${CATEGORY_BARS_VALUE_LABEL_HEIGHT})`}
        >
          {/* Сетка + тики оси Y. */}
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

          {/* Столбцы + подписи значений над ними. */}
          {layout.rows.map((bar, i) => (
            <g key={bar.key}>
              <rect
                x={bar.x}
                y={bar.y}
                width={bar.width}
                height={bar.height}
                className={cn(
                  "transition-colors",
                  hover === i
                    ? resolveBarClass(hoveredBarClassName, bar)
                    : resolveBarClass(barClassName, bar),
                )}
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover((v) => (v === i ? null : v))}
              />
              {/* Подпись внутри столбца у верхнего края (напр. вклад фактора «21 балл») —
                  вместо обычной подписи значения над столбцом. */}
              {bar.inBarLabel ? (
                <text
                  x={bar.x + bar.width / 2}
                  y={Math.min(bar.y + 13, bar.y + bar.height - 3)}
                  textAnchor="middle"
                  className="fill-white text-[10px] font-semibold tabular-nums"
                >
                  {bar.inBarLabel}
                </text>
              ) : bar.value > 0 ? (
                <text
                  x={bar.x + bar.width / 2}
                  y={bar.y - 4}
                  textAnchor="middle"
                  className="fill-slate-600 text-[10px] tabular-nums"
                >
                  {bar.valueLabel}
                </text>
              ) : null}
              {/* Подпись внутри столбца у нижнего края (напр. вес фактора «25%»). Только если
                  столбец достаточно высок, чтобы вместить обе подписи без наезда (правка
                  2026-08-14: вес перенесён из верха в низ, в верху — вклад в итог). */}
              {bar.bottomInBarLabel && bar.height > 28 ? (
                <text
                  x={bar.x + bar.width / 2}
                  y={bar.y + bar.height - 5}
                  textAnchor="middle"
                  className="fill-white/85 text-[9px] tabular-nums"
                >
                  {bar.bottomInBarLabel}
                </text>
              ) : null}
            </g>
          ))}

          {/* Ось X. */}
          <line
            x1={0}
            x2={layout.chartW}
            y1={layout.chartH}
            y2={layout.chartH}
            className="text-slate-300"
            stroke="currentColor"
            strokeWidth={1}
          />

          {/* Подписи категорий под осью X. */}
          {layout.rows.map((bar) => {
            const labelY = layout.chartH + 12
            if (layout.xLabelMode === "rotated") {
              return (
                <text
                  key={`xlabel-${bar.key}`}
                  x={bar.x + bar.width / 2}
                  y={labelY}
                  textAnchor="end"
                  className="fill-slate-500 text-[10px]"
                  transform={`rotate(-45 ${bar.x + bar.width / 2} ${labelY})`}
                >
                  {bar.xLabel}
                </text>
              )
            }
            return (
              <text
                key={`xlabel-${bar.key}`}
                x={bar.x + bar.width / 2}
                y={labelY}
                textAnchor={bar.xLabelAnchor}
                className="fill-slate-500 text-[10px]"
              >
                {bar.xLabel}
              </text>
            )
          })}
        </g>
      </svg>

      {/* Тултип наведённого столбца. */}
      {hover != null && layout.rows[hover] ? (
        <ChartTooltip
          x={CATEGORY_BARS_Y_AXIS_WIDTH + layout.rows[hover]!.x + layout.rows[hover]!.width / 2}
          y={CATEGORY_BARS_VALUE_LABEL_HEIGHT + layout.rows[hover]!.y}
          rows={
            formatTooltip
              ? formatTooltip(layout.rows[hover]!)
              : [{ label: layout.rows[hover]!.label, value: layout.rows[hover]!.tooltipValueLabel }]
          }
        />
      ) : null}
    </div>
  )
}
