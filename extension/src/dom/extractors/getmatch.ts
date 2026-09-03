/**
 * GM-5: getmatch.ru VacancyExtractor — обёртка над selectors-getmatch.ts.
 */

import {
  detectGetmatchAlreadyApplied,
  detectGetmatchLetterRequired,
  detectGetmatchVacancyArchived,
  extractGetmatchVacancyIdFromUrl,
  gmSel,
  parseGetmatchVacancyFromDom,
  readGetmatchCoverLetterFromPage,
} from '../selectors-getmatch'
import type { ParsedVacancy, ScorePayload, VacancyExtractor } from './types'

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
    // EXT-G3 (2026-07-09, проверено на живой странице вакансии и в bundled i18n getmatch):
    // кандидату НЕ показывается число откликов/конкурентов на вакансию — это not applicable,
    // а не недосмотр. "views"/"Просмотры" в бандле — статистика профиля кандидата (см.
    // getmatch-profile-stats.ts), "Отклики"/"viewed" — статусы СОБСТВЕННЫХ откликов кандидата
    // в /applications, не публичный счётчик на карточке вакансии. selectors-getmatch.ts не
    // парсит total_responses_count вообще — здесь всегда null.
    total_responses: parsed.total_responses_count ?? null,
    letter_required: parsed.letter_required ?? null,
    published_at: parsed.published_at || null,
    employer_id: parsed.employer_id || null,
    skills: parsed.skills,
    specialization: parsed.specialization ?? null,
    seniority: parsed.seniority ?? null,
    parse_method: parsed.parse_method ?? null,
    employment_type: parsed.employment_type ?? null,
    location_raw: parsed.location_raw || parsed.area || parsed.address || null,
    remote_type: parsed.remote_type ?? null,
    source: 'getmatch',
    is_archived: Boolean(parsed.is_archived),
  }
}

const getmatchVacancyExtractor: VacancyExtractor = {
  site: 'getmatch',
  // getter, не литерал — `gmSel` читает рантайм-конфиг, который на момент загрузки модуля
  // ещё не гидрирован из storage (как `get descriptionSelectors()` у hh-экстрактора).
  get descriptionSelectors() {
    return [
      gmSel('description'),
      'section.b-vacancy-description',
      '.b-vacancy-description',
      'section.b-vacancy-v2',
    ]
  },
  parseVacancyFromDom: parseGetmatchVacancyFromDom,
  extractVacancyId: extractGetmatchVacancyIdFromUrl,
  buildScorePayload,
  detectAlreadyAppliedOnPage: detectGetmatchAlreadyApplied,
  detectVacancyArchived: detectGetmatchVacancyArchived,
  detectLetterRequired: detectGetmatchLetterRequired,
  readCoverLetterFromPage: readGetmatchCoverLetterFromPage,
  // EXT-G3 выше: getmatch не показывает число откликов вообще — false, не пропуск поля.
  supportsResponsesCount: false,
}

export { getmatchVacancyExtractor }
