import {
  isAutoSyncCandidate,
  parseApplicationsFromJson,
  fetchApplicationsPreview,
  applySync,
} from './getmatch-applications-sync'

/**
 * Фоновый авто-синк откликов getmatch БЕЗ открытия страницы `/applications`.
 *
 * В отличие от hh (`negotiations-heartbeat.ts`, раз в 4 ч), getmatch не нужно дёргать так
 * часто: список откликов там меняется медленно, а владелец просил максимум ~2 прогона в сутки.
 * Поэтому здесь нет таймера — прогон запускается ТОЛЬКО при открытии вкладки getmatch.ru
 * (заходит ли пользователь в /applications или нет — неважно), а троттлинг через
 * `chrome.storage.local` гарантирует не чаще 2 раз в день (12 ч). Если пользователь не заходил
 * на getmatch — синк просто не запускается (ничего не крашится; догонится при следующем заходе).
 *
 * Данные читаются тем же способом, что и страница «Отклики» — `fetch('/api/applications/candidate?section=all')`
 * с `credentials: 'same-origin'` (cookies подставляются сами), но в отличие от DOM-вкладки этот
 * JSON содержит ВСЕ отклики (new+approved+rejected) одним запросом, включая отказы и одобрения,
 * которые DOM-страница показывает только на своих вкладках.
 */

const HEARTBEAT_MIN_INTERVAL_MS = 12 * 60 * 60 * 1000 // ~2 раза в сутки
const HEARTBEAT_LOCK_KEY = 'jh_gm_heartbeat_last_run'
const FIRST_RUN_DELAY_MS = 8_000

function isExtensionAlive() {
  try {
    return typeof chrome !== 'undefined' && Boolean(chrome.runtime?.id)
  } catch {
    return false
  }
}

function heartbeatSendMessage(message: unknown): Promise<any> {
  return new Promise((resolve) => {
    if (!isExtensionAlive()) {
      resolve({ ok: false, error: 'Расширение обновлено — обновите страницу getmatch.ru (F5)' })
      return
    }
    try {
      chrome.runtime.sendMessage(message, (response) => {
        if (chrome.runtime.lastError) {
          resolve({ ok: false, error: chrome.runtime.lastError.message })
          return
        }
        resolve(response)
      })
    } catch (err) {
      resolve({ ok: false, error: String((err as Error).message || err) })
    }
  })
}

/** Мягкая лидер-элекция через `chrome.storage.local`: если другая вкладка уже прогнала синк в
 *  пределах 12 ч — не дублируем сетевой+LLM трафик. */
function tryClaimHeartbeat(): Promise<boolean> {
  return new Promise((resolve) => {
    chrome.storage.local.get(HEARTBEAT_LOCK_KEY, (result) => {
      const last = Number(result[HEARTBEAT_LOCK_KEY] || 0)
      const now = Date.now()
      if (now - last < HEARTBEAT_MIN_INTERVAL_MS - 60_000) {
        resolve(false)
        return
      }
      chrome.storage.local.set({ [HEARTBEAT_LOCK_KEY]: now }, () => resolve(true))
    })
  })
}

/** GET /api/applications/candidate?section=all&offset=0&limit=100 — все отклики одним запросом. */
async function fetchApplicationsPayload(): Promise<unknown> {
  const response = await fetch('/api/applications/candidate?section=all&offset=0&limit=100', {
    credentials: 'same-origin',
    headers: { 'content-type': 'application/json', 'x-client-platform': 'web' },
  })
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.json()
}

async function runHeartbeatOnce() {
  if (!isExtensionAlive()) return
  const claimed = await tryClaimHeartbeat()
  if (!claimed) return

  try {
    const payload = await fetchApplicationsPayload()
    const items = parseApplicationsFromJson(payload)
    if (!items.length) return

    const { error } = await fetchApplicationsPreview(items, heartbeatSendMessage)
    if (error) {
      console.warn('[Job Hunter] getmatch heartbeat preview:', error)
      return
    }

    const candidates = items.filter(isAutoSyncCandidate)
    if (!candidates.length) return

    const data = await applySync(candidates, { force: false }, heartbeatSendMessage)
    const synced = data?.synced_count ?? 0
    if (synced > 0) {
      console.info(`[Job Hunter] getmatch авто-синк: обновлено ${synced}`)
    }
  } catch (err) {
    // Не залогинен на getmatch / сеть моргнула — молча пропускаем, догоним при следующем заходе.
    console.warn('[Job Hunter] getmatch heartbeat:', err)
  }
}

/** Единственный прогон почти сразу после открытия вкладки getmatch.ru (без таймера-повторителя):
 *  троттлинг «не чаще 2 раз в сутки» живёт в tryClaimHeartbeat на общем storage. */
function startGetmatchHeartbeat() {
  setTimeout(() => void runHeartbeatOnce(), FIRST_RUN_DELAY_MS)
}

export { startGetmatchHeartbeat }
