/**
 * FR2-71: хелсчек селекторов — 0 карточек SERP/каталога или пустой парсинг вакансии
 * → событие в бэкенд-лог (POST /api/logs/frontend через X-API-Key в background).
 * Один раз на (site, page, reason, url) за жизнь вкладки — без спама при debounce/MutationObserver.
 */

export type ParseHealthSite = 'hh' | 'getmatch' | 'habr'
export type ParseHealthPage = 'serp' | 'catalog' | 'vacancy'
export type ParseHealthReason =
  | 'zero_cards'
  | 'vacancy_empty'
  | 'vacancy_timeout'
  | 'responses_count_missing'
  | 'rsc_fallback_to_jsonld'
  | 'rsc_fallback_to_dom'
  | 'unknown_selector_key'
  | 'invalid_selector'
  | 'config_schema_invalid'
  | 'config_http_insecure'

export type ParseHealthPayload = {
  site: ParseHealthSite
  page: ParseHealthPage
  reason: ParseHealthReason
  url?: string
  detail?: string
  /**
   * Чем распарсилась страница: hh `config` | `default` | `structural` | `serp_json`;
   * getmatch `rsc` | `jsonld` | `dom`.
   */
  method?: string
  /** hh: версия применённого selector pack. */
  config_version?: number
  /** hh: откуда pack — сервер / кэш / встроенный. */
  config_origin?: 'server' | 'storage' | 'builtin'
  /** getmatch: ошибка RSC-парсинга, из-за которой сработал fallback. */
  rsc_error?: string
}

const reported = new Set<string>()

function reportKey(payload: ParseHealthPayload, url: string): string {
  const base = url.split('#')[0] || url
  return `${payload.site}:${payload.page}:${payload.reason}:${base}`
}

/** Сообщить о смерти парсера (fire-and-forget). Повтор с тем же ключом игнорируется. */
export function reportParseHealth(payload: ParseHealthPayload): void {
  const url =
    payload.url ?? (typeof location !== 'undefined' ? location.href : '')
  const key = reportKey(payload, url)
  if (reported.has(key)) return
  reported.add(key)

  try {
    chrome.runtime.sendMessage(
      { action: 'report_parse_health', payload: { ...payload, url } },
      () => {
        // swallow lastError — бэкенд/SW могут быть недоступны
        void chrome.runtime.lastError
      },
    )
  } catch {
    /* service worker недоступен */
  }
}

/** Сброс дедупа — только для unit-тестов. */
export function _resetParseHealthReportedForTests(): void {
  reported.clear()
}
