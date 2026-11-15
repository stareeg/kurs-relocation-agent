/**
 * Агент — главный экран (шаг U-0/U-1, каркас визуала как в COWORK): один свободный чат
 * без привязки к вакансии, чтобы можно было написать агенту что угодно и минимально
 * проверить его работу. Пустой экран — приветствие и большое поле ввода; с историей —
 * лента + композер снизу. Переписка с HR переехала в правую панель раздела «Вакансии»
 * (вкладка «Чат» в дровере), «контексты» убраны.
 */
import { useEffect, useMemo, useRef, useState } from "react"
import { Copy, Loader2, Paperclip, Send, Sparkles, Trash2 } from "lucide-react"
import { toast } from "sonner"
import { cn } from "@/lib/utils"
import { linkify } from "@/components/chat/linkify"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuTrigger,
} from "@/components/ui/context-menu"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { MarkdownView } from "@/components/markdown-view"
import { AttachmentChips } from "@/components/chat/attachments/AttachmentChips"
import { AttachmentGrid } from "@/components/chat/attachments/AttachmentGrid"
import { ImageCropper } from "@/components/chat/attachments/ImageCropper"
import {
  ACCEPTED_ATTACHMENT_MIME,
  isImageFile,
  usePasteImages,
} from "@/components/chat/attachments/use-paste-images"
import {
  useAttachmentUpload,
  type PendingAttachment,
} from "@/components/chat/attachments/use-attachment-upload"
import type { AttachmentOut } from "@/api/attachments"
import {
  useAgentConversation,
  type AgentChatMessage,
  type AgentChatTier,
} from "./use-agent-conversation"

const TIER_STORAGE_KEY = "copilot.agent-chat.tier"

const TIER_OPTIONS: { value: AgentChatTier; label: string }[] = [
  { value: "", label: "Авто" },
  { value: "advanced", label: "Умная" },
  { value: "basic", label: "Быстрая" },
]

function loadTier(): AgentChatTier {
  try {
    const raw = localStorage.getItem(TIER_STORAGE_KEY)
    return raw === "advanced" || raw === "basic" ? raw : ""
  } catch {
    return ""
  }
}

function fmtTime(ms: number): string {
  const d = new Date(ms)
  const p = (n: number) => String(n).padStart(2, "0")
  return `${p(d.getDate())}.${p(d.getMonth() + 1)} ${p(d.getHours())}:${p(d.getMinutes())}`
}

function Bubble({
  mine,
  body,
  time,
  error,
  attachments = [],
  onCopy,
}: {
  mine: boolean
  body: string
  time?: string
  error?: boolean
  attachments?: AttachmentOut[]
  onCopy?: () => void
}) {
  const row = (
    <div className={cn("flex", mine ? "justify-end" : "justify-start")}>
      <div className="flex max-w-[85%] flex-col">
        {!mine && (
          <div className="mb-1 flex items-center gap-1 text-xs text-slate-400">Агент</div>
        )}
        <div
          className={cn(
            "rounded-2xl px-3.5 py-2 text-sm leading-snug",
            mine ? "rounded-br-sm bg-sky-100 text-slate-900" : "rounded-bl-sm bg-violet-100",
            error && "bg-rose-50",
          )}
        >
          {attachments.length > 0 ? <AttachmentGrid attachments={attachments} className="mb-1" /> : null}
          {body ? (
            mine ? (
              <p className="whitespace-pre-wrap break-words text-base leading-snug">
                {linkify(body)}
              </p>
            ) : (
              <MarkdownView markdown={body} chat />
            )
          ) : null}
          <div className="mt-0.5 flex items-center justify-end gap-2 text-xs">
            {time && <span className="font-semibold tabular-nums text-slate-400">{time}</span>}
          </div>
        </div>
      </div>
    </div>
  )
  if (!onCopy) return row
  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>{row}</ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuItem onSelect={onCopy}>
          <Copy />
          Копировать
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  )
}

function copyText(text: string, toastOne: boolean) {
  navigator.clipboard.writeText(text).then(
    () => toast.success(toastOne ? "Сообщение скопировано" : "Сообщения скопированы"),
    () => toast.error("Не удалось скопировать"),
  )
}

export function AgentChat() {
  const conv = useAgentConversation()
  const [text, setText] = useState("")
  const [tier, setTier] = useState<AgentChatTier>(loadTier)
  const [confirmClear, setConfirmClear] = useState(false)
  const attachments = useAttachmentUpload()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [cropTarget, setCropTarget] = useState<{ key: string; attachment: AttachmentOut } | null>(
    null,
  )
  const paste = usePasteImages({
    onFiles: attachments.addFiles,
    queuedCount: attachments.items.length,
    disabled: attachments.isUploading,
  })

  const hasMessages = conv.messages.length > 0 || conv.pending != null

  const scrollRef = useRef<HTMLDivElement | null>(null)
  const prevLen = useRef(0)
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const total = conv.messages.length + (conv.pending ? 1 : 0)
    const grew = total > prevLen.current
    prevLen.current = total
    if (grew) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" })
  }, [conv.messages, conv.pending])

  const readyAttachments = useMemo(
    () =>
      attachments.items
        .filter((i): i is PendingAttachment & { attachment: AttachmentOut } => i.attachment != null)
        .map((i) => i.attachment),
    [attachments.items],
  )

  function send() {
    const t = text.trim()
    if ((!t.trim() && attachments.attachmentIds.length === 0) || conv.isRunning) return
    conv.askLlm(t, readyAttachments, tier)
    setText("")
    attachments.clear()
  }

  function copyMessage(m: AgentChatMessage) {
    copyText(`${m.role === "user" ? "Я" : "Агент"}: ${m.content}`, true)
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-slate-50">
      {hasMessages ? (
        <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-3xl space-y-1.5 px-4 py-4">
            {conv.messages.map((m) => (
              <Bubble
                key={m.id}
                mine={m.role === "user"}
                body={m.content}
                time={fmtTime(m.createdAt)}
                error={m.error}
                attachments={m.attachments}
                onCopy={() => copyMessage(m)}
              />
            ))}
            {conv.pending ? (
              <>
                <Bubble
                  mine
                  body={conv.pending.question}
                  time={fmtTime(conv.pending.askedAt)}
                  attachments={conv.pending.attachments}
                />
                {conv.pending.answer ? (
                  <Bubble mine={false} body={conv.pending.answer} error={conv.pending.error} />
                ) : conv.isRunning ? (
                  <div className="flex justify-start">
                    <div className="flex items-center gap-2 rounded-2xl rounded-bl-sm bg-violet-100 px-3 py-2 text-xs text-slate-500">
                      <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />
                      Думаю…
                    </div>
                  </div>
                ) : null}
              </>
            ) : null}
          </div>
        </div>
      ) : (
        <div className="min-h-0 flex-1" />
      )}

      <div
        className={cn(
          "shrink-0 border-t bg-white",
          !hasMessages && "border-t-0 bg-transparent",
        )}
      >
        <div className="mx-auto w-full max-w-3xl p-4">
          {hasMessages ? null : (
            <div className="mb-3 flex flex-col items-center gap-1 text-center">
              <Sparkles className="size-6 text-violet-500" strokeWidth={2} />
              <h1 className="text-lg font-semibold text-slate-900">Агент</h1>
              <p className="text-sm text-slate-500">
                Напишите что угодно: найти вакансию, проверить условия въезда, разобрать оффер.
                Переписка с HR — в разделе «Вакансии».
              </p>
            </div>
          )}
          <div
            className={cn(
              "space-y-2 rounded-2xl border bg-white p-3 shadow-sm transition-colors",
              paste.isDraggingOver &&
                "bg-sky-50 outline-dashed outline-2 -outline-offset-2 outline-sky-300",
            )}
            onPaste={paste.onPaste}
            onDragEnter={paste.onDragEnter}
            onDragOver={paste.onDragOver}
            onDragLeave={paste.onDragLeave}
            onDrop={paste.onDrop}
          >
            {attachments.items.length > 0 ? (
              <AttachmentChips
                items={attachments.items}
                onRemove={attachments.remove}
                onRetry={attachments.retry}
                onOpen={(item) => {
                  if (!item.attachment || !isImageFile(item.file)) return
                  setCropTarget({ key: item.key, attachment: item.attachment })
                }}
              />
            ) : null}
            <Textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Спросите агента…"
              className="max-h-40 bg-transparent"
              autoFocus
              disabled={conv.isRunning}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && (e.metaKey || e.ctrlKey)) {
                  e.preventDefault()
                  send()
                }
              }}
            />
            <div className="flex items-center justify-between gap-2">
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
                <Select
                  value={tier}
                  onValueChange={(v) => {
                    const next = v as AgentChatTier
                    setTier(next)
                    try {
                      localStorage.setItem(TIER_STORAGE_KEY, next)
                    } catch {
                      /* ignore */
                    }
                  }}
                >
                  <SelectTrigger className="h-8 w-[120px] bg-transparent" aria-label="Модель">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {TIER_OPTIONS.map((o) => (
                      <SelectItem key={o.value} value={o.value}>
                        {o.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {hasMessages ? (
                  <Button
                    size="icon"
                    variant="ghost"
                    type="button"
                    aria-label="Очистить диалог"
                    className="text-slate-400 hover:text-rose-600"
                    onClick={() => setConfirmClear(true)}
                  >
                    <Trash2 className="size-4" strokeWidth={2} />
                  </Button>
                ) : null}
              </div>
              <Button
                size="icon"
                type="button"
                aria-label="Отправить"
                disabled={conv.isRunning || (!text.trim() && attachments.attachmentIds.length === 0)}
                onClick={send}
              >
                {conv.isRunning ? (
                  <Loader2 className="size-4 animate-spin" strokeWidth={2} />
                ) : (
                  <Send className="size-4" strokeWidth={2} />
                )}
              </Button>
            </div>
          </div>
          <p className="mt-1.5 text-center text-[11px] text-slate-400">
            Ответ генерируется моделью и может содержать ошибки — проверяйте важное.
          </p>
        </div>
      </div>

      {cropTarget ? (
        <ImageCropper
          attachment={cropTarget.attachment}
          onOpenChange={(open) => {
            if (!open) setCropTarget(null)
          }}
          onCropped={(attachment) => {
            attachments.replace(cropTarget.key, attachment)
            setCropTarget(null)
          }}
        />
      ) : null}

      <ConfirmDialog
        open={confirmClear}
        onOpenChange={setConfirmClear}
        title="Очистить диалог с агентом?"
        description="История хранится в этом браузере и будет удалена. Действие необратимо."
        confirmLabel="Очистить"
        onConfirm={() => {
          conv.clear()
          setConfirmClear(false)
        }}
      />
    </div>
  )
}
