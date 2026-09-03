import { useEffect, useMemo, useRef, useState } from "react"
import { Copy, CornerUpLeft, Loader2, Send, Sparkles, User, X } from "lucide-react"
import { toast } from "sonner"
import type { AdminRecentAction, AdminSupportMessage } from "@/api/admin"
import { Button } from "@/components/ui/button"
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuTrigger,
} from "@/components/ui/context-menu"
import { HelpTip } from "@/components/ui/help-tip"
import { Textarea } from "@/components/ui/textarea"
import {
  flashMessage,
  ModeSegment,
  oneLine,
  type ReplyTarget,
} from "@/components/chat/composer-widgets"
import { MarkdownView } from "@/components/markdown-view"
import { formatMoment } from "@/features/admin/admin-format"
import { formatRecentAction } from "@/features/admin/recent-actions"
import { useAdminSupportThread, useSendAdminSupportMessage } from "@/features/admin/use-admin"
import { usePersistedBoolean } from "@/lib/use-persisted-boolean"
import { cn } from "@/lib/utils"

type SupportMode = "user" | "agent"

/**
 * Лента поддержки в карточке человека: Telegram (человек видит) и агент (только оператор).
 */
export function SupportChat({
  accountId,
  canMessageUser,
  recentActions,
  compact = false,
}: {
  accountId: number
  canMessageUser: boolean
  recentActions?: readonly AdminRecentAction[] | null
  compact?: boolean
}) {
  const thread = useAdminSupportThread(accountId)
  const send = useSendAdminSupportMessage()
  const [mode, setMode] = useState<SupportMode>("user")
  const [text, setText] = useState("")
  const [replyTo, setReplyTo] = useState<ReplyTarget | null>(null)
  const [hideUser, setHideUser] = usePersistedBoolean("copilot.admin.support.hide-user")
  const [hideAgent, setHideAgent] = usePersistedBoolean("copilot.admin.support.hide-agent")
  const scroller = useRef<HTMLDivElement>(null)
  const items = useMemo(() => thread.data?.items ?? [], [thread.data?.items])
  const byId = useMemo(() => new Map(items.map((item) => [item.id, item])), [items])
  const visible = items.filter((item) => (item.channel === "agent" ? !hideAgent : !hideUser))
  const actions = (recentActions ?? []).slice(0, 6)

  useEffect(() => {
    const node = scroller.current
    if (!node) return
    node.scrollTop = node.scrollHeight
  }, [visible.length, send.isPending])

  const busy = send.isPending
  const canSend =
    Boolean(text.trim()) &&
    !busy &&
    (mode === "agent" || canMessageUser)

  const submit = () => {
    const body = text.trim()
    if (!body || !canSend) return
    send.mutate(
      {
        accountId,
        channel: mode,
        text: body,
        replyToId: replyTo?.id ?? null,
      },
      {
        onSuccess: () => {
          setText("")
          setReplyTo(null)
        },
      },
    )
  }

  return (
    <div
      className={cn(
        "flex min-h-0 shrink-0 flex-col bg-white",
        compact ? "w-[22rem] max-w-[min(22rem,calc(100vw-2rem))]" : "border-t",
      )}
    >
      {actions.length > 0 ? (
        <ul
          className={cn(
            "shrink-0 space-y-0.5 border-b bg-slate-50/80 py-2",
            compact ? "px-3" : "px-5",
          )}
        >
          {actions.map((action, index) => (
            <li
              key={`${action.kind}-${action.at ?? index}-${action.label}`}
              className="flex items-baseline gap-2 text-xs text-slate-500"
            >
              <span className="shrink-0 tabular-nums text-slate-400">
                {formatMoment(action.at)}
              </span>
              <span className="min-w-0 truncate text-slate-700">
                {formatRecentAction(action)}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      {thread.isLoading && items.length === 0 ? (
        <p className={cn("shrink-0 py-2 text-xs text-slate-400", compact ? "px-3" : "px-5")}>
          Загрузка переписки…
        </p>
      ) : visible.length > 0 ? (
        <div
          ref={scroller}
          className={cn(
            "max-h-[55vh] space-y-1.5 overflow-y-auto py-3",
            compact ? "max-h-48 px-3" : "px-5",
          )}
        >
          {visible.map((item) => (
            <SupportBubble
              key={item.id}
              item={item}
              quoted={resolveQuote(item, byId)}
              onReply={() =>
                setReplyTo({
                  id: item.id,
                  label: supportAuthorLabel(item),
                  body: item.body,
                })
              }
              onCopy={() => copyBody(item.body)}
            />
          ))}
        </div>
      ) : items.length > 0 ? (
        <p className={cn("shrink-0 py-2 text-xs text-slate-400", compact ? "px-3" : "px-5")}>
          Сообщения скрыты глазиком режима.
        </p>
      ) : null}
      <div className={cn("space-y-2 border-t py-3", compact ? "px-3" : "px-5")}>
        <div className="flex items-center gap-1.5">
          <div className="inline-flex min-w-0 flex-1 items-center gap-1 rounded-xl bg-slate-100 p-1">
            <ModeSegment
              active={mode === "user"}
              onClick={() => setMode("user")}
              icon={User}
              label="Пользователь"
              hidden={hideUser}
              onToggleHidden={() => setHideUser((value) => !value)}
              hideTitle="сообщения пользователя"
            />
            <ModeSegment
              active={mode === "agent"}
              onClick={() => setMode("agent")}
              icon={Sparkles}
              label="Агент"
              hidden={hideAgent}
              onToggleHidden={() => setHideAgent((value) => !value)}
              hideTitle="переписку с агентом"
            />
          </div>
          {!compact ? <HelpTip id="admin.support-chat" showIcon /> : null}
          <Button
            size="default"
            className="h-9 shrink-0 gap-1.5 px-3"
            disabled={!canSend}
            onClick={submit}
          >
            {busy ? (
              <Loader2 className="size-4 animate-spin" strokeWidth={2} />
            ) : (
              <Send className="size-4" strokeWidth={2} />
            )}
            Отправить
          </Button>
        </div>
        {replyTo ? (
          <div className="flex items-center gap-2 rounded-lg border-l-2 border-sky-400 bg-sky-50/60 py-1.5 pl-2.5 pr-1.5">
            <CornerUpLeft className="size-3.5 shrink-0 text-sky-500" strokeWidth={2} />
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-medium text-sky-800">{replyTo.label}</p>
              <p className="truncate text-xs text-slate-500">{oneLine(replyTo.body, 100)}</p>
            </div>
            <button
              type="button"
              onClick={() => setReplyTo(null)}
              aria-label="Убрать ответ"
              className="rounded-md p-1 text-slate-400 transition-colors hover:bg-slate-200/60 hover:text-slate-600"
            >
              <X className="size-3.5" strokeWidth={2} />
            </button>
          </div>
        ) : null}
        {!canMessageUser && mode === "user" ? (
          <p className="text-xs text-slate-400">Нет привязанного чата — доставить некуда.</p>
        ) : null}
        {mode === "agent" ? (
          <p className="text-xs text-slate-400">Человек эту ветку не видит.</p>
        ) : null}
        <Textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault()
              submit()
            }
          }}
          placeholder={mode === "agent" ? "Спросить агента поддержки…" : "Написать человеку…"}
          disabled={busy}
          aria-label="Текст сообщения"
          className="text-sm"
        />
      </div>
    </div>
  )
}

function SupportBubble({
  item,
  quoted,
  onReply,
  onCopy,
}: {
  item: AdminSupportMessage
  quoted: { id: number; label: string; snippet: string } | null
  onReply: () => void
  onCopy: () => void
}) {
  const mine = item.role === "admin"
  const agent = item.role === "agent"
  const row = (
    <div id={`msg-${item.id}`} className={cn("flex", mine ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[80%] rounded-2xl px-3 py-1.5",
          mine
            ? "rounded-br-sm bg-sky-100"
            : agent
              ? "rounded-bl-sm bg-violet-100"
              : "rounded-bl-sm bg-slate-100",
        )}
      >
        {quoted ? (
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation()
              flashMessage(quoted.id)
            }}
            className="mb-1 flex w-full min-w-0 items-start rounded-md border-l-2 border-slate-400/50 bg-black/[0.04] px-1.5 py-1 text-left"
          >
            <span className="min-w-0">
              <span className="block text-xs font-medium text-slate-600">{quoted.label}</span>
              <span className="block truncate text-xs text-slate-500">{quoted.snippet}</span>
            </span>
          </button>
        ) : null}
        {agent ? (
          <MarkdownView markdown={item.body} chat />
        ) : (
          <p className="whitespace-pre-wrap break-words text-sm leading-snug text-slate-900">
            {item.body}
          </p>
        )}
        <div className="mt-0.5 flex items-center justify-end gap-2 text-xs">
          <span className="font-medium text-slate-400">{supportAuthorLabel(item)}</span>
          <span className="font-semibold tabular-nums text-slate-500">
            {formatMoment(item.created_at)}
          </span>
        </div>
      </div>
    </div>
  )

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
      </ContextMenuContent>
    </ContextMenu>
  )
}

function supportAuthorLabel(item: AdminSupportMessage): string {
  if (item.role === "agent") return "Агент"
  if (item.role === "user") return "Пользователь"
  return item.channel === "agent" ? "Вы → агент" : "Вы"
}

function resolveQuote(
  item: AdminSupportMessage,
  byId: Map<number, AdminSupportMessage>,
): { id: number; label: string; snippet: string } | null {
  if (item.reply_to_id == null) return null
  const source = byId.get(item.reply_to_id)
  if (!source) return null
  return { id: source.id, label: supportAuthorLabel(source), snippet: oneLine(source.body, 70) }
}

function copyBody(body: string) {
  if (!body) return
  void navigator.clipboard.writeText(body).then(
    () => toast.success("Сообщение скопировано"),
    () => toast.error("Не удалось скопировать"),
  )
}
