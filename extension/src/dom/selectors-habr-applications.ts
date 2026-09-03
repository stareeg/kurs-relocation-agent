/**
 * S13: парсинг «Ваши отклики» career.habr.com (`/profile/responses`).
 * Список откликов подгружается клиентским API `/api/frontend/responses` — в SSR-JSON его нет
 * (там только `hhImport`), поэтому данные приходят перехватом XHR/fetch из адаптера
 * (`content/habr-applications.ts`), а здесь — только чистые функции над уже распарсенным JSON.
 *
 * Аналог `selectors-getmatch-applications.ts`, но источник — JSON-ответ API, а не DOM.
 */

import {
  isStaleInteraction,
  normalizeGetmatchAppliedAt,
  STALE_INTERACTION_DAYS,
} from './selectors-getmatch-applications'

const FUNNEL_APPLIED = 'Отклик'
const FUNNEL_REJECTED = 'Отказ'
const FUNNEL_SCREENING = 'Скрининг'

export type HabrApplicationStatus =
  | 'new'
  | 'viewed'
  | 'invitation'
  | 'rejected'
  | 'archived'
  | 'unknown'

export type ParsedHabrApplication = {
  vacancy_id: string
  title: string
  company: string
  url: string
  /** Сырой статус Хабр (текст/токен из JSON) — для дебага и hh_status_raw. */
  habr_status_raw: string
  habr_status: HabrApplicationStatus
  is_archived: boolean
  is_stale: boolean
  skip_stage_update: boolean
  applied_at: string | null
  employer_viewed: boolean | null
  hh_status_raw: string
  hh_status: string
  funnel_status_preview: string
  needs_interview_tracking: boolean
  sync_state?: string
  is_discrepancy?: boolean
  current_status?: string | null
  needs_vacancy_text?: boolean
}

const HABR_VACANCY_ID_PREFIX = 'habr_'

/** Вытащить числовой id вакансии из поля/ссылки; на выходе `habr_{numeric}` или null. */
function extractHabrVacancyIdFromValue(raw: unknown): string | null {
  if (raw == null) return null
  if (typeof raw === 'number' && Number.isFinite(raw)) {
    return `${HABR_VACANCY_ID_PREFIX}${Math.trunc(raw)}`
  }
  const s = String(raw)
  const m = s.match(/\/vacancies\/(\d+)/)
  if (m) return `${HABR_VACANCY_ID_PREFIX}${m[1]}`
  if (/^\d+$/.test(s.trim())) return `${HABR_VACANCY_ID_PREFIX}${s.trim()}`
  return null
}

function str(raw: unknown): string {
  if (raw == null) return ''
  if (typeof raw === 'string') return raw.replace(/\s+/g, ' ').trim()
  if (typeof raw === 'number' || typeof raw === 'boolean') return String(raw)
  return ''
}

/** Список откликов из payload `/api/frontend/responses` (поддерживает `list`/`objects`/
 *  `responses`, либо сам payload — массив). */
export function habrResponsesList(payload: unknown): unknown[] {
  if (Array.isArray(payload)) return payload
  if (payload && typeof payload === 'object') {
    const obj = payload as Record<string, unknown>
    for (const key of ['list', 'objects', 'responses', 'items']) {
      if (Array.isArray(obj[key])) return obj[key] as unknown[]
    }
    // Иногда обёртка: { responses: { list: [...] } } или { data: { list: [...] } }
    const nested = obj.responses ?? obj.data
    if (nested && typeof nested === 'object' && !Array.isArray(nested)) {
      const inner = habrResponsesList(nested)
      if (inner.length) return inner
    }
  }
  return []
}

/** Вакансия из элемента отклика: либо поле `vacancy`, либо сам элемент (если он «вакансийный»). */
function vacancyOf(item: Record<string, unknown>): Record<string, unknown> | null {
  const vac = item.vacancy
  if (vac && typeof vac === 'object' && !Array.isArray(vac)) {
    return vac as Record<string, unknown>
  }
  // Фолбэк: сам элемент несёт title + (id|href) — значит это и есть карточка вакансии.
  if (item.title || item.id || item.href) return item
  return null
}

function companyOf(vac: Record<string, unknown>): string {
  const c = vac.company
  if (c && typeof c === 'object' && !Array.isArray(c)) {
    const title = str((c as Record<string, unknown>).title)
    if (title) return title
  }
  if (str(vac.companyTitle)) return str(vac.companyTitle)
  if (str(vac.company_name)) return str(vac.company_name)
  return ''
}

function urlOf(vac: Record<string, unknown>, vacancyId: string | null): string {
  const href = str(vac.href) || str(vac.url)
  if (href) {
    try {
      return new URL(href, 'https://career.habr.com').href.split('?')[0]
    } catch {
      return href.split('?')[0]
    }
  }
  const numeric = vacancyId?.replace(HABR_VACANCY_ID_PREFIX, '')
  return numeric ? `https://career.habr.com/vacancies/${numeric}` : ''
}

/** Нормализованный статус Хабр → один из токенов. Порядок важен (отказ раньше «просмотрен»). */
export function normalizeHabrStatus(
  raw: unknown,
  archived: boolean,
): HabrApplicationStatus {
  if (archived) return 'archived'
  const t = str(raw).toLowerCase()
  if (!t) return 'unknown'
  if (/отказ|отклон|отказано|rejected|discard|declined/.test(t)) return 'rejected'
  if (/приглаш|invitation|собеседов|interview|интервью|оффер|offer|hired/.test(t)) {
    return 'invitation'
  }
  if (/просмотр|viewed|в\s+работе|рассматр|consider/.test(t)) return 'viewed'
  if (/нов|new|отклик|отправл|не\s+просмотрен|not\s*\.?\s*viewed/.test(t)) return 'new'
  if (/архив|archived/.test(t)) return 'archived'
  return 'unknown'
}

/** Хабр-статус → hh_status + воронка (бэкенд negotiations-sync принимает те же значения). */
export function mapHabrStatusToFunnel(
  habrStatus: HabrApplicationStatus,
  isArchived: boolean,
): {
  funnel_status_preview: string
  hh_status: string
  skip_stage_update: boolean
  employer_viewed: boolean | null
  needs_interview_tracking: boolean
} {
  if (habrStatus === 'rejected') {
    return {
      funnel_status_preview: FUNNEL_REJECTED,
      hh_status: 'rejected',
      skip_stage_update: false,
      employer_viewed: true,
      needs_interview_tracking: false,
    }
  }
  if (habrStatus === 'invitation') {
    return {
      funnel_status_preview: FUNNEL_SCREENING,
      hh_status: 'invitation',
      skip_stage_update: false,
      employer_viewed: true,
      needs_interview_tracking: false,
    }
  }
  if (habrStatus === 'viewed') {
    return {
      funnel_status_preview: FUNNEL_APPLIED,
      hh_status: 'viewed_by_employer',
      skip_stage_update: false,
      employer_viewed: true,
      needs_interview_tracking: false,
    }
  }
  if (habrStatus === 'archived') {
    // «в архиве»/«вакансия снята» — как у getmatch: не отказ, а минимальный «Отклик» + пропуск
    // обновления стадии (воронку не трогаем). Отказ даёт только явный статус или stale > 90 дней.
    return {
      funnel_status_preview: FUNNEL_APPLIED,
      hh_status: 'unknown',
      skip_stage_update: true,
      employer_viewed: null,
      needs_interview_tracking: false,
    }
  }
  // new / unknown — минимум «Отклик».
  return {
    funnel_status_preview: FUNNEL_APPLIED,
    hh_status: habrStatus === 'new' ? 'not_viewed_by_employer' : 'unknown',
    skip_stage_update: isArchived,
    employer_viewed: habrStatus === 'new' ? false : null,
    needs_interview_tracking: false,
  }
}

export function habrStatusDisplayLabel(status: HabrApplicationStatus): string {
  if (status === 'new') return 'Новый'
  if (status === 'viewed') return 'Просмотрен'
  if (status === 'invitation') return 'Приглашение'
  if (status === 'rejected') return 'Отказ'
  if (status === 'archived') return 'В архиве'
  return 'Неизвестно'
}

export function parseHabrApplicationItem(item: unknown): ParsedHabrApplication | null {
  if (!item || typeof item !== 'object' || Array.isArray(item)) return null
  const obj = item as Record<string, unknown>

  const vac = vacancyOf(obj)
  const vacancyId = extractHabrVacancyIdFromValue(
    vac?.id ?? vac?.vacancy_id ?? vac?.href ?? obj.vacancy_id ?? obj.id,
  )
  if (!vacancyId) return null

  const archived = Boolean(obj.archived === true || obj.is_archived === true)
  const rawStatus = obj.status ?? obj.state ?? obj.response_status ?? (archived ? 'archived' : '')
  const habrStatus = normalizeHabrStatus(rawStatus, archived)

  const title = str(vac?.title ?? obj.title)
  const company = companyOf(vac ?? obj)
  const url = urlOf(vac ?? obj, vacancyId)
  const appliedAtRaw = obj.publishedAt ?? obj.published_at ?? obj.createdAt ?? obj.created_at
  const applied_at = normalizeGetmatchAppliedAt(appliedAtRaw ? str(appliedAtRaw) : null)
  const is_stale = isStaleInteraction(applied_at, STALE_INTERACTION_DAYS)

  const mapped = mapHabrStatusToFunnel(habrStatus, archived)

  const habr_status_raw = [str(rawStatus), archived ? 'в архиве' : ''].filter(Boolean).join(' · ')

  // Если отклик старше порога — уводим в «Отказ», как у getmatch.
  if (is_stale) {
    return {
      vacancy_id: vacancyId,
      title,
      company,
      url,
      habr_status_raw: habr_status_raw || habrStatusDisplayLabel(habrStatus),
      habr_status: habrStatus,
      is_archived: true,
      is_stale: true,
      applied_at,
      funnel_status_preview: FUNNEL_REJECTED,
      hh_status: 'unknown',
      hh_status_raw: habr_status_raw,
      skip_stage_update: false,
      employer_viewed: mapped.employer_viewed,
      needs_interview_tracking: false,
    }
  }

  return {
    vacancy_id: vacancyId,
    title,
    company,
    url,
    habr_status_raw,
    habr_status: habrStatus,
    is_archived: archived,
    is_stale: false,
    applied_at,
    hh_status_raw: habr_status_raw,
    ...mapped,
  }
}

export function parseHabrResponsesFromJson(
  payload: unknown,
): ParsedHabrApplication[] {
  const byId = new Map<string, ParsedHabrApplication>()
  for (const item of habrResponsesList(payload)) {
    const parsed = parseHabrApplicationItem(item)
    if (parsed) byId.set(parsed.vacancy_id, parsed)
  }
  return Array.from(byId.values())
}

/** Ключ страницы для SPA-навигации (pathname + query — фильтры Хабр). */
export function habrResponsesPageKey(url = location.href): string {
  try {
    const u = new URL(String(url), 'https://career.habr.com')
    return `${u.pathname}|${u.search}`
  } catch {
    return `${String(url).split('#')[0]}|search=`
  }
}

/** Отпечаток списка откликов — не дёргаем preview, пока JSON не изменился. */
export function habrResponsesFingerprint(payload: unknown): string {
  const parts: string[] = [habrResponsesPageKey()]
  for (const item of habrResponsesList(payload)) {
    const obj = item as Record<string, unknown> | null
    if (!obj) continue
    const vac = vacancyOf(obj)
    const id = extractHabrVacancyIdFromValue(vac?.id ?? vac?.href ?? obj.id ?? obj.href) || ''
    const status = normalizeHabrStatus(obj.status ?? obj.state, Boolean(obj.archived))
    parts.push(`${id}|${status}`)
  }
  return parts.join(';')
}
