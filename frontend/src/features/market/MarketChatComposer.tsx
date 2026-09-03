/**
 * Композер чата «Рынка» (Заход 6, п.7): зеркало `DialogComposer` (чат по вакансии), но без
 * HR-режима — здесь только «Агент» (нет переключателя веток) — и с блоком «Спросить»
 * (контекст графика поверх переписки, п.9). Кнопка вложения и «Агент»/глазик — слева верхней
 * строки; «Отправить»/«Очистить» (тот же размер/визуал, что «Отправить») — у правого края той
 * же строки (правка 2026-08-19 п.7), поле ввода — отдельной строкой ниже во всю ширину.
 */
import { useMemo, useRef, useState } from "react"
import { BarChart3, Eraser, Eye, EyeOff, Loader2, Paperclip, Send, Sparkles, X } from "lucide-react"
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
import type { AskContext } from "./market-chat-context"
import type { MarketConversation } from "./use-market-conversation"

export type MarketReplyTarget = { id: number; label: string; body: string }

export function MarketChatComposer({
  conv,
  hideAgent,
  onToggleHideAgent,
  replyTo,
  onClearReply,
  askContext,
  onClearAskContext,
  selection,
  onCopySelection,
  onRequestDeleteSelection,
  onRequestClear,
}: {
  conv: MarketConversation
  hideAgent: boolean
  onToggleHideAgent: () => void
  replyTo: MarketReplyTarget | null
  onClearReply: () => void
  askContext: AskContext | null
  onClearAskContext: () => void
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
    // Прикреплённый контекст графика («Спросить») уходит текстом перед вопросом владельца —
    // в ленте это читается как «ответ на график» (тот же приём, что цитата reply).
    const withContext = askContext
      ? `[Контекст графика «${askContext.title}»: ${askContext.body}]\n\n${t}`
      : t
    if (!withContext.trim() && attachments.attachmentIds.length === 0) return
    if (conv.isRunning) return
    conv.askLlm(withContext, replyTo?.id, readyAttachments)
    setText("")
    attachments.clear()
    onClearReply()
    onClearAskContext()
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
      <div className="flex flex-wrap items-center justify-between gap-1">
        {selection.isSelecting ? (
          <SelectionToolbar
            count={selection.selectedIds.size}
            onCopy={onCopySelection}
            onDelete={onRequestDeleteSelection}
            onClear={selection.clear}
          />
        ) : (
          <>
            <div className="flex items-center gap-1.5">
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
            {/* Правка 2026-08-19 п.7: «Отправить»/«Очистить» переехали на строку с «Агент» —
                Очистить тем же размером/визуалом, что Отправить, слева от неё. */}
            <div className="flex shrink-0 items-center gap-1.5">
              {hasMessages ? (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-9 gap-1.5 px-3"
                  onClick={onRequestClear}
                  title="Очистить весь диалог"
                >
                  <Eraser className="size-4" strokeWidth={2} />
                  Очистить
                </Button>
              ) : null}
              <Button
                size="sm"
                className="h-9 gap-1.5 px-3"
                disabled={
                  (!text.trim() && attachments.attachmentIds.length === 0 && !askContext) ||
                  conv.isRunning
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

      {askContext ? (
        <div className="flex items-center gap-2 rounded-lg border-l-2 border-violet-400 bg-violet-50/60 py-1.5 pl-2.5 pr-1.5">
          <BarChart3 className="size-3.5 shrink-0 text-violet-500" strokeWidth={2} />
          <div className="min-w-0 flex-1">
            <p className="truncate text-xs font-medium text-violet-800">{askContext.title}</p>
            <p className="truncate text-xs text-slate-500">{oneLine(askContext.body, 100)}</p>
          </div>
          <button
            type="button"
            onClick={onClearAskContext}
            aria-label="Убрать контекст графика"
            className="rounded-md p-1 text-slate-400 transition-colors hover:bg-slate-200/60 hover:text-slate-600"
          >
            <X className="size-3.5" strokeWidth={2} />
          </button>
        </div>
      ) : null}

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

      <Textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Спросите про ситуацию на рынке: что усилить, на что обратить внимание…"
        maxHeight={160}
        disabled={conv.isRunning}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault()
            send()
          }
        }}
      />

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
