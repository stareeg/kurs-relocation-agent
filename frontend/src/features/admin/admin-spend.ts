/**
 * График расхода: ответ `/spend` → вход CategoryBars / stacked-столбики.
 *
 * Столбик «сегодня» обязан сходиться с KPI: это проверяет бэкенд-тест, здесь только
 * подписи оси. День — короткая дата, модель — короткий slug, фича — короткое русское имя.
 */
import type { AdminSpendRow } from "@/api/admin"
import { msLabel, pctLabel, usd } from "@/features/admin/admin-format"
import { formatDayShort, type CategoryBarsInput } from "@/features/market/charts"

/** Фичи дешевле порога не рисуем в таблице и на столбиках — шум, не сигнал. */
export const FEATURE_MIN_USD = 0.05

/**
 * Короткие русские имена LLM-фич. Ключ — `LlmFeature.name` из реестра.
 * Нет в словаре — режем длинный ключ, не показываем сырой snake_case целиком.
 */
export const FEATURE_LABELS: Record<string, string> = {
  "без фичи": "без фичи",
  job_search: "Скоринг вакансии",
  salary_estimate: "Оценка зарплаты",
  remote_feasibility: "Формат работы",
  company_normalize: "Имя компании",
  skip_reason_backfill: "Причина пропуска",
  skip_reasons_gen: "Причины пропуска",
  vacancy_skill_requirements: "Навыки вакансии",
  vacancy_text_format: "Текст вакансии",
  vacancy_work_terms: "Условия работы",
  screening_brief: "Бриф скрининга",
  screening_pitch: "Питч",
  screening_questions: "Вопросы скрининга",
  prep: "Подготовка",
  prep_pack: "Пакет к техничке",
  debrief: "Разбор собеса",
  debrief_resolution: "Итог разбора",
  next_stage_hint: "Следующий этап",
  qa: "Вопрос по вакансии",
  question_match: "Тема вопроса",
  competency_canon: "Компетенции",
  screening_chat_summary: "Сводка скрининга",
  prep_topic_expand: "Раскрытие темы",
  cover_letter: "Сопроводительное",
  hr_direction: "Направление HR",
  hr_parse: "Разбор HR",
  hr_segment: "Нарезка HR",
  event_extract: "События из HR",
  funnel: "Воронка",
  stage_type: "Тип этапа",
  channel_vacancy_parse: "Разбор вакансии",
  hr_facts: "Факты из HR",
  hr_import: "Импорт HR",
  archive_disposition: "Архив",
  anketa_answer: "Анкеты",
  chat: "Чат",
  qa_vacancy: "Чат по вакансии",
  resume_gap_chat: "Чат по резюме",
  hr_draft_chat: "Черновик HR",
  chat_followups: "Подсказки чата",
  attachment_read: "Разбор вложения",
  admin_support: "Агент поддержки",
  resume_parse_pdf: "PDF резюме",
  resume_strengthen: "Усиление резюме",
  resume_strengthen_critic: "Критика резюме",
  resume_role_fit: "Попадание в роль",
  weak_bullets: "Слабые буллеты",
  resume_search_profile_suggest: "Критерии поиска",
  resume_skill_suggest: "Навыки резюме",
  intl_experience: "Международный опыт",
  offer_parse: "Разбор оффера",
  offer_compare: "Сравнение офферов",
  offer_negotiation: "Торг по офферу",
  offer_bonus_estimate: "Бонусы оффера",
  offers_chat: "Чат по офферам",
  situation: "Ситуация на рынке",
  market_chat: "Чат по рынку",
  salary_extract: "Суммы из текста",
}

/**
 * Имена фоновых задач очереди (раздел «Действия»). LLM-фичи берутся из FEATURE_LABELS;
 * здесь — cron/воркер-kinds без отдельной LLM-фичи.
 */
export const TASK_KIND_LABELS: Record<string, string> = {
  ...FEATURE_LABELS,
  situation_refresh: "Обновление ситуации",
  market_snapshot_refresh: "Снимок рынка",
  tg_push: "Пуш в Telegram",
  tg_cleanup: "Очистка Telegram",
  admin_message: "Сообщение админа",
  key_request: "Заявка на ключ",
  attachments_gc: "Уборка вложений",
  empty_stub_purge: "Уборка пустых заглушек",
  opportunities_coverage_metrics: "Покрытие вакансий",
  rescore_weights_version: "Пересчёт весов",
  skip_reasons: "Причины пропуска",
  cover_letter_pregen: "Сопроводительное заранее",
  attachment_read: "Разбор вложения",
}

/** Понятное русское имя kind очереди; неизвестный — коротко, без snake_case целиком. */
export function taskKindLabel(kind: string): string {
  const key = kind.trim()
  if (!key) return "—"
  return TASK_KIND_LABELS[key] ?? clipLabel(key.replaceAll("_", " "))
}

export function spendBarsInput(rows: readonly AdminSpendRow[]): CategoryBarsInput {
  return {
    rows: rows.map((row) => ({
      key: row.key,
      label: spendRowLabel(row.key),
      value: row.cost_usd,
    })),
    unit: "$",
    emptyLabel: "Нет трат",
  }
}

/**
 * Подпись строки разреза: день — короткой датой, фича — по словарю, модель — ключом.
 *
 * Охранник намеренно шире, чем «ровно ISO-день»: бэкенд до Этапа 1 отдавал `g.day::text` от
 * `generate_series`, то есть «2026-08-12 00:00:00+00», ключ не совпадал с `^\d{4}-\d{2}-\d{2}$`
 * и печатался сырым — повёрнутый на 45° таймстемп поверх заголовка таблицы. Каст на бэкенде
 * починен, но в `llm_result_cache` и в открытых вкладках старые ответы ещё живут, а через
 * полгода никто не вспомнит, почему подпись развалилась. Поэтому день узнаётся по началу
 * строки, а не по всей.
 */
export function spendRowLabel(key: string): string {
  const day = isoDayPrefix(key)
  if (day) return formatDayShort(day)
  const feature = FEATURE_LABELS[key]
  if (feature) return feature
  return clipLabel(shortModelSlug(key))
}

export function shortModelSlug(slug: string): string {
  const trimmed = slug.trim()
  if (!trimmed) return "—"
  const slash = trimmed.lastIndexOf("/")
  return slash >= 0 ? trimmed.slice(slash + 1) : trimmed
}

/** «2026-08-12» из ключа-дня в любом виде: и голый день, и день с временем/зоной. */
function isoDayPrefix(value: string): string | null {
  const match = /^(\d{4}-\d{2}-\d{2})(?:[T ]|$)/.exec(value)
  return match ? match[1] : null
}

function clipLabel(value: string): string {
  return value.length > 22 ? `${value.slice(0, 20)}…` : value
}

export function cacheHitLabel(rate: number | null | undefined, calls: number): string {
  if (rate == null || calls <= 0) return "кэш: нет вызовов"
  return `кэш ${Math.round(rate * 100)}%`
}

export function latencyLabel(
  medianMs: number | null | undefined,
  p95Ms: number | null | undefined,
): string {
  if (medianMs == null && p95Ms == null) return "latency: нет замеров"
  return `p50 ${msLabel(medianMs)} · p95 ${msLabel(p95Ms)}`
}

export function retryLabel(share: number | null | undefined): string {
  if (share == null) return "повторы: нет вызовов"
  return `повторы ${pctLabel(share)}`
}

export function spendTooltipLines(
  row: AdminSpendRow | undefined,
  barLabel: string,
): { label?: string; value: string }[] {
  const lines = [{ label: barLabel, value: usd(row?.cost_usd ?? 0) }]
  if (!row || row.calls <= 0) return lines
  lines.push({ label: "кэш", value: pctLabel(row.cache_hit_rate) })
  lines.push({ label: "p50", value: msLabel(row.median_ms) })
  lines.push({ label: "p95", value: msLabel(row.p95_ms) })
  lines.push({ label: "повторы", value: pctLabel(row.retry_share) })
  if (row.segments && row.segments.length > 1) {
    for (const segment of row.segments) {
      lines.push({ label: shortModelSlug(segment.key), value: usd(segment.cost_usd) })
    }
  }
  return lines
}

export function findSpendRow(
  rows: readonly AdminSpendRow[],
  key: string,
): AdminSpendRow | undefined {
  return rows.find((row) => row.key === key)
}

/**
 * Дневной разрез: последняя дата сверху в таблице и слева на графике.
 * Другие разрезы не трогаем — там порядок по деньгам.
 */
export function orderSpendRows(
  rows: readonly AdminSpendRow[],
  groupBy: string,
): AdminSpendRow[] {
  if (groupBy !== "day") return [...rows]
  return [...rows].sort((a, b) => (a.key < b.key ? 1 : a.key > b.key ? -1 : 0))
}

/** Для разреза «по фичам» прячем мелочь дешевле 5¢ — в итогах шапки она всё равно есть. */
export function visibleSpendRows(
  rows: readonly AdminSpendRow[],
  groupBy: string,
): AdminSpendRow[] {
  if (groupBy !== "feature") return [...rows]
  return rows.filter((row) => row.cost_usd >= FEATURE_MIN_USD)
}

export function spendModelKeys(rows: readonly AdminSpendRow[]): string[] {
  const totals = new Map<string, number>()
  for (const row of rows) {
    for (const segment of row.segments ?? []) {
      totals.set(segment.key, (totals.get(segment.key) ?? 0) + segment.cost_usd)
    }
  }
  return [...totals.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([key]) => key)
}

export function filterSpendByModel(
  rows: readonly AdminSpendRow[],
  model: string,
): AdminSpendRow[] {
  if (!model || model === "all") return [...rows]
  return rows.map((row) => {
    const segment = (row.segments ?? []).find((item) => item.key === model)
    return {
      ...row,
      cost_usd: segment?.cost_usd ?? 0,
      calls: segment?.calls ?? 0,
      segments: segment ? [segment] : [],
    }
  })
}
