/**
 * Фабрика VacancyExtractor по площадке.
 */

import type { SiteId } from '../site-router'
import { getmatchVacancyExtractor } from './getmatch'
import { habrVacancyExtractor } from './habr'
import { hhVacancyExtractor } from './hh'
import type { VacancyExtractor } from './types'

const EXTRACTORS: Record<SiteId, VacancyExtractor> = {
  hh: hhVacancyExtractor,
  getmatch: getmatchVacancyExtractor,
  habr: habrVacancyExtractor,
}

export function getVacancyExtractor(site: SiteId | null): VacancyExtractor | null {
  if (!site) return null
  return EXTRACTORS[site] ?? null
}

export function getActiveVacancyExtractor(): VacancyExtractor | null {
  const host = location.hostname.toLowerCase()
  if (host === 'hh.ru' || host.endsWith('.hh.ru')) return EXTRACTORS.hh
  if (host === 'getmatch.ru' || host.endsWith('.getmatch.ru')) {
    return EXTRACTORS.getmatch
  }
  if (host === 'career.habr.com' || host.endsWith('.career.habr.com')) {
    return EXTRACTORS.habr
  }
  return null
}

export type { ParsedVacancy, ScorePayload, VacancyExtractor } from './types'
export { hhVacancyExtractor } from './hh'
export { extractGetmatchVacancyIdFromUrl, GM_VACANCY_ID_PREFIX } from '../selectors-getmatch'
export { getmatchVacancyExtractor } from './getmatch'
export { habrVacancyExtractor, HABR_VACANCY_ID_PREFIX } from './habr'
