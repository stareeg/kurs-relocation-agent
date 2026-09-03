// L-04: клиентский RUM — LCP/INP + метки «клик → ttfb / first_token / done».
// Пачка уходит в POST /api/logs/frontend (та же ручка, что error-capture), витрина «Логи».

const FLUSH_ENDPOINT = "/api/logs/frontend"
const FLUSH_INTERVAL_MS = 20_000
const MAX_BUFFER = 100

export type RumKind = "rum_lcp" | "rum_inp" | "rum_ttfb" | "rum_first_token" | "rum_done"

export interface RumEntry {
  ts: string
  level: "INFO"
  kind: RumKind
  message: string
  duration_ms: number
  url?: string
  endpoint?: string
}

type Interaction = {
  name: string
  endpoint?: string
  t0: number
  ttfbMs?: number
  firstTokenMs?: number
  doneMs?: number
}

const buffer: RumEntry[] = []
let active: Interaction | null = null
let installed = false
let flushTimer: ReturnType<typeof setInterval> | undefined
/** Лучший (наибольший) INP за сессию вкладки — отдаём при hide. */
let inpCandidateMs = 0

function pageUrl(): string | undefined {
  try {
    return typeof window !== "undefined" ? window.location.href : undefined
  } catch {
    return undefined
  }
}

function push(entry: Omit<RumEntry, "ts" | "level"> & { ts?: string }): void {
  buffer.push({
    ts: entry.ts ?? new Date().toISOString(),
    level: "INFO",
    kind: entry.kind,
    message: entry.message,
    duration_ms: Math.round(entry.duration_ms),
    url: entry.url ?? pageUrl(),
    endpoint: entry.endpoint,
  })
  if (buffer.length > MAX_BUFFER) {
    buffer.splice(0, buffer.length - MAX_BUFFER)
  }
}

/** Текущий буфер (для тестов / отладки). */
export function getRumBuffer(): readonly RumEntry[] {
  return buffer
}

/** Сброс буфера и активного взаимодействия (тесты). */
export function resetRumForTests(): void {
  buffer.length = 0
  active = null
  inpCandidateMs = 0
}

/**
 * Начать измерение взаимодействия (обычно по клику «Отправить» / «Собрать»).
 * Повторный begin закрывает предыдущее без done (обрыв).
 */
export function beginInteraction(name: string, endpoint?: string): void {
  if (active) {
    // Неполный цикл не пишем как done — только оставляем частичные метки, если были.
    active = null
  }
  active = {
    name,
    endpoint,
    t0: performance.now(),
  }
}

export function markTtfb(): void {
  if (!active || active.ttfbMs != null) return
  const ms = performance.now() - active.t0
  active.ttfbMs = ms
  push({
    kind: "rum_ttfb",
    message: `клик → первый байт · ${active.name}`,
    duration_ms: ms,
    endpoint: active.endpoint,
  })
}

export function markFirstToken(): void {
  if (!active || active.firstTokenMs != null) return
  const ms = performance.now() - active.t0
  active.firstTokenMs = ms
  push({
    kind: "rum_first_token",
    message: `клик → первый токен · ${active.name}`,
    duration_ms: ms,
    endpoint: active.endpoint,
  })
}

export function markDone(): void {
  if (!active || active.doneMs != null) return
  const ms = performance.now() - active.t0
  active.doneMs = ms
  push({
    kind: "rum_done",
    message: `клик → полный ответ · ${active.name}`,
    duration_ms: ms,
    endpoint: active.endpoint,
  })
  active = null
}

/** Отменить незавершённое взаимодействие (ошибка сети / abort). */
export function cancelInteraction(): void {
  active = null
}

async function flush(): Promise<void> {
  if (buffer.length === 0) return
  const sent = buffer.splice(0, buffer.length)
  try {
    const res = await fetch(FLUSH_ENDPOINT, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entries: sent }),
    })
    if (!res.ok) {
      // вернуть в буфер — следующий флаш повторит
      buffer.unshift(...sent)
      if (buffer.length > MAX_BUFFER) buffer.length = MAX_BUFFER
    }
  } catch {
    buffer.unshift(...sent)
    if (buffer.length > MAX_BUFFER) buffer.length = MAX_BUFFER
  }
}

function flushOnUnload(): void {
  reportInpIfAny()
  if (buffer.length === 0) return
  const sent = buffer.splice(0, buffer.length)
  const blob = new Blob([JSON.stringify({ entries: sent })], {
    type: "application/json",
  })
  if (!navigator.sendBeacon(FLUSH_ENDPOINT, blob)) {
    buffer.unshift(...sent)
  }
}

function observeLcp(): void {
  if (typeof PerformanceObserver === "undefined") return
  try {
    const po = new PerformanceObserver((list) => {
      const entries = list.getEntries()
      const last = entries[entries.length - 1]
      if (!last) return
      // LCP обновляется несколько раз — пишем каждое улучшение; витрине ок.
      push({
        kind: "rum_lcp",
        message: "LCP",
        duration_ms: last.startTime,
      })
    })
    po.observe({ type: "largest-contentful-paint", buffered: true })
  } catch {
    // браузер без LCP
  }
}

function observeInp(): void {
  if (typeof PerformanceObserver === "undefined") return
  try {
    const po = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        // Event Timing: interaction latency ≈ duration (упрощённый INP-кандидат).
        const e = entry as PerformanceEntry & { interactionId?: number; duration: number }
        if (!e.interactionId) continue
        if (e.duration > inpCandidateMs) inpCandidateMs = e.duration
      }
    })
    po.observe({
      type: "event",
      buffered: true,
      durationThreshold: 40,
    } as PerformanceObserverInit)
  } catch {
    // Safari / старые движки
  }
}

function reportInpIfAny(): void {
  if (inpCandidateMs <= 0) return
  push({
    kind: "rum_inp",
    message: "INP",
    duration_ms: inpCandidateMs,
  })
  inpCandidateMs = 0
}

/** Один раз при старте приложения (main.tsx). */
export function initRum(): void {
  if (installed || typeof window === "undefined") return
  installed = true
  observeLcp()
  observeInp()
  window.addEventListener("beforeunload", flushOnUnload)
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) flushOnUnload()
  })
  flushTimer = setInterval(() => void flush(), FLUSH_INTERVAL_MS)
}

/** Для тестов: остановить интервал. */
export function stopRumForTests(): void {
  if (flushTimer !== undefined) clearInterval(flushTimer)
  flushTimer = undefined
  installed = false
}

/** Принудительный flush (тесты / отладка). */
export async function flushRum(): Promise<void> {
  await flush()
}
