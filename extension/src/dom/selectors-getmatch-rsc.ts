/**
 * GM-5: извлечение `initialVacancy` из RSC Flight Stream страницы getmatch.ru.
 *
 * getmatch.ru — Next.js App Router: полный объект вакансии приходит в HTML внутри
 * `self.__next_f.push([1,"..."])` (экранированный JSON). Это primary-источник —
 * богаче и стабильнее DOM-селекторов (не зависит от вёрстки, отдаёт skills/
 * specialization/seniority/company.industry/company.size из коробки).
 *
 * См. plans/getmatch_refactoring_plan.md — Шаг 2.
 */

import { GETMATCH_PAGE_TYPE } from './site-router'
import type { ParsedVacancy } from './extractors/types'

/** Структура `initialVacancy` (неполная — только поля, нужные парсеру). */
export interface InitialVacancy {
  published_at?: string | null
  is_active?: boolean
  position?: string
  id?: number
  cover_letter_required?: boolean
  salary_description?: string | null
  salary_hidden?: boolean
  salary_display_from?: number | null
  salary_display_to?: number | null
  salary_currency?: string | null
  salary_taxes?: string | null
  skills_objects?: { name?: string; slug?: string; is_custom?: boolean }[]
  location_requirements?: {
    location_id?: string
    format?: string
    exclude?: boolean
  }[]
  location_items?: { label?: string; format?: string; exclude?: boolean }[]
  company?: {
    id?: string | null
    name?: string | null
    logotype?: string | null
    url?: string | null
    industry?: string | null
    size?: string | null
    short_description?: string | null
  } | null
  specialization?: string | null
  seniorities?: string[]
  required_years_of_experience?: number | null
  english_level?: string | null
  offer_description?: string | null
  stack_description?: string | null
  breadcrumbs?: string[]
}

const _PUSH = 'self.__next_f.push('

/**
 * Вырезает сбалансированный JSON-массив, начиная с `[` по индексу `start`.
 * Учитывает строки и экранирование, чтобы не споткнуться о `]` внутри строки.
 */
function extractBalancedArray(s: string, start: number): string | null {
  let depth = 0
  let inStr = false
  let esc = false
  for (let i = start; i < s.length; i++) {
    const c = s[i]
    if (inStr) {
      if (esc) esc = false
      else if (c === '\\') esc = true
      else if (c === '"') inStr = false
    } else if (c === '"') {
      inStr = true
    } else if (c === '[') {
      depth++
    } else if (c === ']') {
      depth--
      if (depth === 0) return s.slice(start, i + 1)
    }
  }
  return null
}

/**
 * Извлекает сырой Flight Stream из HTML: склеивает строковые payload'ы всех
 * `self.__next_f.push([1,"..."])`. Аргумент push парсится как валидный JSON-массив
 * `[1, "..."]` — это надёжнее ручного расклеивания `\"`.
 */
export function extractFlightStream(html: string): string {
  const parts: string[] = []
  let pos = 0
  for (;;) {
    const idx = html.indexOf(_PUSH, pos)
    if (idx < 0) break
    let argStart = idx + _PUSH.length
    while (argStart < html.length && /[ \t\r\n]/.test(html[argStart])) argStart++
    if (html[argStart] !== '[') {
      pos = argStart
      continue
    }
    const arr = extractBalancedArray(html, argStart)
    if (!arr) break
    try {
      const payload = JSON.parse(arr) as unknown
      if (Array.isArray(payload) && payload.length >= 2 && typeof payload[1] === 'string') {
        parts.push(payload[1])
      }
    } catch {
      // некорректный push — пропускаем, следующий может быть валидным
    }
    pos = argStart + arr.length
  }
  return parts.join('')
}

/** Вырезает сбалансированный JSON-объект `{...}`, начиная с `{` по индексу `start`. */
function extractBalancedObject(s: string, start: number): string | null {
  let depth = 0
  let inStr = false
  let esc = false
  for (let i = start; i < s.length; i++) {
    const c = s[i]
    if (inStr) {
      if (esc) esc = false
      else if (c === '\\') esc = true
      else if (c === '"') inStr = false
    } else if (c === '"') {
      inStr = true
    } else if (c === '{') {
      depth++
    } else if (c === '}') {
      depth--
      if (depth === 0) return s.slice(start, i + 1)
    }
  }
  return null
}

/**
 * Пытается найти и распарсить `initialVacancy` в Flight Stream.
 * Возвращает объект или null, если маркер/объект отсутствуют.
 */
export function extractInitialVacancy(flight: string): Record<string, unknown> | null {
  const marker = '"initialVacancy":{'
  const idx = flight.indexOf(marker)
  if (idx < 0) return null
  const start = idx + '"initialVacancy":'.length
  const raw = extractBalancedObject(flight, start)
  if (!raw) return null
  try {
    return JSON.parse(raw) as Record<string, unknown>
  } catch {
    return null
  }
}

function normalizeText(raw: string | null | undefined): string {
  return (raw || '')
    .replace(/[\u200B-\u200D\uFEFF]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

function stripHtml(html: string): string {
  return normalizeText(html.replace(/<[^>]+>/g, ' '))
}

/** Формат из `location_items`: первый подходящий `format` (remote/office/hybrid). */
function extractWorkFormat(items: { label?: string; format?: string }[] | undefined): string {
  const labels: string[] = []
  for (const item of items || []) {
    const fmt = normalizeText(item.format)
    if (fmt && !labels.includes(fmt)) labels.push(fmt)
  }
  return labels.join(' · ')
}

/** Локации: все `label` из `location_items`, кроме дублей. */
function extractArea(items: { label?: string }[] | undefined): string {
  const labels: string[] = []
  for (const item of items || []) {
    const label = normalizeText(item.label)
    if (label && !labels.includes(label)) labels.push(label)
  }
  return labels.join(' · ')
}

function formatSalary(data: InitialVacancy): string {
  // Человекочитаемая строка уже есть в salary_description — берём её как канон.
  const desc = normalizeText(data.salary_description)
  if (desc) return desc

  const from = data.salary_display_from
  const to = data.salary_display_to
  const currency = normalizeText(data.salary_currency) || '₽'
  if (from != null && to != null) return `${from} — ${to} ${currency}`
  if (from != null) return `от ${from} ${currency}`
  if (to != null) return `до ${to} ${currency}`
  return ''
}

/** `company.name` → «Конфиденциально», если скрыта или отсутствует. */
function extractCompany(company: InitialVacancy['company']): string {
  const name = normalizeText(company?.name)
  return name && name !== 'Название скрыто' ? name : 'Конфиденциально'
}

/** `company.url` → слаг компании (`/companies/{slug}` → `{slug}`). */
function extractEmployerId(company: InitialVacancy['company']): string | null {
  const url = normalizeText(company?.url)
  if (!url) return null
  const m = url.match(/\/companies\/([^/?#]+)/)
  return m ? m[1] : null
}

/** Вакансия заархивирована, если явно `is_active === false`. */
function isArchived(data: InitialVacancy): boolean {
  return data.is_active === false
}

/**
 * Маппинг `initialVacancy` → `ParsedVacancy`.
 * `url` — полный URL страницы (для `vacancy_id`/`url`); при его отсутствии id берётся из объекта.
 */
export function mapRscToParsedVacancy(data: InitialVacancy, url: string): ParsedVacancy {
  const title = normalizeText(data.position)
  const company = extractCompany(data.company)
  const salary = formatSalary(data)
  const workFormat = extractWorkFormat(data.location_items)
  const area = extractArea(data.location_items)
  const skills = (data.skills_objects || [])
    .map((s) => normalizeText(s.name))
    .filter(Boolean)
  const specialization = normalizeText(data.specialization) || undefined
  const seniority = normalizeText(data.seniorities?.[0]) || undefined

  const vacancyId = data.id != null ? `gm_${data.id}` : null
  const employerId = extractEmployerId(data.company)
  const archived = isArchived(data)
  const publishedAt = normalizeText(data.published_at) || null

  const descriptionHtml = data.offer_description || ''
  const description = stripHtml(descriptionHtml)

  const parts: string[] = []
  if (archived) {
    parts.push('ВАКАНСИЯ СНЯТА (getmatch): работодатель, вероятно, больше не принимает отклики.')
  }
  if (title) parts.push(title)
  if (company) parts.push(`Компания: ${company}`)
  if (salary) parts.push(`Зарплата: ${salary}`)
  if (workFormat) parts.push(`Формат работы: ${workFormat}`)
  if (area) parts.push(`Локация: ${area}`)
  if (specialization) parts.push(`Специализация: ${specialization}`)
  if (seniority) parts.push(`Грейд: ${seniority}`)
  if (skills.length) parts.push(`Навыки: ${skills.join(', ')}`)
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
    letter_required: data.cover_letter_required === true,
    published_at: publishedAt,
    employer_id: employerId,
    skills,
    specialization,
    seniority,
    parse_method: 'rsc',
    text: parts.join('\n').trim(),
    url,
    vacancy_id: vacancyId,
    page_type: GETMATCH_PAGE_TYPE.VACANCY,
    source: 'getmatch',
    is_archived: archived,
  }
}

/**
 * Primary-слой: парсинг вакансии из RSC Flight Stream по сырому HTML.
 * Чистая функция (без `document`) — используется тестами и document-обёрткой.
 */
export function parseGetmatchVacancyFromRscHtml(
  html: string,
  url = location.href,
): ParsedVacancy | null {
  if (!html) return null

  const flight = extractFlightStream(html)
  if (!flight) return null

  const data = extractInitialVacancy(flight) as InitialVacancy | null
  if (!data || !data.position) return null

  return mapRscToParsedVacancy(data, url)
}

/**
 * Primary-слой: парсинг вакансии из RSC Flight Stream текущего `document`.
 * Возвращает null, если Flight Stream/initialVacancy отсутствуют (SPA-навигация
 * без SSR-пейлоада) — тогда вызывающий код пробует JSON-LD и DOM.
 */
export function parseGetmatchVacancyFromRsc(url = location.href): ParsedVacancy | null {
  let html = ''
  try {
    html = document?.documentElement?.outerHTML || document?.body?.innerHTML || ''
  } catch {
    return null
  }
  return parseGetmatchVacancyFromRscHtml(html, url)
}

/** Наличие Flight Stream в текущем документе (SSR-заход). */
export function isRscAvailable(root: Document = document): boolean {
  try {
    return /self\.__next_f\.push/.test(root.documentElement.innerHTML.slice(0, 50000))
  } catch {
    return false
  }
}
