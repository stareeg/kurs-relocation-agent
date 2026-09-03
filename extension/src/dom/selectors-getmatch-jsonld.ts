/**
 * GM-5: JSON-LD fallback-парсер страницы вакансии getmatch.ru.
 *
 * Второй слой извлечения после RSC Flight Stream. JSON-LD (`<script
 * type="application/ld+json">`, Schema.org `JobPosting`) — SEO-контракт, который
 * сайты ломают редко. Поля беднее, чем `initialVacancy`, но стабильнее.
 *
 * См. plans/getmatch_refactoring_plan.md — Шаг 2.4.
 */

import { GETMATCH_PAGE_TYPE } from './site-router'
import type { ParsedVacancy } from './extractors/types'

const JSON_LD_RE = /<script[^>]*type="application\/ld\+json"[^>]*>([\s\S]*?)<\/script>/gi

type JsonLdJobPosting = {
  '@type'?: string
  title?: string
  hiringOrganization?: { name?: string } | string
  baseSalary?: {
    currency?: string
    value?: { minValue?: number | string; maxValue?: number | string }
  }
  employmentType?: string
  datePosted?: string
  description?: string
  jobLocation?: { address?: { addressLocality?: string } }[]
  jobLocationType?: string
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

/** Извлекает первый `JobPosting` из всех JSON-LD-блоков страницы, или null. */
export function extractJsonLdJobPosting(html: string): JsonLdJobPosting | null {
  for (const match of html.matchAll(JSON_LD_RE)) {
    const chunk = match[1]
    if (!chunk) continue
    try {
      const data = JSON.parse(chunk) as unknown
      if (Array.isArray(data)) {
        for (const item of data) {
          if (item && typeof item === 'object' && (item as JsonLdJobPosting)['@type'] === 'JobPosting') {
            return item as JsonLdJobPosting
          }
        }
      } else if (data && typeof data === 'object' && (data as JsonLdJobPosting)['@type'] === 'JobPosting') {
        return data as JsonLdJobPosting
      }
    } catch {
      // некорректный JSON-LD — пробуем следующий блок
    }
  }
  return null
}

function formatSalary(job: JsonLdJobPosting): string {
  const currency = normalizeText(job.baseSalary?.currency) || '₽'
  const minV = job.baseSalary?.value?.minValue
  const maxV = job.baseSalary?.value?.maxValue
  const min = minV != null ? String(minV) : ''
  const max = maxV != null ? String(maxV) : ''
  if (min && max) return `${min} — ${max} ${currency}`
  if (min) return `от ${min} ${currency}`
  if (max) return `до ${max} ${currency}`
  return ''
}

function extractCompany(org: JsonLdJobPosting['hiringOrganization']): string {
  if (!org) return ''
  if (typeof org === 'string') return normalizeText(org)
  const name = normalizeText(org.name)
  return name && name !== 'Название скрыто' ? name : 'Конфиденциально'
}

function extractArea(job: JsonLdJobPosting): string {
  const localities: string[] = []
  for (const loc of job.jobLocation || []) {
    const addr = normalizeText(loc?.address?.addressLocality)
    if (addr && !localities.includes(addr)) localities.push(addr)
  }
  return localities.join(' · ')
}

/** `jobLocationType: TELECOMMUTE` → удалёнка. */
function extractWorkFormat(job: JsonLdJobPosting): string {
  const type = normalizeText(job.jobLocationType)
  if (type.toUpperCase() === 'TELECOMMUTE') return 'remote'
  return ''
}

/** ID из `datePosted` не вытащить — vacancy_id берётся из URL вызывающим кодом. */
export function mapJsonLdToParsedVacancy(job: JsonLdJobPosting, url: string, vacancyId: string | null): ParsedVacancy {
  const title = normalizeText(job.title)
  const company = extractCompany(job.hiringOrganization)
  const salary = formatSalary(job)
  const area = extractArea(job)
  const workFormat = extractWorkFormat(job)
  const description = stripHtml(job.description || '')
  const publishedAt = normalizeText(job.datePosted) || null

  const parts: string[] = []
  if (title) parts.push(title)
  if (company) parts.push(`Компания: ${company}`)
  if (salary) parts.push(`Зарплата: ${salary}`)
  if (workFormat) parts.push(`Формат работы: ${workFormat}`)
  if (area) parts.push(`Локация: ${area}`)
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
    parse_method: 'jsonld',
    employment_type: normalizeText(job.employmentType) || undefined,
    location_raw: area || undefined,
    remote_type: normalizeText(job.jobLocationType) || undefined,
    text: parts.join('\n').trim(),
    url,
    vacancy_id: vacancyId,
    page_type: GETMATCH_PAGE_TYPE.VACANCY,
    source: 'getmatch',
  }
}

/**
 * Fallback-слой: парсинг из JSON-LD по сырому HTML.
 * Чистая функция (без `document`) — используется тестами и document-обёрткой.
 */
export function parseGetmatchVacancyFromJsonLdHtml(
  html: string,
  url = location.href,
  vacancyId: string | null = null,
): ParsedVacancy | null {
  if (!html) return null

  const job = extractJsonLdJobPosting(html)
  if (!job) return null

  return mapJsonLdToParsedVacancy(job, url, vacancyId)
}

/**
 * Fallback-слой: парсинг из JSON-LD текущего `document`.
 * Возвращает null, если `JobPosting` отсутствует.
 */
export function parseGetmatchVacancyFromJsonLd(
  url = location.href,
  vacancyId: string | null = null,
): ParsedVacancy | null {
  let html = ''
  try {
    html = document?.documentElement?.outerHTML || document?.body?.innerHTML || ''
  } catch {
    return null
  }
  return parseGetmatchVacancyFromJsonLdHtml(html, url, vacancyId)
}
