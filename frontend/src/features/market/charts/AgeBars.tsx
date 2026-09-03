/**
 * Полосы по возрастным корзинам (V-05, план market_redesign_v3 п. 2.2 / 4.1): на этап — одна
 * полоса вместо точечной ленты вакансий (слипается уже при ~29 точках, п. 2.2). Заливка — одна
 * hue, светлее→темнее через непрозрачность (план 4.2: «упорядоченные шкалы — одна hue, светлее→
 * темнее», «категориальные цвета» здесь запрещены). Общая подпись корзин рисуется один раз под
 * всеми строками — набор корзин фиксирован и одинаков для каждого этапа, повторять его в каждой
 * строке незачем.
 */
import { cn } from "@/lib/utils"
import {
  AGE_BUCKET_KEYS,
  AGE_BUCKET_LABELS,
  ageBarsRows,
  type AgeBarsRow,
  type AgeBarsRowLayout,
  type AgeBarsSegmentLayout,
  type AgeBucketKey,
} from "./age-bars-geometry"

export type { AgeBarsRow }

/** Непрозрачность заливки по индексу корзины — светлее для свежих, темнее для залежавшихся. */
const RAMP_OPACITY = ["opacity-25", "opacity-50", "opacity-75", "opacity-100"]

export function AgeBars({
  rows,
  height = 22,
  className,
  trackClassName = "bg-slate-100",
  fillClassName = "bg-status-warn-dot",
  showLegend = true,
  onSelectBucket,
  formatBucket,
}: {
  rows: readonly AgeBarsRow[]
  height?: number
  className?: string
  trackClassName?: string
  /** Один акцент; порядковую рампу поверх него рисуют RAMP_OPACITY. */
  fillClassName?: string
  showLegend?: boolean
  /** Клик по корзине (например, доска с фильтром по этапу и возрасту). */
  onSelectBucket?: (rowKey: string, bucketKey: AgeBucketKey) => void
  /** Заголовок при наведении/фокусе — то же значение, что и в списке-двойнике. */
  formatBucket?: (segment: AgeBarsSegmentLayout, row: AgeBarsRowLayout) => string
}) {
  const layout = ageBarsRows(rows)
  if (layout.length === 0) return null

  return (
    <div className={cn("flex min-w-0 flex-col gap-2", className)} data-testid="age-bars">
      {layout.map((row) => (
        <div key={row.key} className="min-w-0">
          <div className="mb-1 flex items-baseline gap-1 text-sm text-slate-700">
            <span className="truncate">{row.label}</span>
            <span className="text-slate-400">·</span>
            <span className="tabular-nums">{row.total}</span>
          </div>
          <div className="relative" style={{ height }}>
            <div className={cn("absolute inset-0 rounded-sm", trackClassName)} />
            {row.segments.map((seg) => (
              <div
                key={seg.key}
                style={{ left: `${seg.xPct}%`, width: `${seg.widthPct}%` }}
                className={cn(
                  "absolute inset-y-0 rounded-sm",
                  fillClassName,
                  RAMP_OPACITY[seg.rampIndex],
                  onSelectBucket && "cursor-pointer transition-opacity hover:brightness-110",
                )}
                title={formatBucket ? formatBucket(seg, row) : `${seg.label} · ${seg.count}`}
                role={onSelectBucket ? "button" : undefined}
                tabIndex={onSelectBucket ? 0 : undefined}
                onClick={onSelectBucket ? () => onSelectBucket(row.key, seg.key) : undefined}
                onKeyDown={
                  onSelectBucket
                    ? (e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault()
                          onSelectBucket(row.key, seg.key)
                        }
                      }
                    : undefined
                }
              />
            ))}
          </div>
        </div>
      ))}
      {showLegend ? (
        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
          {AGE_BUCKET_KEYS.map((key, rampIndex) => (
            <span key={key} className="flex items-center gap-1 text-xs text-slate-500">
              <span
                className={cn("size-2 shrink-0 rounded-xs", fillClassName, RAMP_OPACITY[rampIndex])}
              />
              {AGE_BUCKET_LABELS[key]}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  )
}
