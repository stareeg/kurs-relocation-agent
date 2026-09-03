/**
 * GM-4: hh.ru VacancyExtractor — обёртка над selectors.ts (без дублирования парсинга).
 */

import {
  parseVacancyFromDom as parseHhVacancyFromDom,
  extractVacancyId as extractHhVacancyId,
  detectAlreadyAppliedOnPage,
  detectVacancyArchived,
  detectLetterRequired,
} from '../selectors'
import { getSelectors } from '../selectors-config'
import type { ParsedVacancy, ScorePayload, VacancyExtractor } from './types'

function readCoverLetterFromPage(root: Document = document): string {
  const pack = getSelectors()
  const selectors = [
    pack.vacancy.coverLetterInput,
    pack.vacancy.coverLetterInputPopup,
    '[data-qa="vacancy-response-popup-form-letter-input"]',
    '#cover-letter textarea',
    'textarea[data-qa*="letter"]',
  ].filter(Boolean)

  for (const sel of selectors) {
    const el = root.querySelector(sel) || document.querySelector(sel)
    if (!el) continue
    const field = el.matches('textarea, input')
      ? el
      : el.querySelector('textarea, input')
    const node = field || el
    const v = String((node as HTMLInputElement).value ?? node.textContent ?? '').trim()
    if (v.length >= 10) return v
  }
  return ''
}

function buildScorePayload(parsed: ParsedVacancy): ScorePayload {
  return {
    text: parsed.text,
    url: parsed.url,
    vacancy_id: parsed.vacancy_id,
    title: parsed.title,
    company: parsed.company,
    salary_text: parsed.salary,
    area: parsed.area || parsed.address || null,
    work_format: parsed.work_format || null,
    work_schedule: parsed.work_schedule || parsed.schedule || null,
    total_responses: parsed.total_responses_count ?? null,
    letter_required: parsed.letter_required ?? null,
    published_at: parsed.published_at || null,
    employer_id: parsed.employer_id || null,
    parse_method: parsed.parse_method ?? null,
    employment_type: parsed.employment_type ?? null,
    location_raw: parsed.location_raw || parsed.area || parsed.address || null,
    remote_type: parsed.remote_type ?? null,
    source: parsed.source || 'vacancy_page',
    is_archived: Boolean(parsed.is_archived),
  }
}

const hhVacancyExtractor: VacancyExtractor = {
  site: 'hh',
  get descriptionSelectors() {
    const pack = getSelectors()
    return [pack.vacancy.description, ...(pack.fallbacks.description || [])]
  },
  parseVacancyFromDom: parseHhVacancyFromDom,
  extractVacancyId: extractHhVacancyId,
  buildScorePayload,
  detectAlreadyAppliedOnPage,
  detectVacancyArchived,
  detectLetterRequired,
  readCoverLetterFromPage,
  supportsResponsesCount: true,
}

export { hhVacancyExtractor, readCoverLetterFromPage }
