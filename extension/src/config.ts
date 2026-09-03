// Централизованный конфиг расширения. Хранится в chrome.storage.local.
// EX-17: пользователь вводит только адрес сайта (webBaseUrl) — apiBaseUrl выводится
// автоматически (deriveApiBaseUrl). Вход только по личному токену из бота (authToken,
// X-Auth-Token) — бот один на всю инсталляцию, его @handle приходит в /auth/status.bot_username
// (auth/render.ts), отдельного поля под него не требуется. Статический X-API-Key убран: раньше
// был единственным способом достучаться до API без входа, но с приходом личного токена (AUTH-1)
// просить пользователя вручную вставлять ещё один секрет стало избыточно.

// EX-15 (§4.1): дефолт API — не литерал, а define точки сборки (build.mjs подставляет
// EXT_API_BASE_URL при сборке .zip под прод-домен, без правок этого файла). typeof-фоллбэк —
// для запуска вне esbuild (tsx-тесты, где define не существует).
// DEFAULT_WEB_BASE_URL той же природы (WEB_BASE_URL define, build.mjs — тот же apiBaseUrl):
// раньше это был литерал 'http://localhost:5173', из-за чего EXT_API_BASE_URL на сборке ни на
// что не влиял — deriveApiBaseUrl(DEFAULT_WEB_BASE_URL) на localhost всегда переписывал порт на
// 8000 и возвращал localhost:8000, независимо от прод-домена. Друг, скачавший .zip, получал
// рабочий на вид адрес сайта в options, но реально «Failed to fetch» на бэк, пока не заходил в
// options и не менял адрес руками.
declare const API_BASE_URL: string | undefined
declare const WEB_BASE_URL: string | undefined
const BUNDLED_API_BASE_URL =
  typeof API_BASE_URL !== 'undefined' ? API_BASE_URL : 'http://localhost:8000'
const BUNDLED_WEB_BASE_URL =
  typeof WEB_BASE_URL !== 'undefined' ? WEB_BASE_URL : 'http://localhost:5173'

export const DEFAULT_WEB_BASE_URL = BUNDLED_WEB_BASE_URL
export const DEFAULT_API_BASE_URL = BUNDLED_API_BASE_URL

export interface ExtensionConfig {
  /** Адрес сайта — единственное, что вводит пользователь (options/popup). */
  webBaseUrl: string
  /** База API копайлота — выводится из webBaseUrl (см. deriveApiBaseUrl), отдельно не хранится. */
  apiBaseUrl: string
  /** Личный токен из Telegram-бота (X-Auth-Token) — единственный путь входа. */
  authToken: string
}

/** Ключи в chrome.storage.local. */
export const CONFIG_KEYS = ['webBaseUrl', 'authToken'] as const

/** Убирает хвостовой слэш, подставляет дефолт на пустую строку. */
export function normalizeBaseUrl(raw: string | undefined, fallback: string): string {
  return (raw || fallback).trim().replace(/\/$/, '')
}

/** Сегодня API и веб-дэшборд — разные origin в локальной разработке (:8000 и :5173, единого
 * reverse-proxy нет): на localhost/127.0.0.1 подставляем порт API по конвенции. На проде (после
 * `vm_multitenant_hosting`, Caddy на одном домене) apiBaseUrl совпадает с webBaseUrl. */
export function deriveApiBaseUrl(webBaseUrl: string): string {
  try {
    const url = new URL(webBaseUrl)
    if (url.hostname === 'localhost' || url.hostname === '127.0.0.1') {
      url.port = '8000'
    }
    return url.origin
  } catch {
    return DEFAULT_API_BASE_URL
  }
}

/** Читает весь конфиг из storage с подстановкой дефолтов. */
export async function loadConfig(): Promise<ExtensionConfig> {
  const cfg = await chrome.storage.local.get(CONFIG_KEYS as unknown as string[])
  const webBaseUrl = normalizeBaseUrl(cfg.webBaseUrl, DEFAULT_WEB_BASE_URL)
  return {
    webBaseUrl,
    apiBaseUrl: deriveApiBaseUrl(webBaseUrl),
    authToken: (cfg.authToken || '').trim(),
  }
}
