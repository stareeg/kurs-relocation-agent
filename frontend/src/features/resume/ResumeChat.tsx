/**
 * Чат по резюме — теперь в основном потоке страницы (под формой), а не в левой панели.
 * Паритет с `MarketChat`: контекстное меню (Ответить/Копировать/Удалить), выделение протяжкой,
 * скрытие переписки с Агентом, вложения, ответ на сообщение, очистка диалога с подтверждением.
 *
 * Стрим ответа живёт в module-scope сторе (resume-chat-stream.ts) через `useResumeConversation`,
 * поэтому переключение вкладки не рвёт стрим и не теряет ответ (баг «ответ пропадает при уходе
 * с Резюме» — асинхронность «переключился на другой раздел, пока агент думает»).
 */
import { memo, useEffect, useMemo, useRef, useState, type MouseEvent } from "react"
import { Copy, CornerUpLeft, Loader2, Trash2 } from "lucide-react"
import { toast } from "sonner"
import { cn, MOTION_RISE, useNewIds } from "@/lib/utils"
import { usePersistedBoolean } from "@/lib/use-persisted-boolean"
import { linkify } from "@/components/chat/linkify"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuTrigger,
} from "@/components/ui/context-menu"
import { pluralMessages } from "@/components/chat/composer-widgets"
import { AttachmentGrid } from "@/components/chat/attachments/AttachmentGrid"
import { MarkdownView } from "@/components/markdown-view"
import { useMessageSelection } from "@/features/jobs/use-message-selection"
import type { AttachmentOut } from "@/api/attachments"
import type { ResumeChatMessage } from "@/api/resume"
import { ResumeChatComposer, type ResumeReplyTarget } from "./ResumeChatComposer"
import { useResumeConversation } from "./use-resume-conversation"

/** Идентифицируемое сообщение ленты: либо сохранённое (с id), либо пузырь из pending-очереди. */
interface ChatRow {
  /** Ключ React. У сохранённых — `saved:<id>`, у pending — `pending:<localId>:<role>`. */
  key: string
  /** id в БД — для контекстного меню (Ответить/Копировать/Удалить). null у pending-пузырей. */
  messageId: number | null
  msg: { role: "user" | "assistant"; text: string; error?: boolean }
  attachments?: AttachmentOut[]
  replyTo?: { label: string; snippet: string; sourceId: number } | null
}

function oneLine(s: string, max: number): string {
  const flat = s.replace(/\s+/g, " ").trim()
  return flat.length > max ? `${flat.slice(0, max - 1)}…` : flat
}

function isInteractiveTarget(e: { target: EventTarget | null }): boolean {
  if (!(e.target instanceof HTMLElement)) return false
  const el = e.target.closest("a, button")
  return el != null && !el.hasAttribute("data-attachment-thumb")
}

function Bubble({
  mine,
  label,
  body,
  time,
  error,
  messageId,
  quoted,
  attachments = [],
  appear,
  selected,
  selecting,
  onMouseDownSelect,
  onMouseEnterSelect,
  onContextMenuSelect,
  onReply,
  onCopy,
  onDelete,
}: {
  mine: boolean
  label: string
  body: string
  time?: string | null
  error?: boolean
  messageId?: number
  quoted?: { label: string; snippet: string; sourceId: number } | null
  attachments?: AttachmentOut[]
  appear?: boolean
  selected?: boolean
  selecting?: boolean
  onMouseDownSelect?: (e: MouseEvent<HTMLDivElement>) => void
  onMouseEnterSelect?: () => void
  onContextMenuSelect?: () => void
  onReply?: () => void
  onCopy?: () => void
  onDelete?: () => void
}) {
  const row = (
    <div
      id={messageId != null ? `resume-msg-${messageId}` : undefined}
      className={cn("flex", mine ? "justify-end" : "justify-start", appear && MOTION_RISE)}
      onMouseDown={onMouseDownSelect}
      onMouseEnter={onMouseEnterSelect}
      onContextMenu={onContextMenuSelect}
    >
      <div className="flex max-w-[85%] flex-col">
        {!mine && (
          <div className="mb-1 flex items-center gap-1 text-xs text-slate-400">{label}</div>
        )}
        <div
          className={cn(
            "rounded-2xl px-3.5 py-2 text-sm leading-snug transition-shadow",
            mine ? "rounded-br-sm bg-sky-100 text-slate-900" : "rounded-bl-sm bg-violet-100",
            error && "bg-rose-50",
            selecting && "cursor-pointer select-none",
            selected && "ring-2 ring-sky-400 ring-offset-1",
          )}
        >
          {quoted ? (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                document.getElementById(`resume-msg-${quoted.sourceId}`)?.scrollIntoView({
                  behavior: "smooth",
                  block: "center",
                })
              }}
              className="mb-1 flex w-full min-w-0 items-start gap-1.5 rounded-md border-l-2 border-slate-400/50 bg-black/[0.04] px-1.5 py-1 text-left"
            >
              <span className="min-w-0">
                <span className="block text-xs font-medium text-slate-600">{quoted.label}</span>
                <span className="block truncate text-xs text-slate-500">{quoted.snippet}</span>
              </span>
            </button>
          ) : null}
          {attachments.length > 0 ? (
            <AttachmentGrid attachments={attachments} className="mb-1" />
          ) : null}
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

  if (messageId == null || !onReply || !onCopy || !onDelete) return row

  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>{row}</ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuItem onSelect={onReply}>
          <CornerUpLeft />
          Ответить
        </ContextMenuItem>
        <ContextMenuItem onSelect={onCopy}>
          <Copy />
          Копировать
        </ContextMenuItem>
        <ContextMenuItem variant="destructive" onSelect={onDelete}>
          <Trash2 />
          Удалить
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  )
}

export const ResumeChat = memo(function ResumeChat({ className }: { className?: string }) {
  const conv = useResumeConversation()
  const [hideAgent, setHideAgent] = usePersistedBoolean("copilot.resume-chat.hide-agent")
  const selection = useMessageSelection()
  const [replyTo, setReplyTo] = useState<ResumeReplyTarget | null>(null)
  const [pendingDeleteIds, setPendingDeleteIds] = useState<number[] | null>(null)
  const [confirmClear, setConfirmClear] = useState(false)

  // Карта сохранённых реплик для разрешения цитат (reply_to → исходное сообщение).
  const messagesById = useMemo(() => {
    const map = new Map<number, ResumeChatMessage>()
    for (const m of conv.savedItems) map.set(m.id, m)
    return map
  }, [conv.savedItems])

  const ROLE_LABEL = conv.roleLabel

  // Строим единый список рядов ленты: сохранённые (с id/attachments/reply_to) + pending-очередь.
  const rows: ChatRow[] = useMemo(() => {
    const savedRows: ChatRow[] = conv.savedItems.map((m) => {
      const replyId = m.reply_to_message_id
      const src = replyId != null ? messagesById.get(replyId) : undefined
      const quoted = src
        ? {
            label: ROLE_LABEL[src.role],
            snippet: oneLine(src.content, 70),
            sourceId: src.id,
          }
        : null
      return {
        key: `saved:${m.id}`,
        messageId: m.id,
        msg: { role: m.role, text: m.content },
        attachments: m.attachments,
        replyTo: quoted,
      }
    })
    // pending-обмены из стрим-стора (без id — контекстное меню недоступно).
    // Показываем только если обмен ещё не персистирован в savedItems (по тексту вопроса).
    const pending = conv.pending
    const pendingRows: ChatRow[] = []
    if (pending) {
      const savedQuestions = new Set(conv.savedItems.map((m) => m.content.trim()))
      if (!savedQuestions.has(pending.question.trim())) {
        pendingRows.push({
          key: `pending:${pending.localId}:user`,
          messageId: null,
          msg: { role: "user", text: pending.question },
          attachments: pending.attachments,
        })
        if (pending.answer.trim() || pending.status !== "done") {
          pendingRows.push({
            key: `pending:${pending.localId}:assistant`,
            messageId: null,
            msg: { role: "assistant", text: pending.answer, error: pending.error },
          })
        }
      }
    }
    return [...savedRows, ...pendingRows]
  }, [conv.savedItems, conv.pending, messagesById, ROLE_LABEL])

  const attachmentMessageIds = conv.savedItems
    .filter((m) => (m.attachments?.length ?? 0) > 0)
    .map((m) => m.id)
  const newAttachmentIds = useNewIds(attachmentMessageIds)

  // Чат теперь с собственной прокруткой: max-h ≈ экран по вертикали, скролл внутри.
  // Композер прижат снизу, не перекрывает форму. Автоскролл — вниз списка.
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const prevLen = useRef(0)
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const total = rows.length + (conv.isRunning ? 1 : 0)
    const grew = total > prevLen.current
    prevLen.current = total
    if (grew) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" })
  }, [rows, conv.isRunning])

  function targetIds(id: number): number[] {
    return selection.selectedIds.size > 0 ? Array.from(selection.selectedIds) : [id]
  }

  function copySelection(ids: number[]) {
    const idSet = new Set(ids)
    const selected = conv.savedItems.filter((m) => idSet.has(m.id))
    const text = selected.map((m) => `${ROLE_LABEL[m.role]}: ${m.content}`).join("\n\n")
    selection.clear()
    if (!text) return
    navigator.clipboard.writeText(text).then(
      () =>
        toast.success(selected.length === 1 ? "Сообщение скопировано" : "Сообщения скопированы"),
      () => toast.error("Не удалось скопировать"),
    )
  }

  function requestDeleteSelection(ids: number[]) {
    if (ids.length === 0) return
    setPendingDeleteIds(ids)
  }

  async function confirmDelete() {
    if (!pendingDeleteIds) return
    try {
      await conv.deleteMessages(pendingDeleteIds)
      selection.clear()
    } catch {
      /* тост в хуке */
    } finally {
      setPendingDeleteIds(null)
    }
  }

  async function doClear() {
    try {
      await conv.clear()
    } catch {
      /* тост в хуке */
    } finally {
      setConfirmClear(false)
    }
  }

  const hasMessages = rows.length > 0

  return (
    <div className={cn("flex flex-col border-t bg-white", className)}>
      {!hideAgent && hasMessages ? (
        <div ref={scrollRef} className="max-h-[55vh] space-y-1.5 overflow-y-auto px-4 pt-3">
          {rows.map((r) => {
            const id = r.messageId
            return (
              <Bubble
                key={r.key}
                mine={r.msg.role === "user"}
                label={ROLE_LABEL[r.msg.role]}
                body={r.msg.text}
                error={r.msg.error}
                messageId={id ?? undefined}
                quoted={r.replyTo}
                attachments={r.attachments}
                appear={id != null && newAttachmentIds.has(id)}
                selected={id != null && selection.selectedIds.has(id)}
                selecting={selection.isSelecting}
                onMouseDownSelect={(e) => {
                  if (id == null || e.button !== 0 || isInteractiveTarget(e)) return
                  selection.startPress(id)
                }}
                onMouseEnterSelect={() => {
                  if (id == null) return
                  selection.enterDrag(id)
                }}
                onContextMenuSelect={() => {
                  if (id == null) return
                  selection.ensureSelected(id)
                }}
                onReply={
                  id != null
                    ? () =>
                        setReplyTo({
                          id,
                          label: ROLE_LABEL[r.msg.role],
                          body: r.msg.text,
                        })
                    : undefined
                }
                onCopy={id != null ? () => copySelection(targetIds(id)) : undefined}
                onDelete={id != null ? () => requestDeleteSelection(targetIds(id)) : undefined}
              />
            )
          })}
          {conv.isRunning && !conv.pending ? (
            <div className="flex justify-start">
              <div className="flex items-center gap-2 rounded-2xl rounded-bl-sm bg-violet-100 px-3 py-2 text-xs text-slate-500">
                <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />
                Думаю…
              </div>
            </div>
          ) : null}
        </div>
      ) : null}

      <ResumeChatComposer
        conv={conv}
        hideAgent={hideAgent}
        onToggleHideAgent={() => setHideAgent((v) => !v)}
        replyTo={replyTo}
        onClearReply={() => setReplyTo(null)}
        selection={selection}
        onCopySelection={() => copySelection(Array.from(selection.selectedIds))}
        onRequestDeleteSelection={() =>
          requestDeleteSelection(Array.from(selection.selectedIds))
        }
        onRequestClear={() => setConfirmClear(true)}
      />

      <ConfirmDialog
        open={pendingDeleteIds != null}
        onOpenChange={(open) => {
          if (!open) setPendingDeleteIds(null)
        }}
        title={
          pendingDeleteIds
            ? `Удалить ${pendingDeleteIds.length} ${pluralMessages(pendingDeleteIds.length)}?`
            : "Удалить сообщение?"
        }
        description="Действие необратимо."
        onConfirm={() => void confirmDelete()}
      />
      <ConfirmDialog
        open={confirmClear}
        onOpenChange={setConfirmClear}
        title="Очистить весь чат?"
        description="Вся история диалога по резюме будет удалена. Действие необратимо."
        confirmLabel="Очистить"
        onConfirm={() => void doClear()}
      />
    </div>
  )
})
