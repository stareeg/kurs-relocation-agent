import { useCallback, useState } from "react"
import type { Job } from "@/api/jobs"
import { cardDateMs, FUNNEL_STAGES, resolveStage, RECOMMENDED_RECOS, type FunnelStage } from "./funnel"
import { jobSourceGroup, SOURCE_GROUPS, type SourceGroup } from "./source"
import { jobTrack, type JobTrack } from "./use-job-track"

// Фильтры рабочего стола вакансий (JS-1.3). Считаем на клиенте, над уже догруженным курсором
// окном (L-30: GET /api/jobs — курсорная пагинация, а не один большой `limit`) — это держит dnd,
// оптимистичный кэш ["jobs"] и дровер консистентными без рефетча. Ограничение сознательное: поиск/
// фильтр не видят ещё не догруженные страницы (доска и так упорядочена активные-этапы-первыми/
// по скору, так что нужное обычно уже в первой странице); полный server-side поиск — отдельная
// задача, если этого станет не хватать на реальном объёме владельца.
//
// Сортировку из фильтров убрали: она теперь автоматическая по виду (доска — по скору, список — по
// релевантной дате статуса, cardDateMs). Фильтр «реальность удалёнки» убран из UX как лишний шум
// (под-скор и так виден в карточке/дровере).

export type SortKey = "score_desc" | "score_asc" | "date_desc" | "date_asc"

// Фильтры-множества (UI-0): мультивыбор чипами вместо select-боксов, пустой массив = «любой».
export type JobFilters = {
  search: string // подстрока по названию/компании/ID вакансии, регистронезависимо (применяется кнопкой)
  statuses: FunnelStage[] // пусто = любой статус
  minScore: number // 0..100 (ползунок, шаг 10), 0 = любой скор
  // Период по «релевантной дате» карточки (cardDateMs): на Скрининге/Техничке/Оффере —
  // updated_at (сдвиг статуса), иначе applied_at/scored_at. Имена scored* — исторические.
  scoredFrom: string // «YYYY-MM-DD» или «»
  scoredTo: string // «YYYY-MM-DD» или «»
  sources: SourceGroup[] // пусто = любой источник (GM-6)
  // Шаг 10: показывать только рекомендованные (recommendation ∈ strong_apply/apply) — бейдж
  // каталога getmatch. Не пользовательский фильтр, чипа в тулбаре нет (deep-link из расширения).
  recommended: boolean
  // Точечный список job.id (L-01): переход из «Рынка» на конкретные вакансии (например, «5 самых
  // залежавшихся» из «Где стоит») — не пользовательский фильтр, чипа в тулбаре нет.
  ids: number[]
  // Э3.1: сегмент трека. Пусто = «Все». Чип в тулбаре только при включённом втором треке —
  // не очередь, а фильтр: иначе две рубрики на одной доске выглядят сравнимыми.
  track: JobTrack | ""
}

export const EMPTY_FILTERS: JobFilters = {
  search: "",
  statuses: [],
  minScore: 0,
  scoredFrom: "",
  scoredTo: "",
  sources: [],
  recommended: false,
  ids: [],
  track: "",
}

function toISODate(d: Date): string {
  const m = String(d.getMonth() + 1).padStart(2, "0")
  const day = String(d.getDate()).padStart(2, "0")
  return `${d.getFullYear()}-${m}-${day}`
}

/** Локальная полночь YYYY-MM-DD — без UTC-сдвига Date.parse("YYYY-MM-DD"). */
function dayStartMs(isoDay: string): number {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDay)
  if (!m) return NaN
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])).getTime()
}

/** Исключающий конец дня (локальная полночь следующего дня). */
function dayEndExclusiveMs(isoDay: string): number {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDay)
  if (!m) return NaN
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]) + 1).getTime()
}

// Дефолтный период — последние 14 дней, вычислен один раз при загрузке модуля. Было 7: слишком
// узко под реальный ритм воронки (вакансия, к которой вернулись через неделю-полторы, молча
// выпадала с доски). DEFAULT_FILTERS — только начальное состояние рабочего стола при заходе на
// страницу; EMPTY_FILTERS — нейтральная «пустая» база (тесты, filtersActive «ничего не сужает») и
// цель для «Сбросить» — кнопка обязана снимать все фильтры целиком, включая Период, а не
// подставлять другой (пусть и дефолтный) диапазон.
/** Последние `n` дней включительно (сегодня — верхняя граница). n=14 — дефолт доски. */
function lastNDays(n: number): { from: string; to: string } {
  const end = new Date()
  end.setHours(0, 0, 0, 0)
  const start = new Date(end)
  start.setDate(start.getDate() - (n - 1))
  return { from: toISODate(start), to: toISODate(end) }
}

export const DEFAULT_PERIOD_DAYS = 14

const DEFAULT_RANGE = lastNDays(DEFAULT_PERIOD_DAYS)

export const DEFAULT_FILTERS: JobFilters = {
  ...EMPTY_FILTERS,
  scoredFrom: DEFAULT_RANGE.from,
  scoredTo: DEFAULT_RANGE.to,
}

// Сужает ли набор хоть один фильтр. Управляет показом «Сбросить».
export function filtersActive(f: JobFilters): boolean {
  return (
    f.search.trim() !== "" ||
    f.statuses.length > 0 ||
    f.minScore > 0 ||
    f.scoredFrom !== "" ||
    f.scoredTo !== "" ||
    f.sources.length > 0 ||
    f.recommended ||
    f.ids.length > 0 ||
    Boolean(f.track)
  )
}

/** Выключенный второй трек не применяет сегмент — контрола нет, порядок доски как раньше. */
export function effectiveJobFilters(f: JobFilters, secondJobOn: boolean): JobFilters {
  return secondJobOn || !f.track ? f : { ...f, track: "" }
}

/** Ищем ли прямо сейчас по строке — от этого зависит, применяется ли окно по датам. */
export function searchActive(f: JobFilters): boolean {
  return f.search.trim() !== ""
}

export function filterJobs(jobs: Job[], f: JobFilters): Job[] {
  const q = f.search.trim().toLowerCase()
  // Поиск по названию/компании/ID игнорирует период: искать «куда пропала вакансия» и при этом
  // самому же прятать её окном дат — бессмысленно, а владельцу приходилось каждый раз вручную
  // снимать фильтр по датам. Остальные фильтры (этап, источник, скор) поиск не отменяет —
  // они сужают сознательно и видны чипами.
  const ignoreDates = q.length > 0
  const from = !ignoreDates && f.scoredFrom ? dayStartMs(f.scoredFrom) : NaN
  const to = !ignoreDates && f.scoredTo ? dayEndExclusiveMs(f.scoredTo) : NaN
  const ids = f.ids.length > 0 ? new Set(f.ids) : null
  return jobs.filter((j) => {
    if (ids && (j.id == null || !ids.has(j.id))) return false
    if (f.track && jobTrack(j) !== f.track) return false
    if (q) {
      const hay = `${j.title ?? ""} ${j.company ?? ""} ${j.vacancy_id ?? ""}`.toLowerCase()
      if (!hay.includes(q)) return false
    }
    if (f.statuses.length > 0 && !f.statuses.includes(resolveStage(j.status))) return false
    if (f.sources.length > 0 && !f.sources.includes(jobSourceGroup(j))) return false
    if (f.recommended && !RECOMMENDED_RECOS.includes(j.recommendation as (typeof RECOMMENDED_RECOS)[number])) {
      return false
    }
    if (f.minScore > 0 && (j.overall_score ?? -1) < f.minScore) return false
    if (!Number.isNaN(from) || !Number.isNaN(to)) {
      // Та же дата, что на карточке/в списке — иначе дефолтное окно прячет живой Скрининг/
      // Техничку/Оффер со старым scored_at, хотя updated_at свежий (help: jobs.date-range).
      const t = cardDateMs(j)
      if (!Number.isFinite(t) || t === -Infinity) return false
      if (!Number.isNaN(from) && t < from) return false
      if (!Number.isNaN(to) && t >= to) return false
    }
    return true
  })
}

/** Сработал ли жёсткий гейт (дилбрейкер). С Этапа 1 балл при гейте больше не режется
 *  множителем (plans/scoring_precision_2026_08_17.md §1.4): число отвечает «насколько подходит
 *  по существу», а «есть дилбрейкер» — отдельный флаг. Поэтому в сортировке по скору
 *  гейтованные обязаны идти отдельной группой, иначе зарезанная сильная вакансия встаёт выше
 *  честной средней. */
function isGated(j: Job): boolean {
  return Boolean(j.score?.gate_triggered)
}

function trackRank(j: Job): number {
  return jobTrack(j) === "primary" ? 0 : 1
}

function compareBySort(a: Job, b: Job, sort: SortKey): number {
  switch (sort) {
    case "score_asc":
      // Худшие первыми — гейтованные тоже.
      return Number(isGated(b)) - Number(isGated(a)) || (a.overall_score ?? -1) - (b.overall_score ?? -1)
    case "date_desc":
      return cardDateMs(b) - cardDateMs(a)
    case "date_asc":
      return cardDateMs(a) - cardDateMs(b)
    case "score_desc":
    default:
      return Number(isGated(a)) - Number(isGated(b)) || (b.overall_score ?? -1) - (a.overall_score ?? -1)
  }
}

// Сортировка по скору / релевантной дате (cardDateMs). Доска зовёт «score_desc».
// `groupByTrack` — Э3.1: при «Все» и включённом втором треке основной трек идёт первым,
// внутри — как раньше (гейтованные отдельно, дальше по баллу/дате). Выключенный второй
// трек не передаёт флаг — порядок доски не меняется.
export function sortJobs(
  jobs: Job[],
  sort: SortKey,
  opts?: { groupByTrack?: boolean },
): Job[] {
  const group = Boolean(opts?.groupByTrack)
  const arr = [...jobs]
  arr.sort((a, b) => {
    if (group) {
      const byTrack = trackRank(a) - trackRank(b)
      if (byTrack !== 0) return byTrack
    }
    return compareBySort(a, b, sort)
  })
  return arr
}

// Состояние фильтров переживает уход со страницы (переход в другой раздел и обратно) — держим
// его в модульном синглтоне (один рабочий стол на владельца), useState лишь сидит из него и
// пишет назад. Иначе фильтры сбрасывались бы на каждый возврат во вкладку.
let persisted: JobFilters = DEFAULT_FILTERS

export function useJobFilters() {
  const [filters, setFilters] = useState<JobFilters>(() => persisted)

  const update = useCallback(<K extends keyof JobFilters>(key: K, value: JobFilters[K]) => {
    setFilters((f) => {
      const next = { ...f, [key]: value }
      persisted = next
      return next
    })
  }, [])

  const reset = useCallback(() => {
    persisted = EMPTY_FILTERS
    setFilters(EMPTY_FILTERS)
  }, [])

  // L-01: применить несколько полей сразу (переход по ссылке из «Рынка») — в отличие от `update`,
  // не завязан на один ключ за вызов.
  const applyFilters = useCallback((partial: Partial<JobFilters>) => {
    setFilters((f) => {
      const next = { ...f, ...partial }
      persisted = next
      return next
    })
  }, [])

  return { filters, update, reset, applyFilters }
}

// --- L-01: фильтры доски из адреса ---
// Единственные имена query-параметров, которые понимает /jobs как ссылку из «Рынка» (и любого
// другого раздела). Значения — как в остальном приложении: `stage` — значения FunnelStage,
// `source` — SourceGroup, оба через запятую; `period` — число дней (как `?period=` на «Рынке»)
// или «all»; `ids` — job.id через запятую (точечный список, например «5 самых залежавшихся»);
// `recommended` — флаг «только рекомендованные» (Шаг 10, бейдж каталога getmatch).
export const FILTER_PARAM_KEYS = ["stage", "minScore", "source", "period", "ids", "recommended"] as const

function parseStageParam(raw: string | null): FunnelStage[] | undefined {
  if (raw == null) return undefined
  const stages = FUNNEL_STAGES as readonly string[]
  const parsed = raw
    .split(",")
    .map((s) => s.trim())
    .filter((s) => stages.includes(s)) as FunnelStage[]
  return parsed
}

function parseSourceParam(raw: string | null): SourceGroup[] | undefined {
  if (raw == null) return undefined
  const groups = SOURCE_GROUPS as readonly string[]
  const parsed = raw
    .split(",")
    .map((s) => s.trim())
    .filter((s) => groups.includes(s)) as SourceGroup[]
  return parsed
}

function parseIdsParam(raw: string | null): number[] | undefined {
  if (raw == null) return undefined
  return raw
    .split(",")
    .map((s) => Number(s.trim()))
    .filter((n) => Number.isFinite(n))
}

function parseMinScoreParam(raw: string | null): number | undefined {
  if (raw == null) return undefined
  const n = Number(raw)
  if (!Number.isFinite(n)) return undefined
  return Math.min(100, Math.max(0, n))
}

/** «all» / отсутствующий день → без границ; иначе последние N дней (см. `lastNDays`). */
function parsePeriodParam(raw: string | null): { from: string; to: string } {
  if (raw == null || raw === "all") return { from: "", to: "" }
  const n = Number(raw)
  if (!Number.isFinite(n) || n <= 0) return { from: "", to: "" }
  return lastNDays(n)
}

/**
 * Разобрать query-параметры /jobs в набор фильтров (L-01). Возвращает `null`, если в адресе нет
 * ни одного из поддерживаемых ключей — тогда персистентные фильтры трогать не нужно.
 *
 * Период — не смёрженный, а полностью заданный этим вызовом: если ссылка не передала `period`,
 * это трактуется как «без ограничения по времени», а не как дефолтные «последние 7 дней» доски.
 * Иначе ссылка вида «Скрининг, 18» без периода тихо теряла бы карточки под дефолтным окном
 * (план, риск в L-01) — здесь мы не полагаемся на то, что каждая ссылка не забудет период.
 */
export function filtersFromSearchParams(params: URLSearchParams): Partial<JobFilters> | null {
  if (!FILTER_PARAM_KEYS.some((k) => params.has(k))) return null
  const range = parsePeriodParam(params.get("period"))
  return {
    search: "",
    statuses: parseStageParam(params.get("stage")) ?? [],
    minScore: parseMinScoreParam(params.get("minScore")) ?? 0,
    sources: parseSourceParam(params.get("source")) ?? [],
    recommended: params.get("recommended") === "1",
    ids: parseIdsParam(params.get("ids")) ?? [],
    scoredFrom: range.from,
    scoredTo: range.to,
    track: "",
  }
}
