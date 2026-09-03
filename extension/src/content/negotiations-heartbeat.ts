import { isAutoSyncCandidate, parseNegotiationsFromRoot, fetchNegotiationsPreview, applySync } from './negotiations-sync'
import { showToast } from './dock'

/**
 * Автосинк откликов БЕЗ захода на `/applicant/negotiations`. Пока открыта любая вкладка
 * hh.ru, раз в HEARTBEAT_INTERVAL_MS тихо читаем первую страницу списка (свежая активность) через
 * `fetch` + `DOMParser` — не через service worker: `fetch` из фонового скрипта идёт с origin
 * `chrome-extension://…`, cookies hh.ru туда не гарантированы (SameSite), тогда как `fetch` из
 * контент-скрипта уже исполняется в контексте hh.ru.
 */

const HEARTBEAT_INTERVAL_MS = 4 * 60 * 60 * 1000; // ~раз в 4 часа (было 15 мин — слишком частый LLM-трафик)
const HEARTBEAT_LOCK_KEY = 'jh_neg_heartbeat_last_run';
const FIRST_RUN_DELAY_MS = 20_000;

function isExtensionAlive() {
  try {
    return typeof chrome !== 'undefined' && Boolean(chrome.runtime?.id);
  } catch {
    return false;
  }
}

function heartbeatSendMessage(message): Promise<any> {
  return new Promise((resolve) => {
    if (!isExtensionAlive()) {
      resolve({ ok: false, error: 'Расширение обновлено — обновите страницу hh.ru (F5)' });
      return;
    }
    try {
      chrome.runtime.sendMessage(message, (response) => {
        if (chrome.runtime.lastError) {
          resolve({ ok: false, error: chrome.runtime.lastError.message });
          return;
        }
        resolve(response);
      });
    } catch (err) {
      resolve({ ok: false, error: String(err.message || err) });
    }
  });
}

/** Мягкая лидер-элекция через общий `chrome.storage.local`: если другая вкладка (или эта же, на
 *  предыдущем тике) уже прогнала heartbeat в пределах интервала — не дублируем сетевой+LLM трафик. */
function tryClaimHeartbeat() {
  return new Promise((resolve) => {
    chrome.storage.local.get(HEARTBEAT_LOCK_KEY, (result) => {
      const last = result[HEARTBEAT_LOCK_KEY] || 0;
      const now = Date.now();
      if (now - last < HEARTBEAT_INTERVAL_MS - 5000) {
        resolve(false);
        return;
      }
      chrome.storage.local.set({ [HEARTBEAT_LOCK_KEY]: now }, () => resolve(true));
    });
  });
}

async function fetchNegotiationsDocument() {
  const response = await fetch('/applicant/negotiations', { credentials: 'same-origin' });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const html = await response.text();
  return new DOMParser().parseFromString(html, 'text/html');
}

async function runHeartbeatOnce() {
  if (!isExtensionAlive()) return;
  const claimed = await tryClaimHeartbeat();
  if (!claimed) return;

  try {
    const doc = await fetchNegotiationsDocument();
    const items = parseNegotiationsFromRoot(doc);
    if (!items.length) return;

    const { error } = await fetchNegotiationsPreview(items, heartbeatSendMessage);
    if (error) {
      console.warn('[Job Hunter] heartbeat preview:', error);
      return;
    }

    const candidates = items.filter(isAutoSyncCandidate);
    if (!candidates.length) return;

    const data = await applySync(candidates, { force: false }, heartbeatSendMessage);
    const synced = data?.synced_count ?? 0;
    if (synced > 0) {
      showToast(`Автосинк откликов: обновлено ${synced}`);
    }
  } catch (err) {
    console.warn('[Job Hunter] negotiations heartbeat:', err);
  }
}

/** Запускает фоновый цикл: первый прогон почти сразу (не тормозит загрузку страницы), дальше
 *  каждые HEARTBEAT_INTERVAL_MS — пока открыта эта вкладка hh.ru. */
function startNegotiationsHeartbeat() {
  setTimeout(() => void runHeartbeatOnce(), FIRST_RUN_DELAY_MS);
  setInterval(() => void runHeartbeatOnce(), HEARTBEAT_INTERVAL_MS);
}

export { startNegotiationsHeartbeat };
