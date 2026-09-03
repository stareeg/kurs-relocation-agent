/**
 * GM-5.3: парсинг «Статистика найма» getmatch.ru (`/profile/statistics`).
 * DOM-референс: plans/«Статистика найма — getmatch.html» (2026-07-06).
 */

export const GETMATCH_PROFILE_RESUME_ID = 'getmatch:profile'

export type ParsedGetmatchProfileViewer = {
  company: string
  date: string
  source: string
}

export type ParsedGetmatchProfileStats = {
  resume_id: string
  period: string
  impressions: number
  views: number
  invitations: number
  recommended_vacancies: number
  views_delta: number
  invitations_delta: number
  raw: {
    source: 'getmatch'
    total_text: string
    viewers: ParsedGetmatchProfileViewer[]
    viewer_count: number
  }
}

function queryText(root: ParentNode, selector: string): string {
  const el = root.querySelector(selector)
  return (el?.textContent || '').replace(/\s+/g, ' ').trim()
}

/** «N просмотров за 30 дней» / «Нет просмотров за 30 дней» → число или null. */
export function parseGetmatchViewsTotal(text: string): number | null {
  const norm = String(text || '').replace(/\s+/g, ' ').trim()
  if (/нет\s+просмотров\s+за\s+30\s+д/i.test(norm)) return 0
  const m = norm.match(/(\d[\d ]*\d|\d)\s+просмотр(?:а|ов)?\s+за\s+30\s+д/i)
  if (!m) return null
  return parseInt(m[1].replace(/\s/g, ''), 10)
}

/**
 * Снимок «Кто смотрел ваш профиль» — просмотры за 30 дней.
 * null — карточка статистики не найдена (SPA ещё не дорисовала).
 */
export function parseGetmatchProfileStatsFromDom(
  root: ParentNode = document,
): ParsedGetmatchProfileStats | null {
  const card = root.querySelector('[class*="profileStatisticsCard_card"]')
  if (!card) return null

  const totalText = queryText(card, '[class*="profileStatisticsCard_total"]')
  let views = parseGetmatchViewsTotal(totalText)

  if (views === null) {
    const emptyText = queryText(card, '[class*="profileStatisticsCard_empty"]')
    if (/нет\s+просмотров/i.test(emptyText)) views = 0
  }

  if (views === null) return null

  const rows = Array.from(card.querySelectorAll('[class*="profileStatisticsCard_row"]'))
  const viewers: ParsedGetmatchProfileViewer[] = rows
    .map((row) => ({
      company: queryText(row, '[class*="profileStatisticsCard_company"]'),
      date: queryText(row, '[class*="profileStatisticsCard_date"]'),
      source: queryText(row, '[class*="profileStatisticsCard_source"]'),
    }))
    .filter((v) => v.company || v.date)

  return {
    resume_id: GETMATCH_PROFILE_RESUME_ID,
    period: '30d',
    impressions: 0,
    views,
    invitations: 0,
    recommended_vacancies: 0,
    views_delta: 0,
    invitations_delta: 0,
    raw: {
      source: 'getmatch',
      total_text: totalText,
      viewers,
      viewer_count: rows.length,
    },
  }
}
