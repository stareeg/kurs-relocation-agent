import type { MarketGridCell } from "@/api/market"

/** Общие форматтеры значений/дельт ячеек рынка (X-03: вынесены из старой сетки). */
export type GridUnit = MarketGridCell["unit"] | "minutes" | "hours"

export function unitSuffix(unit: GridUnit): string {
  switch (unit) {
    case "count":
      return "шт"
    case "pct":
      return "%"
    case "score":
      return "балл"
    case "days":
      return "дн"
    case "minutes":
      return "мин"
    case "hours":
      return "ч"
    case "money":
      return "₽"
    default:
      return ""
  }
}

/** Формат значения ячейки: pct — десятые, count/score — целые, money — как пришло с бэка. */
export function formatCellValue(value: MarketGridCell["value"], unit: GridUnit): string {
  if (value == null || value === "") return "—"
  if (unit === "money") return String(value)
  if (typeof value === "string") return value
  if (unit === "pct") {
    const n = Number(value)
    return Number.isFinite(n) ? (Math.round(n * 10) / 10).toFixed(1).replace(/\.0$/, "") : "—"
  }
  if (unit === "minutes" || unit === "hours" || unit === "days") {
    const n = Number(value)
    return Number.isFinite(n) ? (Number.isInteger(n) ? String(n) : n.toFixed(1)) : "—"
  }
  if (unit === "score") return String(Math.round(Number(value)))
  return String(Math.round(Number(value)))
}

/** Суточная дельта: только знак и число, без единиц (размерность = у основной метрики). */
export function formatCellDelta(delta: number, unit: GridUnit): string {
  const r =
    unit === "pct" || unit === "score" || unit === "days" || unit === "hours" || unit === "minutes"
      ? Math.round(delta * 10) / 10
      : Math.round(delta)
  const sign = r > 0 ? "+" : ""
  if (Number.isInteger(r)) return `${sign}${r}`
  return `${sign}${r.toFixed(1)}`
}

/** count / base × 100 с одним знаком после запятой (как бэкенд `_pct1`). */
export function ratioPct(
  count: MarketGridCell["value"],
  base: MarketGridCell["value"],
): number | null {
  const c = typeof count === "number" ? count : Number(count)
  const b = typeof base === "number" ? base : Number(base)
  if (!Number.isFinite(c) || !Number.isFinite(b) || b <= 0) return null
  return Math.round((c / b) * 1000) / 10
}

const FX_SYMBOL: Record<string, string> = { USD: "$", EUR: "€", GBP: "£" }
const FX_PERIOD: Record<string, string> = {
  hour: "ч",
  day: "день",
  month: "мес",
  year: "год",
}

/** Ставка без FX: $45/ч, €8к/мес. Мелкие hourly не сокращаем в «к». */
export function formatFxRate(mid: number, currency: string, period: string): string {
  const sym = FX_SYMBOL[currency] ?? `${currency} `
  const p = FX_PERIOD[period] ?? period
  const n = mid >= 1000 ? `${Math.round(mid / 1000)}к` : String(mid)
  return `${sym}${n}/${p}`
}
