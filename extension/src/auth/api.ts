// EX-10: вызовы бэкенда для входа расширения — прямой fetch со страницы (без background-релея),
// options.ts/popup.ts и так делают прямые fetch со своих страниц, тот же паттерн.

/** Зеркало api/schemas/auth.py: AuthStatusResponse. */
export interface AuthStatus {
  authed: boolean
  auth_token_configured: boolean
  openrouter_key_configured: boolean
  extension_confirmed: boolean
  bot_configured: boolean
  bot_username: string | null
  account_username: string | null
}

/** X-Auth-Token (личный токен) — единственный путь входа расширения (EX-17: статический
 * X-API-Key убран, см. config.ts). */
export function buildAuthHeaders(authToken: string): Record<string, string> {
  const headers: Record<string, string> = {}
  if (authToken) headers['X-Auth-Token'] = authToken
  return headers
}

/** GET /auth/status — публичная ручка, отдаёт authed=false вместо HTTP-ошибки на плохой токен. */
export async function fetchAuthStatus(baseUrl: string, authToken: string): Promise<AuthStatus> {
  const r = await fetch(`${baseUrl}/auth/status`, {
    headers: buildAuthHeaders(authToken),
  })
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}

/** POST /auth/token — единственный путь, который умеет «усыновить» переносимый cc.… токен
 * (AUTH-2). Возвращает AuthStatus напрямую — второй вызов /auth/status не нужен. Сервер заодно
 * ставит Set-Cookie — расширение её игнорирует, токен в chrome.storage.local остаётся
 * единственным источником правды на клиенте (см. §2.1 плана). */
export async function loginWithToken(baseUrl: string, rawToken: string): Promise<AuthStatus> {
  const r = await fetch(`${baseUrl}/auth/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token: rawToken }),
  })
  if (!r.ok) {
    const detail = await r.json().catch(() => null)
    throw new Error(detail?.detail || `HTTP ${r.status}`)
  }
  return r.json()
}

/** EX-10 fix: content-script-safe варианты для дока на hh.ru/getmatch.ru. Прямой fetch() выше
 * там не работает — content script шлёт запросы с Origin страницы (https://hh.ru), а не
 * chrome-extension://<id>, и бэк такой Origin в CORS не пускает (options.ts/popup.ts — страницы
 * самого расширения, для них chrome-extension:// подходит под extension_origin_regex, поэтому
 * прямой fetch() выше для них ок). Релей через background — тот шлёт от имени расширения. */
function relayToBackground<T>(action: string, payload: unknown): Promise<T> {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage({ action, payload }, (response) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message))
        return
      }
      if (!response?.ok) {
        reject(new Error(response?.error || `${action} failed`))
        return
      }
      resolve(response.data as T)
    })
  })
}

export function fetchAuthStatusViaBackground(authToken: string): Promise<AuthStatus> {
  return relayToBackground('auth_status', { token: authToken })
}

export function loginWithTokenViaBackground(rawToken: string): Promise<AuthStatus> {
  return relayToBackground('login', { token: rawToken })
}
