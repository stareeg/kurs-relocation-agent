import { useCallback, useRef, useState } from "react"
import type { ClipboardEvent, DragEvent } from "react"
import { toast } from "sonner"

// Вставка/drag&drop/выбор файлов в композер (план §6.2; текстовые документы — 2026-08-11).
// Чистые функции вынесены отдельно от хука, чтобы их можно было прогнать в vitest без
// jsdom-событий буфера обмена.

export const ACCEPTED_ATTACHMENT_MIME = new Set([
  "image/png",
  "image/jpeg",
  "image/webp",
  "image/gif",
  "text/plain",
  "text/markdown",
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
])

// Расширение → mime — фолбэк, когда браузер прислал generic/пустой `file.type` (частый случай
// для .md — не все ОС знают эту ассоциацию). Зеркало бэка (`_DOCUMENT_EXT_MIME`,
// core/domains/assistant/attachments/service.py).
const EXT_FALLBACK_MIME: Record<string, string> = {
  ".txt": "text/plain",
  ".md": "text/markdown",
  ".pdf": "application/pdf",
  ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

function fileExt(name: string): string {
  const dot = name.lastIndexOf(".")
  return dot === -1 ? "" : name.slice(dot).toLowerCase()
}

/** Картинка или текстовый документ (txt/md/pdf/docx) — по mime, с фолбэком на расширение. */
export function isAcceptedAttachment(file: File): boolean {
  if (ACCEPTED_ATTACHMENT_MIME.has(file.type)) return true
  return fileExt(file.name) in EXT_FALLBACK_MIME
}

/** Картинка (не документ) — для мест, которым нужна именно картинка (кроп/просмотрщик). */
export function isImageFile(file: File): boolean {
  return file.type.startsWith("image/")
}

export const ATTACHMENT_MAX_PER_MESSAGE = 10

/**
 * Chrome кладёт вставленный скрин и в `files`, и в `items` одновременно — без дедупа по
 * name+size+lastModified получили бы двойной чип на одну вставку.
 */
export function extractImageFiles(data: DataTransfer | null | undefined): File[] {
  if (!data) return []
  const files: File[] = []
  const seen = new Set<string>()
  const push = (file: File | null) => {
    if (!file || !isAcceptedAttachment(file)) return
    const sig = `${file.name}:${file.size}:${file.lastModified}`
    if (seen.has(sig)) return
    seen.add(sig)
    files.push(file)
  }
  // `FileList`/`DataTransferItemList` не итерируемы в текущем lib-таргете — индексный доступ.
  for (let i = 0; i < data.files.length; i += 1) push(data.files[i])
  for (let i = 0; i < data.items.length; i += 1) {
    const item = data.items[i]
    if (item.kind === "file") push(item.getAsFile())
  }
  return files
}

/** Есть ли в буфере текст рядом с картинкой — тогда `preventDefault` только на картинки. */
export function hasPastedText(data: DataTransfer | null | undefined): boolean {
  return (data?.getData("text/plain") ?? "").trim().length > 0
}

export interface PartitionedFiles {
  accepted: File[]
  rejected: File[]
}

/** HEIC/AVIF/SVG/zip и прочее не из белого списка — отклоняются с тостом, до похода на сервер. */
export function partitionAcceptedFiles(files: File[]): PartitionedFiles {
  const accepted: File[] = []
  const rejected: File[] = []
  for (const file of files) {
    ;(isAcceptedAttachment(file) ? accepted : rejected).push(file)
  }
  return { accepted, rejected }
}

/** Клампует пачку под лимит на сообщение и возвращает, сколько пришлось отбросить. */
export function clampToRemainingSlots(
  files: File[],
  alreadyQueued: number,
  limit: number = ATTACHMENT_MAX_PER_MESSAGE,
): { files: File[]; dropped: number } {
  const room = Math.max(0, limit - alreadyQueued)
  if (files.length <= room) return { files, dropped: 0 }
  return { files: files.slice(0, room), dropped: files.length - room }
}

export interface UsePasteImagesOptions {
  onFiles: (files: File[]) => void
  /** Сколько уже в очереди композера — для клампа лимита на сообщение. */
  queuedCount: number
  disabled?: boolean
}

export interface UsePasteImagesResult {
  isDraggingOver: boolean
  onPaste: (e: ClipboardEvent) => void
  onDragEnter: (e: DragEvent) => void
  onDragOver: (e: DragEvent) => void
  onDragLeave: (e: DragEvent) => void
  onDrop: (e: DragEvent) => void
}

/** Вешается на композер целиком (не только на textarea) и на ленту — drag&drop работает в обеих зонах. */
export function usePasteImages({
  onFiles,
  queuedCount,
  disabled,
}: UsePasteImagesOptions): UsePasteImagesResult {
  const [isDraggingOver, setDraggingOver] = useState(false)
  const dragDepth = useRef(0)

  const acceptFiles = useCallback(
    (files: File[]) => {
      if (disabled || files.length === 0) return
      const { accepted, rejected } = partitionAcceptedFiles(files)
      if (rejected.length > 0) {
        toast.error("Формат не поддерживается — PNG/JPEG/WebP/GIF или .txt/.md/.pdf/.docx")
      }
      if (accepted.length === 0) return
      const { files: clamped, dropped } = clampToRemainingSlots(accepted, queuedCount)
      if (dropped > 0) {
        toast.error(`Не больше ${ATTACHMENT_MAX_PER_MESSAGE} вложений в одном сообщении`)
      }
      if (clamped.length > 0) onFiles(clamped)
    },
    [disabled, onFiles, queuedCount],
  )

  const onPaste = useCallback(
    (e: ClipboardEvent) => {
      const images = extractImageFiles(e.clipboardData)
      if (images.length === 0) return
      if (!hasPastedText(e.clipboardData)) e.preventDefault()
      acceptFiles(images)
    },
    [acceptFiles],
  )

  const hasFilesPayload = (e: DragEvent) => Array.from(e.dataTransfer.types).includes("Files")

  const onDragEnter = useCallback(
    (e: DragEvent) => {
      if (disabled || !hasFilesPayload(e)) return
      e.preventDefault()
      dragDepth.current += 1
      setDraggingOver(true)
    },
    [disabled],
  )

  const onDragOver = useCallback(
    (e: DragEvent) => {
      if (disabled || !hasFilesPayload(e)) return
      e.preventDefault()
    },
    [disabled],
  )

  const onDragLeave = useCallback(() => {
    dragDepth.current = Math.max(0, dragDepth.current - 1)
    if (dragDepth.current === 0) setDraggingOver(false)
  }, [])

  const onDrop = useCallback(
    (e: DragEvent) => {
      if (disabled) return
      e.preventDefault()
      dragDepth.current = 0
      setDraggingOver(false)
      const files = Array.from(e.dataTransfer.files).filter(isAcceptedAttachment)
      acceptFiles(files)
    },
    [disabled, acceptFiles],
  )

  return { isDraggingOver, onPaste, onDragEnter, onDragOver, onDragLeave, onDrop }
}
