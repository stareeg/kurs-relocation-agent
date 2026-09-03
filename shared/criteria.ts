// Общий словарь критериев скоринга веб-дровера и панели расширения (E-02): ярлыки, порядок
// критериев и классификация good/mid/bad — единственный источник, чтобы «Домен» в расширении и
// «Содержание роли» в вебе (или разные пороги той же полосы) не разъезжались по памяти между
// правками. Нейтральная классификация ("good"|"mid"|"bad"|"neutral") — общий словарь
// строк разбора (`.jh-breakdown-fill.good` и т.п. в extension/src/ui/panel.css); веб сводит
// её к своему StatusTone (mid→warn, neutral→info) на своей стороне, здесь этого типа нет,
// чтобы модуль не тянул зависимость на дизайн-систему веба (см. shared/highlight.ts).
export type CriterionTone = "good" | "mid" | "bad" | "neutral"

// Шесть критериев overall_score в порядке убывания веса по умолчанию (см. core/domains/
// opportunities/score_breakdown.py) — порядок строк разбора в дровере и сегментов бара в панели.
export const SCORE_BREAKDOWN_KEYS = [
  "salary",
  "work_format",
  "grade_match",
  "role_content",
  "management",
  "company",
] as const
export const SECOND_JOB_SCORE_BREAKDOWN_KEYS = [
  "flexibility",
  "role_content",
  "compat",
  "rate",
  "company",
] as const
export type PrimaryScoreBreakdownKey = (typeof SCORE_BREAKDOWN_KEYS)[number]
export type SecondJobScoreBreakdownKey = (typeof SECOND_JOB_SCORE_BREAKDOWN_KEYS)[number]
export type ScoreBreakdownKey = PrimaryScoreBreakdownKey | SecondJobScoreBreakdownKey

export const SCORE_BREAKDOWN_LABEL: Record<ScoreBreakdownKey, string> = {
  salary: "Зарплата",
  work_format: "Формат",
  grade_match: "Грейд",
  role_content: "Домен",
  management: "Роль",
  company: "Компания",
  flexibility: "Гибкость",
  compat: "Совместимость",
  rate: "Ставка",
}

// Порядок отображения 6 критериев в сетке 2×3 (панель расширения / дровер, Решение 3): НЕ порядок
// веса (тот — SCORE_BREAKDOWN_KEYS, канон для бэка/весов), а фиксированный порядок ячеек grid
// (grid-auto-flow: row, 2 колонки) — иначе разбор перемешивался от вакансии к вакансии (раньше
// строки сортировались по значению). Ячейки заполняются по строкам, поэтому пары идут
// [левая, правая] на каждую строку: Зарплата/Роль, Формат/Домен, Грейд/Компания — левая колонка
// сверху вниз: Зарплата/Формат/Грейд, правая: Роль/Домен/Компания.
export const SCORE_BREAKDOWN_DISPLAY_ORDER: readonly ScoreBreakdownKey[] = [
  "salary",
  "management",
  "work_format",
  "role_content",
  "grade_match",
  "company",
]

export const SECOND_JOB_BREAKDOWN_DISPLAY_ORDER: readonly ScoreBreakdownKey[] = [
  "flexibility",
  "compat",
  "role_content",
  "rate",
  "company",
]

// Фолбэк, пока /api/settings ещё не загружен (или недоступен) — совпадает с дефолтом бэка
// (core/platform/repo/settings.py DEFAULT_SCORING_WEIGHTS), не источник правды (B-04): правка весов на
// «Резюме» обязана менять знаменатель «X из Y» без правки кода на любой из двух поверхностей.
export const DEFAULT_SCORE_BREAKDOWN_MAX: Record<ScoreBreakdownKey, number> = {
  salary: 20,
  work_format: 20,
  grade_match: 15,
  role_content: 15,
  management: 15,
  company: 15,
  flexibility: 25,
  compat: 20,
  rate: 20,
}

export const SECOND_JOB_SCORE_BREAKDOWN_MAX: Record<string, number> = {
  flexibility: 25,
  role_content: 25,
  compat: 20,
  rate: 20,
  company: 10,
}

// Относительная шкала грейда (к цели из резюме, ScoreResult.grade_match.level).
// `role_shift` — не уровень модели, а `off_profile` с `off_profile_kind = "role_shift"`
// (см. gradeLevelKey): та же профессия, сдвиг «руками ↔ управление».
export const GRADE_LABEL: Record<string, string> = {
  match: "Совпадает",
  above: "Выше цели",
  slightly_below: "Чуть ниже",
  far_below: "Заметно ниже",
  off_profile: "Не по профилю",
  role_shift: "Сдвиг роли",
}
export const GRADE_TONE: Record<string, CriterionTone> = {
  match: "good",
  above: "mid",
  slightly_below: "mid",
  far_below: "bad",
  off_profile: "bad",
  role_shift: "mid",
}

/** Ключ шкалы грейда с учётом `off_profile_kind`.
 *
 * Одна метка `off_profile` накрывала и чужую профессию, и сдвиг «руками ↔ управление» внутри
 * своей — и обе красились «bad» с форс-skip. С Этапа 1 второй случай не дилбрейкер (его цена
 * зависит от role_kind резюме), поэтому и в UI он не должен читаться как «не по профилю». */
export function gradeLevelKey(
  grade: { level?: string | null; off_profile_kind?: string | null } | null | undefined,
): string {
  if (grade?.level === "off_profile" && grade.off_profile_kind === "role_shift") return "role_shift"
  return grade?.level ?? ""
}

// Пригодность формата за пределами заявленного (ScoreResult.remote_abroad_compat.level) —
// метрика «Удалёнка» в панели; не путать с remote_feasibility (V-05, «реальность» формата по
// тексту JD), которая уникальна для веба и в этот словарь не входит (E-04).
export const REMOTE_ABROAD_LABEL: Record<string, string> = {
  ideal: "Весь мир",
  ok: "Только РФ",
  risky: "Уточнить",
  blocker: "Офис/нет",
}
export const REMOTE_ABROAD_TONE: Record<string, CriterionTone> = {
  ideal: "good",
  ok: "neutral",
  risky: "mid",
  blocker: "bad",
}

// Уровень управления (ScoreResult.burnout_risk.level; алиас поля — management, см. CLAUDE.md).
// Короткие русские подписи для карточки «Грейд»; medium без «и то и другое» — лучше грейд
// из reasoning (см. gradeFactCard), иначе пустая подпись не показываем как англицизм.
export const MANAGEMENT_LABEL: Record<string, string> = {
  low: "Работа руками",
  medium: "—",
  high: "Управлять людьми",
}
export const MANAGEMENT_TONE: Record<string, CriterionTone> = {
  low: "good",
  medium: "mid",
  high: "bad",
}

// ScoreResult.company_fit.level.
export const COMPANY_FIT_TONE: Record<string, CriterionTone> = {
  strong: "good",
  ok: "neutral",
  weak: "bad",
  unknown: "neutral",
}

// Пороги метрики «Домен» (role_content_match.score, 0-100).
export function roleContentTone(score: number | null | undefined): CriterionTone {
  if (score == null) return "neutral"
  if (score >= 70) return "good"
  if (score >= 40) return "mid"
  return "bad"
}

export function salaryTone(
  meetsMin: boolean | null | undefined,
  hasValue: boolean,
): CriterionTone {
  if (meetsMin) return "good"
  return hasValue ? "bad" : "neutral"
}

// ScoreResult.recommendation — подписи и тон для чипа «Совет» (U-01): единый словарь панели
// расширения и веб-дровера. «strong» вне CriterionTone — отдельный StatusTone веба; mid/bad/good
// сводятся на стороне веба через CRITERION_TO_STATUS_TONE (maybe → warn, apply → good).
export type RecommendationTone = CriterionTone | "strong"

export const RECOMMENDATION_LABEL: Record<string, string> = {
  strong_apply: "Сильный фит",
  apply: "Подать",
  maybe: "Возможно",
  skip: "Пропустить",
}

export const RECOMMENDATION_TONE: Record<string, RecommendationTone> = {
  strong_apply: "strong",
  apply: "good",
  maybe: "mid",
  skip: "bad",
}

// Дискретная шкала цвета overall_score (U-02): пороги 80/60 — как scoreTone в вебе; обе
// поверхности мапят good/mid/low/none на свои токены (emerald/amber/slate).
export type ScoreLevel = "good" | "mid" | "low" | "none"

export function scoreLevel(score?: number | null): ScoreLevel {
  if (score == null) return "none"
  if (score >= 80) return "good"
  if (score >= 60) return "mid"
  return "low"
}

// Конкуренция по числу откликов на площадке (U-03): пороги 100/500 — единая эвристика панели
// расширения и веб-дровера (площадка уровень не отдаёт, только count).
export type CompetitionLevel = "low" | "medium" | "high"

export const COMPETITION_MEDIUM_THRESHOLD = 100
export const COMPETITION_HIGH_THRESHOLD = 500

export function competitionLevel(
  totalResponses: number | null | undefined,
): CompetitionLevel | null {
  if (totalResponses == null) return null
  if (totalResponses > COMPETITION_HIGH_THRESHOLD) return "high"
  if (totalResponses > COMPETITION_MEDIUM_THRESHOLD) return "medium"
  return "low"
}

export const COMPETITION_LEVEL_SUFFIX: Record<CompetitionLevel, string> = {
  low: "",
  medium: "средняя конкуренция",
  high: "высокая конкуренция",
}

// Минимальная форма ScoreResult, которой достаточно для классификации разбора баллов — обе
// поверхности типизируют полный score сами (Job["score"] в вебе, нетипизированный `s` в панели).
export type ScoreBreakdownInput = {
  salary: { meets_min?: boolean | null; value_or_range?: string | null; estimated_range?: string | null }
  remote_abroad_compat: { level: string }
  grade_match: { level: string; off_profile_kind?: string | null }
  role_content_match: { score?: number | null }
  burnout_risk: { level: string }
  company_fit?: { level?: string | null } | null
}

// Классификация good/mid/bad/neutral по критерию (EXT-S1) — общая для бара вклада в панели и
// строк разбора в дровере, чтобы обе поверхности красили один и тот же критерий одинаково.
export function scoreBreakdownTone(key: ScoreBreakdownKey, s: ScoreBreakdownInput): CriterionTone {
  switch (key) {
    case "salary":
      return salaryTone(
        s.salary.meets_min,
        Boolean(s.salary.value_or_range || s.salary.estimated_range),
      )
    case "work_format":
      return REMOTE_ABROAD_TONE[s.remote_abroad_compat.level] ?? "neutral"
    case "grade_match":
      return GRADE_TONE[gradeLevelKey(s.grade_match)] ?? "neutral"
    case "role_content":
      return roleContentTone(s.role_content_match.score)
    case "management":
      return MANAGEMENT_TONE[s.burnout_risk.level] ?? "neutral"
    case "company":
      return COMPANY_FIT_TONE[s.company_fit?.level ?? "unknown"] ?? "neutral"
    case "flexibility":
    case "compat":
    case "rate":
      return "neutral"
  }
}

export type ScoreAdjustment = { delta: number; reason: string }

/** Полная форма score_breakdown — шесть осей основного трека или пять второго. */
export function isPrimaryScoreBreakdown(
  breakdown: unknown,
): breakdown is Record<PrimaryScoreBreakdownKey, number> {
  if (!breakdown || typeof breakdown !== "object") return false
  const b = breakdown as Record<string, unknown>
  return SCORE_BREAKDOWN_KEYS.every((k) => typeof b[k] === "number")
}

export function isSecondJobScoreBreakdown(
  breakdown: unknown,
): breakdown is Record<SecondJobScoreBreakdownKey, number> {
  if (!breakdown || typeof breakdown !== "object") return false
  const b = breakdown as Record<string, unknown>
  return SECOND_JOB_SCORE_BREAKDOWN_KEYS.every((k) => typeof b[k] === "number")
}

export function isScoreBreakdownComplete(
  breakdown: unknown,
): breakdown is Record<string, number> {
  return isPrimaryScoreBreakdown(breakdown) || isSecondJobScoreBreakdown(breakdown)
}

export function fractionTone(value: number, max: number): CriterionTone {
  if (!(max > 0)) return "neutral"
  const f = value / max
  if (f >= 0.7) return "good"
  if (f >= 0.4) return "mid"
  return "bad"
}

/** Тултип калибровки: «+N: причина; …» — единый формат панели и дровера (U-06). */
export function scoreCalibrationAdjustmentsTitle(
  adjustments?: ScoreAdjustment[] | null,
): string {
  if (!adjustments?.length) return ""
  return adjustments
    .map((a) => `${a.delta > 0 ? "+" : ""}${a.delta}: ${a.reason}`)
    .join("; ")
}
