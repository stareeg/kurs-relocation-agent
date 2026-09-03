import {
  ApiError,
  errorMessageFromBody,
  LLM_TIMEOUT_MS,
  NETWORK_UNAVAILABLE_MSG,
  REQUEST_TIMEOUT_MSG,
} from "@/api/client"
import { captureHttpError, captureNetworkError } from "@/lib/error-capture"
import { beginInteraction, cancelInteraction, markDone, markFirstToken, markTtfb } from "@/lib/rum"

export type SseCanonicalEvent = "part" | "progress" | "done" | "error"

export interface SseEvent {
  seq: number | null
  event: string
  data: Record<string, unknown>
}

const BASE = import.meta.env.VITE_API_BASE ?? ""

export type StreamSseOptions = {
  method?: string
  body?: unknown
  headers?: Record<string, string>
  signal?: AbortSignal
  /** 0 — без таймера. По умолчанию LLM_TIMEOUT_MS. */
  timeoutMs?: number
  /** Для переподключения (L-39): уйдёт в заголовок Last-Event-ID. */
  lastEventId?: number | string | null
  /**
   * L-04: имя взаимодействия для RUM (клик → ttfb / first_token / done).
   * Если задано — метки уходят батчем в /api/logs/frontend.
   */
  rumInteraction?: string
  onEvent: (e: SseEvent) => void
}

// Разбор одного SSE-кадра (id/event/data).
function parseFrame(frame: string): SseEvent | null {
  let event = "message"
  let seq: number | null = null
  const dataLines: string[] = []
  for (const raw of frame.split("\n")) {
    const line = raw.replace(/\r$/, "")
    if (line.startsWith(":")) continue // комментарий / heartbeat
    if (line.startsWith("id:")) {
      const v = line.slice(3).trim()
      seq = v === "" ? null : Number(v)
    } else if (line.startsWith("event:")) {
      event = line.slice(6).trim()
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).replace(/^ /, ""))
    }
  }
  if (dataLines.length === 0) return null
  let data: Record<string, unknown>
  try {
    data = JSON.parse(dataLines.join("\n")) as Record<string, unknown>
  } catch {
    data = { raw: dataLines.join("\n") }
  }
  return { seq, event, data }
}

/** Прогнать кадры из буфера, вернуть остаток. Экспорт для тестов. */
export function drainFrames(buffer: string, onEvent: (e: SseEvent) => void): string {
  let sep: number
  let rest = buffer
  while ((sep = rest.indexOf("\n\n")) !== -1) {
    const frame = rest.slice(0, sep)
    rest = rest.slice(sep + 2)
    const ev = parseFrame(frame)
    if (ev) onEvent(ev)
  }
  return rest
}

/** Семантический подтип из data.type (канон A-14) либо само SSE-событие. */
export function eventKind(e: SseEvent): string {
  const t = e.data.type
  return typeof t === "string" && t.length > 0 ? t : e.event
}

/** Терминальный кадр единого контракта. */
export function isTerminalSse(e: SseEvent): boolean {
  return e.event === "done" || e.event === "error"
}

/**
 * Единый SSE-клиент (A-14): `Accept: text/event-stream`, события part/progress/done/error,
 * heartbeat-комментарии игнорируются парсером.
 */
export async function streamSse(path: string, options: StreamSseOptions): Promise<void> {
  const {
    method = "POST",
    body,
    headers = {},
    signal,
    timeoutMs = LLM_TIMEOUT_MS,
    lastEventId,
    rumInteraction,
    onEvent,
  } = options

  const controller = new AbortController()
  const startedAt = performance.now()
  let timedOut = false
  let timer: ReturnType<typeof setTimeout> | undefined
  if (timeoutMs > 0) {
    timer = setTimeout(() => {
      timedOut = true
      controller.abort()
    }, timeoutMs)
  }

  const abortOuter = () => controller.abort()
  if (signal) {
    if (signal.aborted) abortOuter()
    else signal.addEventListener("abort", abortOuter, { once: true })
  }

  const reqHeaders: Record<string, string> = {
    Accept: "text/event-stream",
    ...headers,
  }
  let reqBody: string | undefined
  if (body !== undefined) {
    reqHeaders["Content-Type"] = reqHeaders["Content-Type"] ?? "application/json"
    reqBody = typeof body === "string" ? body : JSON.stringify(body)
  }
  if (lastEventId != null && lastEventId !== "") {
    reqHeaders["Last-Event-ID"] = String(lastEventId)
  }

  if (rumInteraction) {
    beginInteraction(rumInteraction, path)
  }

  let sawFirstToken = false
  let finished = false
  const onEventRum = (e: SseEvent) => {
    if (rumInteraction && !sawFirstToken && e.event === "part") {
      sawFirstToken = true
      markFirstToken()
    }
    if (rumInteraction && isTerminalSse(e)) {
      finished = true
      if (e.event === "done") markDone()
      else cancelInteraction()
    }
    onEvent(e)
  }

  try {
    let response: Response
    try {
      response = await fetch(`${BASE}${path}`, {
        method,
        credentials: "include",
        headers: reqHeaders,
        body: reqBody,
        signal: controller.signal,
      })
    } catch (err) {
      const duration_ms = performance.now() - startedAt
      if (rumInteraction) cancelInteraction()
      if (signal?.aborted && !timedOut) throw err
      if (timedOut) {
        captureNetworkError({ endpoint: path, reason: "timeout", duration_ms })
        throw new ApiError(0, REQUEST_TIMEOUT_MSG)
      }
      captureNetworkError({ endpoint: path, reason: "network", duration_ms })
      throw new ApiError(0, NETWORK_UNAVAILABLE_MSG)
    }

    if (response.status === 401) {
      if (rumInteraction) cancelInteraction()
      throw new ApiError(401, "Не авторизован")
    }
    if (!response.ok) {
      if (rumInteraction) cancelInteraction()
      let errBody: unknown
      try {
        errBody = await response.json()
      } catch {
        errBody = undefined
      }
      captureHttpError({
        endpoint: path,
        status: response.status,
        duration_ms: performance.now() - startedAt,
      })
      throw new ApiError(
        response.status,
        errorMessageFromBody(errBody, response.statusText || "Поток недоступен"),
        errBody,
      )
    }

    // Первый байт = заголовки ответа получены (тело ещё стримится).
    if (rumInteraction) markTtfb()

    if (!response.body) {
      if (rumInteraction) cancelInteraction()
      throw new ApiError(0, "Пустой ответ сервера")
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ""
    try {
      for (;;) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        buffer = drainFrames(buffer, onEventRum)
      }
      // Хвост без финального \n\n — редкий случай обрыва; не форсим.
      if (buffer.trim()) {
        drainFrames(buffer + "\n\n", onEventRum)
      }
      if (rumInteraction && !finished) {
        // Стрим закрылся без terminal-кадра — считаем завершённым.
        markDone()
      }
    } finally {
      reader.releaseLock()
    }
  } finally {
    if (timer !== undefined) clearTimeout(timer)
    signal?.removeEventListener("abort", abortOuter)
  }
}
