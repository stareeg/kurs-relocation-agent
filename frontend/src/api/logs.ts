import { apiFetchBlob, getRecentSuccesses } from "@/api/client"
import { captureClientEnv, flushNow, getCapturedErrors } from "@/lib/error-capture"

export type LogsBundleResult = "full" | "fallback"

const SETTINGS_KEY_PREFIX = "copilot."
const SECRET_KEY_HINTS = ["token", "key", "secret", "password"]

function stamp(): string {
  return new Date().toISOString().slice(0, 16).replace(/[T:]/g, "-")
}

function triggerDownload(blob: Blob, filename: string): void {
  const href = URL.createObjectURL(blob)
  const anchor = document.createElement("a")
  anchor.href = href
  anchor.download = filename
  anchor.rel = "noopener"
  // Без appendChild часть браузеров глотает программный click, особенно после await.
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(href)
}

// Ключи настроек, не значения секретов — на случай, если в будущем появится ключ вида *_token.
function readLocalStorageSettings(): Record<string, string> {
  const out: Record<string, string> = {}
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i)
    if (!key || !key.startsWith(SETTINGS_KEY_PREFIX)) continue
    if (SECRET_KEY_HINTS.some((hint) => key.toLowerCase().includes(hint))) continue
    out[key] = localStorage.getItem(key) ?? ""
  }
  return out
}

/** FR2-19: бэкенд недоступен — собрать, что есть на клиенте, и скачать JSON вместо zip-бандла. */
function downloadFallbackBundle(): void {
  const payload = {
    generated_at: new Date().toISOString(),
    reason: "backend_unreachable",
    user_agent: navigator.userAgent,
    url: window.location.href,
    localStorage_settings: readLocalStorageSettings(),
    recent_successful_requests: getRecentSuccesses(),
    captured_errors: getCapturedErrors(),
  }
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" })
  triggerDownload(blob, `copilot-incident-frontend-only-${stamp()}.json`)
}

/** Скачать инцидент-бандл: zip с бэкенда, либо клиентский JSON-фолбэк, если API недостижимо.
 * Возвращает, какой путь сработал — для разного текста тоста.
 *
 * Перед запросом досылаем окружение вкладки и незафлашенные крошки: иначе браузер, версия и
 * последние ошибки попали бы в базу только через 15 секунд — уже после сборки архива. */
export async function downloadLogsBundle(): Promise<LogsBundleResult> {
  try {
    captureClientEnv()
    await flushNow()
    const { blob, filename } = await apiFetchBlob("/api/logs/bundle", {
      skipSeriousToast: true,
    })
    triggerDownload(blob, filename ?? `support_bundle-${stamp()}.zip`)
    return "full"
  } catch {
    downloadFallbackBundle()
    return "fallback"
  }
}
