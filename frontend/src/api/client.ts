// Тонкая типизированная обёртка над fetch (ux_plan.md, 2.2).
// Cookie-сессия → credentials:include. 401 → единый перехват (протухшая сессия).
// Типы тел/ответов берём из автогена schema.d.ts, руками интерфейсы не пишем.
// FR2-68: AbortController-таймаут + человеческое сообщение при network/timeout.

import { captureHttpError, captureNetworkError } from "@/lib/error-capture"

const BASE = import.meta.env.VITE_API_BASE ?? ""

/** Обычные CRUD/GET — если бэкенд молчит дольше, скорее всего он лежит. */
export const DEFAULT_TIMEOUT_MS = 30_000
/** LLM-ручки (L-13): budget_ms + 1 repair не должны обрываться клиентом раньше бэкенда. */
export const LLM_TIMEOUT_MS = 300_000

export const NETWORK_UNAVAILABLE_MSG = "Сервер недоступен (программа остановлена?)"
export const REQUEST_TIMEOUT_MSG = "Сервер не ответил вовремя — попробуйте ещё раз"

export class ApiError extends Error {
  status: number
  body: unknown
  /** Машинный код из конверта A-15 (`invalid_input`, `llm_error`, …), если есть. */
  code: string | null

  constructor(status: number, message: string, body?: unknown) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.body = body
    this.code = codeOf(body)
  }
}

export type ApiCallOptions = {
  /** 0 — без таймера (отмена только через signal). По умолчанию DEFAULT_TIMEOUT_MS. */
  timeoutMs?: number
  signal?: AbortSignal
  /** Не показывать тост «Скачать логи» — когда сам запрос и есть скачивание логов. */
  skipSeriousToast?: boolean
}

type ApiFetchInit = RequestInit & {
  timeoutMs?: number
  /** Не дёргать глобальный onUnauthorized на 401 — для формы логина (неверный токен ≠ разлогин). */
  skip401Handler?: boolean
  skipSeriousToast?: boolean
}

// Обработчик протухшей сессии. AuthProvider подписывается: чистит кэш, редирект на /login.
let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(fn: (() => void) | null) {
  onUnauthorized = fn
}

/**
 * Человекочитаемое сообщение из тела ошибки (A-15).
 * Поддерживает: `{detail: "…"}`, `{detail: {message, code}}`, голый `{message}`.
 */
export function errorMessageFromBody(body: unknown, fallback: string): string {
  if (!body || typeof body !== "object") return fallback
  const rec = body as Record<string, unknown>
  const d = rec.detail
  if (typeof d === "string" && d.trim()) return d
  if (d && typeof d === "object") {
    const msg = (d as { message?: unknown }).message
    if (typeof msg === "string" && msg.trim()) return msg
  }
  if (typeof rec.message === "string" && rec.message.trim()) return rec.message
  return fallback
}

function codeOf(body: unknown): string | null {
  if (!body || typeof body !== "object") return null
  const rec = body as Record<string, unknown>
  const d = rec.detail
  if (d && typeof d === "object") {
    const code = (d as { code?: unknown }).code
    if (typeof code === "string" && code) return code
  }
  if (typeof rec.code === "string" && rec.code) return rec.code
  return null
}

// FR2-19: последние удачные запросы — попадают в клиентский фолбэк-бандл, когда бэкенд лежит
// (показывают, когда связь ещё была).
const MAX_RECENT_SUCCESSES = 20
const recentSuccesses: { endpoint: string; ts: string }[] = []

function recordSuccess(endpoint: string): void {
  recentSuccesses.push({ endpoint, ts: new Date().toISOString() })
  if (recentSuccesses.length > MAX_RECENT_SUCCESSES) recentSuccesses.shift()
}

export function getRecentSuccesses(): { endpoint: string; ts: string }[] {
  return [...recentSuccesses]
}

/** Связать внешний signal + свой таймер в один AbortController. */
function bindAbort(
  timeoutMs: number,
  outer?: AbortSignal,
): {
  signal: AbortSignal
  didTimeout: () => boolean
  cleanup: () => void
} {
  const controller = new AbortController()
  let timedOut = false
  let timer: ReturnType<typeof setTimeout> | undefined

  const abortFromOuter = () => {
    if (!controller.signal.aborted) controller.abort()
  }

  if (outer) {
    if (outer.aborted) abortFromOuter()
    else outer.addEventListener("abort", abortFromOuter, { once: true })
  }

  if (timeoutMs > 0) {
    timer = setTimeout(() => {
      timedOut = true
      if (!controller.signal.aborted) controller.abort()
    }, timeoutMs)
  }

  return {
    signal: controller.signal,
    didTimeout: () => timedOut,
    cleanup: () => {
      if (timer !== undefined) clearTimeout(timer)
      outer?.removeEventListener("abort", abortFromOuter)
    },
  }
}

/** Ленивый импорт: `toasts.ts` статически тянет `api/logs.ts`, а тот — этот модуль.
 * Статический import замкнул бы цикл и заставил кнопку «Скачать логи» грузить чанк
 * уже после клика — браузер тогда блокирует `a.download` как не-жест пользователя. */
function emitSeriousErrorToast(message: string): void {
  void import("@/lib/toasts").then((m) => m.showSeriousErrorToast(message))
}

function throwFetchFailure(
  path: string,
  startedAt: number,
  didTimeout: boolean,
  outerAborted: boolean,
  err: unknown,
  skipSeriousToast = false,
): never {
  // Явная отмена вызывающим (размонтирование, смена вкладки) — не маскируем.
  if (outerAborted && !didTimeout) throw err

  const duration_ms = performance.now() - startedAt
  if (didTimeout) {
    captureNetworkError({ endpoint: path, reason: "timeout", duration_ms })
    if (!skipSeriousToast) emitSeriousErrorToast(REQUEST_TIMEOUT_MSG)
    throw new ApiError(0, REQUEST_TIMEOUT_MSG)
  }
  captureNetworkError({ endpoint: path, reason: "network", duration_ms })
  if (!skipSeriousToast) emitSeriousErrorToast(NETWORK_UNAVAILABLE_MSG)
  throw new ApiError(0, NETWORK_UNAVAILABLE_MSG)
}

/** 5xx (в т.ч. LLM недоступна — LlmError маппится в 503, api/errors.py) — серьёзная ошибка,
 * стоит показать кнопку «Скачать логи». 4xx — обычно ошибка ввода/данных, у неё уже есть
 * свой понятный текст в конкретном месте вызова, тут не дублируем. */
function reportIfSeriousStatus(status: number, message: string, skipSeriousToast = false): void {
  if (status >= 500 && !skipSeriousToast) emitSeriousErrorToast(message)
}

export async function apiFetch<T>(path: string, init: ApiFetchInit = {}): Promise<T> {
  const {
    headers,
    timeoutMs,
    signal: outerSignal,
    skip401Handler,
    skipSeriousToast,
    ...rest
  } = init
  // Внешний signal без timeoutMs — отмена на совести вызывающего (SSE/AbortSignal.timeout).
  const effectiveTimeout = timeoutMs ?? (outerSignal ? 0 : DEFAULT_TIMEOUT_MS)
  const startedAt = performance.now()
  const abort = bindAbort(effectiveTimeout, outerSignal)

  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      credentials: "include",
      ...rest,
      signal: abort.signal,
      headers: { "Content-Type": "application/json", ...headers },
    })
  } catch (err) {
    throwFetchFailure(
      path,
      startedAt,
      abort.didTimeout(),
      Boolean(outerSignal?.aborted),
      err,
      skipSeriousToast,
    )
  } finally {
    abort.cleanup()
  }

  if (res.status === 401 && !skip401Handler) {
    onUnauthorized?.()
    throw new ApiError(401, "Не авторизован")
  }

  if (!res.ok) {
    captureHttpError({
      endpoint: path,
      status: res.status,
      duration_ms: performance.now() - startedAt,
    })
    let body: unknown
    try {
      body = await res.json()
    } catch {
      body = undefined
    }
    const message = errorMessageFromBody(body, res.statusText)
    reportIfSeriousStatus(res.status, message, skipSeriousToast)
    throw new ApiError(res.status, message, body)
  }

  recordSuccess(path)

  if (res.status === 204) return undefined as T

  const ct = res.headers.get("content-type") ?? ""
  if (ct.includes("application/json")) return (await res.json()) as T
  return (await res.text()) as unknown as T
}

// Удобные методы. body сериализуем в JSON.
export const api = {
  get: <T>(path: string, opts?: ApiCallOptions) => apiFetch<T>(path, { method: "GET", ...opts }),
  post: <T>(path: string, body?: unknown, opts?: ApiCallOptions) =>
    apiFetch<T>(path, {
      method: "POST",
      body: body === undefined ? undefined : JSON.stringify(body),
      ...opts,
    }),
  put: <T>(path: string, body?: unknown, opts?: ApiCallOptions) =>
    apiFetch<T>(path, {
      method: "PUT",
      body: body === undefined ? undefined : JSON.stringify(body),
      ...opts,
    }),
  patch: <T>(path: string, body?: unknown, opts?: ApiCallOptions) =>
    apiFetch<T>(path, {
      method: "PATCH",
      body: body === undefined ? undefined : JSON.stringify(body),
      ...opts,
    }),
  del: <T>(path: string, opts?: ApiCallOptions) => apiFetch<T>(path, { method: "DELETE", ...opts }),
  upload: <T>(path: string, formData: FormData, opts?: ApiCallOptions) =>
    apiUpload<T>(path, formData, opts),
}

// Скачивание бинарных ответов (zip-бандл логов и т.п.) — не JSON, имя файла из заголовка.
export async function apiFetchBlob(
  path: string,
  opts?: ApiCallOptions,
): Promise<{ blob: Blob; filename: string | null }> {
  const { timeoutMs, signal: outerSignal, skipSeriousToast } = opts ?? {}
  const effectiveTimeout = timeoutMs ?? (outerSignal ? 0 : DEFAULT_TIMEOUT_MS)
  const startedAt = performance.now()
  const abort = bindAbort(effectiveTimeout, outerSignal)

  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      credentials: "include",
      signal: abort.signal,
    })
  } catch (err) {
    throwFetchFailure(
      path,
      startedAt,
      abort.didTimeout(),
      Boolean(outerSignal?.aborted),
      err,
      skipSeriousToast,
    )
  } finally {
    abort.cleanup()
  }

  if (res.status === 401) {
    onUnauthorized?.()
    throw new ApiError(401, "Не авторизован")
  }

  if (!res.ok) {
    captureHttpError({
      endpoint: path,
      status: res.status,
      duration_ms: performance.now() - startedAt,
    })
    let body: unknown
    try {
      body = await res.json()
    } catch {
      body = undefined
    }
    const message = errorMessageFromBody(body, res.statusText)
    reportIfSeriousStatus(res.status, message, skipSeriousToast)
    throw new ApiError(res.status, message, body)
  }

  recordSuccess(path)

  const match = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") ?? "")
  return { blob: await res.blob(), filename: match ? match[1] : null }
}

export async function apiUpload<T>(
  path: string,
  formData: FormData,
  opts?: ApiCallOptions,
): Promise<T> {
  const { timeoutMs, signal: outerSignal, skipSeriousToast } = opts ?? {}
  // PDF→LLM parse и подобные — по умолчанию LLM-таймаут, если не задано иное.
  const effectiveTimeout = timeoutMs ?? (outerSignal ? 0 : LLM_TIMEOUT_MS)
  const startedAt = performance.now()
  const abort = bindAbort(effectiveTimeout, outerSignal)

  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      method: "POST",
      credentials: "include",
      body: formData,
      signal: abort.signal,
    })
  } catch (err) {
    throwFetchFailure(
      path,
      startedAt,
      abort.didTimeout(),
      Boolean(outerSignal?.aborted),
      err,
      skipSeriousToast,
    )
  } finally {
    abort.cleanup()
  }

  if (res.status === 401) {
    onUnauthorized?.()
    throw new ApiError(401, "Не авторизован")
  }

  if (!res.ok) {
    captureHttpError({
      endpoint: path,
      status: res.status,
      duration_ms: performance.now() - startedAt,
    })
    let body: unknown
    try {
      body = await res.json()
    } catch {
      body = undefined
    }
    const message = errorMessageFromBody(body, res.statusText)
    reportIfSeriousStatus(res.status, message, skipSeriousToast)
    throw new ApiError(res.status, message, body)
  }

  recordSuccess(path)
  return (await res.json()) as T
}
