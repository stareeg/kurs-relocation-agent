import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
  type RefObject,
} from "react"
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleDashed,
  Copy,
  CornerUpLeft,
  Download,
  FileSearch,
  LineChart,
  Loader2,
  Paperclip,
  Send,
  Sparkles,
  Trash2,
  X,
} from "lucide-react"
import { toast } from "sonner"
import type { Job } from "@/api/jobs"
import type { AttachmentOut } from "@/api/attachments"
import type { DebriefResult } from "@/api/debrief"
import type { PrepChatMessageOut, PrepQuestionOut } from "@/api/prep"
import { Button } from "@/components/ui/button"
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuTrigger,
} from "@/components/ui/context-menu"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { HelpTip } from "@/components/ui/help-tip"
import { MarkdownView } from "@/components/markdown-view"
import { Textarea } from "@/components/ui/textarea"
import { cn, MOTION_RISE, useNewIds } from "@/lib/utils"
import {
  flashMessage,
  ModeSegment,
  oneLine,
  SelectionToolbar,
  type ReplyTarget,
} from "@/components/chat/composer-widgets"
import { AttachmentChips } from "@/components/chat/attachments/AttachmentChips"
import { AttachmentGrid } from "@/components/chat/attachments/AttachmentGrid"
import { copyImageToClipboard } from "@/components/chat/attachments/copy-image"
import { ImageCropper } from "@/components/chat/attachments/ImageCropper"
import { ImageViewer } from "@/components/chat/attachments/ImageViewer"
import {
  useAttachmentUpload,
  type PendingAttachment,
} from "@/components/chat/attachments/use-attachment-upload"
import {
  ACCEPTED_ATTACHMENT_MIME,
  usePasteImages,
} from "@/components/chat/attachments/use-paste-images"
import type { MessageSelection } from "@/features/jobs/use-message-selection"
import type { useAnalyzeDebrief } from "@/features/tech/use-debrief"
import { usePrepChat, useSendPrepChat } from "./use-prep"
import { TelegramPushButton } from "@/features/settings/TelegramPushButton"
import {
  buildPrepChatBody,
  classifyPrepChatChannels,
  extractExternalTranscript,
  prepMessageAuthorLabel,
  sanitizeChatContent,
  type PrepChatChannel,
} from "./prep-chat-shared"

const MIN_TRANSCRIPT = 20

// Два режима композера, а не три: «Внешний ИИ» убран — вставленную переписку разбирает сам агент
// (см. блок «Владелец вставил чужую переписку» в промпте чата подготовки), отдельная кнопка
// «Импорт» для того же действия только дробила вход. Старые реплики импорта в ленте остаются и
// показываются вместе с ответами агента (канал `external` больше не прячется отдельно).
export type PrepView = "questions" | "debrief"

function fmtTime(ts?: string | null): string {
  if (!ts) return ""
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ""
  return d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })
}

// Клики по ссылке/кнопке цитаты внутри пузыря не должны запускать выделение (как в VacancyDialog).
// Миниатюра вложения — тоже `<button>`, но она должна протягиваться/выделяться как текст
// (`data-attachment-thumb` отличает её от прочих кнопок, план §6.6).
function isInteractiveTarget(e: { target: EventTarget | null }): boolean {
  if (!(e.target instanceof HTMLElement)) return false
  const el = e.target.closest("a, button")
  return el != null && !el.hasAttribute("data-attachment-thumb")
}

// Скачивает вложение по прямому URL (тот же origin — cookie доезжает, план §5).
function downloadAttachment(attachment: AttachmentOut) {
  const link = document.createElement("a")
  link.href = attachment.url
  link.download = `attachment-${attachment.id}`
  document.body.appendChild(link)
  link.click()
  link.remove()
}

// Экспортирована — переиспользуется QuestionsChatPanel (Скрининги): та же логика цитаты-ответа
// нужна и там, чат подготовки общий (prep_chat, накопительный по вакансии).
// eslint-disable-next-line react-refresh/only-export-components -- утилита рядом с компонентами чата, общий модуль
export function resolvePrepQuote(
  message: PrepChatMessageOut,
  messagesById: Map<number, PrepChatMessageOut>,
  channelById: Map<number, PrepChatChannel>,
): { label: string; snippet: string; sourceId: number } | null {
  const replyId = message.reply_to_message_id
  if (replyId == null) return null
  const src = messagesById.get(replyId)
  if (!src) return null
  const mine = src.role === "user"
  const external = mine ? extractExternalTranscript(src.content) : null
  return {
    sourceId: src.id,
    label: prepMessageAuthorLabel(mine, channelById.get(src.id) ?? "agent"),
    snippet: oneLine(external ?? sanitizeChatContent(src.content), 70),
  }
}

// Экспортирована — переиспользуется QuestionsChatPanel (Скрининги) для реплик общего чата
// подготовки (prep_chat), тем же визуальным языком и той же механикой выделения.
export function ChatBubble({
  msg,
  channel,
  quoted,
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
  msg: PrepChatMessageOut
  channel: PrepChatChannel
  quoted?: { label: string; snippet: string; sourceId: number } | null
  /** План §6.3: появление сообщения с картинкой в ленте — fade + подъём, только для только что
   * пришедших реплик (см. `useNewIds`), не для истории при первой отрисовке. */
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
  const mine = msg.role === "user"
  const externalTranscript = mine ? extractExternalTranscript(msg.content) : null
  const content = mine
    ? externalTranscript != null
      ? "Внешняя переписка (парсинг)"
      : msg.content
    : sanitizeChatContent(msg.content)
  const label = prepMessageAuthorLabel(mine, channel)
  const attachments = msg.attachments ?? []
  const hasAttachments = attachments.length > 0
  // План §6.3: сообщение только с картинками (без текста) — пузырь теряет фон/паддинги, картинка
  // и есть пузырь; скругление то же, время+подпись — поверх нижнего правого угла.
  const imageOnly = hasAttachments && content.trim() === ""
  const roundedSide = mine ? "rounded-br-sm" : "rounded-bl-sm"

  function copyExternal() {
    if (!externalTranscript) return
    void navigator.clipboard.writeText(externalTranscript).then(
      () => toast.success("Переписка скопирована"),
      () => toast.error("Не удалось скопировать"),
    )
  }

  const row = (
    <div
      id={msg.id >= 0 ? `msg-${msg.id}` : undefined}
      className={cn("flex", mine ? "justify-end" : "justify-start", appear && MOTION_RISE)}
      onMouseDown={onMouseDownSelect}
      onMouseEnter={onMouseEnterSelect}
      onContextMenu={onContextMenuSelect}
    >
      <div
        className={cn(
          "max-w-[85%] rounded-2xl text-base leading-snug text-slate-900 transition-shadow",
          imageOnly
            ? cn("relative overflow-hidden", roundedSide)
            : cn("px-3.5 py-2", mine ? "rounded-br-sm bg-sky-100" : "rounded-bl-sm bg-violet-100"),
          selecting && "cursor-pointer select-none",
          selected && "ring-2 ring-sky-400 ring-offset-1",
        )}
      >
        {quoted ? (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              flashMessage(quoted.sourceId)
            }}
            className={cn(
              "mb-1 flex w-full min-w-0 items-start gap-1.5 border-l-2 border-slate-400/50 bg-black/[0.04] px-1.5 py-1 text-left",
              imageOnly ? "m-1.5 w-[calc(100%-0.75rem)] rounded-md" : "rounded-md",
            )}
          >
            <span className="min-w-0">
              <span className="block text-xs font-medium text-slate-600">{quoted.label}</span>
              <span className="block truncate text-xs text-slate-500">{quoted.snippet}</span>
            </span>
          </button>
        ) : null}
        {hasAttachments ? (
          <AttachmentGrid
            attachments={attachments}
            className={imageOnly ? "overflow-hidden rounded-[inherit]" : "mb-1"}
            onThumbnailClick={selecting ? () => false : undefined}
          />
        ) : null}
        {imageOnly ? (
          <div className="pointer-events-none absolute bottom-1 right-1 flex items-center gap-1.5 rounded-full bg-black/55 px-2 py-0.5 text-xs text-white">
            <span className="font-semibold uppercase tracking-wide">{label}</span>
            {msg.created_at && (
              <span className="font-semibold tabular-nums">{fmtTime(msg.created_at)}</span>
            )}
          </div>
        ) : (
          <>
            {mine ? (
              <p className="whitespace-pre-wrap">{content}</p>
            ) : (
              <MarkdownView markdown={content} chat />
            )}
            {externalTranscript != null && (
              <div className="mt-2 border-t border-sky-200/80 pt-2">
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  className="h-7 gap-1.5 px-2 text-xs text-slate-600 hover:bg-sky-50 hover:text-slate-900"
                  onClick={copyExternal}
                >
                  <Copy className="size-3.5" strokeWidth={2} />
                  Скопировать переписку
                </Button>
              </div>
            )}
            <div className="mt-0.5 flex items-center justify-end gap-2 text-xs">
              <span className="font-semibold uppercase tracking-wide text-slate-400">{label}</span>
              {msg.created_at && (
                <span className="font-semibold tabular-nums text-slate-400">
                  {fmtTime(msg.created_at)}
                </span>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )

  if (msg.id < 0 || !onReply || !onCopy || !onDelete) return row

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
        {hasAttachments ? (
          <>
            <ContextMenuItem
              onSelect={() => {
                void copyImageToClipboard(attachments[0].url).then(
                  () => toast.success("Картинка скопирована"),
                  () => toast.error("Не удалось скопировать"),
                )
              }}
            >
              <Copy />
              Копировать картинку
            </ContextMenuItem>
            <ContextMenuItem onSelect={() => downloadAttachment(attachments[0])}>
              <Download />
              Сохранить как…
            </ContextMenuItem>
          </>
        ) : null}
        <ContextMenuItem variant="destructive" onSelect={onDelete}>
          <Trash2 />
          Удалить
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  )
}

/** Локальная карточка экспорта контекста в ленте (не пишется в историю чата / LLM). */
export type ContextExportPayload = {
  kind: "prep" | "sobes"
  text: string
  subtitle: string
}

export function ContextExportCard({
  payload,
  onDismiss,
}: {
  payload: ContextExportPayload
  onDismiss?: () => void
}) {
  const [copied, setCopied] = useState(false)
  const title = payload.kind === "sobes" ? "Контекст для собеса" : "Контекст для внешнего ИИ"

  function copy() {
    void navigator.clipboard.writeText(payload.text).then(
      () => {
        setCopied(true)
        toast.success("Скопировано")
        window.setTimeout(() => setCopied(false), 1500)
      },
      () => toast.error("Не удалось скопировать"),
    )
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="flex items-start justify-between gap-3 border-b border-slate-100 px-4 py-3">
        <div className="min-w-0 space-y-0.5">
          <p className="text-sm font-medium text-slate-900">{title}</p>
          <p className="text-xs text-slate-500">{payload.subtitle}</p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Button size="sm" variant="outline" className="h-8 gap-1.5" onClick={copy}>
            {copied ? (
              <CheckCircle2 className="size-3.5 text-emerald-600" strokeWidth={2} />
            ) : (
              <Copy className="size-3.5" strokeWidth={2} />
            )}
            {copied ? "Скопировано" : "Копировать"}
          </Button>
          {onDismiss && (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="h-8 w-8 px-0 text-slate-400 hover:text-slate-700"
              aria-label="Убрать"
              onClick={onDismiss}
            >
              <X className="size-3.5" strokeWidth={2} />
            </Button>
          )}
        </div>
      </div>
      <div className="max-h-64 overflow-auto px-4 py-3 text-base leading-snug text-slate-700">
        <MarkdownView markdown={payload.text} chat />
      </div>
    </div>
  )
}

// RD-22b: как кандидат ответил на вопрос (по расшифровке) — «Сильно/Средне/Слабо»; ответа в
// расшифровке нет → честное «Под вопросом» вместо выдуманной оценки. Заменяет старый outcome-бейдж
// «Выпал/Не выпал», который ничего не говорил про качество ответа.
function QuestionMasteryBadge({ q }: { q: PrepQuestionOut }) {
  if (q.mastery === "confident") {
    return (
      <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">
        <CheckCircle2 className="size-3" strokeWidth={2.5} />
        Сильно
      </span>
    )
  }
  if (q.mastery === "medium") {
    return (
      <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700">
        <CheckCircle2 className="size-3" strokeWidth={2.5} />
        Средне
      </span>
    )
  }
  if (q.mastery === "weak") {
    return (
      <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-rose-50 px-2 py-0.5 text-xs font-medium text-rose-700">
        <CircleDashed className="size-3" strokeWidth={2.5} />
        Слабо
      </span>
    )
  }
  if (q.outcome === "asked") {
    return (
      <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">
        <CircleDashed className="size-3" strokeWidth={2.5} />
        Под вопросом
      </span>
    )
  }
  return null
}

/** Карточка вопрос→ответ в ленте: клик раскрывает готовый ответ (режим диалоговой подготовки).
 * Экспортирована — переиспользуется TechPage (вопросы HR-скрининга из screening-пакета тем же
 * визуальным языком, что prep-вопросы тех. этапов) и QuestionsChatPanel (Скрининги, где вопрос —
 * «сообщение агента» с той же механикой выделения, что у обычных реплик чата — см. опциональные
 * пропы селекции ниже).
 * Пропы выделения опциональны и не переданы у существующих потребителей — поведение там не
 * меняется; переданы они только там, где у вопроса есть стабильный синтетический id. */
export function QuestionBubble({
  q,
  index,
  isNew = false,
  onReveal,
  selected,
  selecting,
  onMouseDownSelect,
  onMouseEnterSelect,
  onContextMenuSelect,
  onReply,
  onCopy,
  onDelete,
}: {
  q: PrepQuestionOut
  index: number
  isNew?: boolean
  onReveal?: (q: PrepQuestionOut) => void
  selected?: boolean
  selecting?: boolean
  onMouseDownSelect?: (e: MouseEvent<HTMLButtonElement>) => void
  onMouseEnterSelect?: () => void
  onContextMenuSelect?: () => void
  onReply?: () => void
  onCopy?: () => void
  onDelete?: () => void
}) {
  const [open, setOpen] = useState(false)
  const hasAnswer = q.answer.trim().length > 0
  const revealedRef = useRef(false)
  const topic = q.topic?.trim() ?? ""

  function toggle() {
    if (!hasAnswer) return
    const next = !open
    setOpen(next)
    if (next && !revealedRef.current) {
      revealedRef.current = true
      onReveal?.(q)
    }
  }

  const bubble = (
    <div className="flex justify-start">
      <button
        type="button"
        disabled={!hasAnswer}
        onClick={toggle}
        onMouseDown={onMouseDownSelect}
        onMouseEnter={onMouseEnterSelect}
        onContextMenu={onContextMenuSelect}
        aria-expanded={hasAnswer ? open : undefined}
        className={cn(
          "group w-full max-w-[42rem] rounded-xl border px-4 py-3 text-left transition-all duration-200",
          hasAnswer
            ? "cursor-pointer border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50/80"
            : "cursor-default border-slate-200 bg-slate-50/60",
          isNew && "border-emerald-200 ring-2 ring-emerald-400/40",
          open && "border-slate-300 bg-white shadow-sm",
          selecting && "cursor-pointer select-none",
          selected && "ring-2 ring-sky-400 ring-offset-1",
        )}
      >
        <div className="flex items-start gap-3">
          <span
            className={cn(
              "mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-md text-xs font-medium tabular-nums",
              open ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-500",
            )}
          >
            {index}
          </span>
          <div className="min-w-0 flex-1 space-y-2">
            <div className="flex items-start justify-between gap-3">
              <p className="text-base font-medium leading-snug text-slate-900">{q.text}</p>
              <div className="flex shrink-0 items-center gap-1.5">
                <QuestionMasteryBadge q={q} />
                {hasAnswer && (
                  <ChevronRight
                    className={cn(
                      "size-4 text-slate-400 transition-transform duration-200 group-hover:text-slate-600",
                      open && "rotate-90",
                    )}
                    strokeWidth={2}
                    aria-hidden
                  />
                )}
              </div>
            </div>
            {(topic || (q.hint.trim() && !open)) && (
              <div className="flex flex-wrap items-center gap-2">
                {topic && (
                  <span className="rounded-md bg-slate-100 px-1.5 py-0.5 text-xs font-medium text-slate-500">
                    {topic}
                  </span>
                )}
                {q.hint.trim() && !open && <span className="text-sm text-slate-500">{q.hint}</span>}
              </div>
            )}
            {hasAnswer && !open && (
              <p className="text-xs text-slate-400 transition-colors group-hover:text-slate-600">
                Открыть ответ
              </p>
            )}
            {open && hasAnswer && (
              <div className="rounded-lg bg-slate-50 px-3 py-2.5">
                <p className="mb-1.5 text-xs font-medium uppercase tracking-wider text-slate-400">
                  Ответ
                </p>
                <div className="text-base leading-snug text-slate-700">
                  <MarkdownView markdown={q.answer} chat />
                </div>
              </div>
            )}
          </div>
        </div>
      </button>
    </div>
  )

  if (!onReply || !onCopy || !onDelete) return bubble

  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>{bubble}</ContextMenuTrigger>
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

/** Лента чата + Q&A-карточки. Скролл родителя (TechPage overflow) тянем вниз при новых репликах. */
export function PrepChatThread({
  vacancyId,
  questions = [],
  newlyAddedTexts,
  pendingContent,
  pendingChannel = "agent",
  isPending,
  elapsedMs,
  scrollParentRef,
  onRevealQuestion,
  contextExport = null,
  contextExportPending = false,
  onDismissContextExport,
  hideAgent = false,
  selection,
  onReply,
  onCopySelection,
  onDeleteSelection,
}: {
  vacancyId: string | null
  questions?: PrepQuestionOut[]
  newlyAddedTexts?: Set<string>
  pendingContent?: string | null
  pendingChannel?: PrepChatChannel
  isPending?: boolean
  elapsedMs?: number
  scrollParentRef?: RefObject<HTMLDivElement | null>
  onRevealQuestion?: (q: PrepQuestionOut) => void
  contextExport?: ContextExportPayload | null
  contextExportPending?: boolean
  onDismissContextExport?: () => void
  hideAgent?: boolean
  selection?: MessageSelection
  onReply?: (target: ReplyTarget) => void
  onCopySelection?: (ids: number[]) => void
  onDeleteSelection?: (ids: number[]) => void
}) {
  const { data: chatData, isLoading: chatLoading } = usePrepChat(vacancyId)
  const bottomRef = useRef<HTMLDivElement | null>(null)
  const history = useMemo(() => chatData?.items ?? [], [chatData])

  const channels = useMemo(() => classifyPrepChatChannels(history), [history])
  const channelById = useMemo(() => {
    const map = new Map<number, PrepChatChannel>()
    history.forEach((m, i) => map.set(m.id, channels[i]))
    return map
  }, [history, channels])
  const messagesById = useMemo(() => {
    const map = new Map<number, PrepChatMessageOut>()
    for (const m of history) map.set(m.id, m)
    return map
  }, [history])

  // План §6.3: анимируем появление только тех реплик с картинкой, что довставились после первой
  // отрисовки ленты, а не всю историю при открытии Техничек.
  const attachmentMessageIds = history
    .filter((m) => (m.attachments?.length ?? 0) > 0)
    .map((m) => m.id)
  const newAttachmentIds = useNewIds(attachmentMessageIds)

  const optimisticUser: PrepChatMessageOut | null =
    isPending && pendingContent
      ? {
          id: -1,
          vacancy_id: vacancyId ?? "",
          role: "user",
          content: pendingContent,
          created_at: null,
          reply_to_message_id: null,
        }
      : null

  const visible: PrepChatMessageOut[] = [...history, ...(optimisticUser ? [optimisticUser] : [])]
  const visibleChannels: PrepChatChannel[] = [
    ...channels,
    ...(optimisticUser ? [pendingChannel] : []),
  ]
  // «Глазик» у «Агента» гасит всю переписку с моделью — и обычные ответы, и старые реплики
  // импорта внешней переписки (отдельного режима/фильтра у них больше нет).
  const shown = visible.map((m, i) => ({ m, channel: visibleChannels[i] })).filter(() => !hideAgent)

  function targetIds(id: number): number[] {
    if (!selection || selection.selectedIds.size === 0) return [id]
    return Array.from(selection.selectedIds)
  }

  useEffect(() => {
    const parent = scrollParentRef?.current
    if (parent) {
      parent.scrollTo({ top: parent.scrollHeight, behavior: "smooth" })
      return
    }
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" })
  }, [
    visible.length,
    questions.length,
    vacancyId,
    isPending,
    scrollParentRef,
    contextExport?.text,
    contextExportPending,
  ])

  if (chatLoading && !contextExport && !contextExportPending) {
    return (
      <div className="flex items-center gap-2 justify-center py-4 text-sm text-slate-400">
        <Loader2 className="size-4 animate-spin" strokeWidth={2} />
        Загружаю чат…
      </div>
    )
  }

  if (
    visible.length === 0 &&
    questions.length === 0 &&
    !isPending &&
    !contextExport &&
    !contextExportPending
  ) {
    return null
  }

  const shownQuestions = hideAgent ? [] : questions
  const fresh = newlyAddedTexts ?? new Set<string>()
  const stableQuestions = shownQuestions.filter((q) => !fresh.has(q.text))
  const freshQuestions = shownQuestions.filter((q) => fresh.has(q.text))

  // Нумерация сквозная по всем карточкам в ленте (стабильные → свежие), чтобы при добавлении
  // пачки номера не прыгали у уже видимых вопросов.
  const stableCount = stableQuestions.length
  const pendingHidden = hideAgent

  return (
    <div className="space-y-3">
      {stableQuestions.map((q, i) => (
        <QuestionBubble
          key={`q-${i}-${q.text.slice(0, 40)}`}
          q={q}
          index={i + 1}
          onReveal={onRevealQuestion}
        />
      ))}
      {shown.map(({ m, channel }) => (
        <ChatBubble
          key={m.id}
          msg={m}
          channel={channel}
          quoted={resolvePrepQuote(m, messagesById, channelById)}
          appear={newAttachmentIds.has(m.id)}
          selected={selection?.selectedIds.has(m.id) ?? false}
          selecting={selection?.isSelecting ?? false}
          onMouseDownSelect={(e) => {
            if (e.button !== 0 || isInteractiveTarget(e) || m.id < 0) return
            selection?.startPress(m.id)
          }}
          onMouseEnterSelect={() => {
            if (m.id >= 0) selection?.enterDrag(m.id)
          }}
          onContextMenuSelect={() => {
            if (m.id >= 0) selection?.ensureSelected(m.id)
          }}
          onReply={
            m.id >= 0 && onReply
              ? () => {
                  const bodyText =
                    (m.role === "user" ? extractExternalTranscript(m.content) : null) ??
                    sanitizeChatContent(m.content)
                  const firstAttachment = m.attachments?.[0]
                  onReply({
                    id: m.id,
                    label: prepMessageAuthorLabel(m.role === "user", channel),
                    body: bodyText.trim()
                      ? bodyText
                      : (firstAttachment?.analysis?.title ?? "Вложение"),
                    thumbUrl: firstAttachment?.thumb_url,
                  })
                }
              : undefined
          }
          onCopy={m.id >= 0 && onCopySelection ? () => onCopySelection(targetIds(m.id)) : undefined}
          onDelete={
            m.id >= 0 && onDeleteSelection ? () => onDeleteSelection(targetIds(m.id)) : undefined
          }
        />
      ))}
      {freshQuestions.map((q, i) => (
        <QuestionBubble
          key={`qn-${i}-${q.text.slice(0, 40)}`}
          q={q}
          index={stableCount + i + 1}
          isNew
          onReveal={onRevealQuestion}
        />
      ))}
      {isPending && !pendingHidden && (
        <div className="flex justify-start">
          <div className="flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-2 text-sm text-slate-500">
            <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />
            Готовлю ответ… {Math.floor((elapsedMs ?? 0) / 1000)}с
          </div>
        </div>
      )}
      {contextExportPending && (
        <div className="flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-500">
          <Loader2 className="size-4 animate-spin" strokeWidth={2} />
          Собираю контекст…
        </div>
      )}
      {contextExport && !contextExportPending && (
        <ContextExportCard payload={contextExport} onDismiss={onDismissContextExport} />
      )}
      <div ref={bottomRef} />
    </div>
  )
}

// Композер снизу: Агент (свободный чат; он же разбирает вставленную чужую переписку) /
// Расшифровка (вставить транскрипт собеса) — тот же переключатель с «глазиком» скрытия, что у
// Агент/HR в разделе «Чаты» (UX8). У «Расшифровки» появляется галка, когда по этапу разбор уже
// есть — «вставлено/не вставлено» видно прямо на переключалке.
export function PrepChat({
  job,
  stage,
  focusTopics,
  view,
  onChangeView,
  hideAgent,
  onToggleHideAgent,
  hideDebrief,
  onToggleHideDebrief,
  onOpenTopics,
  analyze,
  debriefInterviewStageId,
  debriefDone = false,
  transcriptDraft = null,
  onDebriefAnalyzed,
  onDebriefSubmitted,
  contextMenuOpen,
  onContextMenuOpenChange,
  onRequestPrepContext,
  onRequestSobesContext,
  contextBusy = false,
  contextDisabled = false,
  replyTo = null,
  onClearReply,
  selection,
  onCopySelection,
  onRequestDeleteSelection,
  onQuestions,
  onSendState,
  composerSeed,
}: {
  job: Job | null
  stage: string
  focusTopics: string[]
  view: PrepView
  onChangeView: (view: PrepView) => void
  hideAgent: boolean
  onToggleHideAgent: () => void
  hideDebrief: boolean
  onToggleHideDebrief: () => void
  /** Кнопка «Темы» в тулбаре (слева от «В Telegram») — открывает ProgressPanel выдвижной панелью
   * (план п.5). Нет пропа → кнопка не рендерится. */
  onOpenTopics?: () => void
  /** Общий с DebriefSection/DebriefPendingCard экземпляр мутации - владелец состояния остаётся в
   * TechPage (там же читает `analyze.isPending`/`elapsedMs` для карточки ожидания над лентой). */
  analyze: ReturnType<typeof useAnalyzeDebrief>
  debriefInterviewStageId: number | null
  /** По этому этапу расшифровка уже разобрана — галка на переключалке «Расшифровка». */
  debriefDone?: boolean
  transcriptDraft?: { text: string; nonce: number } | null
  onDebriefAnalyzed: (result: DebriefResult) => void
  /** Задача разбора заведена — родитель возвращает композер в «Агент» (поле не блокируем). */
  onDebriefSubmitted?: () => void
  /** Дропдаун «Контекст» (для внешнего ИИ / оверлея sobes.tech) - логика и мутации остаются в
   * TechPage (тот же `contextExport`, что рисует лента), здесь только сама кнопка в общем тулбаре
   * рядом с переключателем режимов, скрыта в режиме «Расшифровка». */
  contextMenuOpen: boolean
  onContextMenuOpenChange: (open: boolean) => void
  onRequestPrepContext: () => void
  onRequestSobesContext: () => void
  contextBusy?: boolean
  contextDisabled?: boolean
  replyTo?: ReplyTarget | null
  onClearReply: () => void
  selection: MessageSelection
  onCopySelection: () => void
  onRequestDeleteSelection: () => void
  onQuestions?: (questions: PrepQuestionOut[], topic: string | null) => void
  onSendState?: (state: {
    isPending: boolean
    pendingContent: string | null
    pendingChannel: PrepChatChannel
    elapsedMs: number
  }) => void
  /** RD-25: вопрос из «Разбора собеса» — встаёт готовым текстом в композер (обсудить с агентом).
   * При смене значения (по nonce-`seen` ref) затирает черновик владельца намеренно: клик по
   * вопросу означает «обсудим именно его». */
  composerSeed?: string | null
}) {
  const vacancyId = job?.vacancy_id ?? null
  const { data: chatData } = usePrepChat(vacancyId)
  const send = useSendPrepChat(vacancyId, stage, onQuestions)
  const [text, setText] = useState("")
  const [seenVacancyId, setSeenVacancyId] = useState(vacancyId)
  if (vacancyId !== seenVacancyId) {
    setSeenVacancyId(vacancyId)
    setText("")
  }
  // RD-25: seed с «Ответить» из Разбора собеса. Идемпотентно по значению (не спамим setState на
  // каждый рендер родителя): сам текст и есть nonce — два одинаковых клика подряд не перезапишут.
  const [seenSeed, setSeenSeed] = useState<string | null | undefined>(undefined)
  const seed = composerSeed ?? null
  if (seed !== seenSeed) {
    setSeenSeed(seed)
    if (seed) setText(seed)
  }

  // Картинки доступны в обоих режимах: в «Агенте» уходят в модель как вложение реплики, в
  // «Расшифровке» распознанный текст дописывается в поле (носитель текста, §3 плана).
  const attachmentsEnabled = true
  const attachments = useAttachmentUpload()
  const fileInputRef = useRef<HTMLInputElement>(null)
  // Кнопка-скрепка живёт в общем тулбаре (не уезжает при смене режима, как в QuestionsChatPanel
  // Скринингов) — в «Расшифровке» клик дёргает файл-пикер DebriefComposer через его ручку.
  const debriefComposerRef = useRef<DebriefComposerHandle>(null)
  const [debriefState, setDebriefState] = useState<DebriefComposerState>({
    canAnalyze: false,
    analyzing: false,
    elapsedMs: 0,
  })
  function openAttachPicker() {
    if (view === "debrief") debriefComposerRef.current?.openFilePicker()
    else fileInputRef.current?.click()
  }
  const [cropTarget, setCropTarget] = useState<{ key: string; attachment: AttachmentOut } | null>(
    null,
  )
  const [viewerIndex, setViewerIndex] = useState<number | null>(null)
  function clearAttachments() {
    attachments.clear()
  }
  const readyAttachments = useMemo(
    () =>
      attachments.items
        .filter((i): i is PendingAttachment & { attachment: AttachmentOut } => i.attachment != null)
        .map((i) => i.attachment),
    [attachments.items],
  )
  const paste = usePasteImages({
    onFiles: attachments.addFiles,
    queuedCount: attachments.items.length,
    disabled: !attachmentsEnabled || attachments.isUploading,
  })
  function openViewer(item: PendingAttachment) {
    if (!item.attachment) return
    const idx = readyAttachments.findIndex((a) => a.id === item.attachment!.id)
    if (idx !== -1) setViewerIndex(idx)
  }
  function openCrop(item: PendingAttachment) {
    if (!item.attachment) return
    setCropTarget({ key: item.key, attachment: item.attachment })
  }
  const [chatElapsedMs, setChatElapsedMs] = useState(0)
  const busyPending = send.isPending
  useEffect(() => {
    if (!busyPending) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- сброс таймера по флагу мутации
      setChatElapsedMs(0)
      return
    }
    const start = Date.now()
    const id = window.setInterval(() => setChatElapsedMs(Date.now() - start), 1000)
    return () => window.clearInterval(id)
  }, [busyPending])

  useEffect(() => {
    onSendState?.({
      isPending: busyPending,
      pendingContent: send.isPending && send.variables ? send.variables.message : null,
      pendingChannel: "agent",
      elapsedMs: chatElapsedMs,
    })
  }, [busyPending, send.isPending, send.variables, chatElapsedMs, onSendState])

  const history = chatData?.items ?? []
  const trimmed = text.trim()
  const hasAttachments = attachments.attachmentIds.length > 0
  const canSend = !!vacancyId && !busyPending && (trimmed.length > 0 || hasAttachments)

  function submit() {
    if (!canSend) return
    const body = buildPrepChatBody(
      job,
      stage,
      focusTopics,
      trimmed,
      history,
      replyTo?.id,
      attachments.attachmentIds,
    )
    setText("")
    clearAttachments()
    onClearReply()
    send.mutate(body)
  }

  const placeholder = !vacancyId
    ? "Сначала выберите вакансию"
    : "Спросите про тему, попросите ещё пачку вопросов или вставьте переписку из другого чата — разберу…"

  return (
    <section
      className={cn(
        "flex shrink-0 flex-col border-t bg-white transition-colors",
        attachmentsEnabled &&
          paste.isDraggingOver &&
          "bg-sky-50 outline-dashed outline-2 -outline-offset-2 outline-sky-300",
      )}
      onPaste={attachmentsEnabled ? paste.onPaste : undefined}
      onDragEnter={attachmentsEnabled ? paste.onDragEnter : undefined}
      onDragOver={attachmentsEnabled ? paste.onDragOver : undefined}
      onDragLeave={attachmentsEnabled ? paste.onDragLeave : undefined}
      onDrop={attachmentsEnabled ? paste.onDrop : undefined}
    >
      <div className="flex flex-wrap items-center gap-1.5 p-3 pb-0">
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
              {attachmentsEnabled ? (
                <>
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
                  <HelpTip id="tech.attachments" side="top">
                    <Button
                      size="icon"
                      variant="outline"
                      type="button"
                      aria-label="Приложить картинку"
                      disabled={
                        !vacancyId || (view === "debrief" ? debriefState.analyzing : busyPending)
                      }
                      onClick={openAttachPicker}
                    >
                      <Paperclip className="size-4" strokeWidth={2} />
                    </Button>
                  </HelpTip>
                </>
              ) : null}
              <div className="inline-flex items-center gap-1 rounded-xl bg-slate-100 p-1">
                <ModeSegment
                  active={view === "questions"}
                  onClick={() => onChangeView("questions")}
                  icon={Sparkles}
                  label="Агент"
                  hidden={hideAgent}
                  onToggleHidden={onToggleHideAgent}
                  hideTitle="ответы агента"
                />
                <ModeSegment
                  active={view === "debrief"}
                  onClick={() => onChangeView("debrief")}
                  icon={FileSearch}
                  label="Расшифровка"
                  hidden={hideDebrief}
                  onToggleHidden={onToggleHideDebrief}
                  hideTitle="расшифровку"
                  done={debriefDone}
                  doneTitle="Расшифровка этого этапа уже разобрана"
                />
              </div>
            </div>
            <div className="ml-auto flex shrink-0 items-center gap-1.5">
              {onOpenTopics && (
                <Button
                  size="sm"
                  variant="outline"
                  className="gap-1.5"
                  onClick={onOpenTopics}
                  aria-label="Темы"
                >
                  <LineChart className="size-4" strokeWidth={2} />
                  Темы
                </Button>
              )}
              {vacancyId && <TelegramPushButton kind="prep_questions" vacancyId={vacancyId} />}
              <DropdownMenu open={contextMenuOpen} onOpenChange={onContextMenuOpenChange}>
                <HelpTip id="chat.copy-context" side="bottom">
                  <DropdownMenuTrigger asChild>
                    <Button
                      size="sm"
                      variant="outline"
                      className="gap-1.5"
                      disabled={contextBusy || contextDisabled}
                      aria-label="Собрать контекст"
                    >
                      {contextBusy ? (
                        <Loader2 className="size-4 animate-spin" strokeWidth={2} />
                      ) : (
                        <Copy className="size-4" strokeWidth={2} />
                      )}
                      {contextBusy ? "Собираю…" : "Контекст"}
                      {!contextBusy && (
                        <ChevronDown className="size-3.5 opacity-60" strokeWidth={2} />
                      )}
                    </Button>
                  </DropdownMenuTrigger>
                </HelpTip>
                <DropdownMenuContent className="w-72" align="end">
                  <DropdownMenuItem
                    className="flex-col items-start gap-0.5 py-2"
                    onSelect={onRequestPrepContext}
                  >
                    <span className="text-sm font-medium text-foreground">Для внешнего ИИ</span>
                    <span className="text-xs text-muted-foreground">
                      Полный контекст подготовки — вставить в другой чат
                    </span>
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    className="flex-col items-start gap-0.5 py-2"
                    onSelect={onRequestSobesContext}
                  >
                    <span className="text-sm font-medium text-foreground">Для собеса</span>
                    <span className="text-xs text-muted-foreground">
                      Сжатая шпаргалка, до 3900 символов
                    </span>
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
              {view === "debrief" ? (
                <>
                  {debriefState.analyzing && (
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      className="text-slate-500"
                      onClick={() => analyze.cancel()}
                    >
                      Отменить
                    </Button>
                  )}
                  <HelpTip id="tech.debrief" side="top">
                    <Button
                      size="sm"
                      className="gap-1.5"
                      disabled={!debriefState.canAnalyze}
                      onClick={() => debriefComposerRef.current?.submit()}
                    >
                      {debriefState.analyzing ? (
                        <Loader2 className="size-4 animate-spin" strokeWidth={2} />
                      ) : (
                        <Sparkles className="size-4" strokeWidth={2} />
                      )}
                      {debriefState.analyzing
                        ? `Анализирую… ${Math.floor(debriefState.elapsedMs / 1000)}с`
                        : "Анализ"}
                    </Button>
                  </HelpTip>
                </>
              ) : (
                <Button size="sm" className="gap-1.5" disabled={!canSend} onClick={submit}>
                  {send.isPending ? (
                    <Loader2 className="size-4 animate-spin" strokeWidth={2} />
                  ) : (
                    <Send className="size-4" strokeWidth={2} />
                  )}
                  {send.isPending ? "Отправляю…" : "Отправить"}
                </Button>
              )}
            </div>
          </>
        )}
        {!selection.isSelecting && <HelpTip id="tech.prep-views" />}
      </div>

      {view === "debrief" ? (
        <DebriefComposer
          ref={debriefComposerRef}
          job={job}
          stage={stage}
          analyze={analyze}
          interviewStageId={debriefInterviewStageId}
          transcriptDraft={transcriptDraft}
          onAnalyzed={onDebriefAnalyzed}
          onSubmitted={onDebriefSubmitted}
          onStateChange={setDebriefState}
          hideOwnAttachButton
        />
      ) : (
        <>
          {replyTo ? (
            <div className="mx-3 mt-2 flex items-center gap-2 rounded-lg border-l-2 border-sky-400 bg-sky-50/60 py-1.5 pl-2.5 pr-1.5">
              <CornerUpLeft className="size-3.5 shrink-0 text-sky-500" strokeWidth={2} />
              {replyTo.thumbUrl ? (
                <img
                  src={replyTo.thumbUrl}
                  alt=""
                  className="size-5 shrink-0 rounded object-cover"
                />
              ) : null}
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

          {attachmentsEnabled && attachments.items.length > 0 ? (
            <div className="px-3 pt-2">
              <AttachmentChips
                items={attachments.items}
                onRemove={attachments.remove}
                onRetry={attachments.retry}
                onOpen={openViewer}
              />
            </div>
          ) : null}

          <div className="p-3">
            <Textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={placeholder}
              disabled={!vacancyId || busyPending}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                  e.preventDefault()
                  submit()
                }
              }}
            />
          </div>
        </>
      )}

      {attachmentsEnabled ? (
        <>
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
          {viewerIndex != null && readyAttachments[viewerIndex] ? (
            <ImageViewer
              attachments={readyAttachments}
              index={viewerIndex}
              onIndexChange={setViewerIndex}
              onClose={() => setViewerIndex(null)}
              onCropRequested={(attachment) => {
                setViewerIndex(null)
                const item = attachments.items.find((i) => i.attachment?.id === attachment.id)
                // Открываем кроппер следующим тиком — иначе просмотрщик (свой Radix Dialog) и
                // кроппер (тоже Dialog) закрываются/открываются в одном коммите, и второй
                // диалог может унаследовать недочищенный body-lock/aria-hidden первого.
                if (item) window.setTimeout(() => openCrop(item), 0)
              }}
            />
          ) : null}
        </>
      ) : null}
    </section>
  )
}

// Композер режима «Расшифровка»: третий режим композера «Подготовки» (Агент/Внешний ИИ/
// Расшифровка) — вставить расшифровку и разобрать, тем же чатом, что вопросы подготовки (RD-25→
// слияние: раньше был отдельным верхнеуровневым разделом «Разбор собеса», дублировал контент).
// Общий тулбар и шапка — у родителя (PrepChat/QuestionsChatPanel), здесь только сам композер.
/** Ручка для внешнего управления композером — родитель рендерит свой общий тулбар (кнопка-
 * скрепка + «Анализ» в одном ряду с переключателем режимов, см. QuestionsChatPanel/PrepChat) и
 * дёргает выбор файла/отправку через ref, вместо дублирования своей кнопки/инпута здесь. */
export type DebriefComposerHandle = { openFilePicker: () => void; submit: () => void }

/** Состояние для кнопки «Анализ» в общем тулбаре родителя - тот не дублирует `canAnalyze`. */
export type DebriefComposerState = { canAnalyze: boolean; analyzing: boolean; elapsedMs: number }

export const DebriefComposer = forwardRef<
  DebriefComposerHandle,
  {
    job: Job | null
    stage: string
    analyze?: ReturnType<typeof useAnalyzeDebrief>
    interviewStageId?: number | null
    transcriptDraft?: { text: string; nonce: number } | null
    onAnalyzed?: (result: DebriefResult) => void
    /** Задача разбора заведена (LLM ещё не ответила) — родитель возвращает композер в «Агент»:
     * ждать минуту с заблокированным полем и своим же текстом в нём незачем, прогресс виден
     * карточкой в ленте. */
    onSubmitted?: () => void
    // Родитель уже рендерит свою кнопку-скрепку (тот же слот, что и в режиме «Агент») и дёргает
    // выбор файла через ref — свою кнопку/инпут прятать, чтобы не задваивать.
    hideOwnAttachButton?: boolean
    onStateChange?: (state: DebriefComposerState) => void
  }
>(function DebriefComposer(
  {
    job,
    stage,
    analyze,
    interviewStageId = null,
    transcriptDraft = null,
    onAnalyzed,
    onSubmitted,
    hideOwnAttachButton = false,
    onStateChange,
  },
  ref,
) {
  const vacancyId = job?.vacancy_id ?? null
  const [text, setText] = useState("")
  const [seenDraftNonce, setSeenDraftNonce] = useState<number | null>(null)
  if (transcriptDraft && transcriptDraft.nonce !== seenDraftNonce) {
    setSeenDraftNonce(transcriptDraft.nonce)
    setText(transcriptDraft.text)
  }
  const [seenVacancyId, setSeenVacancyId] = useState(vacancyId)
  if (vacancyId !== seenVacancyId) {
    setSeenVacancyId(vacancyId)
    setText("")
  }

  // Э4-4 (план chat_image_attachments): скрин собеса/транскрипции — "носитель текста" (§3
  // плана), без ветки-переключателя (в отличие от HR-импорта/«Внешнего ИИ» — здесь картинка
  // всегда источник текста расшифровки, а не альтернативное вложение диалога). Распознанный
  // текст дописывается в поле ниже сам, как только готов — владелец видит и правит до анализа.
  const attachments = useAttachmentUpload()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [cropTarget, setCropTarget] = useState<{ key: string; attachment: AttachmentOut } | null>(
    null,
  )
  const [viewerIndex, setViewerIndex] = useState<number | null>(null)
  const appendedAttachmentIds = useRef<Set<number>>(new Set())

  useEffect(() => {
    attachments.clear()
    appendedAttachmentIds.current.clear()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- сброс только по смене вакансии
  }, [vacancyId])

  useEffect(() => {
    for (const item of attachments.items) {
      const att = item.attachment
      if (!att || att.analysis_status !== "ready" || !att.analysis) continue
      if (appendedAttachmentIds.current.has(att.id)) continue
      appendedAttachmentIds.current.add(att.id)
      const recognized = att.analysis.text.trim()
      if (!recognized) continue
      // Вливаем текст распознавания, пришедший асинхронно (поллинг/live-статус вложения).
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setText((prev) => (prev.trim() ? `${prev.trim()}\n\n${recognized}` : recognized))
    }
  }, [attachments.items])

  const readyAttachments = useMemo(
    () =>
      attachments.items
        .filter((i): i is PendingAttachment & { attachment: AttachmentOut } => i.attachment != null)
        .map((i) => i.attachment),
    [attachments.items],
  )
  const paste = usePasteImages({
    onFiles: attachments.addFiles,
    queuedCount: attachments.items.length,
    disabled: attachments.isUploading,
  })
  function openViewer(item: PendingAttachment) {
    if (!item.attachment) return
    const idx = readyAttachments.findIndex((a) => a.id === item.attachment!.id)
    if (idx !== -1) setViewerIndex(idx)
  }
  function openCrop(item: PendingAttachment) {
    if (!item.attachment) return
    setCropTarget({ key: item.key, attachment: item.attachment })
  }

  const trimmed = text.trim()
  const analyzing = !!analyze?.isPending
  const canAnalyze = !!job && trimmed.length >= MIN_TRANSCRIPT && !analyzing

  const runAnalyze = useCallback(() => {
    if (!job || !canAnalyze || !analyze) return
    const hasScore = job.score && Object.keys(job.score).length > 0
    // UX21: HR-скрининг в Техничках хранит внутренний этап `hr_screening`, но бэкенд разбора
    // (PrepStage/DebriefAnalyzeRequest) знает его как `screening` — нормализуем перед отправкой,
    // иначе дебриф этапа сохранится с невалидным типом и не всплывёт в нужной секции.
    const debriefStage = stage === "hr_screening" ? "screening" : stage
    analyze.mutate(
      {
        transcript: trimmed,
        stage: debriefStage as never,
        vacancy_text: job.vacancy_text,
        title: job.title,
        company: job.company,
        salary_text: job.salary_text,
        score: hasScore ? (job.score as never) : null,
        interview_stage_id: interviewStageId,
        attachment_ids: attachments.attachmentIds,
      },
      { onSuccess: (result) => onAnalyzed?.(result) },
    )
    // Чистим поле сразу, не по ответу LLM: разбор — фоновая задача (`useAnalyzeDebrief` держит
    // текст у себя и вернёт его в поле, если задача упадёт), а владелец в это время должен иметь
    // возможность писать агенту, а не смотреть на свою же расшифровку в мёртвом инпуте.
    setText("")
    attachments.clear()
    appendedAttachmentIds.current.clear()
    onSubmitted?.()
  }, [
    job,
    canAnalyze,
    analyze,
    stage,
    trimmed,
    interviewStageId,
    attachments,
    onAnalyzed,
    onSubmitted,
  ])

  useImperativeHandle(
    ref,
    () => ({ openFilePicker: () => fileInputRef.current?.click(), submit: runAnalyze }),
    [runAnalyze],
  )

  const elapsedMs = analyze?.elapsedMs ?? 0
  useEffect(() => {
    onStateChange?.({ canAnalyze, analyzing, elapsedMs })
    // eslint-disable-next-line react-hooks/exhaustive-deps -- onStateChange - стабильный колбэк родителя, не триггерим по нему
  }, [canAnalyze, analyzing, elapsedMs])

  return (
    // Без своей верхней рамки: композер живёт ВНУТРИ уже обведённого блока родителя (там же
    // переключалка Агент/Расшифровка), и `border-t` рисовал лишнюю полоску между переключалкой и
    // полем ввода — её ни на что нельзя было нажать.
    <section
      className={cn(
        "flex shrink-0 flex-col bg-white transition-colors",
        paste.isDraggingOver &&
          "bg-sky-50 outline-dashed outline-2 -outline-offset-2 outline-sky-300",
      )}
      onPaste={paste.onPaste}
      onDragEnter={paste.onDragEnter}
      onDragOver={paste.onDragOver}
      onDragLeave={paste.onDragLeave}
      onDrop={paste.onDrop}
    >
      {/* RD-25: плашка «Разбор собеса» убрана — назначение поля читается из placeholder. Кнопка
          прикрепления и «Анализ» теперь в общем тулбаре родителя (тот же ряд, что переключатель
          режимов) — здесь остаётся только скрытый инпут файла, открывается через ref. */}
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
      {!hideOwnAttachButton && (
        <div className="flex items-center gap-1.5 border-b px-3 py-2">
          <HelpTip id="tech.attachments" side="top">
            <Button
              size="sm"
              variant="outline"
              type="button"
              className="gap-1.5"
              aria-label="Приложить скриншот собеса"
              disabled={!vacancyId || analyzing}
              onClick={() => fileInputRef.current?.click()}
            >
              <Paperclip className="size-4" strokeWidth={2} />
              Приложить
            </Button>
          </HelpTip>
        </div>
      )}
      {attachments.items.length > 0 ? (
        <div className="px-3 pt-2">
          <AttachmentChips
            items={attachments.items}
            onRemove={attachments.remove}
            onRetry={attachments.retry}
            onOpen={openViewer}
          />
        </div>
      ) : null}
      <div className="flex items-end gap-2 p-3">
        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Вставьте расшифровку или заметки после собеса — текст с диктофона, чат из Teams/Zoom, свои пометки, скриншот…"
          className="flex-1"
          disabled={!vacancyId}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault()
              runAnalyze()
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
      {viewerIndex != null && readyAttachments[viewerIndex] ? (
        <ImageViewer
          attachments={readyAttachments}
          index={viewerIndex}
          onIndexChange={setViewerIndex}
          onClose={() => setViewerIndex(null)}
          onCropRequested={(attachment) => {
            setViewerIndex(null)
            const item = attachments.items.find((i) => i.attachment?.id === attachment.id)
            // Открываем кроппер следующим тиком — иначе просмотрщик (свой Radix Dialog) и
            // кроппер (тоже Dialog) закрываются/открываются в одном коммите, и второй
            // диалог может унаследовать недочищенный body-lock/aria-hidden первого.
            if (item) window.setTimeout(() => openCrop(item), 0)
          }}
        />
      ) : null}
    </section>
  )
})
