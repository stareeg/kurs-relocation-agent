import { useCallback, useEffect, useRef, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { fetchAttachmentMeta, uploadAttachments, type AttachmentOut } from "@/api/attachments"
import { ApiError } from "@/api/client"
import { useLiveEventsConnected } from "@/app/use-live-invalidation"

// Очередь вложений композера (план §4/§6.1): мгновенный локальный превью через objectURL, затем
// апload, отмена/повтор по чипу. Черновик = React-состояние без связки (план §2.3) — само
// сообщение создаётся сервером только из готовых `attachment_id`.

export type PendingAttachmentStatus = "uploading" | "ready" | "error"

export interface PendingAttachment {
  /** Стабильный клиентский id — переживает retry (id вложения на сервере ещё не известен). */
  key: string
  file: File
  previewUrl: string
  status: PendingAttachmentStatus
  attachment: AttachmentOut | null
  errorMessage: string | null
}

export interface UseAttachmentUploadResult {
  items: PendingAttachment[]
  addFiles: (files: File[]) => void
  remove: (key: string) => void
  retry: (key: string) => void
  clear: () => void
  /** После кропа с чипа (до отправки) — подменить вложение на новую (обрезанную) строку. */
  replace: (key: string, attachment: AttachmentOut) => void
  attachmentIds: number[]
  isUploading: boolean
}

function messageFromError(err: unknown): string {
  return err instanceof ApiError ? err.message : "Не удалось загрузить"
}

export function useAttachmentUpload(): UseAttachmentUploadResult {
  const [items, setItems] = useState<PendingAttachment[]>([])
  const itemsRef = useRef(items)
  useEffect(() => {
    itemsRef.current = items
  }, [items])

  const runUpload = useCallback((keys: string[], files: File[]) => {
    uploadAttachments(files)
      .then((results) => {
        setItems((prev) =>
          prev.map((item) => {
            const idx = keys.indexOf(item.key)
            if (idx === -1) return item
            const result = results[idx]
            return result
              ? { ...item, status: "ready" as const, attachment: result, errorMessage: null }
              : { ...item, status: "error" as const, errorMessage: "Не удалось загрузить" }
          }),
        )
      })
      .catch((err: unknown) => {
        const message = messageFromError(err)
        setItems((prev) =>
          prev.map((item) =>
            keys.includes(item.key)
              ? { ...item, status: "error" as const, errorMessage: message }
              : item,
          ),
        )
      })
  }, [])

  const addFiles = useCallback(
    (files: File[]) => {
      if (files.length === 0) return
      const added: PendingAttachment[] = files.map((file) => ({
        key: crypto.randomUUID(),
        file,
        previewUrl: URL.createObjectURL(file),
        status: "uploading",
        attachment: null,
        errorMessage: null,
      }))
      setItems((prev) => [...prev, ...added])
      runUpload(
        added.map((i) => i.key),
        files,
      )
    },
    [runUpload],
  )

  const remove = useCallback((key: string) => {
    setItems((prev) => {
      const target = prev.find((i) => i.key === key)
      if (target) URL.revokeObjectURL(target.previewUrl)
      return prev.filter((i) => i.key !== key)
    })
  }, [])

  const retry = useCallback(
    (key: string) => {
      const item = itemsRef.current.find((i) => i.key === key)
      if (!item) return
      setItems((prev) =>
        prev.map((i) => (i.key === key ? { ...i, status: "uploading", errorMessage: null } : i)),
      )
      runUpload([key], [item.file])
    },
    [runUpload],
  )

  const replace = useCallback((key: string, attachment: AttachmentOut) => {
    setItems((prev) => prev.map((i) => (i.key === key ? { ...i, attachment } : i)))
  }, [])

  const clear = useCallback(() => {
    for (const item of itemsRef.current) URL.revokeObjectURL(item.previewUrl)
    setItems([])
  }, [])

  // Размонтирование композера (переключили вакансию/вкладку) — не течём blob-URL забытых черновиков.
  useEffect(
    () => () => {
      for (const item of itemsRef.current) URL.revokeObjectURL(item.previewUrl)
    },
    [],
  )

  const attachmentIds = items
    .filter(
      (i): i is PendingAttachment & { attachment: AttachmentOut } =>
        i.status === "ready" && i.attachment != null,
    )
    .map((i) => i.attachment.id)
  const isUploading = items.some((i) => i.status === "uploading")

  return { items, addFiles, remove, retry, clear, replace, attachmentIds, isUploading }
}

/**
 * Живой статус одного вложения (Э1-7): резолвер `AttachmentAnalyzed` инвалидирует именно
 * `["attachment", id]`, не всю ленту — распознавание стартует до привязки к сообщению. Пока канал
 * не подключён или статус ещё `pending` — фолбэк-поллинг; иначе полагаемся на инвалидацию.
 */
export function useAttachmentMeta(id: number | null, initialData?: AttachmentOut) {
  const liveConnected = useLiveEventsConnected()
  return useQuery({
    queryKey: ["attachment", id],
    queryFn: () => fetchAttachmentMeta(id as number),
    enabled: id != null,
    initialData,
    staleTime: 10_000,
    refetchInterval: (query) => {
      const status = query.state.data?.analysis_status
      if (status !== "pending") return false
      return liveConnected ? false : 2_000
    },
  })
}
