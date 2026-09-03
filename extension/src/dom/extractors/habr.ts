/**
 * Хабр Карьера: VacancyExtractor для career.habr.com.
 * Primary источник — SSR-JSON в <script type="application/json" data-ssr-state="true">.
 * Fallback — JSON-LD (<script type="application/ld+json">).
 *
 * См. plans/habr_integration_plan.md — Шаг 1 (расширение) и контекст разбора HTML.
 */

import { HABR_PAGE_TYPE } from '../site-router'
import type { ParsedVacancy, ScorePayload, VacancyExtractor } from './types'

const HABR_VACANCY_ID_PREFIX = 'habr_'

/** Primary SSR-JSON: <script type="application/json" data-ssr-state="true">...</script> */
const SSR_RE = /<script[^>]*type="application\/json"[^>]*data-ssr-state="true"[^>]*>([\s\S]*?)<\/script>/i

/** Fallback: JSON-LD JobPosting */
const JSON_LD_RE = /<script[^>]*type="application\/ld\+json"[^>]*>([\s\S]*?)<\/script>/i

/** Описание вакансии — article внутри main или section описания */
const DESCRIPTION_SELECTORS = [
  'article.vacancy-card',
  '.vacancy-card',
  '[class*="vacancy-card"]',
  '.vacancy-description',
  '[class*="vacancy-description"]',
  'main article',
  'main .article-style',
  'main .basic-section--appearance-vacancy-description',
  '.basic-section--appearance-vacancy-description',
]

/** Селекторы описания для VacancyWaitHints (waitForVacancyDomReady). */
const DESCRIPTION_HINT_SELECTORS = [
  'article',
  '.vacancy-card',
  '[class*="vacancy-card"]',
  '.vacancy-description',
  'main',
]

function normalizeText(raw: string): string {
  return (raw || '')
    .replace(/[\u200B-\u200D\uFEFF]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

function htmlToPlainText(el: Element): string {
  const clone = el.cloneNode(true) as Element
  clone
    .querySelectorAll(
      'button, nav, [class*="header"], [class*="toolbar"], [class*="share"], script, style, noscript',
    )
    .forEach((node) => node.remove())
  return normalizeText(clone.textContent || '')
}

function stripHtml(html: string): string {
  return normalizeText(html.replace(/<[^>]+>/g, ' '))
}

// ── SSR-JSON: primary парсер ──

interface HabrSsrVacancy {
  id?: number
  title?: string
  remoteWork?: boolean
  employment?: string
  qualification?: string | null
  salary?: {
    from?: number | null
    to?: number | null
    currency?: string
    formatted?: string
  } | null
  skills?: { title?: string }[]
  divisions?: { title?: string }[]
  locations?: { title?: string }[]
  humanCityNames?: string
  shortGeo?: string
  publishedDate?: {
    date?: string
    title?: string
  } | null
  description?: string
  company?: {
    title?: string
    href?: string
  } | null
}

interface HabrSsrState {
  vacancy?: HabrSsrVacancy
  vacancies?: {
    list?: unknown[]
    meta?: { totalResults?: number; perPage?: number; currentPage?: number; totalPages?: number }
  }
}

/**
 * Извлечь SSR-JSON из HTML страницы career.habr.com.
 * Возвращает распарсенный объект или null.
 */
function extractSsrJson(html: string): HabrSsrState | null {
  const match = SSR_RE.exec(html)
  if (!match || !match[1]) return null
  try {
    const data = JSON.parse(match[1]) as Record<string, unknown>
    // Структура может быть как {vacancy: {...}} так и обёрнутой
    if (data.vacancy) return data as unknown as HabrSsrState
    if (data.vacancies) return data as unknown as HabrSsrState
    return null
  } catch {
    return null
  }
}

/**
 * Извлечь JSON-LD (JobPosting) из HTML — fallback.
 */
function extractJsonLd(html: string): Record<string, unknown> | null {
  const match = JSON_LD_RE.exec(html)
  if (!match || !match[1]) return null
  try {
    const data = JSON.parse(match[1]) as Record<string, unknown>
    if (data['@type'] === 'JobPosting') return data
    // Может быть массив
    if (Array.isArray(data)) {
      for (const item of data) {
        if (typeof item === 'object' && item !== null && item['@type'] === 'JobPosting') {
          return item as Record<string, unknown>
        }
      }
    }
    return null
  } catch {
    return null
  }
}

// ── Извлечение ID ──

/** Числовой ID вакансии из URL: /vacancies/{id} → "habr_{id}" */
export function extractHabrVacancyIdFromUrl(url = location.href): string | null {
  const m = String(url || '').match(/\/vacancies\/(\d+)/)
  return m ? `${HABR_VACANCY_ID_PREFIX}${m[1]}` : null
}

function extractHabrVacancyIdFromSsr(ssr: HabrSsrState | null): string | null {
  if (ssr?.vacancy?.id) return `${HABR_VACANCY_ID_PREFIX}${ssr.vacancy.id}`
  return null
}

// ── Парсинг вакансии из SSR-JSON ──

function parseSsrToVacancy(ssr: HabrSsrState, url: string): ParsedVacancy | null {
  const vac = ssr.vacancy
  if (!vac) return null

  const title = normalizeText(vac.title || '')
  const company = normalizeText(vac.company?.title || '')
  const salary = normalizeText(vac.salary?.formatted || '')

  const skills = (vac.skills || [])
    .map((s) => normalizeText(s.title || ''))
    .filter(Boolean)
  const qualification = normalizeText(vac.qualification || '') || null
  const salaryCurrency = normalizeText(vac.salary?.currency || 'rur') || null

  // Локация
  const locations = (vac.locations || []).map((l) => normalizeText(l.title || '')).filter(Boolean)
  const area = vac.humanCityNames || vac.shortGeo || locations.join(', ') || ''

  // Формат работы: remoteWork → удалённо/офис
  let workFormat = ''
  if (vac.remoteWork === true) {
    workFormat = 'удалённо'
  } else if (vac.remoteWork === false) {
    workFormat = 'офис'
  }

  // Специализации
  const divisions = (vac.divisions || [])
    .map((d) => normalizeText(d.title || ''))
    .filter(Boolean)

  // Дата публикации
  let publishedAt: string | null = null
  if (vac.publishedDate?.date) {
    publishedAt = vac.publishedDate.date
  }

  // Описание: HTML → plain text
  const description = stripHtml(vac.description || '')

  // Сборка текста для LLM
  const parts: string[] = []
  if (title) parts.push(title)
  if (company) parts.push(`Компания: ${company}`)
  if (salary) parts.push(`Зарплата: ${salary}`)
  if (area) parts.push(`Локация: ${area}`)
  if (workFormat) parts.push(`Формат работы: ${workFormat}`)
  if (skills.length) {
    parts.push(`Навыки: ${skills.join(', ')}`)
  }
  if (qualification) {
    parts.push(`Квалификация: ${qualification}`)
  }
  if (divisions.length) {
    parts.push(`Специализации: ${divisions.join(', ')}`)
  }
  if (description) {
    parts.push('')
    parts.push(description)
  }

  return {
    title,
    company,
    salary,
    work_format: workFormat,
    area,
    description,
    published_at: publishedAt,
    skills,
    qualification,
    salary_currency: salaryCurrency,
    text: parts.join('\n').trim(),
    url,
    vacancy_id: extractHabrVacancyIdFromSsr(ssr),
    page_type: HABR_PAGE_TYPE.VACANCY,
    source: 'habr',
  }
}

// ── Fallback: парсинг из JSON-LD ──

function parseJsonLdToVacancy(jsonLd: Record<string, unknown>, url: string): ParsedVacancy | null {
  const title = normalizeText(String(jsonLd.title || ''))
  const company = jsonLd.hiringOrganization
    ? normalizeText(
        String(
          (jsonLd.hiringOrganization as Record<string, unknown>).name ||
            (jsonLd.hiringOrganization as Record<string, unknown>).title ||
            jsonLd.hiringOrganization ||
            '',
        ),
      )
    : ''

  // baseSalary может быть {currency, value: {minValue, maxValue, unitText}}
  let salary = ''
  if (jsonLd.baseSalary) {
    const bs = jsonLd.baseSalary as Record<string, unknown>
    const currency = String(bs.currency || '')
    const value = bs.value as Record<string, unknown> | undefined
    if (value) {
      const minV = value.minValue != null ? String(value.minValue) : ''
      const maxV = value.maxValue != null ? String(value.maxValue) : ''
      if (minV && maxV) {
        salary = `${minV}—${maxV} ${currency}`
      } else if (minV) {
        salary = `от ${minV} ${currency}`
      } else if (maxV) {
        salary = `до ${maxV} ${currency}`
      }
    }
    salary = normalizeText(salary)
  }

  const descRaw = String(jsonLd.description || '')
  const description = stripHtml(descRaw)

  // ID из identifier или url
  let vacancyId: string | null = null
  if (jsonLd.identifier) {
    const id = String(jsonLd.identifier)
    if (/^\d+$/.test(id)) vacancyId = `${HABR_VACANCY_ID_PREFIX}${id}`
  }
  if (!vacancyId) {
    vacancyId = extractHabrVacancyIdFromUrl(url)
  }

  const parts: string[] = []
  if (title) parts.push(title)
  if (company) parts.push(`Компания: ${company}`)
  if (salary) parts.push(`Зарплата: ${salary}`)
  if (description) {
    parts.push('')
    parts.push(description)
  }

  return {
    title,
    company,
    salary,
    description,
    text: parts.join('\n').trim(),
    url,
    vacancy_id: vacancyId,
    page_type: HABR_PAGE_TYPE.VACANCY,
    source: 'habr',
  }
}

// ── DOM-парсинг как фолбэк (когда нет SSR-JSON и JSON-LD) ──

function parseFromDom(url: string): ParsedVacancy {
  const root = document
  const title =
    normalizeText(
      root.querySelector('h1')?.textContent || root.querySelector('[class*="title"]')?.textContent || '',
    ) || ''
  const vacancyId = extractHabrVacancyIdFromUrl(url)
  const company = normalizeText(
    root.querySelector('[class*="company"] a')?.textContent ||
      root.querySelector('[class*="company"]')?.textContent ||
      root.querySelector('a[href*="/companies/"]')?.textContent ||
      '',
  )

  let description = ''
  for (const sel of DESCRIPTION_SELECTORS) {
    const el = root.querySelector(sel)
    if (el) {
      description = htmlToPlainText(el)
      if (description.length >= 80) break
    }
  }

  const parts: string[] = []
  if (title) parts.push(title)
  if (company) parts.push(`Компания: ${company}`)
  if (description) parts.push(description)

  return {
    title,
    company,
    salary: '',
    description,
    text: parts.join('\n').trim(),
    url,
    vacancy_id: vacancyId,
    page_type: HABR_PAGE_TYPE.VACANCY,
    source: 'habr',
  }
}

// ── Main: parseHabrVacancyFromDom (primary: SSR → JSON-LD → DOM) ──

export function parseHabrVacancyFromDom(url = location.href): ParsedVacancy {
  // Доступ к document только в браузере — в тестах globalThis.document подменяется
  const html =
    typeof document !== 'undefined'
      ? document.documentElement?.outerHTML || document.body?.innerHTML || ''
      : ''

  // 1. Primary: SSR-JSON
  const ssr = html ? extractSsrJson(html) : null
  if (ssr?.vacancy) {
    const parsed = parseSsrToVacancy(ssr, url)
    if (parsed) return parsed
  }

  // 2. Fallback: JSON-LD
  if (html) {
    const jsonLd = extractJsonLd(html)
    if (jsonLd) {
      const parsed = parseJsonLdToVacancy(jsonLd, url)
      if (parsed) return parsed
    }
  }

  // 3. DOM fallback (последний шанс)
  return parseFromDom(url)
}

// ── Листинг (discovery, Фаза D редизайна «Расширения») ──
// Живая разведка (Playwright, 2026-08-19, залогинен): career.habr.com/vacancies[?...фильтры]
// рендерит тот же SSR-JSON, что и страница вакансии, только ключ `vacancies` вместо `vacancy`:
// `vacancies.list[]` (готовые карточки — id/href/title/company) + `vacancies.meta`
// (currentPage/totalPages). Пагинация — обычный `?page=N` поверх текущего URL (сохраняя прочие
// query-параметры фильтров), без клиентского state — проще, чем у getmatch, как у hh.

export interface HabrListingCard {
  vacancy_id: string
  url: string
  title: string
  company?: string
}

export interface HabrListingResult {
  cards: HabrListingCard[]
  nextPageUrl: string | null
}

export function parseHabrListingFromDom(url = location.href): HabrListingResult {
  const html =
    typeof document !== 'undefined'
      ? document.documentElement?.outerHTML || document.body?.innerHTML || ''
      : ''
  const ssr = html ? extractSsrJson(html) : null
  const list = ssr?.vacancies?.list
  if (!Array.isArray(list)) return { cards: [], nextPageUrl: null }

  const cards: HabrListingCard[] = []
  for (const raw of list) {
    const v = raw as { id?: number; href?: string; title?: string; company?: { title?: string } }
    if (!v.id || !v.href) continue
    const company = normalizeText(v.company?.title || '')
    cards.push({
      vacancy_id: `${HABR_VACANCY_ID_PREFIX}${v.id}`,
      url: `https://career.habr.com${v.href}`,
      title: normalizeText(v.title || ''),
      company: company || undefined,
    })
  }

  const meta = ssr?.vacancies?.meta
  let nextPageUrl: string | null = null
  if (meta && typeof meta.currentPage === 'number' && typeof meta.totalPages === 'number') {
    if (meta.currentPage < meta.totalPages) {
      try {
        const next = new URL(url)
        next.searchParams.set('page', String(meta.currentPage + 1))
        nextPageUrl = next.toString()
      } catch {
        nextPageUrl = null
      }
    }
  }

  return { cards, nextPageUrl }
}

// ── ScorePayload ──

function buildScorePayload(parsed: ParsedVacancy): ScorePayload {
  return {
    text: parsed.text,
    url: parsed.url,
    vacancy_id: parsed.vacancy_id,
    title: parsed.title,
    company: parsed.company,
    salary_text: parsed.salary,
    area: parsed.area || null,
    work_format: parsed.work_format || null,
    work_schedule: parsed.work_schedule || null,
    total_responses: parsed.total_responses_count ?? null,
    letter_required: parsed.letter_required ?? null,
    published_at: parsed.published_at || null,
    employer_id: parsed.employer_id || null,
    skills: parsed.skills,
    qualification: parsed.qualification ?? null,
    salary_currency: parsed.salary_currency ?? null,
    employment_type: parsed.employment_type ?? null,
    location_raw: parsed.location_raw || parsed.area || null,
    remote_type: parsed.remote_type ?? null,
    source: 'habr',
    is_archived: Boolean(parsed.is_archived),
  }
}

// ── VacancyExtractor ──

export const habrVacancyExtractor: VacancyExtractor = {
  site: 'habr',
  descriptionSelectors: DESCRIPTION_HINT_SELECTORS,
  parseVacancyFromDom: parseHabrVacancyFromDom,
  extractVacancyId: extractHabrVacancyIdFromUrl,
  buildScorePayload,
  // Хабр Карьера не показывает число откликов кандидату (аналогично getmatch)
  supportsResponsesCount: false,
}

export { HABR_VACANCY_ID_PREFIX }