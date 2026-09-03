/**
 * Шкала периода «Рынка» (правка 2026-08-03): вместо дискретных чипов 7/30/90 — диапазон,
 * заданный двумя границами в «днях назад от сегодня». Правая по умолчанию на сегодняшнем дне
 * (`DEFAULT_TO_DAYS`), левая — на 14 днях назад (`DEFAULT_FROM_DAYS`); обе двигаются независимо
 * (см. `PeriodRangeSlider`). Чистая логика без DOM/React — тестируется отдельно.
 *
 * Домен шкалы (сколько дней назад можно утянуть левый край) — динамический (правка 2026-08-04):
 * реальная дата первой заскоренной вакансии (`MarketOverview.history_start_days`), а не жёстко
 * прибитые 90 дней — искусственный потолок не имеет смысла: у нового пользователя история короче,
 * у давнего — может быть длиннее. `RANGE_MAX_DAYS` остаётся дефолтом/фолбэком для всех функций
 * ниже, пока бэкенд не ответил (загрузка / нет ещё ни одной вакансии).
 */
import { clampPct } from "./charts/pct"

/** Домен шкалы: 0 — сегодня. */
export const RANGE_MIN_DAYS = 0
/** Фолбэк-домен, пока не известна реальная дата первой заскоренной вакансии. */
export const RANGE_MAX_DAYS = 90

export const DEFAULT_FROM_DAYS = 14
export const DEFAULT_TO_DAYS = 0

/** Границам не даём сомкнуться — период короче суток не имеет смысла. */
export const MIN_SPAN_DAYS = 1

export type MarketRange = { fromDays: number; toDays: number }

export const DEFAULT_MARKET_RANGE: MarketRange = {
  fromDays: DEFAULT_FROM_DAYS,
  toDays: DEFAULT_TO_DAYS,
}

function clampDays(value: number, maxDays: number = RANGE_MAX_DAYS): number {
  if (!Number.isFinite(value)) return RANGE_MIN_DAYS
  return Math.min(maxDays, Math.max(RANGE_MIN_DAYS, Math.round(value)))
}

/** Приводит произвольную пару границ к валидному диапазону: клип к домену + минимальный зазор. */
export function clampRange(range: MarketRange, maxDays: number = RANGE_MAX_DAYS): MarketRange {
  let fromDays = clampDays(range.fromDays, maxDays)
  let toDays = clampDays(range.toDays, maxDays)
  if (fromDays - toDays < MIN_SPAN_DAYS) {
    fromDays = Math.min(maxDays, toDays + MIN_SPAN_DAYS)
    if (fromDays - toDays < MIN_SPAN_DAYS)
      toDays = Math.max(RANGE_MIN_DAYS, fromDays - MIN_SPAN_DAYS)
  }
  return { fromDays, toDays }
}

/**
 * Двигает ОДНУ границу (перетаскивание/клавиатура), не трогая другую — в отличие от
 * `clampRange` (нормализация произвольной пары, например при разборе `?range=`), здесь при
 * подходе к соседней границе двигаемая останавливается у неё с зазором `MIN_SPAN_DAYS`, а не
 * толкает соседнюю дальше. Иначе перетаскивание одного бегунка визуально дёргало бы второй.
 */
export function moveHandle(
  range: MarketRange,
  handle: "from" | "to",
  days: number,
  maxDays: number = RANGE_MAX_DAYS,
): MarketRange {
  const target = clampDays(days, maxDays)
  if (handle === "from") {
    const fromDays = Math.min(maxDays, Math.max(target, range.toDays + MIN_SPAN_DAYS))
    return { fromDays, toDays: range.toDays }
  }
  const toDays = Math.max(RANGE_MIN_DAYS, Math.min(target, range.fromDays - MIN_SPAN_DAYS))
  return { fromDays: range.fromDays, toDays }
}

/** «14-0» — компактная сериализация для `?range=` / sessionStorage. */
export function formatRangeParam(range: MarketRange): string {
  return `${range.fromDays}-${range.toDays}`
}

/** Разбирает `?range=`; незнакомый формат или невалидные числа → `null` (вызывающий берёт дефолт). */
export function parseRangeParam(raw: string | null | undefined): MarketRange | null {
  if (!raw) return null
  const m = /^(\d+)-(\d+)$/.exec(raw.trim())
  if (!m) return null
  const fromDays = Number(m[1])
  const toDays = Number(m[2])
  if (!Number.isFinite(fromDays) || !Number.isFinite(toDays)) return null
  return clampRange({ fromDays, toDays })
}

/** Ширина окна в днях — то, что раньше называлось «периодом» (7/30/90). */
export function rangeSpanDays(range: MarketRange): number {
  return Math.max(MIN_SPAN_DAYS, range.fromDays - range.toDays)
}

/** Позиция границы на шкале, 0..100 слева направо (0 = самая старая дата, 100 = сегодня). */
export function daysToPct(days: number, maxDays: number = RANGE_MAX_DAYS): number {
  return clampPct(100 - (clampDays(days, maxDays) / maxDays) * 100)
}

/** Обратное преобразование: позиция на шкале (0..100) → «дней назад», округлено до целых суток. */
export function pctToDays(pct: number, maxDays: number = RANGE_MAX_DAYS): number {
  const clamped = clampPct(pct)
  return clampDays(((100 - clamped) / 100) * maxDays, maxDays)
}

function pad2(n: number): string {
  return String(n).padStart(2, "0")
}

/** Дата границы в формате «день.месяц» — подпись при перетаскивании (план п. 2). */
export function formatBoundaryDate(daysAgo: number, now: Date = new Date()): string {
  const d = new Date(now)
  d.setDate(d.getDate() - daysAgo)
  return `${pad2(d.getDate())}.${pad2(d.getMonth() + 1)}`
}
