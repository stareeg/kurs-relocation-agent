/**
 * Раннер discovery (авто-открытие вакансий): по тику `chrome.alarms` листает SERP hh.ru /
 * каталог getmatch.ru фоновыми вкладками, парами (`batch_size`, дефолт 2) с небольшим сдвигом
 * старта — не строго последовательно, как auto-apply-runner (там это оправдано ценой ошибки —
 * реальный клик по «Откликнуться»), но и не заливом всех разом. Каждый кандидат скорится тем же
 * путём, что обычный визит владельца (`resetForNavigation` → `maybeAutoScore`/`runScoringFlow`
 * в content-script, main.ts) — раннер только открывает вкладку и ждёт готовности
 * (`discovery_wait_for_score`), никакой отдельной логики скоринга здесь нет.
 *
 * Реальный отклик не отправляется вообще — вакансия просто остаётся «Просмотрено», а решить,
 * на что отвечать, — работа уже существующей очереди автооткликов (auto-apply-runner.ts).
 *
 * `runDiscoveryCycle` — чистая оркестрация поверх инжектируемых зависимостей (без прямого
 * chrome.tabs/chrome.storage/fetch внутри), как и у auto-apply-runner — тестируется без
 * реального браузера. `createRealDeps` — единственное место, где это встречается с настоящим
 * chrome.*.
 */

import { getFlag, getRuntimeConfig } from '../dom/extension-runtime-config'
import type { HttpDeps } from './auto-apply-runner'
import { keepAliveSleep } from './keep-alive'

export type DiscoveryPlatform = 'hh' | 'getmatch' | 'habr'
export type DiscoveryOutcome = 'scored' | 'already_known' | 'parse_error'
export type DiscoveryPauseReason = 'daily_cap' | 'pages_exhausted' | 'suspected_block'

export interface DiscoveryCandidate {
  vacancy_id: string
  url: string
  title?: string
  company?: string
}

/** Позиция раннера на текущем search-URL — переживает усыпление service worker'а между тиками
 *  (chrome.storage.local, не in-memory). `urlIndex` — какой из `config.searchUrls` листаем
 *  сейчас (Этап 5 редизайна «Расширения»: несколько search-URL на площадку, раннер обходит их
 *  по кругу за сессию); опционален для обратной совместимости со старыми моками в тестах —
 *  везде читается как `cursor.urlIndex ?? 0`. */
export interface DiscoveryCursor {
  pendingCandidates: DiscoveryCandidate[]
  nextPageUrl: string | null
  pagesVisited: number
  urlIndex?: number
}

export interface DiscoveryPlatformConfigLite {
  /** Список search-URL площадки (Этап 5) — обходятся по кругу; пустых/whitespace-only строк
   *  тут уже нет, `createRealDeps.loadPlatformStates` фильтрует их на входе. */
  searchUrls: string[]
  /** 2026-08-28: раннер жёстко берёт 1 (строго последовательный просмотр, owner's spec) —
   *  поле оставлено ради обратной совместимости старых моков в тестах. */
  batchSize: number
  maxPagesPerSession: number
}

export interface DiscoveryStatusLite {
  state: string
  opened: number
  scored: number
  updatedAt: string | null
}

export interface DiscoveryPlatformState {
  platform: DiscoveryPlatform
  config: DiscoveryPlatformConfigLite
  status: DiscoveryStatusLite
}

export interface DiscoveryListResult {
  cards: DiscoveryCandidate[]
  nextPageUrl: string | null
}

export interface DiscoveryRunnerDeps {
  /** Только площадки, у которых конфиг включён И задан search_url — раннер сам не решает, что
   *  включено. Включает площадки в `running` и `paused_daily_cap` (второе — на случай авто-
   *  возврата, см. ниже), остальные `paused_*`/`idle` раннеру сейчас неинтересны. */
  loadPlatformStates: () => Promise<DiscoveryPlatformState[]>
  loadCursor: (platform: DiscoveryPlatform) => Promise<DiscoveryCursor | null>
  saveCursor: (platform: DiscoveryPlatform, cursor: DiscoveryCursor | null) => Promise<void>
  /** Собрать карточки текущей страницы листинга + ссылку на следующую. `url` — первым параметром
   *  для обратной совместимости старых моков в тестах (см. discovery-runner.test.ts), `platform`/
   *  `freshStart` — хвостом, добавлены Этапом 4 редизайна «Расширения» ради рабочей вкладки:
   *  `freshStart=true` (курсор только что заведён — старт сессии или возврат из паузы) заставляет
   *  реальную реализацию (`createRealDeps`) перегрузить вкладку, а не переиспользовать её
   *  состояние — актуально для getmatch, где страница листинга не адресуется URL (продолжение —
   *  клик «вправо» внутри той же вкладки, не навигация). */
  listCandidatesFromPage: (
    url: string,
    platform: DiscoveryPlatform,
    freshStart: boolean,
  ) => Promise<DiscoveryListResult>
  checkSeen: (vacancyId: string) => Promise<boolean>
  /** Открыть вкладку вакансии, дождаться скоринга (или таймаута), закрыть — один атомарный шаг. */
  scoreCandidate: (
    candidate: DiscoveryCandidate,
  ) => Promise<{ outcome: DiscoveryOutcome; title?: string; company?: string }>
  /** `pagesVisited` — сколько страниц листинга уже открыто за текущий проход (Этап 4, для
   *  UI-подписи «страница N» рядом с прогресс-баром просмотра) — хвостовой параметр, та же
   *  обратная совместимость с моками тестов, что у `listCandidatesFromPage` выше. */
  reportTick: (
    platform: DiscoveryPlatform,
    candidate: DiscoveryCandidate,
    outcome: DiscoveryOutcome,
    pagesVisited: number,
  ) => Promise<DiscoveryStatusLite>
  pauseSession: (platform: DiscoveryPlatform, reason: DiscoveryPauseReason) => Promise<void>
  resumeSession: (platform: DiscoveryPlatform) => Promise<void>
  sleep: (ms: number) => Promise<void>
  /** Сдвиг старта между вкладками одной пары (1-3с) — не одновременно, но и не последовательное
   *  ожидание каждой до конца. Практически не срабатывает: раннер берёт 1 вакансию за тик. */
  staggerDelayMs: () => number
  /** Дополнительный рандомный сон перед просмотром вакансий тика (0..1 мин): alarm тикает раз
   *  в минуту, джиттер растягивает фактический интервал до 1–2 мин (owner's spec 2026-08-28).
   *  Опционально — юнит-тесты чистого цикла его не задают. */
  viewJitterMs?: () => number
  /** Heartbeat: итог тика автопросмотра → одна строка в журнал бэка. Опционально —
   *  юнит-тесты чистого цикла его не задают. */
  reportTickSummary?: (summary: DiscoveryTickSummary) => Promise<void>
}

export interface DiscoveryTickSummary {
  platformsRunning: string[]
  opened: number
  scored: number
  alreadyKnown: number
  parseErrors: number
  paused: string[]
  bailReason: string | null
}

const STAGGER_MIN_MS = 1_000
const STAGGER_MAX_MS = 3_000

export function randomStaggerDelayMs(): number {
  return STAGGER_MIN_MS + Math.random() * (STAGGER_MAX_MS - STAGGER_MIN_MS)
}

function isToday(iso: string | null): boolean {
  if (!iso) return false
  return iso.slice(0, 10) === new Date().toISOString().slice(0, 10)
}

/** Один тик по одной площадке. */
async function runPlatformTick(
  state: DiscoveryPlatformState,
  deps: DiscoveryRunnerDeps,
): Promise<void> {
  const { platform, config, status } = state

  // Авто-возврат после дневного лимита: встали на паузу вчера (или раньше) — сегодня уже новый
  // день, продолжаем сами, не заставляя владельца заходить и жать «Возобновить» руками. Паузы
  // по другим причинам (пользователь/страницы кончились/похоже на блокировку) остаются ручными.
  if (status.state === 'paused_daily_cap' && !isToday(status.updatedAt)) {
    await deps.resumeSession(platform)
  } else if (status.state !== 'running') {
    return
  }

  let cursor = (await deps.loadCursor(platform)) ?? {
    pendingCandidates: [],
    nextPageUrl: config.searchUrls[0] ?? null,
    pagesVisited: 0,
    urlIndex: 0,
  }

  if (cursor.pendingCandidates.length < config.batchSize) {
    // Общий бюджет страниц на ПРОХОД (не на отдельный search-URL) — иначе большой список
    // search-URL мог бы растянуть один проход на неограниченное число реальных навигаций.
    if (cursor.pagesVisited >= config.maxPagesPerSession) {
      await deps.pauseSession(platform, 'pages_exhausted')
      await deps.saveCursor(platform, null)
      return
    }

    let nextPageUrl = cursor.nextPageUrl
    let urlIndex = cursor.urlIndex ?? 0
    // Текущий search-URL исчерпан (нет следующей страницы) — Этап 5: переходим к следующему по
    // кругу, а не сразу паузим сессию. `freshStart=true` — это его первая страница, вне
    // зависимости от `pagesVisited` (тот считает страницы за весь проход, не за конкретный URL).
    let freshStartForThisUrl = cursor.pagesVisited === 0
    if (!nextPageUrl) {
      const nextIndex = urlIndex + 1
      if (nextIndex >= config.searchUrls.length) {
        // Обошли весь круг — все search-URL этой площадки исчерпаны, честная пауза.
        await deps.pauseSession(platform, 'pages_exhausted')
        await deps.saveCursor(platform, null)
        return
      }
      urlIndex = nextIndex
      nextPageUrl = config.searchUrls[urlIndex]
      freshStartForThisUrl = true
    }

    const page = await deps.listCandidatesFromPage(nextPageUrl, platform, freshStartForThisUrl)
    if (page.cards.length === 0 && cursor.pendingCandidates.length === 0) {
      // Пустая страница листинга — вероятная капча/блокировка площадки, не конец выдачи (та
      // отдаёт последнюю страницу с карточками и без ссылки «дальше», не пустую страницу).
      await deps.pauseSession(platform, 'suspected_block')
      await deps.saveCursor(platform, null)
      return
    }
    cursor = {
      pendingCandidates: [...cursor.pendingCandidates, ...page.cards],
      nextPageUrl: page.nextPageUrl,
      pagesVisited: cursor.pagesVisited + 1,
      urlIndex,
    }
  }

  // Джиттер темпа — ДО того, как тронуть курсор: alarm тикает раз в `discovery_tick_minutes`
  // (дефолт 0.5 = 30с), сверху добавляем 0..`discovery_delay_ms[1]-[0]` рандома — фактический
  // интервал между просмотрами 30–90с (owner's spec 2026-09). Спим здесь, а не перед самим
  // scoreCandidate: MV3 усыпляет service worker на длинном setTimeout, и смерть SW во сне ПОСЛЕ
  // shift()+saveCursor вычёркивала бы кандидатов молча и навсегда. До вычёркивания смерть
  // безопасна — следующий тик перечитает тот же курсор.
  if (cursor.pendingCandidates.length > 0) {
    const jitter = deps.viewJitterMs?.() ?? 0
    if (jitter > 0) await deps.sleep(jitter)
  }

  const batch: DiscoveryCandidate[] = []
  while (batch.length < config.batchSize && cursor.pendingCandidates.length > 0) {
    const candidate = cursor.pendingCandidates.shift() as DiscoveryCandidate
    const seen = await deps.checkSeen(candidate.vacancy_id)
    if (seen) {
      // Экономим и вкладку, и LLM-вызов — вакансия уже есть в системе, репортим для лога/
      // прозрачности, но не открываем.
      await deps.reportTick(platform, candidate, 'already_known', cursor.pagesVisited)
      continue
    }
    batch.push(candidate)
  }

  await deps.saveCursor(platform, cursor)

  if (batch.length === 0) return

  for (let i = 0; i < batch.length; i++) {
    if (i > 0) await deps.sleep(deps.staggerDelayMs())
    const { outcome } = await deps.scoreCandidate(batch[i])
    await deps.reportTick(platform, batch[i], outcome, cursor.pagesVisited)
  }
}

/** Один тик раннера по всем включённым площадкам.
 *
 *  Сбой одной площадки (упавшая вкладка листинга, `sendTabMessage` после всех ретраев) не
 *  должен ни отменять соседние площадки, ни съедать heartbeat: до 2026-08-31 исключение из
 *  `runPlatformTick` пролетало наружу мимо `reportTickSummary`, и в проде такой тик был
 *  неотличим от «раннер спит» — `reportExtHttpFailure` дедуплится на всю жизнь service
 *  worker'а и после первого раза молчал.
 */
export async function runDiscoveryCycle(deps: DiscoveryRunnerDeps): Promise<void> {
  let states: DiscoveryPlatformState[] = []
  // Heartbeat-инструментовка: считаем, что раннер сделал за тик, оборачивая reportTick/pauseSession.
  const counts = { opened: 0, scored: 0, alreadyKnown: 0, parseErrors: 0 }
  const paused = new Set<string>()
  const failures: string[] = []
  try {
    states = await deps.loadPlatformStates()
    const instrumented: DiscoveryRunnerDeps = {
      ...deps,
      reportTick: async (platform, candidate, outcome, pages) => {
        counts.opened += 1
        if (outcome === 'already_known') counts.alreadyKnown += 1
        else if (outcome === 'parse_error') counts.parseErrors += 1
        else counts.scored += 1
        return deps.reportTick(platform, candidate, outcome, pages)
      },
      pauseSession: async (platform, reason) => {
        paused.add(`${platform}:${reason}`)
        return deps.pauseSession(platform, reason)
      },
    }

    for (const state of states) {
      try {
        await runPlatformTick(state, instrumented)
      } catch (err) {
        failures.push(`${state.platform}:${String((err as Error)?.message || err).slice(0, 120)}`)
      }
    }
  } catch (err) {
    // Упал сам сбор состояний — площадок нет, но heartbeat всё равно обязан уйти.
    failures.push(`states:${String((err as Error)?.message || err).slice(0, 120)}`)
  } finally {
    await deps.reportTickSummary?.({
      platformsRunning: states.map((s) => s.platform),
      opened: counts.opened,
      scored: counts.scored,
      alreadyKnown: counts.alreadyKnown,
      parseErrors: counts.parseErrors,
      paused: [...paused],
      bailReason: failures.length > 0 ? failures.join('; ') : lastDiscoveryBailReason,
    })
  }
}

// Причина, по которой `createRealDeps.loadPlatformStates` вернул пусто (флаг выключен / статус-
// ручка отвалилась) — для heartbeat-репорта. Модульная переменная: цикл чистый, диагностику
// пишет только реальная реализация deps.
let lastDiscoveryBailReason: string | null = null

const PLATFORMS: DiscoveryPlatform[] = ['hh', 'getmatch', 'habr']
const CURSOR_STORAGE_PREFIX = 'jh_discovery_cursor_'

// content-script поднимается по `document_idle` — на свежеоткрытой вкладке вакансии слушатель
// onMessage может ещё не существовать к моменту первого sendMessage (особенно на второй
// вкладке пары, пока service worker занят первой). chrome отдаёт тогда lastError вида
// «Could not establish connection / Receiving end does not exist» — это гонка загрузки, а не
// поломка парсинга. До фикса 2026-08-28 такой кейс молча уходил в `parse_error`, и владельцу
// приходилось часто пересматривать вакансии вручную. Ретраим ровно эти ошибки короткой серией.
const TAB_MESSAGE_RETRY_ATTEMPTS = 6
const TAB_MESSAGE_RETRY_DELAY_MS = 500

function openTab(url: string): Promise<number> {
  return new Promise((resolve, reject) => {
    chrome.tabs.create({ url, active: false }, (tab) => {
      if (chrome.runtime.lastError || !tab?.id) {
        reject(new Error(chrome.runtime.lastError?.message || 'Не удалось открыть вкладку'))
        return
      }
      resolve(tab.id)
    })
  })
}

function waitForTabLoad(tabId: number): Promise<void> {
  const { tab_load_timeout_ms, post_load_settle_ms } = getRuntimeConfig().tuning
  return new Promise((resolve) => {
    let done = false
    const finish = (settle: boolean) => {
      if (done) return
      done = true
      clearTimeout(timeout)
      chrome.tabs.onUpdated.removeListener(listener)
      if (settle) setTimeout(resolve, post_load_settle_ms)
      else resolve()
    }
    const timeout = setTimeout(() => finish(false), tab_load_timeout_ms)
    function listener(updatedTabId: number, info: chrome.tabs.TabChangeInfo) {
      if (updatedTabId === tabId && info.status === 'complete') finish(true)
    }
    chrome.tabs.onUpdated.addListener(listener)
    // Вкладка могла догрузиться до того, как повесили слушатель (кэш / быстрый ответ) —
    // событие 'complete' тогда уже не придёт, и без этой проверки ждали бы весь таймаут зря.
    chrome.tabs.get(tabId, (tab) => {
      if (!chrome.runtime.lastError && tab?.status === 'complete') finish(true)
    })
  })
}

function closeTab(tabId: number): Promise<void> {
  return new Promise((resolve) => {
    chrome.tabs.remove(tabId, () => resolve())
  })
}

/** «Принимающая сторона ещё не поднялась» — гонка загрузки content-script, а не отказ.
 *  Настоящий ответ (`ok:false`) и прочие ошибки сюда не попадают — их наверх сразу. */
function isReceiverNotReady(msg: string): boolean {
  return (
    msg.includes('Receiving end does not exist') ||
    msg.includes('Could not establish connection') ||
    msg.includes('message port closed')
  )
}

function sendTabMessageOnce<T>(tabId: number, message: unknown): Promise<T> {
  return new Promise((resolve, reject) => {
    chrome.tabs.sendMessage(tabId, message, (response) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message))
        return
      }
      if (!response?.ok) {
        reject(new Error(response?.error || 'пустой ответ content-script'))
        return
      }
      resolve(response.data)
    })
  })
}

async function sendTabMessage<T>(tabId: number, message: unknown): Promise<T> {
  let lastErr: Error = new Error('sendTabMessage: не запускался')
  for (let attempt = 0; attempt < TAB_MESSAGE_RETRY_ATTEMPTS; attempt++) {
    try {
      return await sendTabMessageOnce<T>(tabId, message)
    } catch (err) {
      lastErr = err as Error
      if (!isReceiverNotReady(lastErr.message)) throw lastErr
      await new Promise((r) => setTimeout(r, TAB_MESSAGE_RETRY_DELAY_MS))
    }
  }
  throw lastErr
}

// ── Рабочая вкладка листинга (Этап 4 редизайна «Расширения») ──────────────────────────────
// Раньше каждый тик открывал и сразу закрывал вкладку под страницу листинга — видимый флик
// вкладок в браузере (причина #1 из плана) и, для getmatch, ещё и потеря React-состояния
// пагинации между вызовами (страница каталога не адресуется URL — см. selectors-getmatch-
// catalog.ts). Держим одну вкладку на площадку между тиками; id — в chrome.storage.local, не в
// module-переменной: service worker не персистентный, память между пробуждениями не переживает
// (тот же приём, что у курсора выше).

const WORKER_TAB_STORAGE_PREFIX = 'jh_discovery_worker_tab_'

async function getWorkerTabId(platform: DiscoveryPlatform): Promise<number | null> {
  const key = WORKER_TAB_STORAGE_PREFIX + platform
  const result = await chrome.storage.local.get(key)
  return typeof result[key] === 'number' ? result[key] : null
}

async function setWorkerTabId(platform: DiscoveryPlatform, tabId: number | null): Promise<void> {
  const key = WORKER_TAB_STORAGE_PREFIX + platform
  if (tabId == null) {
    await chrome.storage.local.remove(key)
  } else {
    await chrome.storage.local.set({ [key]: tabId })
  }
}

/** Текущий URL вкладки, если она ещё жива — null, если владелец/браузер её уже закрыли (тогда
 *  запись в storage стала мусором, вызывающий код сам решает создать вкладку заново). */
function getTabUrlIfAlive(tabId: number): Promise<string | null> {
  return new Promise((resolve) => {
    chrome.tabs.get(tabId, (tab) => {
      if (chrome.runtime.lastError || !tab) {
        resolve(null)
        return
      }
      resolve(tab.url || tab.pendingUrl || null)
    })
  })
}

function updateTabUrl(tabId: number, url: string): Promise<void> {
  return new Promise((resolve, reject) => {
    chrome.tabs.update(tabId, { url }, () => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message))
        return
      }
      resolve()
    })
  })
}

function reloadTab(tabId: number): Promise<void> {
  return new Promise((resolve, reject) => {
    chrome.tabs.reload(tabId, {}, () => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message))
        return
      }
      resolve()
    })
  })
}

/** Гарантирует, что рабочая вкладка площадки открыта — переиспользует существующую, если она ещё
 *  жива, иначе создаёт новую. `navigated=true` — вкладка только что реально загрузилась (свежий
 *  create/update/reload, контент-скрипт переинициализирован «с нуля»); `false` — вкладка не
 *  трогалась, её текущее DOM-состояние переживает вызов (нужно getmatch-пагинации, см. выше).
 *  `forceReload` — тот же URL, но нужно ИМЕННО перезагрузить (новый проход листинга после паузы:
 *  `chrome.tabs.update` на идентичный URL — no-op в Chrome, `chrome.tabs.reload` — настоящий
 *  сброс состояния). */
async function ensureWorkerTab(
  platform: DiscoveryPlatform,
  url: string,
  forceReload: boolean,
): Promise<{ tabId: number; navigated: boolean }> {
  const existingId = await getWorkerTabId(platform)
  if (existingId != null) {
    const currentUrl = await getTabUrlIfAlive(existingId)
    if (currentUrl != null) {
      if (currentUrl === url) {
        if (!forceReload) return { tabId: existingId, navigated: false }
        await reloadTab(existingId)
        await waitForTabLoad(existingId)
        return { tabId: existingId, navigated: true }
      }
      await updateTabUrl(existingId, url)
      await waitForTabLoad(existingId)
      return { tabId: existingId, navigated: true }
    }
    // Вкладку закрыли снаружи (владелец/браузер) — запись в storage устарела, забываем её.
    await setWorkerTabId(platform, null)
  }
  const tabId = await openTab(url)
  await setWorkerTabId(platform, tabId)
  await waitForTabLoad(tabId)
  return { tabId, navigated: true }
}

/** Закрыть рабочую вкладку площадки, если она есть — стоп/подозрение на блокировку/площадка
 *  выключена (см. `loadPlatformStates`). Пауза «страницы кончились»/«дневной лимит»/«пользователь»
 *  вкладку НЕ закрывает — сессия может продолжиться тем же листингом после «Продолжить». */
async function closeWorkerTab(platform: DiscoveryPlatform): Promise<void> {
  const existingId = await getWorkerTabId(platform)
  if (existingId != null) await closeTab(existingId)
  await setWorkerTabId(platform, null)
}

// ── Кэш страницы листинга (Этап 5 редизайна «Расширения») ──────────────────────────────────
// Раунд-робин по нескольким search-URL (см. runPlatformTick выше) означает, что раннер регулярно
// возвращается к странице 1 УЖЕ недавно просмотренного search-URL — без кэша это каждый раз
// настоящая перезагрузка вкладки ради выдачи, которая почти наверняка не изменилась за
// несколько часов. Кэш — ТОЛЬКО для hh: там страница 1 адресуется обычной ссылкой, кэш-хит просто
// возвращает старый результат, ничего не трогая в реальной вкладке. Для getmatch кэш-хит был бы
// небезопасен — его пагинация живёт в React-состоянии УЖЕ ОТКРЫТОЙ вкладки (см. Этап 4,
// selectors-getmatch-catalog.ts), и «вернуть результат, не трогая вкладку» рассинхронизировало бы
// то, что кэш считает текущей страницей, с тем, что реально показывает браузер.

const PAGE_CACHE_STORAGE_PREFIX = 'jh_discovery_page_cache_'
const PAGE_CACHE_TTL_MS = 2 * 60 * 60 * 1000 // 2 часа, как в плане (Этап 5)

interface PageCacheEntry {
  cachedAt: number
  result: DiscoveryListResult
}

/** Некриптографический хеш строки — только ключ chrome.storage, не для безопасности. */
function hashUrl(url: string): string {
  let h = 0
  for (let i = 0; i < url.length; i++) {
    h = (Math.imul(31, h) + url.charCodeAt(i)) | 0
  }
  return (h >>> 0).toString(36)
}

async function getCachedListing(
  platform: DiscoveryPlatform,
  url: string,
): Promise<DiscoveryListResult | null> {
  const key = PAGE_CACHE_STORAGE_PREFIX + platform + '_' + hashUrl(url)
  const result = await chrome.storage.local.get(key)
  const entry = result[key] as PageCacheEntry | undefined
  if (!entry || Date.now() - entry.cachedAt > PAGE_CACHE_TTL_MS) return null
  return entry.result
}

async function setCachedListing(
  platform: DiscoveryPlatform,
  url: string,
  result: DiscoveryListResult,
): Promise<void> {
  const key = PAGE_CACHE_STORAGE_PREFIX + platform + '_' + hashUrl(url)
  const entry: PageCacheEntry = { cachedAt: Date.now(), result }
  await chrome.storage.local.set({ [key]: entry })
}

/** Единственное место в модуле, трогающее настоящие chrome.tabs/chrome.storage/fetch — вся
 *  логика тика выше тестируется без него. */
export function createRealDeps(http: HttpDeps): DiscoveryRunnerDeps {
  return {
    async loadPlatformStates() {
      lastDiscoveryBailReason = null
      if (!getFlag('discovery_enabled')) {
        lastDiscoveryBailReason = 'flag_discovery_disabled'
        return []
      }
      const settingsResp = await http.apiFetch(
        'discovery_settings',
        http.apiUrl('/api/settings'),
        { headers: http.apiHeaders(false) },
      )
      if (!settingsResp.ok) {
        lastDiscoveryBailReason = `settings_http_${settingsResp.status}`
        return []
      }
      const settings = await settingsResp.json()
      const config = settings?.discovery_config || {}

      const states: DiscoveryPlatformState[] = []
      for (const platform of PLATFORMS) {
        const platformConfig = config[platform] || {}
        // Этап 5: несколько search-URL на площадку — пустые/whitespace-only строки фронт может
        // сохранить как есть (не чистит на каждый кейстрок, см. PlatformPipelineSection.tsx),
        // фильтруем здесь, один раз, а не в каждом потребителе ниже.
        const searchUrls: string[] = (
          Array.isArray(platformConfig.search_urls) ? platformConfig.search_urls : []
        )
          .map((u: unknown) => String(u ?? '').trim())
          .filter(Boolean)
        if (!platformConfig.enabled || searchUrls.length === 0) {
          // Площадку выключили — рабочей вкладке незачем висеть открытой без дела.
          await closeWorkerTab(platform)
          continue
        }

        const statusResp = await http.apiFetch(
          'discovery_status',
          http.apiUrl(`/api/opportunities/discovery/status?platform=${platform}`),
          { headers: http.apiHeaders(false) },
        )
        if (!statusResp.ok) continue
        const status = await statusResp.json()
        // Стоп/подозрение на блокировку — закрываем рабочую вкладку (см. closeWorkerTab).
        // Остальные паузы (страницы кончились/дневной лимит/пользователь) её не трогают —
        // «Продолжить» может застать тот же листинг ещё живым.
        if (status.state === 'idle' || status.state === 'paused_suspected_block') {
          await closeWorkerTab(platform)
          continue
        }
        if (status.state !== 'running' && status.state !== 'paused_daily_cap') continue

        states.push({
          platform,
          config: {
            searchUrls,
            // 2026-08-28: строго 1 вакансия за тик, что бы ни было в сохранённом конфиге.
            batchSize: 1,
            maxPagesPerSession: platformConfig.max_pages_per_session ?? 10,
          },
          status: {
            state: status.state,
            opened: status.opened ?? 0,
            scored: status.scored ?? 0,
            updatedAt: status.updated_at ?? null,
          },
        })
      }
      return states
    },

    async loadCursor(platform) {
      const key = CURSOR_STORAGE_PREFIX + platform
      const result = await chrome.storage.local.get(key)
      return result[key] ?? null
    },

    async saveCursor(platform, cursor) {
      const key = CURSOR_STORAGE_PREFIX + platform
      if (cursor == null) {
        await chrome.storage.local.remove(key)
      } else {
        await chrome.storage.local.set({ [key]: cursor })
      }
    },

    async listCandidatesFromPage(url, platform, freshStart) {
      // Этап 5: первая страница нового прохода (freshStart) на hh/habr — скорее всего уже недавно
      // просматривалась (раунд-робин возвращается к тому же search-URL) — используем кэш вместо
      // настоящей перезагрузки вкладки. Оба URL-адресуемые (см. Фаза D редизайна «Расширения» —
      // habr тоже отдаёт страницу листинга обычной ссылкой `?page=N`, безопасно для кэша).
      // getmatch намеренно исключён — см. комментарий у кэша.
      if (freshStart && (platform === 'hh' || platform === 'habr')) {
        const cached = await getCachedListing(platform, url)
        if (cached) return cached
      }

      // Рабочая вкладка листинга живёт между тиками (Этап 4) — не create/remove на каждый шаг:
      // меньше визуальных «вспышек» + getmatch-пагинация (клик «вправо») требует, чтобы React-
      // состояние вкладки пережило вызов. `navigated=false` — content-script продолжает работать
      // на уже отрисованной странице, шлём ему «продолжить» вместо «прочитать с нуля».
      const { tabId, navigated } = await ensureWorkerTab(platform, url, freshStart)
      const action = navigated ? 'discovery_list_page' : 'discovery_list_page_advance'
      const result = await sendTabMessage<DiscoveryListResult>(tabId, { action })
      if (freshStart && (platform === 'hh' || platform === 'habr'))
        await setCachedListing(platform, url, result)
      return result
    },

    async checkSeen(vacancyId) {
      const resp = await http.apiFetch(
        'discovery_check_seen',
        http.apiUrl(`/vacancies/${encodeURIComponent(vacancyId)}/seen`),
        { headers: http.apiHeaders(false) },
      )
      if (!resp.ok) return false
      const data = await resp.json()
      return Boolean(data?.seen)
    },

    async scoreCandidate(candidate) {
      const tabId = await openTab(candidate.url)
      try {
        await waitForTabLoad(tabId)
        return await sendTabMessage<{ outcome: DiscoveryOutcome; title?: string; company?: string }>(
          tabId,
          { action: 'discovery_wait_for_score', payload: { vacancy_id: candidate.vacancy_id } },
        )
      } catch (err) {
        // Не молча в parse_error — иначе в проде видно только «сбоев: 1» без причины.
        const detail = String((err as Error)?.message || err)
        void http
          .apiFetch('discovery_score_error', http.apiUrl('/api/logs/frontend'), {
            method: 'POST',
            headers: http.apiHeaders(true),
            body: JSON.stringify({
              entries: [
                {
                  ts: new Date().toISOString(),
                  level: 'WARNING',
                  kind: 'extension_parse',
                  message: `Автопросмотр: вакансия ${candidate.vacancy_id} не оценилась · ${detail}`,
                  url: candidate.url,
                  endpoint: 'extension:discovery/score',
                  status: 0,
                },
              ],
            }),
          })
          .catch(() => {})
        return { outcome: 'parse_error' }
      } finally {
        await closeTab(tabId)
      }
    },

    async reportTick(platform, candidate, outcome, pagesVisited) {
      const resp = await http.apiFetch(
        'discovery_tick',
        http.apiUrl(`/api/opportunities/discovery/tick?platform=${platform}`),
        {
          method: 'POST',
          headers: http.apiHeaders(true),
          body: JSON.stringify({
            vacancy_id: candidate.vacancy_id,
            outcome,
            title: candidate.title,
            company: candidate.company,
            pages_visited: pagesVisited,
          }),
        },
      )
      const data = await resp.json()
      return {
        state: data.state,
        opened: data.opened ?? 0,
        scored: data.scored ?? 0,
        updatedAt: data.updated_at ?? null,
      }
    },

    async pauseSession(platform, reason) {
      await http.apiFetch(
        'discovery_pause',
        http.apiUrl(`/api/opportunities/discovery/session?platform=${platform}`),
        {
          method: 'POST',
          headers: http.apiHeaders(true),
          body: JSON.stringify({ action: 'pause', reason }),
        },
      )
    },

    async resumeSession(platform) {
      await http.apiFetch(
        'discovery_resume',
        http.apiUrl(`/api/opportunities/discovery/session?platform=${platform}`),
        {
          method: 'POST',
          headers: http.apiHeaders(true),
          body: JSON.stringify({ action: 'resume' }),
        },
      )
    },

    // Джиттер темпа — до минуты (`discovery_delay_ms`); голый setTimeout столько в MV3 не
    // живёт, воркер гасится и тик умирает до `scoreCandidate` (см. keep-alive.ts).
    sleep(ms) {
      return keepAliveSleep(ms)
    },

    staggerDelayMs: randomStaggerDelayMs,

    viewJitterMs: () => {
      const [lo, hi] = getRuntimeConfig().tuning.discovery_delay_ms
      // Сон = сколько добрать сверх alarm-периода (== lo по конвенции, см. discovery_delay_ms в
      // extension_runtime_config) до случайной точки в [lo, hi].
      return Math.random() * Math.max(0, hi - lo)
    },

    async reportTickSummary(summary) {
      try {
        await http.apiFetch(
          'discovery_tick_report',
          http.apiUrl('/api/opportunities/discovery/tick-report'),
          {
            method: 'POST',
            headers: http.apiHeaders(true),
            body: JSON.stringify({
              platforms_running: summary.platformsRunning,
              opened: summary.opened,
              scored: summary.scored,
              already_known: summary.alreadyKnown,
              parse_errors: summary.parseErrors,
              paused: summary.paused,
              bail_reason: summary.bailReason,
            }),
          },
        )
      } catch {
        /* heartbeat не критичен */
      }
    },
  }
}
