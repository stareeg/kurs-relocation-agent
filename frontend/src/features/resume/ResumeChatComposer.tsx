/**
 * Композер чата по резюме: вложения, загрузка PDF, «Агент», «Очистить», «Отправить».
 * PDF стоит в той же строке, что «Очистить»/«Отправить», слева от них и занимает оставшуюся ширину.
 * Зеркало `MarketChatComposer`, без блока «Спросить».
 */
import { useMemo, useRef, useState } from "react"
import { Eraser, Eye, EyeOff, Loader2, Paperclip, Send, Sparkles, X } from "lucide-react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { HelpTip } from "@/components/ui/help-tip"
import { Textarea } from "@/components/ui/textarea"
import { SelectionToolbar, oneLine } from "@/components/chat/composer-widgets"
import { AttachmentChips } from "@/components/chat/attachments/AttachmentChips"
import { ImageCropper } from "@/components/chat/attachments/ImageCropper"
import { ImageViewer } from "@/components/chat/attachments/ImageViewer"
import {
  useAttachmentUpload,
  type PendingAttachment,
} from "@/components/chat/attachments/use-attachment-upload"
import {
  ACCEPTED_ATTACHMENT_MIME,
  isImageFile,
  usePasteImages,
} from "@/components/chat/attachments/use-paste-images"
import type { AttachmentOut } from "@/api/attachments"
import type { MessageSelection } from "@/features/jobs/use-message-selection"
import { ResumePdfUploadSlot } from "./resume-pdf-slot"
import type { ResumeReplyTarget } from "./use-resume-conversation"
import type { ResumeConversation } from "./use-resume-conversation"

export type { ResumeReplyTarget }

export function ResumeChatComposer({
  conv,
  hideAgent,
  onToggleHideAgent,
  replyTo,
  onClearReply,
  selection,
  onCopySelection,
  onRequestDeleteSelection,
  onRequestClear,
}: {
  conv: ResumeConversation
  hideAgent: boolean
  onToggleHideAgent: () => void
  replyTo: ResumeReplyTarget | null
  onClearReply: () => void
  selection: MessageSelection
  onCopySelection: () => void
  onRequestDeleteSelection: () => void
  onRequestClear: () => void
}) {
  const [text, setText] = useState("")
  const attachments = useAttachmentUpload()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [cropTarget, setCropTarget] = useState<{ key: string; attachment: AttachmentOut } | null>(
    null,
  )
  const [viewerIndex, setViewerIndex] = useState<number | null>(null)

  const readyAttachments = useMemo(
    () =>
      attachments.items
        .filter((i): i is PendingAttachment & { attachment: AttachmentOut } => i.attachment != null)
        .map((i) => i.attachment),
    [attachments.items],
  )
  const readyImageAttachments = useMemo(
    () => readyAttachments.filter((a) => a.mime.startsWith("image/")),
    [readyAttachments],
  )
  const paste = usePasteImages({
    onFiles: attachments.addFiles,
    queuedCount: attachments.items.length,
    disabled: attachments.isUploading,
  })

  const hasMessages = conv.messages.length > 0

  function openViewer(item: PendingAttachment) {
    if (!item.attachment || !isImageFile(item.file)) return
    const idx = readyImageAttachments.findIndex((a) => a.id === item.attachment!.id)
    if (idx !== -1) setViewerIndex(idx)
  }
  function openCrop(item: PendingAttachment) {
    if (!item.attachment || !isImageFile(item.file)) return
    setCropTarget({ key: item.key, attachment: item.attachment })
  }

  function send() {
    const t = text.trim()
    if (!t && attachments.attachmentIds.length === 0) return
    if (conv.isRunning) return
    conv.askLlm(t, replyTo?.id, readyAttachments.length > 0 ? readyAttachments : undefined)
    setText("")
    attachments.clear()
    onClearReply()
  }

  return (
    <div
      className={cn(
        "shrink-0 space-y-2 border-t bg-white p-3 transition-colors",
        paste.isDraggingOver &&
          "bg-sky-50 outline-dashed outline-2 -outline-offset-2 outline-sky-300",
      )}
      onPaste={paste.onPaste}
      onDragEnter={paste.onDragEnter}
      onDragOver={paste.onDragOver}
      onDragLeave={paste.onDragLeave}
      onDrop={paste.onDrop}
    >
      <div className="flex items-center gap-1.5">
        {selection.isSelecting ? (
          <SelectionToolbar
            count={selection.selectedIds.size}
            onCopy={onCopySelection}
            onDelete={onRequestDeleteSelection}
            onClear={selection.clear}
          />
        ) : (
          <>
            <div className="flex shrink-0 items-center gap-1.5">
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept={Array.from(ACCEPTED_ATTACHMENT_MIME).join(",")}
                className="hidden"
                onChange={(e) => {
                  attachments.addFiles(Array.from(e.target.files ?? []))
                  e.target.value = ""
                }}
              />
              <HelpTip id="chat.attachments" side="top">
                <Button
                  size="icon"
                  variant="outline"
                  type="button"
                  aria-label="Приложить файл"
                  disabled={conv.isRunning}
                  onClick={() => fileInputRef.current?.click()}
                >
                  <Paperclip className="size-4" strokeWidth={2} />
                </Button>
              </HelpTip>
              <div className="inline-flex items-center gap-0.5 rounded-lg bg-slate-100 p-1">
                <span className="flex items-center gap-1.5 rounded-lg py-1.5 pl-2.5 pr-1 text-sm font-medium text-slate-900">
                  <Sparkles className="size-4" strokeWidth={2} />
                  Агент
                </span>
                <button
                  type="button"
                  onClick={onToggleHideAgent}
                  aria-label={
                    hideAgent ? "Показать переписку с Агентом" : "Скрыть переписку с Агентом"
                  }
                  title={hideAgent ? "Показать переписку" : "Скрыть переписку"}
                  className="rounded-md p-1.5 text-slate-400 transition-colors hover:bg-slate-200/70 hover:text-slate-600"
                >
                  {hideAgent ? (
                    <EyeOff className="size-3.5" strokeWidth={2} />
                  ) : (
                    <Eye className="size-3.5" strokeWidth={2} />
                  )}
                </button>
              </div>
            </div>
            {/* PDF резюме — по центру оставшегося места, в одной строке с «Очистить»/«Отправить». */}
            <ResumePdfUploadSlot compact />
            <div className="flex shrink-0 items-center gap-1.5">
              {hasMessages ? (
                <Button
                  size="default"
                  variant="ghost"
                  className="h-9 gap-1.5 px-2.5 text-sm text-slate-500 hover:text-slate-700"
                  onClick={onRequestClear}
                  title="Очистить весь диалог"
                >
                  <Eraser className="size-4" strokeWidth={2} />
                  Очистить
                </Button>
              ) : null}
              <Button
                size="default"
                className="h-9 gap-1.5 px-3"
                disabled={
                  (!text.trim() && attachments.attachmentIds.length === 0) || conv.isRunning
                }
                onClick={send}
              >
                {conv.isRunning ? (
                  <Loader2 className="size-4 animate-spin" strokeWidth={2} />
                ) : (
                  <Send className="size-4" strokeWidth={2} />
                )}
                Отправить
              </Button>
            </div>
          </>
        )}
      </div>

      {replyTo ? (
        <div className="flex items-center gap-2 rounded-lg border-l-2 border-sky-400 bg-sky-50/60 py-1.5 pl-2.5 pr-1.5">
          <div className="min-w-0 flex-1">
            <p className="truncate text-xs font-medium text-sky-800">{replyTo.label}</p>
            <p className="truncate text-xs text-slate-500">{oneLine(replyTo.body, 100)}</p>
          </div>
          <button
            type="button"
            onClick={onClearReply}
            aria-label="Убрать ответ"
            className="rounded-md p-1 text-slate-400 transition-colors hover:bg-slate-200/60 hover:text-slate-600"
          >
            <X className="size-3.5" strokeWidth={2} />
          </button>
        </div>
      ) : null}

      {attachments.items.length > 0 ? (
        <AttachmentChips
          items={attachments.items}
          onRemove={attachments.remove}
          onRetry={attachments.retry}
          onOpen={openViewer}
        />
      ) : null}

      <div className="flex items-end gap-2">
        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Спросите про резюме: что усилить, как оформить…"
          className="flex-1"
          maxHeight={160}
          disabled={conv.isRunning}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault()
              send()
            }
          }}
        />
      </div>

      <ImageCropper
        attachment={cropTarget?.attachment ?? null}
        onOpenChange={(open) => {
          if (!open) setCropTarget(null)
        }}
        onCropped={(result) => {
          if (cropTarget) attachments.replace(cropTarget.key, result)
          setCropTarget(null)
        }}
      />
      {viewerIndex != null && readyImageAttachments[viewerIndex] ? (
        <ImageViewer
          attachments={readyImageAttachments}
          index={viewerIndex}
          onIndexChange={setViewerIndex}
          onClose={() => setViewerIndex(null)}
          onCropRequested={(attachment) => {
            setViewerIndex(null)
            const item = attachments.items.find((i) => i.attachment?.id === attachment.id)
            if (item) window.setTimeout(() => openCrop(item), 0)
          }}
        />
      ) : null}
    </div>
  )
}
