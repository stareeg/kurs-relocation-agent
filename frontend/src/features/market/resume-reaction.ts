/**
 * Данные под S-10 «Как рынок реагирует на резюме» (план market_redesign_v3, п. 3.3): три
 * отдельных ряда (показы / просмотры / приглашения) вместо трёхрядного графика на общей
 * оси — старая форма прижимала два ряда к нулю (план §0). Чистая раскладка, без БД и без
 * React — тестируется отдельно от `MarketStance.tsx`.
 */
import type { SparklinePoint } from "./charts/sparkline-geometry"
import type { LineMetricInput } from "./charts/line-chart-geometry"

/** Тот же sentinel, что и `core.domains.profile.resume_stats.GETMATCH_PROFILE_RESUME_ID`. */
export const GETMATCH_PROFILE_RESUME_ID = "getmatch:profile"

export type ResumeReactionSource = "hh" | "getmatch"

export type ResumeReactionPointInput = {
  captured_at: string
  resume_id?: string
  impressions?: number
  views?: number
  invitations?: number
}

function isGetmatchId(resumeId: string | undefined): boolean {
  return (resumeId ?? "").trim() === GETMATCH_PROFILE_RESUME_ID
}

/** Разделяет снимки по площадке — hh и getmatch не смешиваются в одном ряду. */
export function filterResumeReactionBySource(
  points: readonly ResumeReactionPointInput[] | null | undefined,
  source: ResumeReactionSource,
): ResumeReactionPointInput[] {
  if (!points?.length) return []
  return points.filter((p) =>
    source === "getmatch" ? isGetmatchId(p.resume_id) : !isGetmatchId(p.resume_id),
  )
}

/** hh — площадка по умолчанию, если там есть снимки; иначе getmatch. */
export function pickResumeReactionSource(
  points: readonly ResumeReactionPointInput[] | null | undefined,
): ResumeReactionSource {
  if (filterResumeReactionBySource(points, "hh").length > 0) return "hh"
  if (filterResumeReactionBySource(points, "getmatch").length > 0) return "getmatch"
  return "hh"
}

// Правка 2026-08-11 (план п.6): «Приглашения» убраны из графика — блок теперь про статистику
// площадок (показы/просмотры), не воронку откликов; приглашения уже видны в «Воронке»/«Шансе
// оффера». `ResumeReactionPointInput.invitations` в типе остаётся (форма бэкового снимка), просто
// не участвует в построении рядов.
export const RESUME_REACTION_METRIC_KEYS = ["impressions", "views"] as const
export type ResumeReactionMetricKey = (typeof RESUME_REACTION_METRIC_KEYS)[number]

export const RESUME_REACTION_METRIC_LABELS: Readonly<Record<ResumeReactionMetricKey, string>> = {
  impressions: "показы",
  views: "просмотры",
}

export type ResumeReactionMetric = {
  key: ResumeReactionMetricKey
  label: string
  points: SparklinePoint[]
  /** Дни снимков `YYYY-MM-DD`, тот же порядок и длина, что и `points` — подпись в тултипе. */
  days: string[]
  /** ms-таймстампы точек (тот же порядок и длина) — для временной оси X в `LineChart`. */
  timestamps?: number[]
  latest: number | null
  delta: number | null
}

function num(v: number | undefined): number {
  return typeof v === "number" && Number.isFinite(v) ? Math.max(0, v) : 0
}

function dayKey(iso: string): string {
  return new Date(Date.parse(iso)).toISOString().slice(0, 10)
}

/**
 * Три ряда, каждый на своей шкале (её сам поставит `Sparkline`, независимо для каждого
 * инстанса) — это и есть починка «два ряда прижаты к нулю» (план §0).
 */
export function buildResumeReactionMetrics(
  points: readonly ResumeReactionPointInput[] | null | undefined,
): ResumeReactionMetric[] {
  const sorted = [...(points ?? [])]
    .filter((p) => Number.isFinite(Date.parse(p.captured_at)))
    .sort((a, b) => Date.parse(a.captured_at) - Date.parse(b.captured_at))
  const days = sorted.map((p) => dayKey(p.captured_at))

  return RESUME_REACTION_METRIC_KEYS.map((key) => {
    const series = sorted.map((p) => num(p[key]))
    const points: SparklinePoint[] = series.map((y, i) => ({ x: i, y }))
    const timestamps = sorted.map((p) => Date.parse(p.captured_at))
    const latest = series.length > 0 ? series[series.length - 1]! : null
    const delta = series.length >= 2 ? series[series.length - 1]! - series[0]! : null
    return {
      key,
      label: RESUME_REACTION_METRIC_LABELS[key],
      points,
      days,
      timestamps,
      latest,
      delta,
    }
  })
}

export function formatSnapshotDate(iso: string | null | undefined): string | null {
  if (!iso) return null
  const ms = Date.parse(iso)
  if (!Number.isFinite(ms)) return null
  return new Intl.DateTimeFormat("ru-RU", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(ms))
}

/**
 * Вход для `LineChart` из снимков `ResumeStatsSeries`: три метрики (показы / просмотры /
 * приглашения), каждая со своим рядом точек и доменом Y — общая ось X (даты снимков).
 * Источник (hh / getmatch) уже отфильтрован вызывающим через `filterResumeReactionBySource`.
 */
export function lineChartInputFromPoints(
  points: readonly ResumeReactionPointInput[] | null | undefined,
): { metrics: LineMetricInput[]; latestAt: string | null; source: ResumeReactionSource } {
  const source = pickResumeReactionSource(points)
  const filtered = filterResumeReactionBySource(points, source)
  const metrics = buildResumeReactionMetrics(filtered)
  const latestAt = filtered.length > 0 ? filtered[filtered.length - 1]!.captured_at : null
  return {
    metrics: metrics.map((m) => ({
      key: m.key,
      label: RESUME_REACTION_METRIC_LABELS[m.key],
      points: m.points.map((p) => ({ x: p.x ?? 0, y: p.y })),
      days: m.days,
      timestamps: m.timestamps,
      latest: m.latest,
      delta: m.delta,
    })),
    latestAt,
    source,
  }
}
