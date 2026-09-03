import type { Job } from "@/api/jobs"
import type { ScoringWeights } from "@/api/settings"
import type { StatusTone } from "@/components/ui/status-chip"
import { getHelpText } from "@/lib/help-texts"
import {
  type CriterionTone,
  type RecommendationTone,
  RECOMMENDATION_LABEL,
  RECOMMENDATION_TONE,
  scoreLevel,
  type ScoreLevel,
  competitionLevel,
  COMPETITION_LEVEL_SUFFIX,
  type CompetitionLevel,
} from "../../../../shared/criteria"
import {
  scoreBreakdownRows as sharedScoreBreakdownRows,
  scoreCalibrationDelta as sharedScoreCalibrationDelta,
  type ScoreBreakdownRow as SharedScoreBreakdownRow,
} from "../../../../shared/score-breakdown"

export type { CompetitionLevel, ScoreBreakdownKey } from "../../../../shared/criteria"
export {
  competitionLevel,
  SCORE_BREAKDOWN_KEYS,
  SCORE_BREAKDOWN_LABEL,
} from "../../../../shared/criteria"

// Сведение нейтральной классификации good/mid/bad/neutral (shared/criteria) к StatusTone
// дизайн-системы веба — единственное место этого перевода, дальше по файлу везде StatusTone.
const CRITERION_TO_STATUS_TONE: Record<CriterionTone, StatusTone> = {
  good: "good",
  mid: "warn",
  bad: "bad",
  neutral: "info",
}

// Стадии воронки = значения jobs.status (зеркалят core/kernel/schemas/funnel.py FunnelStatus). Порядок —
// путь кандидата; «Архив» сворачиваем в «Отказ» (терминальная колонка).
export const FUNNEL_STAGES = [
  "Просмотр",
  "Отклик",
  "Скрининг",
  "Техничка",
  "Финал",
  "Оффер",
  "Отказ",
] as const
export type FunnelStage = (typeof FUNNEL_STAGES)[number]

// Активные этапы воронки — «в работе» (зеркало core/kernel/schemas/funnel.py ENGAGED_FUNNEL_STATUSES).
export const ENGAGED_FUNNEL_STAGES = ["Отклик", "Скрининг", "Техничка", "Финал", "Оффер"] as const
export type EngagedFunnelStage = (typeof ENGAGED_FUNNEL_STAGES)[number]

const ENGAGED_SET: ReadonlySet<string> = new Set(ENGAGED_FUNNEL_STAGES)

// «Пропущено» — НЕ статус воронки, а ортогональное решение «не подавать» (таблица
// skipped_vacancies, флаг job.skipped). Отдельная терминальная колонка доски: сознательно
// пропущенные уходят из основного потока — иначе при 1000+ вакансий колонки превращаются в кашу.
export const SKIPPED_COLUMN = "Пропущено" as const
export type BoardColumn = FunnelStage | typeof SKIPPED_COLUMN
// Колонки kanban = воронка + терминальная «Пропущено» в конце.
export const BOARD_COLUMNS: readonly BoardColumn[] = [...FUNNEL_STAGES, SKIPPED_COLUMN]

// Легаси-варианты статусов из БД сводим к канону: «Архив» → «Отказ», «Просмотрено» → «Просмотр».
const ALIAS: Record<string, FunnelStage> = { Архив: "Отказ", Просмотрено: "Просмотр" }

// Нормализовать jobs.status к колонке Kanban: пусто/неизвестно → «Просмотр», «Архив» → «Отказ».
export function resolveStage(status?: string | null): FunnelStage {
  const s = (status ?? "").trim()
  if ((FUNNEL_STAGES as readonly string[]).includes(s)) return s as FunnelStage
  return ALIAS[s] ?? "Просмотр"
}

// Следующая стадия воронки по порядку FUNNEL_STAGES — для кнопки «Пройдено» в рельсе вакансий
// (Технички: Техничка→Финал, Финал→Оффер). «Отказ» — терминальная, дальше некуда.
export function nextFunnelStage(stage: FunnelStage): FunnelStage | null {
  const i = FUNNEL_STAGES.indexOf(stage)
  if (i === -1 || i >= FUNNEL_STAGES.length - 2) return null
  return FUNNEL_STAGES[i + 1]
}

// X-07: продвинутая стадия — вместо блуждания по разделам кнопка ведёт прямо к тому, чем сейчас
// занята вакансия (Скрининг/Технички(Финал делит раздел с Техничкой)/Оффер). До Скрининга и после
// Отказа перехода нет — там нечего готовить, только переписка. Общий источник для дровера (шапка)
// и карточки/строки списка (кнопка рядом с «Чат»).
export const SECTION_JUMP: Partial<Record<FunnelStage, { label: string; path: string }>> = {
  Скрининг: { label: "Скрининг →", path: "/screening" },
  Техничка: { label: "Технички →", path: "/tech" },
  Финал: { label: "Технички →", path: "/tech" },
  Оффер: { label: "Оффер →", path: "/offers" },
}

// Кнопка перехода в раздел не имеет смысла для терминальных карточек: «Отказ» уже отсекается тем,
// что у него нет записи в SECTION_JUMP; «Пропущено» — ортогональный флаг поверх любого статуса
// воронки (см. bucketByStage), поэтому его нужно гасить явно, иначе пропущенная вакансия на этапе
// «Техничка» продолжает показывать «Технички →» и в дровере, и на карточке канбана.
export function sectionJumpFor(
  job: Pick<Job, "status" | "skipped">,
): { label: string; path: string } | undefined {
  if (job.skipped) return undefined
  return SECTION_JUMP[resolveStage(job.status)]
}

// corner_case_1: Отказ/Пропущено уводят диалог в архив Чатов автоматически (см. ChatPage
// isAutoArchived) — «Продолжить чат» на карточке/в дровере обещало живой процесс, которого уже
// нет. Единственное место этого перевода — переиспользуется карточкой канбана, списком и дровером.
export function chatButtonLabel(job: Pick<Job, "status" | "skipped" | "has_hr_dialog">): string {
  if (!job.has_hr_dialog) return "Начать чат"
  if (job.skipped || resolveStage(job.status) === "Отказ") return "Архивный чат"
  return "Продолжить чат"
}

/** Активный процесс: engaged-статус или HR-диалог без формального отклика (≈ «Отклик»). */
export function isActiveJob(job: Job): boolean {
  if (job.skipped) return false
  const stage = resolveStage(job.status)
  if (ENGAGED_SET.has(stage)) return true
  if (stage !== "Просмотр") return false
  // has_hr_dialog — клиентское расширение типа Job (H3), определено в @/api/jobs.
  return Boolean(job.has_hr_dialog)
}

export function countActiveJobs(jobs: Job[]): number {
  return jobs.filter(isActiveJob).length
}

export type Column = { stage: BoardColumn; jobs: Job[] }

// Разложить вакансии по колонкам (порядок BOARD_COLUMNS, внутри — как пришли, score desc).
// Пропущенные (job.skipped) уходят в колонку «Пропущено» НЕЗАВИСИМО от статуса воронки; остальные —
// по resolveStage(status). Так сознательно отсеянное не засоряет активные этапы.
export function bucketByStage(jobs: Job[]): Column[] {
  const map = new Map<BoardColumn, Job[]>(BOARD_COLUMNS.map((s) => [s, []]))
  for (const j of jobs) {
    const col: BoardColumn = j.skipped ? SKIPPED_COLUMN : resolveStage(j.status)
    map.get(col)?.push(j)
  }
  return BOARD_COLUMNS.map((stage) => ({ stage, jobs: map.get(stage) ?? [] }))
}

// Цвет балла фита (U-02): дискретная шкала good/mid/low/none из shared/criteria → tailwind.
const SCORE_LEVEL_TONE: Record<ScoreLevel, string> = {
  good: "text-emerald-600",
  mid: "text-amber-600",
  low: "text-slate-500",
  none: "text-slate-400",
}

export function scoreTone(score?: number | null): string {
  return SCORE_LEVEL_TONE[scoreLevel(score)]
}

/** Крутилка у зарплаты — только пока на экране ещё «оценка…».
 *  `estimate_pending` часто залипает true уже после того, как вилка есть
 *  (salary_text / estimated_range) — спиннер тогда врёт. */
export function isSalaryStillPending(
  estimatePending: boolean | undefined,
  salaryText: string,
): boolean {
  return Boolean(estimatePending) && salaryText === "оценка…"
}

// Порог «есть текст JD» — как бэкенд `MIN_VACANCY_TEXT_LEN` / подготовка. Stub из синка
// откликов приходит с пустым текстом и без скора.
export const MIN_VACANCY_TEXT_LEN = 50

/** Нет скора и текст вакансии пустой/короткий — нужен визит на площадку или вставка текста. */
export function needsVacancyText(
  job: Pick<Job, "vacancy_text" | "overall_score"> | null | undefined,
): boolean {
  if (!job) return false
  if (job.overall_score != null && Number.isFinite(job.overall_score)) return false
  return (job.vacancy_text?.trim().length ?? 0) < MIN_VACANCY_TEXT_LEN
}

export const VACANCY_TEXT_NEEDED_HINT =
  "Нужен текст вакансии: откройте страницу на площадке (расширение спарсит) или вставьте текст. Без скора карточка удалится через 6 ч."

function recommendationStatusTone(tone: RecommendationTone): StatusTone {
  if (tone === "strong") return "strong"
  return CRITERION_TO_STATUS_TONE[tone]
}

// Порядок рекомендаций (сильный → пропустить) для чипов-фильтров (JS-1.3).
export const RECO_ORDER = ["strong_apply", "apply", "maybe", "skip"] as const

// «Рекомендованные» (Шаг 10: бейдж каталога getmatch) — strong_apply + apply.
export const RECOMMENDED_RECOS = ["strong_apply", "apply"] as const

// Подписи рекомендации скорера (ScoreResult.recommendation) — приглушённый чип (StatusChip,
// D-04). Ярлыки и базовый тон — shared/criteria (U-01); StatusTone сводится здесь.
export const RECO = Object.fromEntries(
  RECO_ORDER.map((key) => [
    key,
    {
      label: RECOMMENDATION_LABEL[key],
      tone: recommendationStatusTone(RECOMMENDATION_TONE[key]),
    },
  ]),
) as Record<(typeof RECO_ORDER)[number], { label: string; tone: StatusTone }>

// Формат работы (jobs.work_format, новая таксономия hh) → короткий чип (StatusChip, D-04). Тон по
// предпочтению владельца (нужна полная удалёнка): удалёнка → strong, гибрид → warn, офис → bad.
// work_format часто комбо («удалённо, гибрид»); приоритет — самый удобный для кандидата вариант.
// currencyRemote — LLM-сигнал ScoreResult.currency_remote (явно зарубежная компания/валютная
// зарплата); перекрывает обычную удалёнку более узкой меткой «Валютка» (info — нейтральный тег).
export function workFormatChip(
  workFormat?: string | null,
  currencyRemote?: boolean,
): { label: string; tone: StatusTone } | null {
  if (currencyRemote) return { label: "Валютка", tone: "info" }
  const low = (workFormat ?? "").toLowerCase().replace(/ё/g, "е").trim()
  if (!low) return null
  // «валют» — ручной выбор JS-8.3 (WORK_FORMAT_MANUAL_OPTIONS), когда площадка/LLM не смогли
  // определить формат сами; currency_remote (ветка выше) остаётся источником для авто-скоринга.
  if (/валют|currency/.test(low)) return { label: "Валютка", tone: "info" }
  if (/удален|remote|дистанц/.test(low)) return { label: "Удалёнка", tone: "strong" }
  if (/гибрид|hybrid/.test(low)) return { label: "Гибрид", tone: "warn" }
  if (/релокац|relocat|переезд/.test(low)) return { label: "Релокация", tone: "good" }
  if (/офис|на месте|office|on-?site|разъезд/.test(low)) return { label: "Офис", tone: "bad" }
  return null
}

// Короткая метка формата для шапки чата (офис/гибрид/удалёнка/релокация). Без чипа - просто текст.
export function workFormatLabel(workFormat?: string | null): string | null {
  return workFormatChip(workFormat)?.label ?? null
}

// --- Ручной выбор формата (JS-8.3) ---
// Когда площадка не отдала work_format и LLM не смог определить его по тексту — вместо
// прочерка в шапке чата даём выбрать из того же канона, что API принимает в PATCH /api/jobs/{id}
// (api.schemas.jobs.WorkFormatManual). Значения — не коды, а сразу текст, который workFormatChip
// распознает регексом выше (симметрично с тем, как HH присылает свободный текст).
export const WORK_FORMAT_MANUAL_OPTIONS: readonly { value: string; label: string }[] = [
  { value: "Офис", label: "Офис" },
  { value: "Гибрид", label: "Гибрид" },
  { value: "Удалённо", label: "Удалёнка" },
  { value: "Валютная удалёнка", label: "Валютка" },
]

// Бейдж «снята с публикации» (F-12) — один стиль для карточки, списка и дровера.
export const ARCHIVED_BADGE: { label: string; tone: StatusTone } = { label: "Архив", tone: "bad" }

// Бейдж «Автоотклик» (Фаза 7.1, plans/auto_apply_roadmap_2026_08_17.md): отклик ушёл сам,
// не рукой владельца — должен быть виден на карточке, не только в тултипе. `applied_source` —
// источник последней стадии «Отклик» (core.app.channels.AUTO_APPLY_*, префикс "auto_apply_"),
// зеркалит core.domains.opportunities.jobs.is_auto_apply_source.
export function isAutoApplied(job: Pick<Job, "applied_source">): boolean {
  return Boolean(job.applied_source?.startsWith("auto_apply_"))
}

export const AUTO_APPLY_BADGE: { label: string; tone: StatusTone } = {
  label: "Автоотклик",
  tone: "info",
}

// Число откликов на площадке (jobs.total_responses, F-12) с русским склонением.
export function responsesLabel(n: number): string {
  const mod100 = n % 100
  const mod10 = n % 10
  let word: string
  if (mod100 >= 11 && mod100 <= 14) word = "откликов"
  else if (mod10 === 1) word = "отклик"
  else if (mod10 >= 2 && mod10 <= 4) word = "отклика"
  else word = "откликов"
  return `${n} ${word}`
}

const COMPETITION_TONE: Record<CompetitionLevel, StatusTone> = {
  low: "good",
  medium: "warn",
  high: "bad",
}

export function competitionLabel(totalResponses: number): { text: string; tone: StatusTone } {
  const level = competitionLevel(totalResponses)!
  const suffix = COMPETITION_LEVEL_SUFFIX[level]
  return {
    text: suffix ? `${responsesLabel(totalResponses)} · ${suffix}` : responsesLabel(totalResponses),
    tone: COMPETITION_TONE[level],
  }
}

// --- Под-скор «шанс на отклик» (Этап 6 §6.2, backend `competition.py`) ---
// Богаче старой эвристики выше (competitionLevel/competitionLabel — только сырой count,
// пороги 100/500 под расширение): здесь backend уже учёл возраст публикации и
// letter_required. НЕ входит в overall_score (Этап 7 ещё не измерил корреляцию с исходами).
// Старая эвристика остаётся как есть — её используют extension/панель и SERP-контекст, где
// job.competition (посчитан только при скоринге через бэкенд) ещё недоступен.
export type CompetitionInsightLevel = "favorable" | "neutral" | "crowded" | "unknown"
export type CompetitionInsightView = {
  level?: CompetitionInsightLevel
  responses_per_day?: number | null
  age_days?: number | null
  reasoning?: string
}

const COMPETITION_INSIGHT_ORDER: readonly CompetitionInsightLevel[] = [
  "favorable",
  "neutral",
  "crowded",
  "unknown",
]

export const COMPETITION_INSIGHT_LABEL: Record<
  Exclude<CompetitionInsightLevel, "unknown">,
  { short: string; tone: StatusTone }
> = {
  favorable: { short: "хороший шанс", tone: "good" },
  neutral: { short: "средняя конкуренция", tone: "warn" },
  crowded: { short: "высокая конкуренция", tone: "bad" },
}

// Достать под-скор из job (jsonb). "unknown"/битое значение → undefined (бейдж не рисуем, старая
// эвристика по total_responses остаётся видимой сама по себе — см. VacancyMeta).
export function competitionInsightOf(job: Job): CompetitionInsightView | undefined {
  const raw = (job as { competition?: unknown }).competition
  if (!raw || typeof raw !== "object") return undefined
  const view = raw as CompetitionInsightView
  return COMPETITION_INSIGHT_ORDER.includes(view.level as CompetitionInsightLevel)
    ? view
    : undefined
}

export function competitionInsightLabel(
  view: CompetitionInsightView,
): { text: string; tone: StatusTone } | null {
  if (!view.level || view.level === "unknown") return null
  const { short, tone } = COMPETITION_INSIGHT_LABEL[view.level]
  return { text: short, tone }
}

// Активен ли оффер по вакансии (черновик/отклонённый/истёкший не считаем — решение уже не
// актуально или ещё не оформлено).
// и подсветка карточки (OF-7), но локально на объекте job — без похода за отдельным списком офферов.
function hasLiveOffer(job: Job): boolean {
  return job.offer_status === "thinking" || job.offer_status === "accepted"
}

// Формат работы вакансии: условия оффера главнее исходного HH-формата, если оффер активен и
// его формат явно задан и отличается (OF-8.3) — реальность важнее заявленного на момент публикации.
export function effectiveWorkFormat(job: Job): string | null | undefined {
  if (hasLiveOffer(job) && job.offer_work_format && job.offer_work_format !== job.work_format) {
    return job.offer_work_format
  }
  return job.work_format
}

// --- Под-скор «реальность полной удалёнки» (feature 2.2) ---
// Отдельный сигнал поверх скоринга: верить ли заявленной удалёнке (фейк-ремоут отсекаем до
// диалога). Хранится в job.remote_feasibility (jsonb). Тон по дизайн-дисциплине (StatusChip,
// D-04): реальна → strong, условно → warn, вряд ли → bad (как workFormatChip, под жёсткое
// условие удалёнки).
export type RemoteVerdict = "real" | "conditional" | "unlikely"

export const REMOTE_FEASIBILITY: Record<
  RemoteVerdict,
  { label: string; short: string; tone: StatusTone }
> = {
  real: { label: "Удалёнка реальна", short: "Реальна", tone: "strong" },
  conditional: { label: "Удалёнка условно", short: "Скорее Гибрид", tone: "warn" },
  unlikely: { label: "Удалёнка вряд ли", short: "Скорее Офис", tone: "bad" },
}
// Порядок для чипов-фильтров (реальна → вряд ли).
export const REMOTE_VERDICT_ORDER: readonly RemoteVerdict[] = ["real", "conditional", "unlikely"]

export type RemoteSignal = { text: string; polarity: "pro" | "contra" }
export type RemoteFeasibilityView = {
  score?: number
  verdict?: RemoteVerdict
  signals?: RemoteSignal[]
  note?: string
}

// Достать под-скор удалёнки из job (jsonb). Пусто/неизвестный verdict → undefined (бейдж не рисуем).
export function remoteFeasibilityOf(job: Job): RemoteFeasibilityView | undefined {
  const rf = (job as { remote_feasibility?: unknown }).remote_feasibility
  if (!rf || typeof rf !== "object") return undefined
  const view = rf as RemoteFeasibilityView
  return REMOTE_VERDICT_ORDER.includes(view.verdict as RemoteVerdict) ? view : undefined
}

// --- Конфликт формата (V-05) ---
// Заявленный формат хвалит вакансию («Удалёнка»/«Релокация»), а под-скор реальности говорит, что
// по тексту это condition/unlikely — сегодня это видно только в свёрнутом по умолчанию спойлере
// «Реальность удалёнки». Правило (Решение 3 плана): карточка «Формат» красится по вердикту
// реальности, а не по заявленному формату, и подпись цитирует контра-сигнал вместо заголовка
// формата. «Позитивный» чип — strong/good (Удалёнка/Релокация); «Офис» и так bad, добавлять
// предупреждение некуда, «Гибрид» — уже сам по себе предупреждающий warn-тон.
export type FormatConflict = { tone: StatusTone; caption: string }

export function formatConflictOf(
  formatChip: { label: string; tone: StatusTone } | null | undefined,
  remote: RemoteFeasibilityView | undefined,
): FormatConflict | null {
  if (!formatChip || (formatChip.tone !== "strong" && formatChip.tone !== "good")) return null
  if (!remote?.verdict || remote.verdict === "real") return null
  // Короткая подпись — не цитата из JD (обрезка + ложные «офис»-сигналы).
  return {
    tone: REMOTE_FEASIBILITY[remote.verdict].tone,
    caption: REMOTE_FEASIBILITY[remote.verdict].short,
  }
}

// B-02: неизвестный уровень никогда не рендерится сырым в интерфейс. Новая версия модели может
// прислать значение, которого фронт ещё не знает (снапшот jsonb переживает деплой) — ярлык падает
// на «—», а сырой ключ уходит в title/tooltip, а не в текст. Общий резолвер для всех Record-словарей
// уровней (грейд, менеджмент, тип компании — GRADE_LABEL/BURNOUT_LABEL/COMPANY_TYPE_LABEL).
export function levelLabel(
  map: Record<string, string>,
  level: string | null | undefined,
): { label: string; rawTitle?: string } {
  if (!level) return { label: "—" }
  const known = map[level]
  return known ? { label: known } : { label: "—", rawTitle: level }
}

// Тип компании из ScoreResult.company_type. Метки общие для дровера (JS-1.2) и фильтра (JS-1.3).
export const COMPANY_TYPE_LABEL: Record<string, string> = {
  product: "Продукт",
  fintech_product: "Финтех-продукт",
  bank: "Банк",
  startup: "Стартап",
  outsource: "Аутсорс",
  infra: "Инфра",
  agency: "Агентство",
  media: "Медиа",
  retail: "Ритейл",
  manufacturing: "Производство",
  education: "Образование",
  government: "Госсектор",
  nonprofit: "НКО",
  smb: "МСБ",
  unknown: "—",
}
// Порядок типов для выпадашки фильтра; «unknown» сюда не входит (шум в фильтре).
export const COMPANY_TYPE_ORDER = [
  "product",
  "fintech_product",
  "bank",
  "startup",
  "outsource",
  "infra",
  "agency",
  "media",
  "retail",
  "manufacturing",
  "education",
  "government",
  "nonprofit",
  "smb",
] as const

// Достать тип компании из jsonb-разбора (job.score.company_type). Пусто/не строка → undefined.
export function companyTypeOf(job: Job): string | undefined {
  const ct = (job.score as { company_type?: unknown } | undefined)?.company_type
  return typeof ct === "string" && ct ? ct : undefined
}

// --- Зарплата для превью карточки и дровера (шаг 22) ---
// Приоритет: оффер → explicit (salary_text / source=explicit) → оценка (corpus/llm) →
// «—» / «оценка…». source=none без данных — прочерк, не выдуманное число.
const SALARY_UNSPECIFIED = /не\s*указ|не\s*обознач|договор|по\s*резул|обсужд|з\/п\s*не/i

function salarySpecified(text?: string | null): boolean {
  const t = (text ?? "").trim()
  if (!t || t.toLowerCase() === "не указана") return false
  if (SALARY_UNSPECIFIED.test(t)) return false
  return /\d/.test(t)
}

// Срезаем канцелярит hh, «/мес» и суффикс «(… оценка)» (его покажем отдельным тегом); nbsp → пробел.
function cleanSalary(text: string): string {
  return text
    .replace(/\s*\([^)]*оценка[^)]*\)\s*/i, " ")
    .replace(/[,;]?\s*(за|в)\s+месяц/gi, "")
    .replace(/\s*₽?\s*\/\s*мес\w*/gi, "")
    .replace(/[,;]?\s*(до|после)\s+вычета\s+налог\w*/gi, "")
    .replace(/\u00A0/g, " ")
    .replace(/\s{2,}/g, " ")
    .replace(/[,\s]+$/g, "")
    .trim()
}

export type SalarySourceUi = "offer" | "explicit" | "corpus" | "llm" | "none"
export type SalaryConfidenceUi = "high" | "medium" | "low"

type SalaryView = {
  value_or_range?: string
  estimated_range?: string
  estimated_min?: number | null
  estimated_max?: number | null
  meets_min?: boolean
  estimate_pending?: boolean
  confidence?: SalaryConfidenceUi | string
  source?: SalarySourceUi | string
  note?: string
}

export type ResolvedJobSalary = {
  text: string
  isEstimate: boolean
  /** null — в резюме нет salary_min, порог не красим. */
  meetsMin: boolean | null
  confidence: SalaryConfidenceUi
  source: SalarySourceUi
  /** «оценка» / «грубая оценка» для оценочных вилок; null для оффера/explicit. */
  estimateSuffix: string | null
}

function asConfidence(raw: string | undefined): SalaryConfidenceUi {
  if (raw === "high" || raw === "medium" || raw === "low") return raw
  return "low"
}

function estimateSuffixFor(confidence: SalaryConfidenceUi, isEstimate: boolean): string | null {
  if (!isEstimate) return null
  return confidence === "low" ? "грубая оценка" : "оценка"
}

/** Текст на карточке/в списке: сумма + суффикс оценки при необходимости. */
export function formatSalaryCardText(salary: ResolvedJobSalary): string {
  if (salary.text === "—" || salary.text === "оценка…") return salary.text
  const base = polishSalaryDisplay(abbrevSalary(salary.text))
  return salary.estimateSuffix ? `${base} · ${salary.estimateSuffix}` : base
}

function salaryAmountK(n: number): string {
  if (n >= 1_000_000) {
    const v = n / 1_000_000
    return `${Number.isInteger(v) ? v : v.toFixed(1).replace(/\.0$/, "")}М`
  }
  return `${Math.round(n / 1000)}к`
}

/** Краткая зарплата для шапки чата: net-вилка, без простыней про KPI/оклад. */
export function headerSalaryLabel(
  job: Job,
  salaryMin?: number | null,
): {
  text: string
  isEstimate: boolean
  meetsMin: boolean | null
  confidence: SalaryConfidenceUi
  source: SalarySourceUi
} {
  const base = resolveJobSalary(job, salaryMin)
  // Оффер — точный факт, не рыночная LLM-прикидка: показываем как есть (короткой формой через
  // salaryAmountK, не разворачиваем в net-вилку ниже — та ветка читает job.score.salary, который
  // мог остаться от скоринга ДО оффера).
  if (hasLiveOffer(job) && job.offer_base_salary != null) {
    const bonusK = job.offer_bonus_monthly_equiv
      ? ` + ${salaryAmountK(job.offer_bonus_monthly_equiv)}`
      : ""
    return {
      text: `${salaryAmountK(job.offer_base_salary)}${bonusK}`,
      isEstimate: false,
      meetsMin: base.meetsMin,
      confidence: "high",
      source: "offer",
    }
  }
  const sal = (job.score as { salary?: SalaryView } | undefined)?.salary
  const min = sal?.estimated_min ?? null
  const max = sal?.estimated_max ?? null

  const pack = (text: string) => ({
    text,
    isEstimate: base.isEstimate,
    meetsMin: base.meetsMin,
    confidence: base.confidence,
    source: base.source,
  })

  if (min != null && max != null && min > 0 && base.isEstimate) {
    const lo = salaryAmountK(min)
    const hi = salaryAmountK(max)
    const text = min === max || lo === hi ? `${lo} net` : `${lo}–${hi} net`
    return pack(text)
  }

  if (base.text === "—" || base.text === "оценка…") {
    return pack(base.text)
  }

  const raw = base.text
  const netChunk = raw.match(
    /(?:от\s+)?(\d[\d\s]{2,}|\d{3,})\s*(?:–|-|—|до)\s*(\d[\d\s]{2,}|\d{3,})[^\n]{0,40}?(?:net|на\s+руки|руки)/i,
  )
  if (netChunk) {
    const a = parseInt(netChunk[1].replace(/\s/g, ""), 10)
    const b = parseInt(netChunk[2].replace(/\s/g, ""), 10)
    if (Number.isFinite(a) && Number.isFinite(b)) {
      const lo = salaryAmountK(a >= 1000 ? a : a * 1000)
      const hi = salaryAmountK(b >= 1000 ? b : b * 1000)
      return pack(`${lo}–${hi} net`)
    }
  }

  const singleNet = raw.match(/(?:анкор|anchor|от)?\s*(\d{3,})[^\n]{0,30}?(?:net|на\s+руки|руки)/i)
  if (singleNet) {
    const n = parseInt(singleNet[1], 10)
    if (Number.isFinite(n)) {
      const k = n >= 1000 ? n : n * 1000
      return pack(`${salaryAmountK(k)} net`)
    }
  }

  const nums = [...raw.matchAll(/\d[\d\s]{2,}|\d{3,}/g)]
    .map((m) => parseInt(m[0].replace(/\s/g, ""), 10))
    .filter((n) => Number.isFinite(n) && n >= 100)
    .map((n) => (n < 1000 ? n * 1000 : n))

  if (nums.length >= 2) {
    return pack(`${salaryAmountK(nums[0])}–${salaryAmountK(nums[1])}`)
  }
  if (nums.length === 1) {
    return pack(`${salaryAmountK(nums[0])}${base.isEstimate ? "~" : ""}`)
  }

  const short = abbrevSalary(raw)
  return pack(short.length > 22 ? `${short.slice(0, 20)}…` : short)
}

// Подсказка при наведении на «Зарплата» в шапке чата — объясняет пустой/висящий результат,
// а не просто повторяет цифру. «—» без объяснения читался как баг, а не как «вилки правда нет».
// Реальная вилка от HR/из оффера появится сама (explicit → is_salary_locked, LLM больше не зовём).
export function salaryHeaderHint(job: Job, salaryMin?: number | null): string | null {
  const label = headerSalaryLabel(job, salaryMin)
  if (label.text === "оценка…") {
    return "Вилка считается в фоне по тексту вакансии — обновится сама, обычно за минуту."
  }
  if (label.text === "—") {
    return (
      "Не удалось оценить: в вакансии нет цифр, а прикидка по резюме/похожим вакансиям не " +
      "сошлась. Появится сама, если вилку назовёт HR в переписке или её впишете в оффер."
    )
  }
  return null
}

const OFFER_CURRENCY_SYMBOL: Record<string, string> = { RUB: "₽", USD: "$", EUR: "€" }
const OFFER_PERIOD_SUFFIX: Record<string, string> = { month: "мес", year: "год" }

// Точные условия оффера (база + период) — без пометки «оценка», в отличие от рыночной прикидки.
// Хвост «+ N ₽/мес премия» — только для уже посчитанного помесячного эквивалента
// (offer_bonus_monthly_equiv); сырую сумму бонуса без периода сюда не подмешиваем, иначе
// непонятно, «премия 1.2М» — это в год или в месяц.
function formatOfferSalary(job: Job): string | null {
  const amount = job.offer_base_salary
  if (amount == null) return null
  const currency =
    OFFER_CURRENCY_SYMBOL[job.offer_base_salary_currency ?? "RUB"] ??
    job.offer_base_salary_currency ??
    "₽"
  const period = OFFER_PERIOD_SUFFIX[job.offer_base_salary_period ?? "month"] ?? "мес"
  // toLocaleString("ru-RU") ставит NBSP между разрядами — приводим к обычному пробелу (тот же
  // приём, что cleanSalary), иначе визуально неотличимо от бага при копировании/поиске по тексту.
  const base = `${amount.toLocaleString("ru-RU").replace(/\u00A0/g, " ")} ${currency}/${period}`
  if (job.offer_bonus_monthly_equiv) {
    const bonus = job.offer_bonus_monthly_equiv.toLocaleString("ru-RU").replace(/\u00A0/g, " ")
    return `${base} + ${bonus} ${currency}/мес премия`
  }
  return base
}

function resolveExplicitKind(job: Job, sal: SalaryView | undefined): "hr" | "page" | "jd" {
  const note = (sal?.note || "").toLowerCase()
  if (note.includes("hr") || note.includes("рекрутер")) return "hr"
  if (note.includes("карточки") || note.includes("страницы")) return "page"
  if (salarySpecified(job.salary_text)) return "page"
  return "jd"
}

function meetsMinAgainstTarget(
  salaryMin: number | null | undefined,
  predicate: boolean,
): boolean | null {
  if (salaryMin == null || salaryMin <= 0) return null
  return predicate
}

/** Происхождение вилки для дровера (тексты из help-texts / шаблон corpus). */
export function salaryProvenanceLabel(job: Job): string | null {
  const resolved = resolveJobSalary(job)
  if (resolved.source === "offer" || resolved.text === "—" || resolved.text === "оценка…") {
    return null
  }
  const sal = (job.score as { salary?: SalaryView } | undefined)?.salary
  if (resolved.source === "explicit") {
    const kind = resolveExplicitKind(job, sal)
    if (kind === "hr") return getHelpText("jobs.salary-explicit-hr")
    if (kind === "page") return getHelpText("jobs.salary-explicit-page")
    return getHelpText("jobs.salary-explicit-jd")
  }
  if (resolved.source === "corpus") {
    const n = (sal?.note || "").match(/по\s+(\d+)\s+наблюден/i)?.[1]
    if (n) return `по ${n} похожим вакансиям из вашей воронки`
    return getHelpText("jobs.salary-corpus")
  }
  if (resolved.source === "llm") return getHelpText("jobs.salary-llm")
  return null
}

// Итоговая вилка для UI (шаг 22/23). isEstimate только для corpus/llm.
// salaryMin — position.salary_min из резюме; без него meetsMin=null (не красим порог).
export function resolveJobSalary(job: Job, salaryMin?: number | null): ResolvedJobSalary {
  if (hasLiveOffer(job) && job.offer_base_salary != null) {
    const offerText = formatOfferSalary(job)
    if (offerText) {
      return {
        text: offerText,
        isEstimate: false,
        meetsMin: meetsMinAgainstTarget(salaryMin, job.offer_base_salary >= (salaryMin ?? 0)),
        confidence: "high",
        source: "offer",
        estimateSuffix: null,
      }
    }
  }

  const sal = (job.score as { salary?: SalaryView } | undefined)?.salary
  const meetsMin = meetsMinAgainstTarget(salaryMin, Boolean(sal?.meets_min))
  const confidence = asConfidence(sal?.confidence)
  const rawSource = (sal?.source || "none") as string

  if (salarySpecified(job.salary_text)) {
    return {
      text: cleanSalary(job.salary_text as string),
      isEstimate: false,
      meetsMin,
      confidence: "high",
      source: "explicit",
      estimateSuffix: null,
    }
  }

  if (rawSource === "explicit") {
    const val = sal?.value_or_range || ""
    if (salarySpecified(val)) {
      return {
        text: cleanSalary(val),
        isEstimate: false,
        meetsMin,
        confidence: "high",
        source: "explicit",
        estimateSuffix: null,
      }
    }
  }

  const estimateSources = new Set(["corpus", "llm"])
  if (estimateSources.has(rawSource)) {
    const est = sal?.estimated_range || sal?.value_or_range || ""
    if (salarySpecified(est)) {
      const isEstimate = true
      return {
        text: cleanSalary(est),
        isEstimate,
        meetsMin,
        confidence,
        source: rawSource as SalarySourceUi,
        estimateSuffix: estimateSuffixFor(confidence, isEstimate),
      }
    }
  }

  // Legacy jsonb без source: estimated_* → оценка; иначе не выдумываем.
  if (rawSource === "none" || !sal?.source) {
    if (sal?.estimate_pending) {
      return {
        text: "оценка…",
        isEstimate: true,
        meetsMin: null,
        confidence: "low",
        source: "none",
        estimateSuffix: null,
      }
    }
    const legacyEst = sal?.estimated_range
    if (salarySpecified(legacyEst)) {
      return {
        text: cleanSalary(legacyEst as string),
        isEstimate: true,
        meetsMin,
        confidence,
        source: "llm",
        estimateSuffix: estimateSuffixFor(confidence, true),
      }
    }
    if (sal?.estimated_min != null && sal?.estimated_max != null && sal.estimated_min > 0) {
      const lo = salaryAmountK(sal.estimated_min)
      const hi = salaryAmountK(sal.estimated_max)
      const text = lo === hi ? `${lo}` : `${lo}–${hi}`
      return {
        text,
        isEstimate: true,
        meetsMin,
        confidence,
        source: "llm",
        estimateSuffix: estimateSuffixFor(confidence, true),
      }
    }
  }

  if (sal?.estimate_pending) {
    return {
      text: "оценка…",
      isEstimate: true,
      meetsMin: null,
      confidence: "low",
      source: "none",
      estimateSuffix: null,
    }
  }

  return {
    text: "—",
    isEstimate: false,
    meetsMin: null,
    confidence: "low",
    source: "none",
    estimateSuffix: null,
  }
}

// --- Дата публикации ---
// jobs.published_at хранится русским текстом («18 июня 2026»). Приводим к «ДД.ММ» — крупный
// freshness-анкор на карточке (при просмотре 1000+ важно видеть свежесть с одного взгляда).
const RU_MONTHS = [
  "янв",
  "фев",
  "мар",
  "апр",
  "ма",
  "июн",
  "июл",
  "авг",
  "сен",
  "окт",
  "ноя",
  "дек",
]

export function fmtDayMonth(published?: string | null): string | null {
  const raw = (published ?? "").trim().toLowerCase().replace(/ё/g, "е")
  if (!raw) return null
  const ru = raw.match(/(\d{1,2})\s+([а-я]+)/) // «18 июня 2026»
  if (ru) {
    const mon = RU_MONTHS.findIndex((m) => ru[2].startsWith(m))
    if (mon >= 0) return `${ru[1].padStart(2, "0")}.${String(mon + 1).padStart(2, "0")}`
  }
  const iso = raw.match(/(\d{4})-(\d{2})-(\d{2})/) // «2026-06-23»
  if (iso) return `${iso[3]}.${iso[2]}`
  const dot = raw.match(/(\d{1,2})\.(\d{1,2})/) // «23.06.2026»
  if (dot) return `${dot[1].padStart(2, "0")}.${dot[2].padStart(2, "0")}`
  return null
}

/** Дата публикации для дровера: только дата, без времени ISO. */
export function fmtPublishedDate(published?: string | null): string | null {
  const raw = (published ?? "").trim()
  if (!raw) return null
  const iso = raw.match(/(\d{4})-(\d{2})-(\d{2})/)
  if (iso) return `${iso[3]}.${iso[2]}.${iso[1]}`
  // Уже человекочитаемый RU-текст («18 июня 2026») — оставляем как есть.
  if (/[а-яё]/i.test(raw) && !raw.includes("T")) return raw
  return fmtDayMonth(published)
}

// --- Дата для карточки: «последнее изменение, если вакансия пошла дальше» ---
// Пока вакансия на «Просмотр»/«Отклик» — показываем дату отклика (или публикации). Как только
// продвинулась дальше (Скрининг/Техничка/Финал/Оффер/Отказ) — дату последнего изменения строки
// (updated_at): на карточке важно видеть свежесть именно последнего события по вакансии.
const ADVANCED_STAGES: ReadonlySet<FunnelStage> = new Set<FunnelStage>([
  "Скрининг",
  "Техничка",
  "Финал",
  "Оффер",
  "Отказ",
])

export function cardDay(job: Job): { text: string | null; label: string } {
  const stage = resolveStage(job.status)
  if (!job.skipped && ADVANCED_STAGES.has(stage)) {
    const changed = fmtDayMonth(job.updated_at)
    if (changed) return { text: changed, label: stage }
  }
  const applied = fmtDayMonth(job.applied_at)
  if (applied) return { text: applied, label: "Отклик" }
  return { text: fmtDayMonth(job.published_at), label: "Опубл." }
}

// --- «Изменено» для списка (UX3-8): сегодня → ЧЧ:ММ, иначе ДД.ММ ---
// Источник даты — та же логика, что cardDay (updated_at на продвинутых этапах, иначе applied_at,
// иначе published_at). Время показываем только когда источник — updated_at: applied_at приходит
// датой без времени («YYYY-MM-DD»), published_at — русским текстом даты, у обоих нет часов/минут,
// показывать для них ЧЧ:ММ было бы выдумкой.
export function fmtChanged(job: Job): string {
  const stage = resolveStage(job.status)
  if (!job.skipped && ADVANCED_STAGES.has(stage) && job.updated_at) {
    const t = Date.parse(job.updated_at)
    if (!Number.isNaN(t)) {
      const d = new Date(t)
      const now = new Date()
      if (
        d.getFullYear() === now.getFullYear() &&
        d.getMonth() === now.getMonth() &&
        d.getDate() === now.getDate()
      ) {
        return d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })
      }
      const changed = fmtDayMonth(job.updated_at)
      if (changed) return changed
    }
  }
  const applied = fmtDayMonth(job.applied_at)
  if (applied) return applied
  return fmtDayMonth(job.published_at) ?? "—"
}

// Сортировочный ключ списка вакансий (мс): «релевантная дата по статусу» по убыванию. Зеркалит
// cardDay — продвинутые этапы по updated_at (последнее изменение), остальные по дате отклика; если
// её нет — по scored_at (дате просмотра/оценки). published_at не годится (RU-текст, не парсится).
// Пусто/кривое → -Infinity (в хвост при сортировке desc).
export function cardDateMs(job: Job): number {
  const stage = resolveStage(job.status)
  const parse = (iso?: string | null) => {
    const t = iso ? Date.parse(iso) : NaN
    return Number.isNaN(t) ? null : t
  }
  if (!job.skipped && ADVANCED_STAGES.has(stage)) {
    const changed = parse(job.updated_at)
    if (changed != null) return changed
  }
  return parse(job.applied_at) ?? parse(job.scored_at) ?? -Infinity
}

// --- Разбор балла «Почему N» (V-04) — строки из shared/score-breakdown (U-06). ---
type ScoreForBreakdown = NonNullable<Job["score"]>

export type ScoreBreakdownRow = Omit<SharedScoreBreakdownRow, "tone"> & { tone: StatusTone }

export function scoreBreakdownRows(
  s: ScoreForBreakdown,
  weights: ScoringWeights | undefined,
): ScoreBreakdownRow[] | null {
  const rows = sharedScoreBreakdownRows(s, weights)
  if (!rows) return null
  return rows.map((r) => ({
    ...r,
    tone: CRITERION_TO_STATUS_TONE[r.tone],
  }))
}

export function scoreCalibrationDelta(s: ScoreForBreakdown, rows: ScoreBreakdownRow[]): number {
  return sharedScoreCalibrationDelta(s.overall_score, rows)
}

// --- Сокращение сумм для превью карточки: «300 000» → «300к», «1 500 000» → «1.5М» ---
// На карточке нули режут вилку и шумят. Сокращаем тысячи/миллионы, валюту и слова «от/до» храним.
export function abbrevSalary(text: string): string {
  if (!text || text === "—") return text
  return text.replace(/\d[\d\s]*\d|\d+/g, (m) => {
    const n = parseInt(m.replace(/[\s]/g, ""), 10)
    if (!Number.isFinite(n) || n < 1000) return m
    if (n >= 1_000_000) {
      const v = n / 1_000_000
      return `${Number.isInteger(v) ? v : v.toFixed(1).replace(/\.0$/, "")}М`
    }
    return `${Math.round(n / 1000)}к`
  })
}

/** Вилка «от 350к до 400к» без ₽/мес — период и так очевиден. */
export function polishSalaryDisplay(text: string): string {
  let t = text
    .replace(/\s*₽(?:\s*\/\s*мес\w*)?/gi, "")
    .replace(/\s*\/\s*мес\w*/gi, "")
    .replace(/\s*руб\.?/gi, "")
    .replace(/\s{2,}/g, " ")
    .trim()
  const bare = t.match(/^(\d+(?:[.,]\d+)?(?:к|К|М|м)?)\s*[–—−-]+\s*(\d+(?:[.,]\d+)?(?:к|К|М|м)?)$/i)
  if (bare) return `от ${bare[1]} до ${bare[2]}`
  t = t.replace(/\bот\s+/i, "от ").replace(/\s+до\s+/i, " до ")
  return t
}
