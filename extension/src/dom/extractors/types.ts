/**
 * GM-4: контракт парсера вакансии — site-specific реализация, общая панель скоринга.
 */

import type { SiteId } from '../site-router'

export type ParsedVacancy = {
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
  total_responses_count?: number | null
  competition?: string | null
  /** Хабр Карьера: навыки из SSR-JSON `vacancy.skills` */
  skills?: string[]
  /** Хабр Карьера: квалификация (Intern/Junior/Middle/Senior/Lead) */
  qualification?: string | null
  /** Хабр Карьера: валюта зарплаты (rur/usd/eur) */
  salary_currency?: string | null
  /** getmatch: специализация вакансии (specialization) */
  specialization?: string
  /** getmatch: грейд (seniorities[0]) */
  seniority?: string
  /** hh: `config` | `default` | `structural`; getmatch: `rsc` | `jsonld` | `dom`. */
  parse_method?: string
  /** schema.org employmentType / разметка площадки (Э2.6) */
  employment_type?: string
  /** Локация как на странице ("Remote, EMEA") */
  location_raw?: string
  /** schema.org jobLocationType: TELECOMMUTE / HYBRID / ON_SITE */
  remote_type?: string
  text: string
  url: string
  vacancy_id: string | null
  page_type?: string | null
  source: string
  is_archived?: boolean
}

export type ScorePayload = {
  text: string
  url: string
  vacancy_id: string | null
  title: string
  company: string
  salary_text: string
  area: string | null
  work_format: string | null
  work_schedule: string | null
  total_responses: number | null
  letter_required: boolean | null
  published_at: string | null
  employer_id: string | null
  /** Хабр Карьера: навыки из вакансии */
  skills?: string[]
  /** Хабр Карьера: квалификация (Intern/Junior/Middle/Senior/Lead) */
  qualification?: string | null
  /** Хабр Карьера: валюта зарплаты (rur/usd/eur) */
  salary_currency?: string | null
  /** getmatch: специализация вакансии */
  specialization?: string | null
  /** getmatch: грейд (seniorities[0]) */
  seniority?: string | null
  /** hh: `config` | `default` | `structural`; getmatch: `rsc` | `jsonld` | `dom`. */
  parse_method?: string | null
  /** schema.org employmentType / разметка площадки (Э2.6) */
  employment_type?: string | null
  location_raw?: string | null
  remote_type?: string | null
  source: string
  is_archived: boolean
}

/** CSS-селекторы описания вакансии — для waitForVacancyDomReady. */
export type VacancyWaitHints = {
  descriptionSelectors: string[]
}

export interface VacancyExtractor extends VacancyWaitHints {
  site: SiteId
  parseVacancyFromDom(url?: string): ParsedVacancy
  extractVacancyId(url?: string): string | null
  buildScorePayload(parsed: ParsedVacancy): ScorePayload
  detectAlreadyAppliedOnPage?(root?: Document): boolean
  detectVacancyArchived?(root?: Document): boolean
  detectLetterRequired?(root?: Document): boolean
  readCoverLetterFromPage?(root?: Document): string
  /** E-02: площадка вообще показывает число откликов кандидату (getmatch — нет, not applicable). */
  supportsResponsesCount?: boolean
}
