/**
 * GM-5: парсинг карточки вакансии getmatch.ru (`/vacancies/{id}-{slug}`).
 * DOM-референс: plans/MWS.html (b-vacancy-v2, 2026-07).
 */

import {
  getRuntimeConfig,
  getParseSelector,
  matchesTextSignal,
} from './extension-runtime-config'
import { GETMATCH_PAGE_TYPE } from './site-router'
import { parseGetmatchVacancyFromJsonLd } from './selectors-getmatch-jsonld'
import { isRscAvailable, parseGetmatchVacancyFromRsc } from './selectors-getmatch-rsc'

const GM_VACANCY_ID_PREFIX = 'gm_'

// Зашитые дефолты; актуальные значения — из рантайм-конфига расширения
// (`parse_selectors.getmatch` / `text_signals.getmatch`), чтобы правка селектора или
// формулировки на getmatch.ru не требовала переустановки zip. Намеренный дубль с
// `core/domains/opportunities/sources/extension_runtime_config.json`.
const GETMATCH_SELECTORS_DEFAULT: Record<string, string> = {
  header: 'section.b-vacancy-header, .b-vacancy-header',
  title: 'section.b-vacancy-header h1, .b-vacancy-header h1, [class*="vacancy__title"], h1[class*="vacancy"]',
  companyLink: 'section.b-vacancy-header a[href*="/companies/"], .b-vacancy-header a[href*="/companies/"], a[href*="/companies/"]',
  salary: 'section.b-vacancy-header h3, .b-vacancy-header h3, [class*="vacancy__salary"]',
  locations: 'section.b-location .b-vacancy-locations, .b-vacancy-locations, [class*="vacancy__location"]',
  specs: 'section.b-vacancy-v2 .b-specs, .b-vacancy .b-specs',
  stack: 'section.b-vacancy-stack, .b-vacancy-stack',
  description:
    'section.b-vacancy-description, .b-vacancy-description.markdown, [class*="vacancy__description"], [class*="vacancyDescription"]',
  applyButton:
    'button[class*="response"], a[class*="response"], .b-apply-block button, section.b-vacancy-header ~ * button',
  archived: '[class*="vacancy"][class*="archived"], [class*="vacancy"][class*="closed"]',
  appliedBanner: '.b-notification_primary, .b-notification',
}

function gmSel(key: keyof typeof GETMATCH_SELECTORS_DEFAULT): string {
  return getParseSelector('getmatch', key) || GETMATCH_SELECTORS_DEFAULT[key]
}

const GM_RESPONSE_LINK_SELECTORS = [
  '.b-apply-block button',
  'button[class*="response"]',
  'a[class*="response"]',
  '[class*="vacancy"] button',
  'main button',
]

/**
 * EXT-G1/G2 (2026-07-09, Playwright-захват реального клика по «Откликнуться»): форма отклика
 * getmatch целиком монтируется React'ом ПОСЛЕ клика — в исходном DOM вакансии её нет вообще
 * (проверено на live-странице и в архиве `plans/MWS.html`, оба раза 0 <textarea>). Поле
 * сопроводительного — `<textarea name="cover_letter" id="apply_vacancy_info_comment">` внутри
 * `.b-apply-modal__form`, id/name не хэшированы (обычные React-имена полей), устойчивы.
 * Следствие: в отличие от hh, бейдж «Письмо обязательно» на самой странице вакансии (до клика)
 * для getmatch показать нельзя — сигнала о требовании письма нет нигде в DOM до открытия формы.
 */
// Зашитый дефолт; актуальное значение — из рантайм-конфига расширения (`apply_selectors.getmatch`),
// чтобы правка селектора не требовала переустановки zip. Дубль с
// `core/domains/opportunities/sources/extension_runtime_config.json` — намеренный фолбэк.
const GETMATCH_APPLY_SELECTORS = {
  form: '.b-apply-modal__form',
  coverLetterTextarea: 'textarea[name="cover_letter"], #apply_vacancy_info_comment',
}

function gmApplySel(key: 'form' | 'coverLetterTextarea'): string {
  return getRuntimeConfig().apply_selectors.getmatch?.[key] || GETMATCH_APPLY_SELECTORS[key]
}

const FORMAT_TAG_RE =
  /^(удал|гибрид|офис|remote|hybrid|office|relocate|релок)/i

function normalizeText(raw: string): string {
  return (raw || '')
    .replace(/[\u200B-\u200D\uFEFF]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

function queryText(root: ParentNode, selector: string): string {
  const el = root.querySelector(selector)
  return normalizeText(el?.textContent || '')
}

function queryAll(root: ParentNode, selector: string): Element[] {
  try {
    return Array.from(root.querySelectorAll(selector))
  } catch {
    return []
  }
}

function htmlToPlainText(el: Element): string {
  const clone = el.cloneNode(true) as Element
  clone
    .querySelectorAll(
      'button, nav, [class*="header"], [class*="toolbar"], [class*="share"], [class*="breadcrumb"], script, style, noscript',
    )
    .forEach((node) => node.remove())
  return normalizeText(clone.textContent || '')
}

/** Числовой id из URL `/vacancies/{id}-{slug}` → `gm_{id}`. */
export function extractGetmatchVacancyIdFromUrl(url = location.href): string | null {
  const m = String(url || '').match(/\/vacancies\/(\d+)-/)
  return m ? `${GM_VACANCY_ID_PREFIX}${m[1]}` : null
}

function parseTitleFromDocumentTitle(): { title: string; company: string } | null {
  const raw = normalizeText(document.title || '')
  if (!raw) return null
  const withoutSuffix = raw.replace(/\s*[—–-]\s*getmatch.*$/i, '').trim()

  const withPrefix = withoutSuffix.match(/^Вакансия\s+(.+?),\s*работа\s+в\s+(.+?)(?:,\s*в\s+|$)/i)
  if (withPrefix) {
    return { title: withPrefix[1].trim(), company: withPrefix[2].trim() }
  }

  const plain = withoutSuffix.match(/^(.+?),\s*работа\s+в\s+(.+?)(?:,\s*в\s+|$)/i)
  if (plain) {
    return { title: plain[1].trim(), company: plain[2].trim() }
  }
  return null
}

function parseMetaDescription(): { salary: string; published_at: string | null } {
  const meta =
    document.querySelector('meta[property="og:description"]')?.getAttribute('content') ||
    document.querySelector('meta[name="description"]')?.getAttribute('content') ||
    ''
  const text = normalizeText(meta)
  let salary = ''
  const salM = text.match(/Зарплата:\s*([^.;]+(?:₽[^.;]*)?)/i)
  if (salM) salary = normalizeText(salM[1])

  let published_at: string | null = null
  const pubM = text.match(/Дата публикации:\s*(\d{2}\.\d{2}\.\d{4})/i)
  if (pubM) published_at = pubM[1]

  return { salary, published_at }
}

function parseCompanyFromDom(root: ParentNode = document): string {
  for (const sel of gmSel('companyLink').split(/,\s*/)) {
    for (const link of queryAll(root, sel)) {
      const href = (link as HTMLAnchorElement).href || ''
      if (!href.includes('/companies/')) continue
      const text = normalizeText(link.textContent || '')
      if (text.length >= 2 && text.length <= 120) return text
    }
  }
  const logo = root.querySelector('.b-company-logotype img[alt]') as HTMLImageElement | null
  const alt = normalizeText(logo?.alt || '')
  if (alt.length >= 2) return alt
  const subtitle = queryText(root, '[class*="vacancy"] h2, [class*="vacancy__company"]')
  if (subtitle) return subtitle.replace(/^в\s+/i, '').trim()
  return ''
}

function extractEmployerId(root: ParentNode = document): string | null {
  for (const sel of gmSel('companyLink').split(/,\s*/)) {
    const link = root.querySelector(sel) as HTMLAnchorElement | null
    const href = link?.href || ''
    const m = href.match(/\/companies\/([^/?#]+)/)
    if (m) return m[1]
  }
  return null
}

function parseLocationTags(
  root: ParentNode = document,
): { locations: string[]; formats: string[]; unclassified: string[] } {
  const locations: string[] = []
  const formats: string[] = []
  // EXT-G3: тег, не подошедший ни под формат, ни под явный город/метро-паттерн, раньше молча
  // уходил в locations (default-ветка) — искажал area/address непонятным содержимым (грейд-бейдж,
  // язык и т.п.). Складываем такие теги сюда вместо этого; в скоринг они всё равно попадают через
  // общий текст описания (vacancy_text), так что для LLM ничего не теряется.
  const unclassified: string[] = []
  const locRoot =
    root.querySelector('section.b-location .b-vacancy-locations') ||
    root.querySelector('.b-vacancy-locations') ||
    root.querySelector(gmSel('locations'))

  const scope = locRoot || root
  for (const el of queryAll(scope, '[class*="tag_title"], .b-vacancy-locations span')) {
    const t = normalizeText(el.textContent || '')
    if (!t || t.length > 120) continue
    if (FORMAT_TAG_RE.test(t)) formats.push(t)
    else if (/^📍/.test(t) || /москва|петербург|remote|удал|офис|гибрид/i.test(t)) {
      locations.push(t.replace(/^📍\s*/, ''))
    } else if (/^(м\.|метро)/i.test(t)) {
      locations.push(t)
    } else if (!formats.includes(t) && !locations.includes(t) && !unclassified.includes(t)) {
      unclassified.push(t)
    }
  }

  if (!formats.length) {
    const locationText = queryText(root, gmSel('locations'))
    for (const word of ['Удалённо', 'Удаленно', 'Гибрид', 'Офис', 'Remote', 'Hybrid']) {
      if (locationText.includes(word)) formats.push(word)
    }
  }

  return { locations, formats, unclassified }
}

function parseSpecs(root: ParentNode = document): string {
  const blocks: string[] = []
  for (const specs of queryAll(root, gmSel('specs'))) {
    const rows = queryAll(specs, '.row')
    for (const row of rows) {
      const term = normalizeText(row.querySelector('.b-term')?.textContent || '')
      const value = normalizeText(row.querySelector('.b-value')?.textContent || '')
      if (term && value) blocks.push(`${term}: ${value}`)
    }
  }
  return blocks.join('\n')
}

function parseStack(root: ParentNode = document): string {
  const tags: string[] = []
  for (const stack of queryAll(root, gmSel('stack'))) {
    for (const el of queryAll(stack, '[class*="tag_title"]')) {
      const t = normalizeText(el.textContent || '')
      if (t && !tags.includes(t)) tags.push(t)
    }
  }
  return tags.join(', ')
}

function parseDescriptionFromDom(root: ParentNode = document): string {
  for (const sel of gmSel('description').split(/,\s*/)) {
    const el = root.querySelector(sel)
    if (!el) continue
    const text = htmlToPlainText(el)
    if (text.length >= 80) return text
  }
  return ''
}

function normalizeSalary(raw: string): string {
  return normalizeText(raw)
    .replace(/,?\s*по версии getmatch.*$/i, '')
    .replace(/\s*\/\s*мес[^.]*$/i, ' ₽/мес')
    .replace(/\s*₽\s*₽/g, ' ₽')
    .trim()
}

export function detectGetmatchAlreadyApplied(root: Document | Element = document): boolean {
  // Primary: the green ".b-notification_primary" banner («Вы откликнулись» / «Отклик отправлен»).
  // This is the ONLY reliable signal in the getmatch DOM — SSR renders the i18n strings in the
  // Flight Stream, but the actual "already applied" state resolves client-side via an async XHR,
  // which may or may not have completed by the time the extension inspects the page.
  for (const banner of queryAll(root, gmSel('appliedBanner'))) {
    const t = normalizeText(banner.textContent || '')
    if (matchesTextSignal('getmatch', 'already_applied', t)) return true
  }

  // Secondary: the «Откликнуться» button itself displays different text when an application
  // was already sent (e.g. «Вы уже откликались» / «Отклик уже отправлен»). Only inspect
  // buttons with the explicit "response" CSS class — the broader `GETMATCH_SELECTORS.applyButton`
  // catches unrelated UI elements (filters, pagination) whose disabled attribute says nothing
  // about the application state.
  for (const btn of queryAll(root, 'button[class*="response"]')) {
    const t = normalizeText(btn.textContent || '')
    if (!t || t.length > 60) continue
    if (matchesTextSignal('getmatch', 'already_applied', t)) return true
  }

  return false
}

export function detectGetmatchVacancyArchived(root: Document | Element = document): boolean {
  if (queryText(root, gmSel('archived'))) return true
  const bodyText = normalizeText(root.textContent || '')
  return matchesTextSignal('getmatch', 'archived', bodyText)
}

/**
 * Даёт корректный ответ, только пока открыта форма отклика (см. комментарий у
 * GETMATCH_APPLY_SELECTORS) — до клика по «Откликнуться» поля в DOM нет, вернёт false.
 */
export function detectGetmatchLetterRequired(root: Document | Element = document): boolean {
  const textarea = root.querySelector(gmApplySel('coverLetterTextarea')) as HTMLTextAreaElement | null
  if (textarea && (textarea.required || textarea.getAttribute('aria-required') === 'true')) {
    return true
  }
  const scope = root.querySelector(gmApplySel('form')) || root
  return matchesTextSignal('getmatch', 'letter_required', normalizeText(scope.textContent || ''))
}

/** По образцу hh readCoverLetterFromPage (extractors/hh.ts) — тот же порог в 10 символов. */
export function readGetmatchCoverLetterFromPage(root: Document = document): string {
  const el = root.querySelector(gmApplySel('coverLetterTextarea')) as HTMLTextAreaElement | null
  const value = (el?.value ?? '').trim()
  return value.length >= 10 ? value : ''
}

export function parseGetmatchVacancyFromDomLegacy(url = location.href): {
  title: string
  company: string
  salary: string
  schedule?: string
  work_format?: string
  work_schedule?: string
  address?: string
  area?: string
  description?: string
  letter_required?: boolean
  published_at?: string | null
  employer_id?: string | null
  parse_method?: string
  text: string
  url: string
  vacancy_id: string | null
  page_type?: string | null
  source: string
  is_archived?: boolean
} {
  const root = document
  const meta = parseMetaDescription()

  let title = queryText(root, gmSel('title'))
  let company = parseCompanyFromDom(root)

  if (!title || !company) {
    const fromDocTitle = parseTitleFromDocumentTitle()
    if (fromDocTitle) {
      if (!title) title = fromDocTitle.title
      if (!company) company = fromDocTitle.company
    }
  }

  if (!title) {
    const h1 = root.querySelector('section.b-vacancy-v2 h1, .b-vacancy h1, main h1, h1')
    title = normalizeText(h1?.textContent || '')
  }

  let salary = normalizeSalary(queryText(root, gmSel('salary')))
  if (!salary) salary = normalizeSalary(meta.salary)

  const { locations, formats } = parseLocationTags(root)
  const locationLine = locations.join(' · ')
  const format = formats.join(' · ') || ''
  const specs = parseSpecs(root)
  const stack = parseStack(root)
  const description = parseDescriptionFromDom(root)
  const vacancy_id = extractGetmatchVacancyIdFromUrl(url)
  const employer_id = extractEmployerId(root)
  const is_archived = detectGetmatchVacancyArchived(root)
  const letter_required = detectGetmatchLetterRequired(root)
  const published_at = meta.published_at

  const parts: string[] = []
  if (is_archived) {
    parts.push(
      'ВАКАНСИЯ СНЯТА (getmatch): работодатель, вероятно, больше не принимает отклики.',
    )
  }
  if (title) parts.push(title)
  if (company) parts.push(`Компания: ${company}`)
  if (salary) parts.push(`Зарплата: ${salary}`)
  if (format) parts.push(`Формат работы: ${format}`)
  if (locationLine) parts.push(`Локация: ${locationLine}`)
  if (specs) {
    parts.push('')
    parts.push('Параметры вакансии:')
    parts.push(specs)
  }
  if (stack) {
    parts.push('')
    parts.push(`Стек: ${stack}`)
  }
  if (description) {
    parts.push('')
    parts.push(description)
  }

  return {
    title,
    company,
    salary,
    schedule: format,
    work_format: format,
    work_schedule: format,
    address: locationLine,
    area: locations[0]?.split('(')[0]?.trim() || '',
    description,
    letter_required,
    published_at,
    employer_id,
    parse_method: 'dom',
    text: parts.join('\n').trim(),
    url,
    vacancy_id,
    page_type: GETMATCH_PAGE_TYPE.VACANCY,
    source: 'getmatch',
    is_archived,
  }
}

/**
 * Трёхуровневая стратегия извлечения вакансии getmatch (см. план Шаг 2.3):
 *   1. RSC Flight Stream `initialVacancy` — primary, богатый структурированный JSON;
 *   2. JSON-LD `JobPosting` — fallback, SEO-контракт;
 *   3. DOM-селекторы (`parseGetmatchVacancyFromDomLegacy`) — last resort.
 *
 * RSC присутствует в HTML только при SSR-заходе (первое открытие страницы). При SPA-
 * навигации внутри getmatch `self.__next_f.push` в DOM нет — тогда сразу идём на JSON-LD
 * (тоже, как правило, не обновляется) и далее на DOM.
 */
export function parseGetmatchVacancyFromDom(url = location.href): {
  title: string
  company: string
  salary: string
  schedule?: string
  work_format?: string
  work_schedule?: string
  address?: string
  area?: string
  description?: string
  letter_required?: boolean
  published_at?: string | null
  employer_id?: string | null
  skills?: string[]
  specialization?: string
  seniority?: string
  parse_method?: string
  text: string
  url: string
  vacancy_id: string | null
  page_type?: string | null
  source: string
  is_archived?: boolean
} {
  if (isRscAvailable()) {
    // Layer 1: RSC Flight Stream
    try {
      const rsc = parseGetmatchVacancyFromRsc(url)
      if (rsc) return rsc
    } catch {
      // fall through
    }

    // Layer 2: JSON-LD
    try {
      const ld = parseGetmatchVacancyFromJsonLd(url, extractGetmatchVacancyIdFromUrl(url))
      if (ld) return ld
    } catch {
      // fall through
    }
  }

  // Layer 3: DOM (текущая реализация)
  return parseGetmatchVacancyFromDomLegacy(url)
}

export {
  GM_VACANCY_ID_PREFIX,
  GETMATCH_SELECTORS_DEFAULT,
  GETMATCH_APPLY_SELECTORS,
  GM_RESPONSE_LINK_SELECTORS,
  gmApplySel,
  gmSel,
}
