import { getActiveVacancyExtractor, hhVacancyExtractor } from './extractors'
import type { ParsedVacancy, VacancyExtractor } from './extractors/types'

/**
 * DOM utilities: delays and SPA-ready waits before vacancy parsing.
 * GM-4: парсинг через VacancyExtractor (site-agnostic).
 */

const VACANCY_READY_MIN_TEXT = 50
const VACANCY_WAIT_TIMEOUT_MS = 8000
const VACANCY_WAIT_POLL_MS = 200
const VACANCY_STABLE_TIMEOUT_MS = 15000
const VACANCY_STABLE_MS = 700

type WaitOptions = {
  timeoutMs?: number
  pollMs?: number
  minTextLen?: number
  minLen?: number
  stableMs?: number
  shouldCancel?: () => boolean
  extractor?: VacancyExtractor | null
}

function delay(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function resolveExtractor(extractor?: VacancyExtractor | null): VacancyExtractor {
  return extractor ?? getActiveVacancyExtractor() ?? hhVacancyExtractor
}

// Этап 6 §6.1 (plans/scoring_precision_2026_08_17.md): раньше здесь была добавочная 2.5с пауза
// (E-02, «счётчик иногда дорисовывается позже описания»). Живая проверка hh.ru 2026-08-18
// (несколько реальных вакансий, Playwright) показала: страница вакансии не отдаёт число
// откликов НИКОГДА — ни в DOM, ни в embedded-JSON, ни сразу, ни после ожидания. Это не гонка
// прорисовки (ретраем не лечится, как и было записано в плане), а данные, которых hh больше не
// шлёт на эту страницу вовсе. Пауза на каждой вакансии стоила до 2.5с впустую. Синхронный разбор
// (`parseVacancyFromDom` уже пробует `parseResponsesCount` в рамках обычного ожидания текста)
// и WARNING `responses_count_missing` (main.ts) остаются — на случай, если hh вернёт счётчик.

/** Общий хвост обеих wait-функций. */
function finishVacancyWait(
  parsed: ParsedVacancy,
  ready: boolean,
  timedOut: boolean,
  cancelled: boolean,
) {
  return { ready, parsed, timedOut, cancelled }
}

async function waitForText(
  selectors: string | string[],
  options: WaitOptions = {},
) {
  const list = Array.isArray(selectors) ? selectors : [selectors]
  const timeoutMs = options.timeoutMs ?? VACANCY_WAIT_TIMEOUT_MS
  const pollMs = options.pollMs ?? VACANCY_WAIT_POLL_MS
  const minLen = options.minLen ?? 1
  const shouldCancel = options.shouldCancel || (() => false)
  const deadline = Date.now() + timeoutMs

  while (Date.now() < deadline) {
    if (shouldCancel()) return null
    for (const sel of list) {
      try {
        const el = document.querySelector(sel)
        if ((el as HTMLElement | null)?.innerText?.trim().length >= minLen) {
          return el
        }
      } catch {
        /* invalid selector */
      }
    }
    await delay(pollMs)
  }
  return null
}

async function waitForVacancyDomReady(options: WaitOptions = {}) {
  const extractor = resolveExtractor(options.extractor)
  const timeoutMs = options.timeoutMs ?? VACANCY_WAIT_TIMEOUT_MS
  const pollMs = options.pollMs ?? VACANCY_WAIT_POLL_MS
  const minTextLen = options.minTextLen ?? VACANCY_READY_MIN_TEXT
  const shouldCancel = options.shouldCancel || (() => false)
  const deadline = Date.now() + timeoutMs

  let parsed = extractor.parseVacancyFromDom()

  while (Date.now() < deadline) {
    if (shouldCancel()) {
      return { ready: false, parsed, timedOut: false, cancelled: true }
    }
    if (parsed.text && parsed.text.length >= minTextLen) {
      return finishVacancyWait(parsed, true, false, false)
    }

    await waitForText(extractor.descriptionSelectors, {
      timeoutMs: pollMs,
      pollMs: Math.min(100, pollMs),
      minLen: 30,
      shouldCancel,
    })

    if (shouldCancel()) {
      return { ready: false, parsed, timedOut: false, cancelled: true }
    }
    await delay(pollMs)
    parsed = extractor.parseVacancyFromDom()
  }

  if (shouldCancel()) {
    return { ready: false, parsed, timedOut: false, cancelled: true }
  }

  parsed = extractor.parseVacancyFromDom()
  const ready = !!(parsed.text && parsed.text.length >= minTextLen)
  return finishVacancyWait(parsed, ready, !ready, false)
}

async function waitForVacancyStable(options: WaitOptions = {}) {
  const extractor = resolveExtractor(options.extractor)
  const timeoutMs = options.timeoutMs ?? VACANCY_STABLE_TIMEOUT_MS
  const stableMs = options.stableMs ?? VACANCY_STABLE_MS
  const pollMs = options.pollMs ?? VACANCY_WAIT_POLL_MS
  const minTextLen = options.minTextLen ?? VACANCY_READY_MIN_TEXT
  const shouldCancel = options.shouldCancel || (() => false)
  const deadline = Date.now() + timeoutMs

  let lastText = ''
  let lastChangeAt = 0
  let parsed = extractor.parseVacancyFromDom()

  while (Date.now() < deadline) {
    if (shouldCancel()) {
      return { ready: false, parsed, timedOut: false, cancelled: true }
    }
    parsed = extractor.parseVacancyFromDom()
    const text = parsed.text || ''

    if (text.length >= minTextLen) {
      if (text !== lastText) {
        lastText = text
        lastChangeAt = Date.now()
      } else if (lastChangeAt > 0 && Date.now() - lastChangeAt >= stableMs) {
        return finishVacancyWait(parsed, true, false, false)
      }
    } else {
      lastText = ''
      lastChangeAt = 0
    }
    await delay(pollMs)
  }

  if (shouldCancel()) {
    return { ready: false, parsed, timedOut: false, cancelled: true }
  }
  parsed = extractor.parseVacancyFromDom()
  const ready = !!(parsed.text && parsed.text.length >= minTextLen)
  return finishVacancyWait(parsed, ready, !ready, false)
}

export { waitForVacancyDomReady, waitForVacancyStable }
