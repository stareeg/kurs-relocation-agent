import type { components } from "@/api/schema"
import {
  api,
  ApiError,
  errorMessageFromBody,
  NETWORK_UNAVAILABLE_MSG,
  REQUEST_TIMEOUT_MSG,
} from "@/api/client"

// Вложения-картинки (план chat_image_attachments_2026_08_03.md, Э2-1). Типы — из автогена
// schema.d.ts (роутер и схемы уже смёржены, `npm run gen-api:offline` прогнан).

export type AttachmentOut = components["schemas"]["AttachmentOut"]
export type AttachmentAnalysis = components["schemas"]["AttachmentAnalysis"]
export type AttachmentTurn = components["schemas"]["AttachmentTurn"]
export type AttachmentAnalysisStatus = AttachmentOut["analysis_status"]
export type AttachmentCropRequest = components["schemas"]["AttachmentCropRequest"]

// Ветка вложения в режимах-парсерах (Э4-3, план §3) — зеркалит `AttachmentRoute` бэкенда
// (`core/domains/assistant/attachments/models.py`). Ярлык-переключатель на чипе композера
// (`RouteBadge`) шлёт переопределение сервером как `attachment_routes: {id: route}`.
export type AttachmentRoute = "correspondence" | "material"

// Байты того же origin (dev-прокси vite делает cookie общей, см. план §5) — прямой src для <img>,
// без похода за meta, когда id уже известен (только что загрузили / цитата «Ответить»).
export function attachmentUrl(id: number): string {
  return `/api/attachments/${id}`
}

export function attachmentThumbUrl(id: number): string {
  return `/api/attachments/${id}/thumb`
}

// GET /api/attachments/{id}/meta — точечный поллинг статуса распознавания, если SSE-канал лежит.
export function fetchAttachmentMeta(id: number) {
  return api.get<AttachmentOut>(`/api/attachments/${id}/meta`)
}

// POST /api/attachments/{id}/crop — кадрирование не портит оригинал: новая строка с derived_from,
// связку сообщения переключает вызывающая сторона (композер/просмотрщик) на новый id.
export function cropAttachment(id: number, body: AttachmentCropRequest) {
  return api.post<AttachmentOut>(`/api/attachments/${id}/crop`, body)
}

const BASE = import.meta.env.VITE_API_BASE ?? ""

// Нормализация (Pillow: EXIF/даунскейл/WebP) — быстрая, но `files` может прийти пачкой
// (Ctrl+V нескольких скринов сразу); с запасом на медленную сеть, не LLM-таймаут — вызова модели
// тут нет.
const ATTACHMENT_UPLOAD_TIMEOUT_MS = 60_000

export type AttachmentUploadProgress = { loaded: number; total: number }

export type UploadAttachmentsOptions = {
  /** Байты отправки (fetch не даёт upload-прогресс во всех браузерах — поэтому тут XHR). */
  onProgress?: (progress: AttachmentUploadProgress) => void
  signal?: AbortSignal
}

/**
 * POST /api/attachments — multipart, 1..N файлов за один запрос → по одному `AttachmentOut` на
 * файл (идемпотентно по sha256). XMLHttpRequest вместо `api.upload` ради `upload.onprogress` —
 * общий прогресс-бар на пачку из нескольких вставленных скринов, не только spinner на чипе.
 */
export function uploadAttachments(
  files: File[],
  opts: UploadAttachmentsOptions = {},
): Promise<AttachmentOut[]> {
  const { onProgress, signal } = opts
  const formData = new FormData()
  for (const file of files) formData.append("files", file)

  return new Promise<AttachmentOut[]>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    let settled = false
    let timedOut = false

    const onAbort = () => {
      if (!settled) xhr.abort()
    }

    const timer = setTimeout(() => {
      timedOut = true
      xhr.abort()
    }, ATTACHMENT_UPLOAD_TIMEOUT_MS)

    const cleanup = () => {
      clearTimeout(timer)
      signal?.removeEventListener("abort", onAbort)
    }

    if (signal) {
      if (signal.aborted) onAbort()
      else signal.addEventListener("abort", onAbort, { once: true })
    }

    xhr.open("POST", `${BASE}/api/attachments`)
    xhr.withCredentials = true
    xhr.responseType = "json"

    if (xhr.upload && onProgress) {
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress({ loaded: e.loaded, total: e.total })
      }
    }

    xhr.onload = () => {
      if (settled) return
      settled = true
      cleanup()
      if (xhr.status === 401) {
        reject(new ApiError(401, "Не авторизован"))
        return
      }
      if (xhr.status < 200 || xhr.status >= 300) {
        const body: unknown = xhr.response
        reject(new ApiError(xhr.status, errorMessageFromBody(body, xhr.statusText), body))
        return
      }
      resolve((xhr.response as AttachmentOut[]) ?? [])
    }

    xhr.onerror = () => {
      if (settled) return
      settled = true
      cleanup()
      reject(new ApiError(0, NETWORK_UNAVAILABLE_MSG))
    }

    xhr.onabort = () => {
      if (settled) return
      settled = true
      cleanup()
      if (timedOut) reject(new ApiError(0, REQUEST_TIMEOUT_MSG))
      else reject(new DOMException("Загрузка отменена", "AbortError"))
    }

    xhr.send(formData)
  })
}

/** Один файл — тонкая обёртка над `uploadAttachments` для не-пачечных мест (скрепка на один клик). */
export function uploadAttachment(
  file: File,
  opts?: UploadAttachmentsOptions,
): Promise<AttachmentOut> {
  return uploadAttachments([file], opts).then(([result]) => result)
}
