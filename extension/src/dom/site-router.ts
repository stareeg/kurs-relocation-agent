/**
 * GM-4: мультисайтовый роутер расширения (hh.ru + getmatch.ru + career.habr.com).
 * Канонический вход — resolveRoute(); site-specific page types — отдельные enum'ы.
 */

import { getHhPageType, HH_PAGE_TYPE } from './selectors'
export type SiteId = 'hh' | 'getmatch' | 'habr'

export type SiteRoute = {
  site: SiteId | null
  pageType: string | null
}

/** Типы страниц getmatch.ru (GM-5+ подключат адаптеры). */
export const GETMATCH_PAGE_TYPE = {
  VACANCY: 'vacancy',
  APPLICATIONS: 'applications',
  CATALOG: 'catalog',
  PROFILE: 'profile',
  STATS: 'stats',
  OTHER: 'other',
} as const

export type GetmatchPageType =
  (typeof GETMATCH_PAGE_TYPE)[keyof typeof GETMATCH_PAGE_TYPE]

/** Типы страниц career.habr.com. */
export const HABR_PAGE_TYPE = {
  VACANCY: 'vacancy',
  SERP: 'serp',
  /** «Ваши отклики» /profile/responses — S13, синк откликов Хабр через перехват XHR. */
  RESPONSES: 'responses',
  OTHER: 'other',
} as const

export type HabrPageType =
  (typeof HABR_PAGE_TYPE)[keyof typeof HABR_PAGE_TYPE]

function hostnameFromUrl(url: string): string {
  try {
    return new URL(String(url), 'https://hh.ru').hostname.toLowerCase()
  } catch {
    const m = String(url).match(/^https?:\/\/([^/?#]+)/i)
    return m ? m[1].toLowerCase() : ''
  }
}

/** Домен текущей вкладки → площадка или null. */
export function getSite(url = location.href): SiteId | null {
  const host = hostnameFromUrl(url)
  if (!host) return null
  if (host === 'hh.ru' || host.endsWith('.hh.ru')) return 'hh'
  if (host === 'getmatch.ru' || host.endsWith('.getmatch.ru')) return 'getmatch'
  if (host === 'career.habr.com' || host.endsWith('.career.habr.com')) return 'habr'
  return null
}

/** Тип страницы getmatch по pathname (SPA-safe). */
export function getGetmatchPageType(url = location.href): GetmatchPageType {
  let path: string
  try {
    path = new URL(String(url), 'https://getmatch.ru').pathname
  } catch {
    path = String(url).split('#')[0].split('?')[0]
  }

  if (/^\/vacancies\/\d+-/.test(path)) return GETMATCH_PAGE_TYPE.VACANCY
  if (path === '/applications' || path.startsWith('/applications/')) {
    return GETMATCH_PAGE_TYPE.APPLICATIONS
  }
  if (path === '/profile/statistics' || path.startsWith('/profile/statistics/')) {
    return GETMATCH_PAGE_TYPE.STATS
  }
  if (path === '/profile' || path.startsWith('/profile/')) {
    return GETMATCH_PAGE_TYPE.PROFILE
  }
  if (path === '/vacancies' || path.startsWith('/vacancies/')) {
    return GETMATCH_PAGE_TYPE.CATALOG
  }
  return GETMATCH_PAGE_TYPE.OTHER
}

/** Тип страницы career.habr.com по pathname (SPA-safe). */
export function getHabrPageType(url = location.href): HabrPageType {
  let path: string
  try {
    path = new URL(String(url), 'https://career.habr.com').pathname
  } catch {
    path = String(url).split('#')[0].split('?')[0]
  }
  if (/^\/vacancies\/\d+/.test(path)) return HABR_PAGE_TYPE.VACANCY
  if (path === '/vacancies' || path.startsWith('/vacancies?')) return HABR_PAGE_TYPE.SERP
  if (path === '/profile/responses' || path.startsWith('/profile/responses/')) {
    return HABR_PAGE_TYPE.RESPONSES
  }
  return HABR_PAGE_TYPE.OTHER
}

/**
 * Тип страницы для указанной площадки.
 * Без site — определяет площадку из url; неизвестный домен → null.
 */
export function getPageType(
  url = location.href,
  site: SiteId | null = getSite(url),
): string | null {
  if (!site) return null
  if (site === 'hh') return getHhPageType(url)
  if (site === 'getmatch') return getGetmatchPageType(url)
  if (site === 'habr') return getHabrPageType(url)
  return null
}

/** Единая точка маршрутизации для dock и адаптеров. */
export function resolveRoute(url = location.href): SiteRoute {
  const site = getSite(url)
  const pageType = site ? getPageType(url, site) : null
  return { site, pageType }
}

export { HH_PAGE_TYPE, getHhPageType }
