import { useMemo, useState, type MouseEvent } from "react"
import {
  ChevronDown,
  Copy,
  CornerUpLeft,
  Link2,
  ListChecks,
  Loader2,
  MessagesSquare,
  Pencil,
  RotateCcw,
  Trash2,
  TriangleAlert,
} from "lucide-react"
import { toast } from "sonner"
import type { DebriefResult, TranscriptTurn } from "@/api/debrief"
import type { InterviewStageOut } from "@/api/interview-stages"
import type { Job } from "@/api/jobs"
import { AttachmentGrid } from "@/components/chat/attachments/AttachmentGrid"
import { Button } from "@/components/ui/button"
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuTrigger,
} from "@/components/ui/context-menu"
import { SkeletonCard } from "@/components/ui/skeleton"
import { StatusChip, StatusDot } from "@/components/ui/status-chip"
import type { StatusTone } from "@/components/ui/status-chip"
import { cn } from "@/lib/utils"
import { formatDateTime, formatEventLabel } from "@/lib/format"
import type { MessageSelection } from "@/features/jobs/use-message-selection"
import { useDebriefHistory } from "@/features/tech/use-debrief"
import { useInterviewStages } from "@/features/tech/use-interview-stages"
import { buildReviewRows, strongPoints, type ReviewLevel, type ReviewRow } from "./debrief-review"
import { MASTERY_LABEL, MASTERY_TONE } from "./mastery"

// Разбор вставленной расшифровки — ОДНА карточка на разбор: шапка с единственной оценкой,
// переключалка «Диалог | Разбор» и одно содержимое под ней.
//
// Раньше тот же разбор растекался по ленте четырьмя независимыми кусками (пузырь-итог, спойлер
// расшифровки, три кучи weak/strong/honest пузырями, отдельные карточки старых разборов со своей
// оценкой в шапке): оценка читалась дважды, диалог был спрятан под спойлер, а вопросы и их разбор
// лежали в разных местах. Теперь диалог и разбор — две вкладки одного блока, оценка ровно одна.

function safeStr(v: string | null | undefined): string {
  return (v ?? "").trim()
}

const SIGNAL_TONE: Record<DebriefResult["analysis"]["next_steps_signal"], StatusTone> = {
  offer_likely: "strong",
  next_stage_likely: "good",
  ambiguous: "info",
  rejection_likely: "bad",
  unknown: "info",
}

const REVIEW_TONE: Record<ReviewLevel, StatusTone> = {
  confident: MASTERY_TONE.confident,
  medium: MASTERY_TONE.medium,
  weak: MASTERY_TONE.weak,
  unknown: "info",
  honest: "info",
}

const REVIEW_LABEL: Record<ReviewLevel, string> = {
  confident: MASTERY_LABEL.confident,
  medium: MASTERY_LABEL.medium,
  weak: MASTERY_LABEL.weak,
  unknown: "Ответа не слышно",
  honest: "Не в зачёт",
}

function cardKey(r: DebriefResult, idx: number): string {
  return r.id != null ? `id-${r.id}` : `idx-${idx}`
}

// Реплика без явной метки времени наследует время начала разбора (result.created_at) — честный
// фолбэк вместо выдуманной даты (владелец правил: LLM извлекает время реплики, если оно есть в
// исходном транскрипте, иначе не выдумывает).
function fmtTurnTime(ts: string | null | undefined, fallback: string | null | undefined): string {
  const iso = ts || fallback
  if (!iso) return ""
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ""
  return d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })
}

// Стабильный синтетический id реплики транскрипта (нет отдельной строки в БД - транскрипт один
// текст, LLM режет его на реплики при отображении) - тот же приём, что `questionPseudoId` в
// QuestionsChatPanel.tsx: отрицательный id, чтобы делить общий Set выделения с id реальных
// реплик чата подготовки (те положительные), не пересекаясь с ними.
// eslint-disable-next-line react-refresh/only-export-components -- утилита рядом с компонентами разбора, общий модуль
export function transcriptTurnId(debriefId: number, turnIndex: number): number {
  return -(debriefId * 1000 + turnIndex + 1)
}

function scoreTone(score: number): StatusTone {
  if (score >= 7) return "strong"
  if (score >= 5) return "warn"
  return "bad"
}

const SCORE_CLASS: Record<StatusTone, string> = {
  strong: "bg-status-strong-soft text-status-strong-fg",
  good: "bg-status-good-soft text-status-good-fg",
  warn: "bg-status-warn-soft text-status-warn-fg",
  bad: "bg-status-bad-soft text-status-bad-fg",
  info: "bg-slate-100 text-slate-600",
}

function ScoreBadge({ score }: { score: number }) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center rounded-lg px-2 py-0.5 text-sm font-bold tabular-nums",
        SCORE_CLASS[scoreTone(score)],
      )}
      title="Оценка собеса по расшифровке"
    >
      {score}/10
    </span>
  )
}

// DBR-3/UX3-DBR: одна реплика транскрипта — тот же визуальный язык, что у диалога вакансии
// (чат-пузыри): интервьюер слева/violet, кандидат справа/sky. Время реплики снизу справа (как в
// «Чатах») — из LLM-сегментации либо фолбэк на время начала разбора. Выделение/копирование/
// ответ/удаление (id != null) - та же механика, что у ChatBubble (PrepChat.tsx).
function TranscriptBubble({
  turn,
  fallbackTs,
  selected,
  selecting,
  onMouseDownSelect,
  onMouseEnterSelect,
  onContextMenuSelect,
  onReply,
  onCopy,
  onDelete,
}: {
  turn: TranscriptTurn
  fallbackTs: string | null | undefined
  selected?: boolean
  selecting?: boolean
  onMouseDownSelect?: (e: MouseEvent<HTMLDivElement>) => void
  onMouseEnterSelect?: () => void
  onContextMenuSelect?: () => void
  onReply?: () => void
  onCopy?: () => void
  onDelete?: () => void
}) {
  const mine = turn.speaker === "candidate"
  const time = fmtTurnTime(turn.ts, fallbackTs)
  const row = (
    <div
      className={cn("flex", mine ? "justify-end" : "justify-start")}
      onMouseDown={onMouseDownSelect}
      onMouseEnter={onMouseEnterSelect}
      onContextMenu={onContextMenuSelect}
    >
      <div
        className={cn(
          "max-w-[80%] whitespace-pre-wrap break-words rounded-2xl px-3 py-1.5 text-sm leading-snug text-slate-900 transition-shadow",
          mine ? "rounded-br-sm bg-sky-100" : "rounded-bl-sm bg-violet-100",
          selecting && "cursor-pointer select-none",
          selected && "ring-2 ring-sky-400 ring-offset-1",
        )}
      >
        {turn.text}
        {time && <div className="mt-0.5 text-right text-xs font-medium text-slate-400">{time}</div>}
      </div>
    </div>
  )

  if (!onReply && !onDelete) return row

  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>{row}</ContextMenuTrigger>
      <ContextMenuContent>
        {onReply && (
          <ContextMenuItem onSelect={onReply}>
            <CornerUpLeft />
            Ответить
          </ContextMenuItem>
        )}
        <ContextMenuItem onSelect={onCopy}>
          <Copy />
          Копировать
        </ContextMenuItem>
        {onDelete && (
          <ContextMenuItem variant="destructive" onSelect={onDelete}>
            <Trash2 />
            Удалить
          </ContextMenuItem>
        )}
      </ContextMenuContent>
    </ContextMenu>
  )
}

// Транскрипт как естественная лента чата на всю доступную ширину, без вложенной рамки-подобласти.
// Если LLM не смогла сегментировать реплики (старые записи до фичи, либо плохо структурированный
// текст) - молча падаем назад на исходный текст транскрипта.
// UX5-5: экспортируется — переиспользуется спойлером «звонка» в ленте диалога (VacancyDialog),
// там нет интерактива (debriefId/selection/onReply/onDeleteTurn не передаются).
export function TranscriptChat({
  turns,
  transcript,
  fallbackTs,
  debriefId = null,
  selection,
  onReply,
  onDeleteTurn,
}: {
  turns: TranscriptTurn[]
  transcript: string
  fallbackTs: string | null | undefined
  /** Разбор сохранён (есть id) - реплики можно выделять/удалять; без него (черновик, ещё не
   * сохранён на бэкенде) остаётся только просмотр. */
  debriefId?: number | null
  selection?: MessageSelection
  /** Ответить репликой в композер подготовки - работает независимо от debriefId/selection
   * (Скрининги передают только это, без выделения/удаления). */
  onReply?: (text: string) => void
  onDeleteTurn?: (turnIndex: number) => void
}) {
  const raw = safeStr(transcript)
  if (turns.length === 0 && !raw) return null

  function copyTurn(text: string) {
    void navigator.clipboard.writeText(text).then(
      () => toast.success("Скопировано"),
      () => toast.error("Не удалось скопировать"),
    )
  }

  if (turns.length === 0) {
    return (
      <p className="whitespace-pre-wrap rounded-xl border bg-slate-50 p-4 text-sm text-slate-600">
        {raw}
      </p>
    )
  }

  return (
    <div className="space-y-2">
      {turns.map((t, i) => {
        const id = debriefId != null ? transcriptTurnId(debriefId, i) : null
        return (
          <TranscriptBubble
            key={i}
            turn={t}
            fallbackTs={fallbackTs}
            selected={id != null ? (selection?.selectedIds.has(id) ?? false) : false}
            selecting={selection?.isSelecting ?? false}
            onMouseDownSelect={
              id != null
                ? (e) => {
                    if (e.button !== 0) return
                    selection?.startPress(id)
                  }
                : undefined
            }
            onMouseEnterSelect={id != null ? () => selection?.enterDrag(id) : undefined}
            onContextMenuSelect={id != null ? () => selection?.ensureSelected(id) : undefined}
            onReply={onReply ? () => onReply(t.text) : undefined}
            onCopy={() => copyTurn(t.text)}
            onDelete={id != null && onDeleteTurn ? () => onDeleteTurn(i) : undefined}
          />
        )
      })}
    </div>
  )
}

// Одна строка разбора: вопрос + уровень ответа, детали (что пошло не так / как исправить /
// эталон) раскрываются по клику. Клик по «Обсудить» кидает вопрос в композер подготовки.
function ReviewRowCard({ row, onDiscuss }: { row: ReviewRow; onDiscuss?: () => void }) {
  const [open, setOpen] = useState(false)
  const hasDetails = Boolean(row.problem || row.fix || row.reference)
  return (
    <div
      className={cn(
        "rounded-xl border bg-white transition-colors",
        row.level === "weak" ? "border-status-bad-line" : "border-slate-200",
      )}
    >
      <div className="flex items-start gap-2.5 px-3.5 py-2.5">
        <StatusDot tone={REVIEW_TONE[row.level]} className="mt-1.5" />
        <div className="min-w-0 flex-1">
          <button
            type="button"
            onClick={() => hasDetails && setOpen((v) => !v)}
            disabled={!hasDetails}
            aria-expanded={hasDetails ? open : undefined}
            className={cn(
              "flex w-full items-start gap-2 text-left",
              hasDetails ? "cursor-pointer" : "cursor-default",
            )}
          >
            <span className="min-w-0 flex-1 text-sm font-medium leading-snug text-slate-900">
              {row.question}
            </span>
            <span className="flex shrink-0 items-center gap-1.5">
              <span className="text-xs font-medium text-slate-500">{REVIEW_LABEL[row.level]}</span>
              {hasDetails && (
                <ChevronDown
                  className={cn(
                    "size-3.5 text-slate-400 transition-transform",
                    open && "rotate-180",
                  )}
                  strokeWidth={2}
                />
              )}
            </span>
          </button>
          {open && hasDetails && (
            <div className="mt-2 space-y-1.5 border-t border-dashed pt-2 text-sm">
              {row.problem && <p className="text-slate-700">{row.problem}</p>}
              {row.fix && <p className="text-status-strong-fg">{row.fix}</p>}
              {row.reference && (
                <p className="rounded-lg bg-slate-50 p-2 text-slate-700">
                  <span className="font-medium text-slate-900">Эталон: </span>
                  {row.reference}
                </p>
              )}
              {onDiscuss && (
                <div className="flex justify-end">
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-7 gap-1.5 px-2 text-xs text-slate-500"
                    onClick={onDiscuss}
                  >
                    <CornerUpLeft className="size-3.5" strokeWidth={2} />
                    Обсудить с агентом
                  </Button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function ReviewList({
  rows,
  strong,
  onDiscuss,
}: {
  rows: ReviewRow[]
  strong: string[]
  onDiscuss?: (question: string) => void
}) {
  if (rows.length === 0 && strong.length === 0) {
    return (
      <p className="rounded-xl border border-dashed border-slate-200 px-5 py-6 text-center text-sm text-slate-400">
        Разбор по вопросам пуст — в расшифровке не нашлось явных пар вопрос-ответ.
      </p>
    )
  }
  return (
    <div className="space-y-2">
      {rows.map((row, i) => (
        <ReviewRowCard
          key={`${i}-${row.question.slice(0, 40)}`}
          row={row}
          onDiscuss={onDiscuss ? () => onDiscuss(row.question) : undefined}
        />
      ))}
      {strong.length > 0 && (
        <div className="rounded-xl border border-status-strong-line bg-status-strong-soft/40 px-3.5 py-2.5">
          <p className="text-xs font-medium uppercase tracking-wider text-slate-500">Что зашло</p>
          <ul className="mt-1.5 space-y-1">
            {strong.map((s, i) => (
              <li key={i} className="flex gap-2 text-sm text-slate-700">
                <span className="text-status-strong-fg">•</span>
                <span>{s}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

type ReviewTab = "dialog" | "review"

/** Один разбор расшифровки: шапка с оценкой + «Диалог | Разбор». Экспортирован — Скрининги
 * (QuestionsChatPanel) рисуют тем же компонентом свою расшифровку (stage="screening"). */
export function DebriefReview({
  result,
  linkedStage,
  onEdit,
  onReplyQuestion,
  selection,
  onDeleteTurn,
  collapsible = false,
}: {
  result: DebriefResult
  linkedStage: InterviewStageOut | undefined
  onEdit: () => void
  onReplyQuestion?: (question: string) => void
  selection?: MessageSelection
  onDeleteTurn?: (debriefId: number, turnIndex: number) => void
  /** Прошлый разбор в истории — шапка видна, содержимое по клику (свежий раскрыт всегда). */
  collapsible?: boolean
}) {
  const a = result.analysis
  const [tab, setTab] = useState<ReviewTab>("dialog")
  const [open, setOpen] = useState(!collapsible)
  const rows = useMemo(() => buildReviewRows(a), [a])
  const strong = useMemo(() => strongPoints(a), [a])
  const turns = a.transcript_turns ?? []
  const turnCount = turns.length || (safeStr(result.transcript) ? 1 : 0)
  const summary = safeStr(a.summary)
  const tone = SIGNAL_TONE[a.next_steps_signal] ?? "info"

  const TABS: { value: ReviewTab; label: string; count: number; Icon: typeof MessagesSquare }[] = [
    { value: "dialog", label: "Диалог", count: turnCount, Icon: MessagesSquare },
    { value: "review", label: "Разбор", count: rows.length, Icon: ListChecks },
  ]

  return (
    <section className="overflow-hidden rounded-xl border bg-white">
      <div className="space-y-2 px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <ScoreBadge score={a.overall_impression} />
          <StatusChip tone={tone}>
            <StatusDot tone={tone} />
            {result.signal_label || "Без сигнала"}
          </StatusChip>
          {linkedStage && (
            <span
              className="inline-flex shrink-0 items-center gap-1 text-xs text-slate-500"
              title={`Привязано к этапу: ${linkedStage.stage_label}`}
            >
              <Link2 className="size-3" strokeWidth={2} />
              {formatEventLabel(linkedStage.scheduled_at) || linkedStage.stage_label}
            </span>
          )}
          {result.created_at && (
            <span className="shrink-0 text-xs tabular-nums text-slate-400">
              {formatDateTime(result.created_at)}
            </span>
          )}
          {result.id == null && (
            <span className="rounded-md bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500">
              не сохранён
            </span>
          )}
          <div className="ml-auto flex shrink-0 items-center gap-1">
            <Button
              size="sm"
              variant="ghost"
              className="h-7 gap-1.5 px-2 text-xs text-slate-500"
              onClick={onEdit}
            >
              <Pencil className="size-3.5" strokeWidth={2} />
              Изменить расшифровку
            </Button>
            {collapsible && (
              <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                aria-expanded={open}
                aria-label={open ? "Свернуть разбор" : "Раскрыть разбор"}
                className="rounded-md p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
              >
                <ChevronDown
                  className={cn("size-4 transition-transform", open && "rotate-180")}
                  strokeWidth={2}
                />
              </button>
            )}
          </div>
        </div>
        {summary && <p className="whitespace-pre-wrap text-sm leading-snug text-slate-700">{summary}</p>}
      </div>

      {open && (
        <>
          <div className="flex items-center gap-2 border-y bg-slate-50/70 px-4 py-2">
            <div className="inline-flex rounded-lg border border-slate-200 bg-white p-0.5">
              {TABS.map(({ value, label, count, Icon }) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setTab(value)}
                  aria-pressed={tab === value}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-sm font-medium transition-colors",
                    tab === value
                      ? "bg-slate-900 text-white"
                      : "text-slate-600 hover:bg-slate-100",
                  )}
                >
                  <Icon className="size-3.5" strokeWidth={2} />
                  {label}
                  <span className="tabular-nums opacity-70">{count}</span>
                </button>
              ))}
            </div>
          </div>
          <div className="space-y-3 p-4">
            {result.attachments && result.attachments.length > 0 && (
              <AttachmentGrid attachments={result.attachments} className="max-w-xs" />
            )}
            {tab === "dialog" ? (
              <TranscriptChat
                turns={turns}
                transcript={result.transcript ?? ""}
                fallbackTs={result.created_at}
                debriefId={result.id}
                selection={selection}
                onReply={onReplyQuestion}
                onDeleteTurn={
                  result.id != null && onDeleteTurn
                    ? (turnIndex) => onDeleteTurn(result.id!, turnIndex)
                    : undefined
                }
              />
            ) : (
              <ReviewList rows={rows} strong={strong} onDiscuss={onReplyQuestion} />
            )}
          </div>
        </>
      )}
    </section>
  )
}

const PROGRESS_STEPS = [
  { untilMs: 12_000, label: "Читаю расшифровку…" },
  { untilMs: 40_000, label: "Размечаю реплики по говорящим…" },
  { untilMs: 80_000, label: "Оцениваю ответы по вопросам…" },
  { untilMs: Infinity, label: "Собираю итог и сигнал…" },
]

function progressLabel(elapsedMs: number): string {
  return PROGRESS_STEPS.find((s) => elapsedMs < s.untilMs)!.label
}

/** Разбор идёт: вставленный текст сразу виден диалогом, статус меняется по шагам — вместо
 * замершего экрана со спиннером на всю минуту ожидания LLM. Ошибка задачи — здесь же, с
 * «Повторить» и возвратом текста в поле (иначе расшифровка терялась вместе с задачей). */
export function DebriefProgress({
  elapsedMs,
  draftTurns,
  error = null,
  onRetry,
  onRestoreText,
  onDismiss,
}: {
  elapsedMs: number
  draftTurns: TranscriptTurn[]
  error?: string | null
  onRetry?: () => void
  onRestoreText?: () => void
  onDismiss?: () => void
}) {
  const failed = Boolean(error)
  return (
    <section
      className={cn(
        "overflow-hidden rounded-xl border bg-white",
        failed ? "border-status-bad-line" : "border-sky-200",
      )}
    >
      <div
        className={cn(
          "flex flex-wrap items-center gap-2 px-4 py-2.5 text-sm",
          failed ? "bg-status-bad-soft/50" : "bg-sky-50/70",
        )}
      >
        {failed ? (
          <TriangleAlert className="size-4 shrink-0 text-status-bad-fg" strokeWidth={2} />
        ) : (
          <Loader2 className="size-4 shrink-0 animate-spin text-sky-600" strokeWidth={2} />
        )}
        <span className={cn("font-medium", failed ? "text-status-bad-fg" : "text-sky-900")}>
          {failed ? error : progressLabel(elapsedMs)}
        </span>
        {!failed && (
          <span className="tabular-nums text-sky-700/70">{Math.floor(elapsedMs / 1000)}с</span>
        )}
        <div className="ml-auto flex shrink-0 items-center gap-1">
          {failed && onRetry && (
            <Button size="sm" variant="outline" className="h-7 gap-1.5 px-2 text-xs" onClick={onRetry}>
              <RotateCcw className="size-3.5" strokeWidth={2} />
              Повторить
            </Button>
          )}
          {failed && onRestoreText && (
            <Button
              size="sm"
              variant="ghost"
              className="h-7 px-2 text-xs text-slate-600"
              onClick={onRestoreText}
            >
              Вернуть текст в поле
            </Button>
          )}
          {failed && onDismiss && (
            <Button
              size="sm"
              variant="ghost"
              className="h-7 px-2 text-xs text-slate-400"
              onClick={onDismiss}
            >
              Скрыть
            </Button>
          )}
        </div>
      </div>
      {draftTurns.length > 0 && (
        <div className="space-y-2 p-4">
          <TranscriptChat turns={draftTurns} transcript="" fallbackTs={null} />
          {!failed && (
            <p className="text-center text-xs text-slate-400">
              Реплики размечены черновиком — точную разметку и разбор допишу, как будет готово.
            </p>
          )}
        </div>
      )}
    </section>
  )
}

function DebriefSkeleton() {
  return (
    <div className="space-y-4">
      {[0, 1].map((i) => (
        <SkeletonCard key={i} className="h-24" />
      ))}
    </div>
  )
}

// Встроена в общую ленту «Подготовки»: свежий разбор раскрыт, прошлые — той же карточкой, но
// свёрнутой (collapsible). Своего пустого состояния нет: вход в расшифровку живёт в композере
// (режим «Расшифровка»), а родитель рендерит секцию только когда есть что показать.
//
// UX-этап: `stageFilter` отделяет разбор одного этапа от чужих — расшифровка скрининга не висит
// в ленте «Теории». Контекст прошлых этапов при этом не теряется: он уходит в LLM суммаризацией
// через gather_prep_context, а не дословно в ленту. Без `stageFilter` (Скрининги) показываем всю
// историю — там этап единственный (screening).
export function DebriefSection({
  job,
  setStage,
  onEditTranscript,
  onReplyQuestion,
  selection,
  onDeleteTurn,
  stageFilter,
}: {
  job: Job | null
  setStage: (s: string) => void
  onEditTranscript: (transcript: string, stage: string) => void
  /** Клик «Обсудить»/«Ответить» на вопросе или реплике — вопрос уходит в композер подготовки. */
  onReplyQuestion: (question: string) => void
  /** Выделение/удаление реплик транскрипта - полная парность с диалогами по вакансиям (Технички);
   * Скрининги (QuestionsChatPanel) не передают - там только просмотр + «Обсудить». */
  selection?: MessageSelection
  onDeleteTurn?: (debriefId: number, turnIndex: number) => void
  /** Только разборы этого этапа (PrepStage: screening/theory/…). HR-скрининг в Техничках хранится
   *  под stage="screening", поэтому родитель нормализует hr_screening → screening до передачи. */
  stageFilter?: string
}) {
  const vacancyId = job?.vacancy_id ?? null

  const historyQ = useDebriefHistory(vacancyId)
  const items = useMemo(() => {
    const all = historyQ.data?.items ?? []
    return stageFilter ? all.filter((r) => r.stage === stageFilter) : all
  }, [historyQ.data, stageFilter])

  // UX2-9: связать транскрипт с конкретным экземпляром этапа цепочки, не только с грубым форматом —
  // если у вакансии две «Техничка» на разные даты, разбор должен знать, какая именно.
  const stagesQ = useInterviewStages(vacancyId)
  const stageById = useMemo(
    () => new Map((stagesQ.data?.items ?? []).map((s) => [s.id, s])),
    [stagesQ.data],
  )

  function editTranscript(r: DebriefResult) {
    onEditTranscript(r.transcript ?? "", r.stage)
    setStage(r.stage)
  }

  if (!job) return null
  if (historyQ.isLoading) return <DebriefSkeleton />

  return (
    <div className="space-y-3">
      {items.map((r, idx) => (
        <DebriefReview
          key={cardKey(r, idx)}
          result={r}
          linkedStage={
            r.interview_stage_id != null ? stageById.get(r.interview_stage_id) : undefined
          }
          onEdit={() => editTranscript(r)}
          onReplyQuestion={onReplyQuestion}
          selection={selection}
          onDeleteTurn={onDeleteTurn}
          collapsible={idx > 0}
        />
      ))}
    </div>
  )
}
