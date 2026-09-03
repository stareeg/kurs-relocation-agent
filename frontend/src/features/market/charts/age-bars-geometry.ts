/**
 * Pure layout for AgeBars: на каждый этап — одна полоса, разбитая на возрастные корзины.
 * Порядок корзин фиксирован шкалой (свежее → залежалее), а не порядком входа — иначе
 * «до 7 дней» и «больше 3 недель» могли бы поменяться местами от порядка данных. Как и в
 * SegmentedBar, каждая строка нормирована на свою сумму: строка без вакансий — нечего
 * показывать, выпадает.
 */
import { clampPct } from "./pct"

export const AGE_BUCKET_KEYS = ["fresh", "week2", "week3", "stale"] as const
export type AgeBucketKey = (typeof AGE_BUCKET_KEYS)[number]

export const AGE_BUCKET_LABELS: Record<AgeBucketKey, string> = {
  fresh: "до 7 дней",
  week2: "1–2 недели",
  week3: "2–3 недели",
  stale: "больше 3 недель",
}

export type AgeBarsBucket = {
  key: AgeBucketKey
  count: number
}

export type AgeBarsRow = {
  key: string
  label: string
  buckets: readonly AgeBarsBucket[]
}

export type AgeBarsSegmentLayout = {
  key: AgeBucketKey
  label: string
  count: number
  /** Индекс в AGE_BUCKET_KEYS — управляет непрозрачностью рампы (0 = светлее, 3 = темнее). */
  rampIndex: number
  xPct: number
  widthPct: number
}

export type AgeBarsRowLayout = {
  key: string
  label: string
  total: number
  segments: AgeBarsSegmentLayout[]
}

/**
 * Строки по возрастным корзинам: сумма положительных корзин строки — её база. Корзины с
 * count <= 0 не занимают места. Пропущенные в данных ключи корзин считаются нулём.
 */
export function ageBarsRows(rows: readonly AgeBarsRow[]): AgeBarsRowLayout[] {
  const result: AgeBarsRowLayout[] = []
  for (const row of rows) {
    const byKey = new Map(row.buckets.map((b) => [b.key, b.count]))
    const total = AGE_BUCKET_KEYS.reduce((sum, k) => sum + Math.max(0, byKey.get(k) ?? 0), 0)
    if (total <= 0) continue

    const segments: AgeBarsSegmentLayout[] = []
    let cursor = 0
    AGE_BUCKET_KEYS.forEach((key, rampIndex) => {
      const count = byKey.get(key) ?? 0
      if (!(count > 0)) return
      const xPct = clampPct(cursor)
      const widthPct = clampPct(Math.min((count / total) * 100, 100 - xPct))
      if (widthPct <= 0) return
      segments.push({ key, label: AGE_BUCKET_LABELS[key], count, rampIndex, xPct, widthPct })
      cursor += widthPct
    })
    result.push({ key: row.key, label: row.label, total, segments })
  }
  return result
}
