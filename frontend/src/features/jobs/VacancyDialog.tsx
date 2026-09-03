import { Fragment, useMemo, useRef, useState, type MouseEvent, type ReactNode } from "react"
import {
  ChevronDown,
  Clock,
  Copy,
  CornerUpLeft,
  Download,
  Loader2,
  Paperclip,
  Pencil,
  PhoneCall,
  Send,
  Sparkles,
  Trash2,
  User,
  X,
} from "lucide-react"
import { toast } from "sonner"
import { cn, MOTION_RISE, useNewIds } from "@/lib/utils"
import { formatEventLabel } from "@/lib/format"
import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuTrigger,
} from "@/components/ui/context-menu"
import { DateTimePopover } from "@/components/ui/date-time-popover"
import { HelpTip } from "@/components/ui/help-tip"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import { MarkdownView } from "@/components/markdown-view"
import {
  flashMessage,
  ModeSegment,
  oneLine,
  SelectionToolbar,
  type ReplyTarget,
} from "@/components/chat/composer-widgets"
import { linkify } from "@/components/chat/linkify"
import { AttachmentChips } from "@/components/chat/attachments/AttachmentChips"
import { AttachmentGrid } from "@/components/chat/attachments/AttachmentGrid"
import { copyImageToClipboard } from "@/components/chat/attachments/copy-image"
import { ImageCropper } from "@/components/chat/attachments/ImageCropper"
import { ImageViewer } from "@/components/chat/attachments/ImageViewer"
import { defaultAttachmentRoute } from "@/components/chat/attachments/route"
import {
  useAttachmentUpload,
  type PendingAttachment,
} from "@/components/chat/attachments/use-attachment-upload"
import {
  ACCEPTED_ATTACHMENT_MIME,
  usePasteImages,
} from "@/components/chat/attachments/use-paste-images"
import type { AttachmentOut, AttachmentRoute } from "@/api/attachments"
import {
  hrMessageLabel,
  messageAuthorLabel,
  type ConvMessage,
  type MessageKind,
} from "@/api/conversations"
import type { DebriefResult } from "@/api/debrief"
import type { InterviewStageOut } from "@/api/interview-stages"
import { FollowUpChips } from "@/features/chat/FollowUpChips"
import { useActiveContexts } from "@/features/chat/use-active-contexts"
import { useDebriefHistory, usePatchDebriefTranscript } from "@/features/tech/use-debrief"
import {
  useDeleteInterviewStage,
  useInterviewStages,
  usePatchInterviewStage,
} from "@/features/tech/use-interview-stages"
import { TranscriptChat } from "@/features/tech/DebriefSection"
import type { VacancyConversation } from "./use-vacancy-conversation"
import type { MessageSelection } from "./use-message-selection"

export type { ReplyTarget }

// Единый разговор по вакансии (R-4): лента HR-переписки + LLM-чата с пометкой типа реплики, плюс
// композер: агент (стрим LLM) или HR (вставка дампа переписки → LLM-разбор и дополнение ленты).
// Режим «Вакансия» вынесен в закреплённую строку над лентой (VacancyPinnedText, план п.2).

const KIND_META: Record<MessageKind, { mine: boolean; cls: string; label: string }> = {
  hr_in: { mine: false, cls: "bg-violet-100 rounded-bl-sm", label: "HR" },
  hr_out: { mine: true, cls: "bg-sky-100 rounded-br-sm", label: "Я → HR" },
  llm_user: { mine: true, cls: "bg-sky-100 rounded-br-sm", label: "Я" },
  llm_assistant: { mine: false, cls: "bg-violet-100 rounded-bl-sm", label: "Агент" },
}

function resolveQuote(
  message: ConvMessage,
  messagesById: Map<number, ConvMessage>,
  hrContactName?: string | null,
): { label: string; snippet: string; sourceId: number } | null {
  const replyId = message.reply_to_message_id
  if (replyId == null) return null
  const src = messagesById.get(replyId)
  if (!src) return null
  return {
    sourceId: src.id,
    label: messageAuthorLabel(src.kind, hrContactName),
    snippet: oneLine(src.body, 70),
  }
}

function fmtMsgTime(ms: number): string {
  const d = new Date(ms)
  const p = (n: number) => String(n).padStart(2, "0")
  return `${p(d.getDate())}.${p(d.getMonth() + 1)} ${p(d.getHours())}:${p(d.getMinutes())}`
}

function ownMs(m: ConvMessage): number | null {
  for (const v of [m.sent_at, m.created_at]) {
    if (v) {
      const t = Date.parse(v)
      if (!Number.isNaN(t)) return t
    }
  }
  return null
}

// UX5-5: этап становится «звонком» в ленте только когда его дата уже прошла (см. п.4 плана).
function isPastStage(s: InterviewStageOut): boolean {
  if (!s.scheduled_at) return false
  const t = Date.parse(s.scheduled_at)
  return !Number.isNaN(t) && t <= Date.now()
}

// Ближайший ещё не наступивший этап — виджет «скоро собес» внизу диалога. Не просто зеркало
// isPastStage: там status игнорируется (отменённый прошедший этап всё равно рисуется как
// CallEvent), здесь отменённый/перенесённый этап осознанно не считается «предстоящим».
function isFutureStage(s: InterviewStageOut): boolean {
  if (s.status !== "scheduled" || !s.scheduled_at) return false
  const t = Date.parse(s.scheduled_at)
  return !Number.isNaN(t) && t > Date.now()
}

// Клики по ссылке в тексте или по кнопке цитаты (переход к сообщению-источнику) не должны
// запускать выделение — иначе прыжок к цитате мог бы попутно снять/добавить чужое выделение.
// Миниатюра вложения (план §6.6) — тоже `<button>`, но она НЕ попадает в это исключение: картинка
// должна протягиваться/выделяться как текст; `data-attachment-thumb` отличает её от прочих кнопок.
function isInteractiveTarget(e: { target: EventTarget | null }): boolean {
  if (!(e.target instanceof HTMLElement)) return false
  const el = e.target.closest("a, button")
  return el != null && !el.hasAttribute("data-attachment-thumb")
}

// Скачивает вложение по прямому URL (тот же origin — cookie доезжает, см. план §5); программный
// клик по временной ссылке, потому что действие живёт в контекстном меню, а не в <a download>.
function downloadAttachment(attachment: AttachmentOut) {
  const link = document.createElement("a")
  link.href = attachment.url
  link.download = `attachment-${attachment.id}`
  document.body.appendChild(link)
  link.click()
  link.remove()
}

function Bubble({
  kind,
  body,
  time,
  error,
  hrContactName,
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
  kind: MessageKind
  body: string
  time?: string | null
  error?: boolean
  hrContactName?: string | null
  messageId?: number
  quoted?: { label: string; snippet: string; sourceId: number } | null
  attachments?: AttachmentOut[]
  /** План §6.3: появление сообщения с картинкой в ленте — fade + подъём на 180 мс. Только для
   * только что пришедших реплик (см. `useNewIds`), не для истории при первой отрисовке. */
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
  const meta = KIND_META[kind]
  const isLlmAnswer = kind === "llm_assistant"
  const label =
    kind === "hr_in" || kind === "hr_out" ? hrMessageLabel(kind, hrContactName) : meta.label
  const hasAttachments = attachments.length > 0
  // План §6.3: сообщение только с картинками (без текста) — пузырь теряет фон/паддинги, картинка
  // и есть пузырь; скругление то же, время+подпись — поверх нижнего правого угла.
  const imageOnly = hasAttachments && body.trim() === ""
  const roundedSide = meta.mine ? "rounded-br-sm" : "rounded-bl-sm"
  const row = (
    <div
      id={messageId != null ? `msg-${messageId}` : undefined}
      className={cn("flex", meta.mine ? "justify-end" : "justify-start", appear && MOTION_RISE)}
      onMouseDown={onMouseDownSelect}
      onMouseEnter={onMouseEnterSelect}
      onContextMenu={onContextMenuSelect}
    >
      <div
        className={cn(
          "max-w-[68%] rounded-2xl transition-shadow",
          imageOnly
            ? cn("relative overflow-hidden", roundedSide)
            : cn("px-3 py-1.5", error ? "rounded-bl-sm bg-rose-100" : meta.cls),
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
          <>
            {!imageOnly && (kind === "hr_in" || kind === "hr_out") ? (
              // Э4-1: скрин, из которого разобрана эта реплика (якорь пачки импорта, §3 плана) —
              // не вложение диалога, поэтому подписан отдельно от обычной картинки.
              <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-slate-400">
                Источник: скриншот
              </p>
            ) : null}
            <AttachmentGrid
              attachments={attachments}
              className={imageOnly ? "overflow-hidden rounded-[inherit]" : "mb-1"}
              onThumbnailClick={selecting ? () => false : undefined}
            />
          </>
        ) : null}
        {imageOnly ? (
          <div className="pointer-events-none absolute bottom-1 right-1 flex items-center gap-1.5 rounded-full bg-black/55 px-2 py-0.5 text-xs text-white">
            <span className="font-semibold uppercase tracking-wide">{label}</span>
            {time && <span className="font-semibold tabular-nums">{time}</span>}
          </div>
        ) : (
          <>
            {body ? (
              isLlmAnswer ? (
                <MarkdownView markdown={body} chat />
              ) : (
                <p className="whitespace-pre-wrap break-words text-base leading-snug text-slate-900">
                  {linkify(body)}
                </p>
              )
            ) : null}
            <div className="mt-0.5 flex items-center justify-end gap-2 text-xs">
              <span
                className={cn(
                  "font-semibold text-slate-400",
                  kind === "hr_in" || kind === "hr_out"
                    ? "tracking-normal"
                    : "uppercase tracking-wide",
                )}
              >
                {label}
              </span>
              {time && <span className="font-semibold tabular-nums text-slate-500">{time}</span>}
            </div>
          </>
        )}
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

// UX5-5: синтетическая запись «звонок» в ленте диалога — не настоящее сообщение из hr_messages, а
// производная от `interview_stages` (дата) + связанного через `interview_stage_id` дебрифа (если
// есть). Нейтральный системный стиль (пилюля по центру), спойлер — транскрипт с редактированием
// или заглушка, если разбора ещё нет.
function CallEvent({
  stage,
  debrief,
  vacancyId,
}: {
  stage: InterviewStageOut
  debrief: DebriefResult | undefined
  vacancyId: string
}) {
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState("")
  const patchTranscript = usePatchDebriefTranscript(vacancyId)
  const when = formatEventLabel(stage.scheduled_at)
  const label = when ? `Созвон: ${stage.stage_label}, ${when}` : `Созвон: ${stage.stage_label}`
  function startEdit() {
    setText(debrief?.transcript ?? "")
    setEditing(true)
  }
  function saveEdit() {
    if (debrief?.id == null) return
    patchTranscript.mutate(
      { debriefId: debrief.id, transcript: text.trim() },
      { onSuccess: () => setEditing(false) },
    )
  }
  return (
    <div className="flex flex-col items-center gap-1.5 py-1">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-500 shadow-sm transition-colors hover:bg-slate-50"
      >
        <PhoneCall className="size-3.5 shrink-0" strokeWidth={2} />
        {label}
        <ChevronDown
          className={cn(
            "size-3.5 shrink-0 text-slate-400 transition-transform",
            open && "rotate-180",
          )}
          strokeWidth={2}
        />
      </button>
      {open && (
        <div className="w-full max-w-[85%] rounded-xl border bg-white p-3">
          {!debrief ? (
            <p className="text-sm text-slate-400">Расшифровки пока нет</p>
          ) : editing ? (
            <div className="space-y-2">
              <Textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                className="text-sm"
                maxHeight={320}
                disabled={patchTranscript.isPending}
              />
              <div className="flex justify-end gap-2">
                <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
                  Отмена
                </Button>
                <Button
                  size="sm"
                  onClick={saveEdit}
                  disabled={patchTranscript.isPending || !text.trim()}
                >
                  {patchTranscript.isPending ? (
                    <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />
                  ) : (
                    "Сохранить"
                  )}
                </Button>
              </div>
            </div>
          ) : (
            <>
              <TranscriptChat
                turns={debrief.analysis.transcript_turns ?? []}
                transcript={debrief.transcript ?? ""}
                fallbackTs={debrief.created_at}
              />
              <div className="flex justify-end pt-1">
                <Button
                  size="sm"
                  variant="ghost"
                  className="gap-1.5 text-slate-500"
                  onClick={startEdit}
                >
                  <Pencil className="size-3.5" strokeWidth={2} />
                  Изменить
                </Button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}

// Пилюля «скоро собес» внизу ленты — пока дата не наступила (когда наступит, этап сам попадёт
// в isPastStage/CallEvent выше, статус пересчитывается по времени существующей логикой на бэке).
// Клик по дате — быстрый попап «календарь + время» (перенос), отдельная кнопка — удалить встречу
// целиком. Бэкенд не новый: PATCH/DELETE /api/interview-stages/{vacancy_id}/{stage_id} уже есть.
function UpcomingCallWidget({ stage, vacancyId }: { stage: InterviewStageOut; vacancyId: string }) {
  const patchStage = usePatchInterviewStage(vacancyId)
  const deleteStage = useDeleteInterviewStage(vacancyId)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const when = formatEventLabel(stage.scheduled_at)
  const label = when ? `Скоро: ${stage.stage_label}, ${when}` : `Скоро: ${stage.stage_label}`
  return (
    <div className="flex flex-col items-center gap-1.5 py-1">
      <div className="inline-flex items-center gap-0.5 rounded-full border border-sky-200 bg-sky-50 py-1 pl-3 pr-1 text-xs font-medium text-sky-700 shadow-sm">
        <PhoneCall className="size-3.5 shrink-0" strokeWidth={2} />
        <DateTimePopover
          value={stage.scheduled_at}
          onChange={(iso) => patchStage.mutate({ stageId: stage.id, body: { scheduled_at: iso } })}
          trigger={
            <button type="button" className="rounded px-1 hover:underline">
              {label}
            </button>
          }
        />
        <button
          type="button"
          onClick={() => setConfirmDelete(true)}
          title="Удалить встречу"
          className="inline-flex items-center justify-center rounded-full p-1 text-sky-400 transition-colors hover:bg-sky-100 hover:text-sky-700"
        >
          <X className="size-3.5" strokeWidth={2} />
        </button>
      </div>
      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title="Удалить встречу?"
        description="Этап уйдёт из цепочки собеса. Действие необратимо."
        confirmLabel="Удалить"
        onConfirm={() => {
          deleteStage.mutate(stage.id)
          setConfirmDelete(false)
        }}
      />
    </div>
  )
}

// Живой/ещё не сохранённый обмен (`queue`) не имеет стабильного id сообщения (появляется только
// после персиста), поэтому не заводится в общий `Bubble`+`ContextMenu` (тот требует messageId для
// Ответить/Копировать/Удалить разом). Здесь — облегчённая версия того же меню без «Ответить»:
// «Копировать» берёт текст напрямую (без id), «Удалить» = conv.dismissPending(item.localId),
// одинаково для успешных и упавших обменов — раньше это делала только кнопка «Убрать» под ошибкой.
function QueueBubbleMenu({
  text,
  onDelete,
  children,
}: {
  text: string
  onDelete: () => void
  children: ReactNode
}) {
  function copyText() {
    if (!text) return
    navigator.clipboard.writeText(text).then(
      () => toast.success("Сообщение скопировано"),
      () => toast.error("Не удалось скопировать"),
    )
  }
  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>{children}</ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuItem onSelect={copyText}>
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

type TimelineEntry =
  | { kind: "message"; ms: number; message: ConvMessage }
  | { kind: "call"; ms: number; stage: InterviewStageOut }

export function DialogTimeline({
  conv,
  vacancyId,
  hrContactName: hrContactNameProp,
  hideHr,
  hideAi,
  selection,
  onReply,
  onCopySelection,
  onDeleteSelection,
}: {
  conv: VacancyConversation
  vacancyId: string
  hrContactName?: string | null
  hideHr?: boolean
  hideAi?: boolean
  selection: MessageSelection
  onReply: (target: ReplyTarget) => void
  onCopySelection: (ids: number[]) => void
  onDeleteSelection: (ids: number[]) => void
}) {
  const { messages: allMessages, queue, isRunning, isLoading, lastFollowUps, thread } = conv
  const hrContactName = hrContactNameProp ?? thread?.contact_name
  const messages = allMessages.filter(
    (m) =>
      !(hideHr && (m.kind === "hr_in" || m.kind === "hr_out")) &&
      !(hideAi && (m.kind === "llm_user" || m.kind === "llm_assistant")),
  )
  const messagesById = useMemo(() => {
    const map = new Map<number, ConvMessage>()
    for (const m of allMessages) if (m.id != null) map.set(m.id, m)
    return map
  }, [allMessages])

  // План §6.3: анимируем появление только тех реплик с картинкой, что довставились после первой
  // отрисовки ленты (SSE/рефетч), а не всю историю при открытии диалога.
  const attachmentMessageIds = messages
    .filter((m) => (m.attachments?.length ?? 0) > 0)
    .map((m) => m.id)
  const newAttachmentIds = useNewIds(attachmentMessageIds)

  function targetIds(id: number): number[] {
    return selection.selectedIds.size > 0 ? Array.from(selection.selectedIds) : [id]
  }

  // UX5-5: этапы цепочки с известной прошедшей датой становятся «звонками» в ленте; дебриф
  // привязывается по interview_stage_id, если владелец явно связал транскрипт с этой строкой.
  const stagesQ = useInterviewStages(vacancyId)
  const debriefQ = useDebriefHistory(vacancyId)
  const debriefByStage = useMemo(() => {
    const map = new Map<number, DebriefResult>()
    for (const d of debriefQ.data?.items ?? []) {
      if (d.interview_stage_id != null) map.set(d.interview_stage_id, d)
    }
    return map
  }, [debriefQ.data])
  const callStages = useMemo(() => (stagesQ.data?.items ?? []).filter(isPastStage), [stagesQ.data])
  // Ближайший предстоящий этап — один на диалог, виджет внизу ленты (см. UpcomingCallWidget).
  const upcomingStage = useMemo(() => {
    const future = (stagesQ.data?.items ?? []).filter(isFutureStage)
    future.sort(
      (a, b) => Date.parse(a.scheduled_at as string) - Date.parse(b.scheduled_at as string),
    )
    return future[0]
  }, [stagesQ.data])
  const entries = useMemo<TimelineEntry[]>(() => {
    const msgEntries: TimelineEntry[] = messages.map((m) => ({
      kind: "message",
      ms: ownMs(m) ?? 0,
      message: m,
    }))
    const callEntries: TimelineEntry[] = callStages.map((s) => ({
      kind: "call",
      ms: Date.parse(s.scheduled_at as string),
      stage: s,
    }))
    return [...msgEntries, ...callEntries].sort((a, b) => a.ms - b.ms)
  }, [messages, callStages])
  const empty =
    messages.length === 0 && callStages.length === 0 && queue.length === 0 && !upcomingStage
  if (isLoading) {
    return (
      <div className="space-y-2">
        <div className="flex justify-start">
          <Skeleton className="h-12 w-1/2 rounded-2xl" />
        </div>
        <div className="flex justify-end">
          <Skeleton className="h-10 w-2/5 rounded-2xl" />
        </div>
      </div>
    )
  }
  if (empty) {
    return (
      <p className="text-sm text-slate-400">
        Спросите агента по вакансии или переключитесь на HR и вставьте переписку — система разберёт
        её и добавит только новые реплики.
      </p>
    )
  }
  const monotonic = entries.reduce<number[]>((acc, e) => {
    const prev = acc.length ? acc[acc.length - 1] : 0
    return [...acc, e.ms ? Math.max(prev, e.ms) : prev]
  }, [])
  return (
    <div className="space-y-1.5">
      {entries.map((e, i) =>
        e.kind === "message" ? (
          <Bubble
            key={e.message.id}
            kind={e.message.kind}
            body={e.message.body}
            time={monotonic[i] ? fmtMsgTime(monotonic[i]) : null}
            hrContactName={hrContactName}
            messageId={e.message.id}
            quoted={resolveQuote(e.message, messagesById, hrContactName)}
            attachments={e.message.attachments}
            appear={newAttachmentIds.has(e.message.id)}
            selected={selection.selectedIds.has(e.message.id)}
            selecting={selection.isSelecting}
            onMouseDownSelect={(ev) => {
              if (ev.button !== 0 || isInteractiveTarget(ev)) return
              selection.startPress(e.message.id)
            }}
            onMouseEnterSelect={() => selection.enterDrag(e.message.id)}
            onContextMenuSelect={() => selection.ensureSelected(e.message.id)}
            onReply={() => {
              // План §6.6: у сообщения с картинкой цитата над полем ввода показывает миниатюру +
              // заголовок распознавания вместо текстового отрывка.
              const firstAttachment = e.message.attachments?.[0]
              onReply({
                id: e.message.id,
                label: messageAuthorLabel(e.message.kind, hrContactName),
                body: e.message.body || (firstAttachment?.analysis?.title ?? "Вложение"),
                thumbUrl: firstAttachment?.thumb_url,
              })
            }}
            onCopy={() => onCopySelection(targetIds(e.message.id))}
            onDelete={() => onDeleteSelection(targetIds(e.message.id))}
          />
        ) : (
          <CallEvent
            key={`call-${e.stage.id}`}
            stage={e.stage}
            debrief={debriefByStage.get(e.stage.id)}
            vacancyId={vacancyId}
          />
        ),
      )}
      {upcomingStage ? <UpcomingCallWidget stage={upcomingStage} vacancyId={vacancyId} /> : null}
      {!hideAi &&
        queue.map((item) => (
          <Fragment key={item.localId}>
            <QueueBubbleMenu
              text={item.question}
              onDelete={() => conv.dismissPending(item.localId)}
            >
              <Bubble
                kind="llm_user"
                body={item.question}
                time={fmtMsgTime(item.askedAt)}
                attachments={item.attachments}
                appear={Boolean(item.attachments?.length)}
              />
            </QueueBubbleMenu>
            {item.answer ? (
              <QueueBubbleMenu
                text={item.answer}
                onDelete={() => conv.dismissPending(item.localId)}
              >
                <Bubble
                  kind="llm_assistant"
                  body={item.answer}
                  error={item.error}
                  time={fmtMsgTime(item.askedAt)}
                />
              </QueueBubbleMenu>
            ) : item.status === "sending" ? (
              <div className="flex justify-start">
                <div className="rounded-2xl rounded-bl-sm bg-violet-100 px-3 py-2">
                  <span className="inline-flex items-center gap-1.5 text-slate-500">
                    <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />
                    Думаю…
                  </span>
                </div>
              </div>
            ) : (
              // status "queued": предыдущий обмен ещё не отстрелялся — этот вопрос дождётся своей
              // очереди (F-XX, баг «второй вопрос стирает первый»), не потеряется и не улетит сразу.
              <div className="flex justify-end">
                <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-400">
                  <Clock className="size-3 shrink-0" strokeWidth={2} />В ожидании
                </span>
              </div>
            )}
          </Fragment>
        ))}
      {!isRunning && lastFollowUps.length > 0 && (
        <div className="pl-1 pt-0.5">
          <FollowUpChips items={lastFollowUps} onPick={(t) => void conv.askLlm(t)} />
        </div>
      )}
    </div>
  )
}

export function DialogComposer({
  conv,
  canAsk,
  hideHr,
  onToggleHideHr,
  hideAi,
  onToggleHideAi,
  replyTo,
  onClearReply,
  selection,
  onCopySelection,
  onRequestDeleteSelection,
}: {
  conv: VacancyConversation
  canAsk: boolean
  hideHr: boolean
  onToggleHideHr: () => void
  hideAi: boolean
  onToggleHideAi: () => void
  replyTo?: ReplyTarget | null
  onClearReply: () => void
  selection: MessageSelection
  onCopySelection: () => void
  onRequestDeleteSelection: () => void
}) {
  const [mode, setMode] = useState<"assistant" | "hr">("assistant")
  const [text, setText] = useState("")
  const { activeIds } = useActiveContexts()
  // Картинки доступны в обоих режимах: в «Агенте» — вложение диалога (Этап 2), в HR — носитель
  // текста, скрины переписки распознаются и уходят в тот же LLM-сплиттер, что и вставленный текст
  // (Этап 4, Э4-1).
  const attachmentsEnabled = true
  const attachments = useAttachmentUpload()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [cropTarget, setCropTarget] = useState<{ key: string; attachment: AttachmentOut } | null>(
    null,
  )
  const [viewerIndex, setViewerIndex] = useState<number | null>(null)
  // Ярлык-переключатель ветки (§3 плана, Э4-3) — только в режиме HR (носитель текста): владелец
  // может переопределить угадку классификатора по чипу до отправки. Состояние живёт здесь, а не в
  // useAttachmentUpload — переопределение относится к композеру/режиму, не к самой загрузке.
  const [routeOverrides, setRouteOverrides] = useState<Record<string, AttachmentRoute>>({})
  function removeAttachment(key: string) {
    attachments.remove(key)
    setRouteOverrides((prev) => {
      if (!(key in prev)) return prev
      const next = { ...prev }
      delete next[key]
      return next
    })
  }
  function clearAttachments() {
    attachments.clear()
    setRouteOverrides({})
  }
  const readyAttachments = useMemo(
    () =>
      attachments.items
        .filter((i): i is PendingAttachment & { attachment: AttachmentOut } => i.attachment != null)
        .map((i) => i.attachment),
    [attachments.items],
  )
  // Просмотрщик/кроппер — только картинки (2026-08-11): у документа нет пикселей, ни зумить,
  // ни резать нечего.
  const readyImageAttachments = useMemo(
    () => readyAttachments.filter((a) => a.mime.startsWith("image/")),
    [readyAttachments],
  )
  const routes = useMemo(() => {
    const map: Record<string, AttachmentRoute> = {}
    for (const item of attachments.items) {
      if (item.attachment?.analysis_status !== "ready") continue
      map[item.key] = routeOverrides[item.key] ?? defaultAttachmentRoute(item.attachment.analysis)
    }
    return map
  }, [attachments.items, routeOverrides])
  const paste = usePasteImages({
    onFiles: attachments.addFiles,
    queuedCount: attachments.items.length,
    disabled: !attachmentsEnabled || attachments.isUploading,
  })
  if (!canAsk) return null
  // Режим «Агент» больше не блокируется на время ответа (F-XX, баг «второй вопрос стирает
  // первый») — новый вопрос уходит в очередь стора (vacancy-chat-stream.ts) и виден в ленте со
  // статусом «В ожидании», не дожидаясь освобождения агента. HR-импорт остаётся однопоточным —
  // это отдельная мутация, не часть очереди чата.
  const busy = mode === "assistant" ? false : conv.isImporting
  const placeholder =
    mode === "assistant"
      ? "Спросить агента по вакансии…"
      : "Вставьте переписку из Telegram или скриншот переписки — можно захватить и старые сообщения для контекста…"
  function openViewer(item: PendingAttachment) {
    if (!item.attachment || !item.attachment.mime.startsWith("image/")) return
    const idx = readyImageAttachments.findIndex((a) => a.id === item.attachment!.id)
    if (idx !== -1) setViewerIndex(idx)
  }
  function openCrop(item: PendingAttachment) {
    if (!item.attachment || !item.attachment.mime.startsWith("image/")) return
    setCropTarget({ key: item.key, attachment: item.attachment })
  }
  async function send() {
    const t = text.trim()
    if (busy) return
    if (mode === "assistant") {
      // Картинка(и) без текста — законный вопрос (Э2-5): блокируем только пустую отправку.
      if (!t && attachments.attachmentIds.length === 0) return
      setText("")
      clearAttachments()
      void conv.askLlm(t, activeIds, replyTo?.id, readyAttachments)
      onClearReply()
      return
    }
    // Скрин переписки без текста — тоже законный импорт (Э4-1): блокируем только пустую отправку.
    if (!t && attachments.attachmentIds.length === 0) return
    // Только явные переопределения владельца (Э4-3) — остальное решает kind классификатора как
    // раньше, чтобы не гонять по сети то, что и так совпадёт с дефолтом бэка.
    const attachmentRoutes: Record<number, AttachmentRoute> = {}
    for (const item of attachments.items) {
      const override = routeOverrides[item.key]
      if (override && item.attachment) attachmentRoutes[item.attachment.id] = override
    }
    try {
      const res = await conv.importDump(t, attachments.attachmentIds, attachmentRoutes)
      setText("")
      const unrecognized = new Set(res.unrecognized_attachment_ids)
      if (unrecognized.size === 0) {
        clearAttachments()
        return
      }
      // Скрин(ы), которые не похожи на переписку — оставляем в композере, остальное убираем:
      // тост предлагает переключить ветку на «вложение» (§3 плана), картинки уже в очереди.
      for (const item of attachments.items) {
        if (item.attachment && !unrecognized.has(item.attachment.id)) removeAttachment(item.key)
      }
      toast.message("Не нашёл переписки на скриншоте", {
        description: "Похоже, это не переписка — приложить как картинку агенту?",
        duration: 12_000,
        action: {
          label: "Приложить агенту",
          onClick: () => setMode("assistant"),
        },
      })
    } catch {
      /* тост в хуке */
    }
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
            <div className="flex min-w-0 flex-1 items-center gap-1.5">
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
                  <HelpTip id="chat.attachments" side="top">
                    <Button
                      size="icon"
                      variant="outline"
                      type="button"
                      aria-label="Приложить картинку"
                      disabled={busy}
                      onClick={() => fileInputRef.current?.click()}
                    >
                      <Paperclip className="size-4" strokeWidth={2} />
                    </Button>
                  </HelpTip>
                </>
              ) : null}
              <div className="inline-flex items-center gap-1 rounded-xl bg-slate-100 p-1">
                <ModeSegment
                  active={mode === "assistant"}
                  onClick={() => {
                    setMode("assistant")
                    setText("")
                  }}
                  icon={Sparkles}
                  label="Агент"
                  hidden={Boolean(hideAi)}
                  onToggleHidden={onToggleHideAi}
                  hideTitle="ответы агента"
                />
                <ModeSegment
                  active={mode === "hr"}
                  onClick={() => {
                    setMode("hr")
                    setText("")
                    clearAttachments()
                  }}
                  icon={User}
                  label="HR"
                  hidden={Boolean(hideHr)}
                  onToggleHidden={onToggleHideHr}
                  hideTitle="переписку с HR"
                />
              </div>
            </div>
            <Button
              size="default"
              className="h-9 shrink-0 gap-1.5 px-3"
              disabled={(!text.trim() && attachments.attachmentIds.length === 0) || busy}
              onClick={() => void send()}
            >
              {busy ? (
                <Loader2 className="size-4 animate-spin" strokeWidth={2} />
              ) : (
                <Send className="size-4" strokeWidth={2} />
              )}
              Отправить
            </Button>
          </>
        )}
      </div>
      {replyTo && mode === "assistant" ? (
        <div className="flex items-center gap-2 rounded-lg border-l-2 border-sky-400 bg-sky-50/60 py-1.5 pl-2.5 pr-1.5">
          <CornerUpLeft className="size-3.5 shrink-0 text-sky-500" strokeWidth={2} />
          {replyTo.thumbUrl ? (
            <img src={replyTo.thumbUrl} alt="" className="size-5 shrink-0 rounded object-cover" />
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
        <AttachmentChips
          items={attachments.items}
          onRemove={removeAttachment}
          onRetry={attachments.retry}
          onOpen={openViewer}
          routes={mode === "hr" ? routes : undefined}
          onRouteChange={
            mode === "hr"
              ? (key, route) => setRouteOverrides((prev) => ({ ...prev, [key]: route }))
              : undefined
          }
        />
      ) : null}
      <Textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (mode === "assistant" ? !e.shiftKey : e.metaKey || e.ctrlKey)) {
            e.preventDefault()
            void send()
          }
        }}
        placeholder={placeholder}
        disabled={busy}
      />
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
          {viewerIndex != null && readyImageAttachments[viewerIndex] ? (
            <ImageViewer
              attachments={readyImageAttachments}
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
    </div>
  )
}
