import { useCallback, useState, type KeyboardEvent, type PointerEvent } from "react"
import { cn } from "@/lib/utils"
import { useContainerWidth } from "@/lib/use-container-width"
import { ChartTooltip } from "./charts/ChartTooltip"
import {
  DEFAULT_FROM_DAYS,
  daysToPct,
  formatBoundaryDate,
  moveHandle,
  pctToDays,
  RANGE_MAX_DAYS,
  RANGE_MIN_DAYS,
  type MarketRange,
} from "./period-range"
import {
  dayTickPositions,
  rangeBackgroundPoints,
  rangeBackgroundPolyline,
} from "./range-slider-geometry"
import { useMarketChanceHistory, useMarketOverview } from "./use-market-data"
import { useMarketRange } from "./use-market-range"

const TRACK_HEIGHT = 44
type HandleKey = "from" | "to"

function pctFromClientX(clientX: number, rect: DOMRect): number {
  if (rect.width <= 0) return 0
  return Math.min(100, Math.max(0, ((clientX - rect.left) / rect.width) * 100))
}

/**
 * Шкала периода «Рынка» (правка 2026-08-03, заменяет чипы 7/30/90 из S-01): две бегающие
 * границы вместо дискретного выбора — правая по умолчанию на сегодняшнем дне, левая на 14 днях
 * назад, обе двигаются независимо (`moveHandle` останавливает двигаемую границу у соседней с
 * минимальным зазором, не толкая её). Фон полосы — «шанс офферов» по дням за весь домен шкалы,
 * чтобы было видно, на какой части истории стоит выбранный период, а не только его границы.
 * Перетаскивание копит значение локально (`preview`)
 * и коммитит в `?range=`/sessionStorage только на отпускании — иначе каждый пиксель драга бил бы
 * по бэкенду отдельным запросом.
 *
 * Домен шкалы не прибит к фиксированным 90 дням (правка 2026-08-04): `maxDays` — реальная дата
 * первой заскоренной вакансии (`MarketOverview.history_start_days`). Пока грузится — фолбэк
 * `RANGE_MAX_DAYS`; нет вакансий вовсе, либо последний скоринг старше 90 дней (цикл поиска считаем
 * начавшимся заново) — узкий домен `DEFAULT_FROM_DAYS`, не тянем древнюю/пустую историю.
 */
export function PeriodRangeSlider() {
  const overviewQ = useMarketOverview()
  const historyStartDays = overviewQ.data?.history_start_days
  const maxDays = historyStartDays ?? (overviewQ.isLoading ? RANGE_MAX_DAYS : DEFAULT_FROM_DAYS)

  const [range, setRange] = useMarketRange(maxDays)
  const [preview, setPreview] = useState<MarketRange | null>(null)
  const [dragging, setDragging] = useState<HandleKey | null>(null)
  const { ref: trackRef, width: trackWidth } = useContainerWidth<HTMLDivElement>(560)

  const active = preview ?? range
  const dayTicks = dayTickPositions(maxDays, trackWidth)

  // Фон — весь домен шкалы, не текущий выбранный диапазон: так видно, куда попадает выбранный
  // период относительно всей доступной истории.
  const historyQ = useMarketChanceHistory({ fromDays: maxDays, toDays: RANGE_MIN_DAYS })
  const bgPoints = rangeBackgroundPoints(
    (historyQ.data?.points ?? []).map((p) => ({ day: p.day, value: p.score })),
    new Date(),
    maxDays,
  )
  const bgPolyline = bgPoints.length >= 2 ? rangeBackgroundPolyline(bgPoints, TRACK_HEIGHT) : null

  const fromPct = daysToPct(active.fromDays, maxDays)
  const toPct = daysToPct(active.toDays, maxDays)
  const bandStart = Math.min(fromPct, toPct)
  const bandWidth = Math.abs(toPct - fromPct)
  const activePct = dragging === "from" ? fromPct : dragging === "to" ? toPct : null
  const activeDateLabel =
    dragging === "from"
      ? formatBoundaryDate(active.fromDays)
      : dragging === "to"
        ? formatBoundaryDate(active.toDays)
        : null

  const updateHandle = useCallback(
    (handle: HandleKey, clientX: number) => {
      const rect = trackRef.current?.getBoundingClientRect()
      if (!rect) return
      const days = pctToDays(pctFromClientX(clientX, rect), maxDays)
      setPreview((prev) => moveHandle(prev ?? range, handle, days, maxDays))
    },
    [range, maxDays, trackRef],
  )

  function beginDrag(handle: HandleKey) {
    return (e: PointerEvent<HTMLButtonElement>) => {
      e.currentTarget.setPointerCapture?.(e.pointerId)
      setDragging(handle)
      setPreview(range)
      updateHandle(handle, e.clientX)
    }
  }

  function continueDrag(handle: HandleKey) {
    return (e: PointerEvent<HTMLButtonElement>) => {
      if (dragging !== handle) return
      updateHandle(handle, e.clientX)
    }
  }

  function finishDrag(handle: HandleKey) {
    return (e: PointerEvent<HTMLButtonElement>) => {
      if (dragging !== handle) return
      e.currentTarget.releasePointerCapture?.(e.pointerId)
      setDragging(null)
      setPreview((prev) => {
        if (prev) setRange(prev)
        return null
      })
    }
  }

  function onHandleKeyDown(handle: HandleKey) {
    return (e: KeyboardEvent<HTMLButtonElement>) => {
      const step = e.shiftKey ? 7 : 1
      const delta =
        e.key === "ArrowLeft"
          ? step
          : e.key === "ArrowRight"
            ? -step
            : e.key === "Home"
              ? maxDays
              : e.key === "End"
                ? -maxDays
                : null
      if (delta == null) return
      e.preventDefault()
      const current = handle === "from" ? active.fromDays : active.toDays
      setRange(moveHandle(active, handle, current + delta, maxDays))
    }
  }

  return (
    <div className="rounded-xl border bg-white px-4 py-3 shadow-sm" data-testid="period-range">
      {/* Подписи границ — по краям шкалы (не "Период" + дата по центру, план 2026-08-11 п.2):
          левая — начало периода, правая — конец, ровно над своим бегунком. */}
      <div className="mb-1 flex items-center justify-between gap-3 text-sm font-semibold tabular-nums text-slate-600">
        <span>{formatBoundaryDate(active.fromDays)}</span>
        <span>{formatBoundaryDate(active.toDays)}</span>
      </div>
      <div
        ref={trackRef}
        className="relative touch-none select-none"
        style={{ height: TRACK_HEIGHT }}
        data-testid="period-range-track"
      >
        {bgPolyline ? (
          // Фон декоративный (шкала уже сама даёт числа через бегунки) — растянут в 100×TRACK_HEIGHT
          // без сохранения пропорций нарочно, не тот случай, что ловит Q-01 (там — искажение
          // содержательного графика, здесь — фон-подложка).
          <svg
            className="pointer-events-none absolute inset-0 h-full w-full text-sky-400/70"
            viewBox={`0 0 100 ${TRACK_HEIGHT}`}
            preserveAspectRatio="none"
            aria-hidden
          >
            <polyline
              points={bgPolyline}
              fill="none"
              stroke="currentColor"
              strokeWidth={1.5}
              vectorEffect="non-scaling-stroke"
            />
          </svg>
        ) : (
          <div
            className="pointer-events-none absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-slate-200"
            aria-hidden
          />
        )}
        <div
          className="pointer-events-none absolute inset-y-1 rounded-sm bg-sky-500/15"
          style={{ left: `${bandStart}%`, width: `${bandWidth}%` }}
          aria-hidden
          data-testid="period-range-band"
        />
        {/* Засечки «начало дня» — видно, куда по шагам можно сдвинуть границы (план п.2). */}
        {dayTicks.map((pct) => (
          <div
            key={pct}
            className="pointer-events-none absolute top-1/2 h-2 w-px -translate-y-1/2 bg-slate-300"
            style={{ left: `${pct}%` }}
            aria-hidden
          />
        ))}
        <RangeHandle
          pct={fromPct}
          label="Начало периода"
          value={active.fromDays}
          maxDays={maxDays}
          dragging={dragging === "from"}
          onPointerDown={beginDrag("from")}
          onPointerMove={continueDrag("from")}
          onPointerUp={finishDrag("from")}
          onKeyDown={onHandleKeyDown("from")}
        />
        <RangeHandle
          pct={toPct}
          label="Конец периода"
          value={active.toDays}
          maxDays={maxDays}
          dragging={dragging === "to"}
          onPointerDown={beginDrag("to")}
          onPointerMove={continueDrag("to")}
          onPointerUp={finishDrag("to")}
          onKeyDown={onHandleKeyDown("to")}
        />
        {activePct != null && activeDateLabel ? (
          <ChartTooltip x={`${activePct}%`} y={-6} rows={[{ value: activeDateLabel }]} />
        ) : null}
      </div>
    </div>
  )
}

function RangeHandle({
  pct,
  label,
  value,
  maxDays,
  dragging,
  onPointerDown,
  onPointerMove,
  onPointerUp,
  onKeyDown,
}: {
  pct: number
  label: string
  value: number
  maxDays: number
  dragging: boolean
  onPointerDown: (e: PointerEvent<HTMLButtonElement>) => void
  onPointerMove: (e: PointerEvent<HTMLButtonElement>) => void
  onPointerUp: (e: PointerEvent<HTMLButtonElement>) => void
  onKeyDown: (e: KeyboardEvent<HTMLButtonElement>) => void
}) {
  return (
    <button
      type="button"
      role="slider"
      aria-label={label}
      aria-valuemin={RANGE_MIN_DAYS}
      aria-valuemax={maxDays}
      aria-valuenow={value}
      aria-valuetext={formatBoundaryDate(value)}
      className={cn(
        // UX26: ручки шкалы — вертикальные «палочки» (не совсем тонкие), а не кружки:
        // так визуально яснее, что двигается сама граница периода, и масштаб шкалы читается лучше.
        // Правка 2026-08-11 (план п.2): чуть выше самой шкалы (TRACK_HEIGHT=44) и шире — не
        // нужно целиться; диагональная штриховка на самой ручке — визуальный «грип» (видно,
        // что это тянут, а не просто метка).
        "absolute top-1/2 z-10 -translate-x-1/2 -translate-y-1/2 cursor-grab touch-none",
        "h-[52px] w-3 rounded-[4px] border-2 border-sky-600 bg-white shadow-sm transition-transform active:cursor-grabbing",
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-500",
        dragging && "scale-105",
      )}
      style={{
        left: `${pct}%`,
        backgroundImage:
          "repeating-linear-gradient(135deg, rgb(2 132 199 / 0.45) 0px, rgb(2 132 199 / 0.45) 1px, transparent 1px, transparent 4px)",
      }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onKeyDown={onKeyDown}
    />
  )
}
