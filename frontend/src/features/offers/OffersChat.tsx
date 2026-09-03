/**
 * Чат вкладки «Офферы»: паритет с чатом «Рынка»/`Резюме` — закреплённый композер, вложения,
 * «Агент» с глазиком, очистка, копировать/удалить/ответить. Один разговор на аккаунт.
 * Контекст карточек собирается на бэке на каждый запрос — не статичный снимок.
 */
import { useEffect, useMemo, useRef, useState, type MouseEvent } from "react"
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
import type { OffersChatMessage } from "@/api/offers-chat"
import { OffersChatComposer, type OffersReplyTarget } from "./OffersChatComposer"
import { useOffersConversation, type OffersPendingExchange } from "./use-offers-conversation"

const ROLE_LABEL: Record<OffersChatMessage["role"], string> = { user: "Я", assistant: "Агент" }

function fmtMsgTime(iso: string | null | undefined): string | null {
  if (!iso) return null
  const ms = Date.parse(iso)
  if (Number.isNaN(ms)) return null
  const d = new Date(ms)
  const p = (n: number) => String(n).padStart(2, "0")
  return `${p(d.getDate())}.${p(d.getMonth() + 1)} ${p(d.getHours())}:${p(d.getMinutes())}`
}

function oneLine(s: string, max: number): string {
  const flat = s.replace(/\s+/g, " ").trim()
  return flat.length > max ? `${flat.slice(0, max - 1)}…` : flat
}

function resolveQuote(
  message: OffersChatMessage,
  byId: Map<number, OffersChatMessage>,
): { label: string; snippet: string; sourceId: number } | null {
  const replyId = message.reply_to_message_id
  if (replyId == null) return null
  const src = byId.get(replyId)
  if (!src) return null
  return { sourceId: src.id, label: ROLE_LABEL[src.role], snippet: oneLine(src.content, 70) }
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
      id={messageId != null ? `offers-msg-${messageId}` : undefined}
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
                document.getElementById(`offers-msg-${quoted.sourceId}`)?.scrollIntoView({
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

export function OffersChat() {
  const conv = useOffersConversation()
  const [hideAgent, setHideAgent] = usePersistedBoolean("copilot.offers-chat.hide-agent")
  const selection = useMessageSelection()
  const [replyTo, setReplyTo] = useState<OffersReplyTarget | null>(null)
  const [pendingDeleteIds, setPendingDeleteIds] = useState<number[] | null>(null)
  const [confirmClear, setConfirmClear] = useState(false)

  const messagesById = useMemo(() => {
    const map = new Map<number, OffersChatMessage>()
    for (const m of conv.messages) map.set(m.id, m)
    return map
  }, [conv.messages])

  const attachmentMessageIds = conv.messages
    .filter((m) => (m.attachments?.length ?? 0) > 0)
    .map((m) => m.id)
  const newAttachmentIds = useNewIds(attachmentMessageIds)

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

  function targetIds(id: number): number[] {
    return selection.selectedIds.size > 0 ? Array.from(selection.selectedIds) : [id]
  }

  function copySelection(ids: number[]) {
    const idSet = new Set(ids)
    const selected = conv.messages.filter((m) => idSet.has(m.id))
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

  const hasMessages = conv.messages.length > 0 || conv.pending != null

  return (
    <div className="flex flex-col border-t bg-white">
      {!hideAgent && hasMessages ? (
        <div ref={scrollRef} className="max-h-[55vh] space-y-1.5 overflow-y-auto px-4 pt-3">
          {conv.messages.map((m) => (
            <Bubble
              key={m.id}
              mine={m.role === "user"}
              label={ROLE_LABEL[m.role]}
              body={m.content}
              time={fmtMsgTime(m.created_at)}
              messageId={m.id}
              quoted={resolveQuote(m, messagesById)}
              attachments={m.attachments}
              appear={newAttachmentIds.has(m.id)}
              selected={selection.selectedIds.has(m.id)}
              selecting={selection.isSelecting}
              onMouseDownSelect={(e) => {
                if (e.button !== 0 || isInteractiveTarget(e)) return
                selection.startPress(m.id)
              }}
              onMouseEnterSelect={() => selection.enterDrag(m.id)}
              onContextMenuSelect={() => selection.ensureSelected(m.id)}
              onReply={() => setReplyTo({ id: m.id, label: ROLE_LABEL[m.role], body: m.content })}
              onCopy={() => copySelection(targetIds(m.id))}
              onDelete={() => requestDeleteSelection(targetIds(m.id))}
            />
          ))}
          {conv.pending ? (
            <PendingExchangeBubbles pending={conv.pending} isRunning={conv.isRunning} />
          ) : null}
        </div>
      ) : null}

      <OffersChatComposer
        conv={conv}
        hideAgent={hideAgent}
        onToggleHideAgent={() => setHideAgent((v) => !v)}
        replyTo={replyTo}
        onClearReply={() => setReplyTo(null)}
        selection={selection}
        onCopySelection={() => copySelection(Array.from(selection.selectedIds))}
        onRequestDeleteSelection={() => requestDeleteSelection(Array.from(selection.selectedIds))}
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
        description="Вся история диалога по офферам будет удалена. Действие необратимо."
        confirmLabel="Очистить"
        onConfirm={() => void doClear()}
      />
    </div>
  )
}

function PendingExchangeBubbles({
  pending,
  isRunning,
}: {
  pending: OffersPendingExchange
  isRunning: boolean
}) {
  return (
    <>
      <Bubble
        mine
        label={ROLE_LABEL.user}
        body={pending.question}
        time={fmtMsgTime(new Date(pending.askedAt).toISOString())}
        attachments={pending.attachments}
        appear={Boolean(pending.attachments?.length)}
      />
      {pending.answer ? (
        <Bubble
          mine={false}
          label={ROLE_LABEL.assistant}
          body={pending.answer}
          error={pending.error}
        />
      ) : isRunning ? (
        <div className="flex justify-start">
          <div className="flex items-center gap-2 rounded-2xl rounded-bl-sm bg-violet-100 px-3 py-2 text-xs text-slate-500">
            <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />
            Думаю…
          </div>
        </div>
      ) : null}
    </>
  )
}
