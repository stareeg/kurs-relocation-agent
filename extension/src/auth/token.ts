// EX-10: хранение и грубая проверка вида токена входа (X-Auth-Token) из Telegram-бота.
// Regex — копия frontend/src/lib/web-auth-token.ts (два разных npm-пакета, шарить импорт
// между frontend/ и extension/ нечем). Два формата:
// - обычный токен владельца: secrets.token_urlsafe(24) — ~32 символа [A-Za-z0-9_-];
// - переносимый гостевой (AUTH-2): cc.<base64url(аккаунт)>.<секрет>.

const STORAGE_KEY = 'authToken'

export function looksLikeBotAuthToken(raw: string): boolean {
  const token = raw.trim()
  if (/^cc\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{16,}$/.test(token)) return true
  return /^[A-Za-z0-9_-]{28,64}$/.test(token)
}

/** Личный токен из chrome.storage.local этого браузера (пусто, если не вставлен). */
export async function getStoredAuthToken(): Promise<string> {
  const cfg = await chrome.storage.local.get([STORAGE_KEY])
  return String(cfg[STORAGE_KEY] || '').trim()
}

export async function setStoredAuthToken(token: string): Promise<void> {
  await chrome.storage.local.set({ [STORAGE_KEY]: token.trim() })
}

/** Только локальная очистка — НИКОГДА не ходит на /auth/logout (§2.7 плана: одна запись
 * web_auth_token на всю инсталляцию, логаут расширения не должен рвать веб-сессию того же
 * человека на соседней вкладке). */
export async function clearStoredAuthToken(): Promise<void> {
  await chrome.storage.local.remove(STORAGE_KEY)
}

// Ключи, не привязанные к аккаунту — переживают logout: адрес сайта (webBaseUrl) и общий
// DOM-конфиг парсера hh.ru (обновляется централизованно с бэкенда, не персонален).
const ACCOUNT_AGNOSTIC_KEYS = new Set<string>(['webBaseUrl', 'hhParserSelectors', 'hhParserSelectorsEtag'])

/**
 * S-critical (2026-08-26, тот же класс бага, что резюме владельца в LLM-промптах): score-cache.ts
 * (`score:{vacancy_id}`) и qa-история (`qa:{vacancy_id}` в content/main.ts) кэшируют ЧУЖИЕ для
 * следующего аккаунта данные (вердикт скоринга под резюме прошлого аккаунта, текст чата) без
 * TTL короче 14 дней — на общей машине следующий вход другим токеном на миг (а то и дольше)
 * увидел бы их. Логаут обязан стирать весь персональный кэш `chrome.storage.local`, оставляя
 * только ACCOUNT_AGNOSTIC_KEYS. Вызывать из каждого onLogout (options/popup/dock) — и, для
 * подстраховки на случай входа новым токеном без явного «Выйти» (сейчас UI это исключает,
 * но handleLogin не должен полагаться на вызывающего), из onLogin тоже.
 */
export function clearAccountScopedStorage(): Promise<void> {
  return new Promise((resolve) => {
    chrome.storage.local.get(null, (all) => {
      if (chrome.runtime.lastError || !all) {
        resolve()
        return
      }
      const toRemove = Object.keys(all).filter((key) => !ACCOUNT_AGNOSTIC_KEYS.has(key))
      if (!toRemove.length) {
        resolve()
        return
      }
      chrome.storage.local.remove(toRemove, () => resolve())
    })
  })
}
