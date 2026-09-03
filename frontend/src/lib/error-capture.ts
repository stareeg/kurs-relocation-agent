// Захват того, что происходит в браузере: ошибки (window.onerror, unhandledrejection, неудачные
// HTTP-ответы из api/client.ts, падения React в ErrorBoundary) и «хлебные крошки» вокруг них —
// переходы между разделами и снимок окружения вкладки. Крошки нужны затем же, зачем ошибки:
// по одной строке «TypeError» не понять, что человек делал за секунду до неё.
//
// Кольцевой буфер в localStorage (переживает reload/краш вкладки), фоновый сброс пачкой на
// POST /api/logs/frontend → таблица copilot_logs → инцидент-бандл в «Параметрах».

const STORAGE_KEY = "copilot.error-capture.v1"
const MAX_ENTRIES = 200
const FLUSH_INTERVAL_MS = 15_000
const FLUSH_ENDPOINT = "/api/logs/frontend"

export type CapturedLevel = "ERROR" | "WARNING" | "INFO"
export type CapturedKind =
  "onerror" | "unhandledrejection" | "http" | "boundary" | "network" | "nav" | "client_env"

export interface CapturedEntry {
  ts: string
  level: CapturedLevel
  kind: CapturedKind
  message: string
  stack?: string
  url?: string
  endpoint?: string
  status?: number
  duration_ms?: number
}

function pageUrl(): string | undefined {
  try {
    return typeof window !== "undefined" ? window.location.href : undefined
  } catch {
    return undefined
  }
}

function readBuffer(): CapturedEntry[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    return Array.isArray(parsed) ? (parsed as CapturedEntry[]) : []
  } catch {
    return []
  }
}

function writeBuffer(entries: CapturedEntry[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(entries.slice(-MAX_ENTRIES)))
  } catch {
    // localStorage переполнен/недоступен (приватный режим) — буфер теряется, не критично
  }
}

/** Добавить запись в кольцевой буфер. Флаш — фоново, по интервалу или перед закрытием вкладки. */
export function captureError(entry: Omit<CapturedEntry, "ts"> & { ts?: string }): void {
  const buffer = readBuffer()
  buffer.push({ ts: entry.ts ?? new Date().toISOString(), ...entry })
  writeBuffer(buffer)
}

/** Буфер как есть — для клиентского фолбэк-бандла, когда бэкенд недоступен. */
export function getCapturedErrors(): CapturedEntry[] {
  return readBuffer()
}

/** Буфер не должен переживать logout: на общей машине незафлашенные ошибки аккаунта A
 * иначе долетают на /api/logs/frontend уже под сессией аккаунта B.
 * Звать из AuthProvider.clearCache() рядом с qc.clear(). */
export function clearBuffer(): void {
  writeBuffer([])
}

/** Точка входа для api/client.ts: неудачный HTTP-ответ (не сетевой сбой — тот отдельно). */
export function captureHttpError(params: {
  endpoint: string
  status: number
  duration_ms: number
}): void {
  captureError({
    level: params.status >= 500 ? "ERROR" : "WARNING",
    kind: "http",
    message: `HTTP ${params.status} ${params.endpoint}`,
    endpoint: params.endpoint,
    status: params.status,
    duration_ms: Math.round(params.duration_ms),
    url: pageUrl(),
  })
}

/** Крошка «пользователь перешёл в раздел» — контекст для ошибок, случившихся следом.
 * Пишется только после смены location: клик, который роутер не увидел, сюда не попадает. */
export function captureNav(path: string): void {
  captureError({ level: "INFO", kind: "nav", message: `Экран ${path}`, url: pageUrl() })
}

/** Намерение уйти в другой раздел — до смены location. Если следом нет «Экран …», клик съели. */
export function captureNavClick(from: string, to: string): void {
  captureError({
    level: "INFO",
    kind: "nav",
    message: `Клик ${from} → ${to}`,
    url: pageUrl(),
    endpoint: to,
  })
}

function openOverlaySnapshot(): string {
  if (typeof document === "undefined") return ""
  try {
    return Array.from(document.querySelectorAll("[data-state='open']"))
      .map((el) => el.getAttribute("data-slot") || el.tagName.toLowerCase())
      .slice(0, 8)
      .join(",")
  } catch {
    return ""
  }
}

/** Клик по разделу был, location через ~250 мс всё ещё прежний. */
export function captureNavBlocked(from: string, to: string): void {
  const overlays = openOverlaySnapshot()
  captureError({
    level: "WARNING",
    kind: "nav",
    message: overlays
      ? `Клик не сменил экран ${from} → ${to} (open: ${overlays})`
      : `Клик не сменил экран ${from} → ${to}`,
    url: pageUrl(),
    endpoint: to,
  })
}

/** Снимок окружения вкладки: без него по одной ошибке не понять, где и в чём она случилась.
 * Пишется на старте приложения и повторно перед выгрузкой бандла логов. */
export function captureClientEnv(): void {
  try {
    const parts = [
      navigator.userAgent,
      `viewport=${window.innerWidth}x${window.innerHeight}`,
      `dpr=${window.devicePixelRatio}`,
      `tz=${Intl.DateTimeFormat().resolvedOptions().timeZone}`,
      `lang=${navigator.language}`,
      `online=${navigator.onLine}`,
    ]
    captureError({ level: "INFO", kind: "client_env", message: parts.join(" | "), url: pageUrl() })
  } catch {
    // Экзотический браузер без части API — окружение просто не попадёт в лог.
  }
}

/** Немедленно отправить буфер (перед выгрузкой бандла — иначе свежие крошки в него не попадут). */
export async function flushNow(): Promise<void> {
  await flush()
}

/** fetch упал до ответа (бэкенд лежит / таймаут AbortController). */
export function captureNetworkError(params: {
  endpoint: string
  reason: "network" | "timeout"
  duration_ms: number
}): void {
  captureError({
    level: "ERROR",
    kind: "network",
    message:
      params.reason === "timeout" ? `Timeout ${params.endpoint}` : `Network ${params.endpoint}`,
    endpoint: params.endpoint,
    status: 0,
    duration_ms: Math.round(params.duration_ms),
    url: pageUrl(),
  })
}

/** Отправить буфер на бэкенд и очистить только отправленные записи (новые за время запроса — не теряются).
 * Сырой fetch, не api/client.ts — иначе неудачный флаш сам себя рекурсивно залогировал бы. */
async function flush(): Promise<void> {
  const sent = readBuffer()
  if (sent.length === 0) return
  try {
    const res = await fetch(FLUSH_ENDPOINT, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entries: sent }),
    })
    if (!res.ok) return
    const remaining = readBuffer().slice(sent.length)
    writeBuffer(remaining)
  } catch {
    // бэкенд недоступен — буфер остаётся, следующий флаш попробует снова
  }
}

function flushOnUnload(): void {
  const sent = readBuffer()
  if (sent.length === 0) return
  const blob = new Blob([JSON.stringify({ entries: sent })], { type: "application/json" })
  if (navigator.sendBeacon(FLUSH_ENDPOINT, blob)) {
    writeBuffer([])
  }
}

let installed = false

/** Один раз при старте приложения (main.tsx): вешает глобальные хендлеры + фоновый флаш. */
export function initErrorCapture(): void {
  if (installed) return
  installed = true

  captureClientEnv()

  window.onerror = (message, source, _lineno, _colno, error) => {
    captureError({
      level: "ERROR",
      kind: "onerror",
      message: typeof message === "string" ? message : "Необработанная ошибка скрипта",
      stack: error?.stack,
      url: source ?? window.location.href,
    })
  }

  window.addEventListener("unhandledrejection", (event) => {
    const reason: unknown = event.reason
    captureError({
      level: "ERROR",
      kind: "unhandledrejection",
      message: reason instanceof Error ? reason.message : String(reason),
      stack: reason instanceof Error ? reason.stack : undefined,
      url: window.location.href,
    })
  })

  window.addEventListener("beforeunload", flushOnUnload)
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) flushOnUnload()
  })

  setInterval(() => void flush(), FLUSH_INTERVAL_MS)
}
