/**
 * Раннер discovery — оркестрация поверх мок-зависимостей, без реального chrome.tabs.
 * Проверка: пара кандидатов со сдвигом старта (не 10 разом), уже известные вакансии не
 * открываются вкладкой, курсор листинга переживает тик, стоп-условия (дневной лимит/страницы
 * кончились/подозрение на блокировку), авто-возврат из паузы дневного лимита на новый день.
 * Запуск: cd extension && npx tsx tests/discovery-runner.test.ts
 */
import assert from 'node:assert/strict'

import {
  runDiscoveryCycle,
  type DiscoveryCandidate,
  type DiscoveryCursor,
  type DiscoveryPauseReason,
  type DiscoveryPlatformState,
  type DiscoveryRunnerDeps,
  type DiscoveryStatusLite,
  type DiscoveryTickSummary,
} from '../src/background/discovery-runner.ts'

function candidates(n: number, offset = 0): DiscoveryCandidate[] {
  return Array.from({ length: n }, (_, i) => ({
    vacancy_id: String(offset + i + 1),
    url: `https://hh.ru/vacancy/${offset + i + 1}`,
    title: `Вакансия ${offset + i + 1}`,
    company: 'Acme',
  }))
}

function platformState(overrides: Partial<DiscoveryPlatformState> = {}): DiscoveryPlatformState {
  return {
    platform: 'hh',
    config: { searchUrls: ['https://hh.ru/search/vacancy?text=python'], batchSize: 2, maxPagesPerSession: 10 },
    status: { state: 'running', opened: 0, scored: 0, updatedAt: new Date().toISOString() },
    ...overrides,
  }
}

function makeDeps(
  overrides: Partial<DiscoveryRunnerDeps> & {
    states: DiscoveryPlatformState[]
    cursors?: Record<string, DiscoveryCursor | null>
    seen?: Set<string>
    pages?: Record<string, { cards: DiscoveryCandidate[]; nextPageUrl: string | null }>
  },
) {
  const openedListing: string[] = []
  const listCalls: { url: string; platform: string; freshStart: boolean }[] = []
  const opened: DiscoveryCandidate[] = []
  const reported: { candidate: DiscoveryCandidate; outcome: string; pagesVisited: number }[] = []
  const paused: { platform: string; reason: DiscoveryPauseReason }[] = []
  const resumed: string[] = []
  const savedCursors: Record<string, DiscoveryCursor | null> = {}
  const delays: number[] = []

  const cursors = overrides.cursors || {}
  const seen = overrides.seen || new Set<string>()
  const pages = overrides.pages || {}

  let scoredCount = 0
  const deps: DiscoveryRunnerDeps = {
    loadPlatformStates: async () => overrides.states,
    loadCursor: async (platform) => cursors[platform] ?? null,
    saveCursor: async (platform, cursor) => {
      savedCursors[platform] = cursor
    },
    listCandidatesFromPage: async (url, platform, freshStart) => {
      openedListing.push(url)
      listCalls.push({ url, platform, freshStart })
      return pages[url] || { cards: [], nextPageUrl: null }
    },
    checkSeen: async (vacancyId) => seen.has(vacancyId),
    scoreCandidate: overrides.scoreCandidate || (async (candidate) => {
      opened.push(candidate)
      scoredCount += 1
      return { outcome: 'scored' as const }
    }),
    reportTick: overrides.reportTick || (async (_platform, candidate, outcome, pagesVisited) => {
      reported.push({ candidate, outcome, pagesVisited })
      const status: DiscoveryStatusLite = {
        state: 'running',
        opened: reported.length,
        scored: scoredCount,
        updatedAt: new Date().toISOString(),
      }
      return status
    }),
    pauseSession: async (platform, reason) => {
      paused.push({ platform, reason })
    },
    resumeSession: async (platform) => {
      resumed.push(platform)
    },
    sleep: async (ms) => {
      delays.push(ms)
    },
    staggerDelayMs: overrides.staggerDelayMs || (() => 1500),
    reportTickSummary: overrides.reportTickSummary,
  }
  return {
    deps,
    openedListing,
    listCalls,
    opened,
    reported,
    paused,
    resumed,
    savedCursors,
    delays,
  }
}

async function testIdlePlatformIsSkipped() {
  const state = platformState({ status: { state: 'idle', opened: 0, scored: 0, updatedAt: null } })
  const { deps, openedListing, opened } = makeDeps({ states: [state] })

  await runDiscoveryCycle(deps)

  assert.equal(openedListing.length, 0)
  assert.equal(opened.length, 0)
}

async function testPausedByUserIsSkipped() {
  const state = platformState({
    status: { state: 'paused_by_user', opened: 5, scored: 5, updatedAt: new Date().toISOString() },
  })
  const { deps, opened } = makeDeps({ states: [state] })

  await runDiscoveryCycle(deps)

  assert.equal(opened.length, 0, 'ручная пауза не продолжается сама')
}

async function testFetchesListingPageWhenCursorEmpty() {
  const state = platformState()
  const url = state.config.searchUrls[0]
  const { deps, openedListing, opened, delays } = makeDeps({
    states: [state],
    pages: { [url]: { cards: candidates(3), nextPageUrl: 'https://hh.ru/search/vacancy?page=1' } },
  })

  await runDiscoveryCycle(deps)

  assert.equal(openedListing.length, 1, 'страница листинга запрошена один раз за тик')
  assert.equal(opened.length, 2, 'batch_size=2 — берём пару, третий кандидат остаётся в курсоре')
  assert.equal(delays.length, 1, 'сдвиг старта между двумя вкладками пары — одна пауза, не залп')
}

async function testAlreadyKnownCandidatesSkipTabButAreReported() {
  const state = platformState()
  const url = state.config.searchUrls[0]
  const cards = candidates(3)
  const { deps, opened, reported } = makeDeps({
    states: [state],
    pages: { [url]: { cards, nextPageUrl: null } },
    seen: new Set([cards[0].vacancy_id]),
  })

  await runDiscoveryCycle(deps)

  assert.equal(opened.length, 2, 'известная вакансия не открывает вкладку, batch добирается следующими')
  assert.equal(reported.some((r) => r.candidate.vacancy_id === cards[0].vacancy_id && r.outcome === 'already_known'), true)
}

async function testCursorPersistsRemainingCandidates() {
  const state = platformState()
  const url = state.config.searchUrls[0]
  const { deps, savedCursors } = makeDeps({
    states: [state],
    pages: { [url]: { cards: candidates(5), nextPageUrl: 'https://hh.ru/next' } },
  })

  await runDiscoveryCycle(deps)

  const saved = savedCursors.hh
  assert.ok(saved)
  assert.equal(saved!.pendingCandidates.length, 3, '5 карточек - batch_size=2 = 3 в курсоре на следующий тик')
  assert.equal(saved!.nextPageUrl, 'https://hh.ru/next')
  assert.equal(saved!.pagesVisited, 1)
}

async function testUsesExistingCursorWithoutRefetchingPage() {
  const state = platformState()
  const { deps, openedListing, opened } = makeDeps({
    states: [state],
    cursors: { hh: { pendingCandidates: candidates(2), nextPageUrl: null, pagesVisited: 1 } },
  })

  await runDiscoveryCycle(deps)

  assert.equal(openedListing.length, 0, 'кандидатов в курсоре хватает на batch — страницу листинга не трогаем')
  assert.equal(opened.length, 2)
}

async function testPagesExhaustedPausesSession() {
  const state = platformState()
  const { deps, paused, savedCursors } = makeDeps({
    states: [state],
    cursors: { hh: { pendingCandidates: [], nextPageUrl: null, pagesVisited: 1 } },
  })

  await runDiscoveryCycle(deps)

  assert.deepEqual(paused, [{ platform: 'hh', reason: 'pages_exhausted' }])
  assert.equal(savedCursors.hh, null, 'курсор сброшен — следующий старт сессии начнёт заново')
}

async function testMaxPagesPerSessionPausesEvenWithNextPageUrl() {
  const state = platformState({
    config: { searchUrls: ['https://hh.ru/search/vacancy?text=python'], batchSize: 2, maxPagesPerSession: 2 },
  })
  const { deps, paused } = makeDeps({
    states: [state],
    cursors: { hh: { pendingCandidates: [], nextPageUrl: 'https://hh.ru/search?page=2', pagesVisited: 2 } },
  })

  await runDiscoveryCycle(deps)

  assert.deepEqual(paused, [{ platform: 'hh', reason: 'pages_exhausted' }])
}

async function testEmptyListingPagePausesAsSuspectedBlock() {
  const state = platformState()
  const url = state.config.searchUrls[0]
  const { deps, paused } = makeDeps({
    states: [state],
    pages: { [url]: { cards: [], nextPageUrl: null } },
  })

  await runDiscoveryCycle(deps)

  assert.deepEqual(paused, [{ platform: 'hh', reason: 'suspected_block' }])
}

// 2026-08-28: клиентского per-сессионного дневного лимита больше нет — суточный потолок держит
// бэк (`report_tick` → `paused_daily_cap`). Раннер только авто-возобновляет на новый день (тест
// ниже) и уважает уже выставленную бэком паузу в тот же день.
async function testAutoResumesFromDailyCapPauseOnNewDay() {
  const yesterday = new Date(Date.now() - 26 * 3600 * 1000).toISOString()
  const state = platformState({
    status: { state: 'paused_daily_cap', opened: 60, scored: 60, updatedAt: yesterday },
  })
  const { deps, resumed, opened } = makeDeps({
    states: [state],
    cursors: { hh: { pendingCandidates: candidates(2), nextPageUrl: null, pagesVisited: 1 } },
  })

  await runDiscoveryCycle(deps)

  assert.deepEqual(resumed, ['hh'])
  assert.equal(opened.length, 2, 'после авто-возврата тик продолжает обычную работу')
}

async function testStaysPausedForDailyCapWithinSameDay() {
  const state = platformState({
    status: { state: 'paused_daily_cap', opened: 60, scored: 60, updatedAt: new Date().toISOString() },
  })
  const { deps, resumed, opened } = makeDeps({ states: [state] })

  await runDiscoveryCycle(deps)

  assert.equal(resumed.length, 0, 'та же дата — ждём владельца или завтра')
  assert.equal(opened.length, 0)
}

async function testMultiplePlatformsProcessedIndependently() {
  const hh = platformState({ platform: 'hh' })
  const getmatch = platformState({
    platform: 'getmatch',
    config: { searchUrls: ['https://getmatch.ru/vacancies'], batchSize: 2, maxPagesPerSession: 10 },
  })
  const { deps, opened } = makeDeps({
    states: [hh, getmatch],
    cursors: {
      hh: { pendingCandidates: candidates(2, 0), nextPageUrl: null, pagesVisited: 1 },
      getmatch: { pendingCandidates: candidates(2, 100), nextPageUrl: null, pagesVisited: 1 },
    },
  })

  await runDiscoveryCycle(deps)

  assert.equal(opened.length, 4, 'обе площадки обработаны за один цикл')
}

// Этап 4 редизайна «Расширения»: `listCandidatesFromPage`/`reportTick` несут platform/freshStart/
// pagesVisited хвостовыми параметрами — реальная реализация (discovery-runner.ts::createRealDeps)
// использует их, чтобы решить, перезагружать рабочую вкладку листинга или продолжать в той же
// (getmatch-пагинация не адресуется URL, см. selectors-getmatch-catalog.ts). Пур-логика тика сама
// эти значения не толкует, только прокидывает — проверяем именно прокидывание.

async function testListCandidatesFromPageGetsFreshStartOnBrandNewCursor() {
  const state = platformState()
  const url = state.config.searchUrls[0]
  const { deps, listCalls } = makeDeps({
    states: [state],
    // cursors не задан — loadCursor вернёт null, runPlatformTick заведёт курсор с pagesVisited=0.
    pages: { [url]: { cards: candidates(2), nextPageUrl: null } },
  })

  await runDiscoveryCycle(deps)

  assert.equal(listCalls.length, 1)
  assert.deepEqual(listCalls[0], { url, platform: 'hh', freshStart: true })
}

async function testListCandidatesFromPageGetsFreshStartFalseMidPass() {
  const url = 'https://getmatch.ru/vacancies'
  const { deps, listCalls } = makeDeps({
    states: [
      platformState({
        platform: 'getmatch',
        config: { searchUrls: [url], batchSize: 2, maxPagesPerSession: 10 },
      }),
    ],
    // Курсор уже на 2-й странице этого прохода (pagesVisited=2), буфер пуст — нужна ещё страница.
    cursors: { getmatch: { pendingCandidates: [], nextPageUrl: url, pagesVisited: 2 } },
    pages: { [url]: { cards: candidates(2), nextPageUrl: url } },
  })

  await runDiscoveryCycle(deps)

  assert.equal(listCalls.length, 1)
  assert.deepEqual(listCalls[0], { url, platform: 'getmatch', freshStart: false })
}

async function testReportTickCarriesPagesVisited() {
  const state = platformState()
  const url = state.config.searchUrls[0]
  const { deps, reported } = makeDeps({
    states: [state],
    pages: { [url]: { cards: candidates(2), nextPageUrl: null } },
  })

  await runDiscoveryCycle(deps)

  assert.ok(reported.length > 0)
  assert.ok(
    reported.every((r) => r.pagesVisited === 1),
    'страница листинга получена впервые за проход — pagesVisited=1',
  )
}

// Этап 5 редизайна «Расширения»: несколько search-URL на площадку, раннер обходит их по кругу —
// проверка из плана дословно («2 search-URL на hh.ru, короткая сессия — подтвердить что раннер
// переключается между ними, а не зацикливается на первом»). Симулируем несколько тиков подряд,
// перекладывая сохранённый курсор одного тика во входной курсор следующего — так же, как это
// делает реальный `chrome.alarms` между пробуждениями service worker'а.
async function testRoundRobinsBetweenMultipleSearchUrls() {
  const urlA = 'https://hh.ru/search/vacancy?text=python'
  const urlB = 'https://hh.ru/search/vacancy?text=backend'
  const state = platformState({
    config: { searchUrls: [urlA, urlB], batchSize: 2, maxPagesPerSession: 10 },
  })

  // Тик 1: начинаем с первого URL списка, у него всего одна страница.
  const tick1 = makeDeps({
    states: [state],
    pages: { [urlA]: { cards: candidates(1, 0), nextPageUrl: null } },
  })
  await runDiscoveryCycle(tick1.deps)
  assert.deepEqual(tick1.listCalls, [{ url: urlA, platform: 'hh', freshStart: true }])
  const cursorAfterA = tick1.savedCursors.hh
  assert.ok(cursorAfterA, 'курсор сохранён — есть куда возвращаться')
  assert.equal(cursorAfterA!.nextPageUrl, null, 'urlA исчерпан после единственной страницы')

  // Тик 2: urlA исчерпан — раннер сам переключается на urlB, не паузит сессию (в списке есть
  // ещё один URL).
  const tick2 = makeDeps({
    states: [state],
    cursors: { hh: cursorAfterA },
    pages: { [urlB]: { cards: candidates(1, 100), nextPageUrl: null } },
  })
  await runDiscoveryCycle(tick2.deps)
  assert.deepEqual(tick2.listCalls, [{ url: urlB, platform: 'hh', freshStart: true }])
  assert.equal(tick2.paused.length, 0, 'смена search-URL внутри сессии — не пауза')
  const cursorAfterB = tick2.savedCursors.hh
  assert.ok(cursorAfterB)
  assert.equal(cursorAfterB!.urlIndex, 1, 'курсор помнит, что сейчас обходим второй URL списка')

  // Тик 3: urlB тоже исчерпан, и он был последним в списке — честная пауза, а не зацикливание
  // обратно на urlA молча в том же тике.
  const tick3 = makeDeps({ states: [state], cursors: { hh: cursorAfterB } })
  await runDiscoveryCycle(tick3.deps)
  assert.deepEqual(tick3.paused, [{ platform: 'hh', reason: 'pages_exhausted' }])
  assert.equal(tick3.listCalls.length, 0, 'весь список URL уже обойдён — новых запросов листинга нет')
}

async function testMaxPagesPerSessionAppliesAcrossAllSearchUrls() {
  // Бюджет страниц — на ВЕСЬ проход, не на отдельный URL: даже если следующий URL в списке ещё
  // не тронут, общий лимит страниц всё равно останавливает сессию.
  const urlA = 'https://hh.ru/search/vacancy?text=python'
  const urlB = 'https://hh.ru/search/vacancy?text=backend'
  const state = platformState({
    config: { searchUrls: [urlA, urlB], batchSize: 2, maxPagesPerSession: 1 },
  })
  const { deps, paused, listCalls } = makeDeps({
    states: [state],
    cursors: { hh: { pendingCandidates: [], nextPageUrl: null, pagesVisited: 1, urlIndex: 0 } },
  })

  await runDiscoveryCycle(deps)

  assert.deepEqual(paused, [{ platform: 'hh', reason: 'pages_exhausted' }])
  assert.equal(listCalls.length, 0, 'лимит страниц исчерпан раньше, чем раннер успел бы дойти до urlB')
}

await testIdlePlatformIsSkipped()
await testPausedByUserIsSkipped()
await testFetchesListingPageWhenCursorEmpty()
await testAlreadyKnownCandidatesSkipTabButAreReported()
await testCursorPersistsRemainingCandidates()
await testUsesExistingCursorWithoutRefetchingPage()
await testPagesExhaustedPausesSession()
await testMaxPagesPerSessionPausesEvenWithNextPageUrl()
await testEmptyListingPagePausesAsSuspectedBlock()
await testAutoResumesFromDailyCapPauseOnNewDay()
await testStaysPausedForDailyCapWithinSameDay()
await testMultiplePlatformsProcessedIndependently()
await testListCandidatesFromPageGetsFreshStartOnBrandNewCursor()
await testListCandidatesFromPageGetsFreshStartFalseMidPass()
await testReportTickCarriesPagesVisited()
await testRoundRobinsBetweenMultipleSearchUrls()
await testMaxPagesPerSessionAppliesAcrossAllSearchUrls()

async function testReportsTickSummaryWithCounts() {
  const state = platformState()
  const url = state.config.searchUrls[0]
  let summary: unknown
  const { deps } = makeDeps({
    states: [state],
    seen: new Set(['1']), // первый кандидат уже в системе
    pages: { [url]: { cards: candidates(2), nextPageUrl: null } },
    reportTickSummary: async (s) => {
      summary = s
    },
  })

  await runDiscoveryCycle(deps)

  assert.deepEqual(summary, {
    platformsRunning: ['hh'],
    opened: 2, // 1 already_known + 1 scored
    scored: 1,
    alreadyKnown: 1,
    parseErrors: 0,
    paused: [],
    bailReason: null,
  })
}

await testReportsTickSummaryWithCounts()

/** Сбой одной площадки не должен ни отменять соседние, ни съедать heartbeat: до фикса
 *  2026-08-31 исключение из `runPlatformTick` пролетало наружу мимо `reportTickSummary`, и
 *  такой тик был в проде неотличим от «раннер спит». */
async function testFailedPlatformStillReportsSummary() {
  let summary: DiscoveryTickSummary | null = null
  const scored: DiscoveryCandidate[] = []
  const { deps } = makeDeps({
    states: [
      platformState({
        platform: 'hh',
        config: { searchUrls: ['hh-page'], batchSize: 1, maxPagesPerSession: 10 },
      }),
      platformState({
        platform: 'getmatch',
        config: { searchUrls: ['gm-page'], batchSize: 1, maxPagesPerSession: 10 },
      }),
    ],
    pages: {
      'hh-page': { cards: candidates(1), nextPageUrl: null },
      'gm-page': { cards: candidates(1, 100), nextPageUrl: null },
    },
    scoreCandidate: async (candidate) => {
      if (candidate.vacancy_id === '1') throw new Error('вкладка вакансии закрыта')
      scored.push(candidate)
      return { outcome: 'scored' as const }
    },
    reportTickSummary: async (s) => {
      summary = s
    },
  })

  await runDiscoveryCycle(deps)

  assert.ok(summary, 'heartbeat обязан уйти даже когда площадка упала')
  const done = summary as unknown as DiscoveryTickSummary
  assert.ok(
    done.bailReason && done.bailReason.includes('hh:'),
    'причина сбоя площадки — в bail_reason',
  )
  assert.equal(scored.length, 1, 'соседняя площадка обязана отработать несмотря на сбой первой')
}

await testFailedPlatformStillReportsSummary()

/** Упавший сбор состояний тоже обязан оставить строку heartbeat — иначе в журнале тишина. */
async function testFailedLoadStatesStillReportsSummary() {
  let summary: DiscoveryTickSummary | null = null
  const { deps } = makeDeps({ states: [], reportTickSummary: async (s) => { summary = s } })
  const broken: DiscoveryRunnerDeps = {
    ...deps,
    loadPlatformStates: async () => {
      throw new Error('settings недоступны')
    },
  }

  await runDiscoveryCycle(broken)

  assert.ok(summary, 'heartbeat обязан уйти и при падении сбора состояний')
  const done = summary as unknown as DiscoveryTickSummary
  assert.ok(
    done.bailReason && done.bailReason.startsWith('states:'),
    'видно, что упал сбор состояний',
  )
  assert.deepEqual(done.platformsRunning, [])
}

await testFailedLoadStatesStillReportsSummary()

console.log('discovery-runner.test.ts: OK')
