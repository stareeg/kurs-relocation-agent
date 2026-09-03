import { useEffect, useMemo, useRef, useState } from "react"
import {
  ChevronDown,
  Copy,
  FileSearch,
  ListChecks,
  Loader2,
  Paperclip,
  Plus,
  Send,
  Sparkles,
} from "lucide-react"
import { toast } from "sonner"
import type { AttachmentOut } from "@/api/attachments"
import type { InterviewStageOut } from "@/api/interview-stages"
import type { Job } from "@/api/jobs"
import type { PrepQuestionOut } from "@/api/prep"
import type { PitchBlock } from "@/api/screening"
import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { HelpTip } from "@/components/ui/help-tip"
import { SkeletonCard } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"
import { usePersistedBoolean } from "@/lib/use-persisted-boolean"
import { ModeSegment, SelectionToolbar, type ReplyTarget } from "@/components/chat/composer-widgets"
import { AttachmentChips } from "@/components/chat/attachments/AttachmentChips"
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
import { useMessageSelection } from "@/features/jobs/use-message-selection"
import { DebriefProgress, DebriefReview } from "@/features/tech/DebriefSection"
import {
  ChatBubble,
  ContextExportCard,
  DebriefComposer,
  QuestionBubble,
  resolvePrepQuote,
  type ContextExportPayload,
  type DebriefComposerHandle,
  type DebriefComposerState,
} from "@/features/tech/PrepChat"
import {
  buildPrepChatBody,
  classifyPrepChatChannels,
  formatPrepMessagesForCopy,
} from "@/features/tech/prep-chat-shared"
import { draftTranscriptTurns } from "@/features/tech/debrief-review"
import { useAnalyzeDebrief } from "@/features/tech/use-debrief"
import { useInterviewStages } from "@/features/tech/use-interview-stages"
import {
  usePrepChat,
  useSendPrepChat,
  useDeletePrepChatMessage,
  useExportContext,
  useGenerateSobesContext,
} from "@/features/tech/use-prep"
import { useTelegramStatus } from "@/features/settings/use-settings"
import { PitchScript, screeningCtaClass } from "./PitchScript"
import { useDeleteScreeningQuestion, usePushScreeningChatSummary } from "./use-screening"
import { useScreeningDebrief } from "./use-screening-debrief"

type QuestionMode = "hr" | "ask"
type ComposerMode = "agent" | "debrief"

type QuestionSetConfig = {
  items: PrepQuestionOut[]
  onAddMore?: () => void
  addMorePending?: boolean
  loading?: boolean
}

function loadReviewed(storageKey: string): Set<string> {
  try {
    const raw = localStorage.getItem(storageKey)
    if (!raw) return new Set()
    const parsed = JSON.parse(raw) as unknown
    if (!Array.isArray(parsed)) return new Set()
    return new Set(parsed.filter((x): x is string => typeof x === "string"))
  } catch {
    return new Set()
  }
}

function saveReviewed(storageKey: string, ids: Set<string>) {
  try {
    localStorage.setItem(storageKey, JSON.stringify([...ids]))
  } catch {
    // quota / private mode — reviewed остаётся только в сессии
  }
}

/** Стабильный отрицательный id вопроса пакета — чтобы делить общий Set выделения с настоящими
 * (положительными) id реплик чата подготовки, не пересекаясь с ними. */
function questionPseudoId(kind: QuestionMode, text: string): number {
  let h = 0
  const s = `${kind}:${text}`
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0
  return h === 0 ? -1 : -Math.abs(h)
}

function copyText(text: string) {
  if (!text.trim()) return
  void navigator.clipboard.writeText(text).then(
    () => toast.success("Скопировано в буфер"),
    () => toast.error("Не удалось скопировать"),
  )
}

/** Правая панель Скринингов. Два состояния экрана, а не одна общая свалка:
 *
 * - **до скрининга** — подготовка: «Рассказ об опыте» закреплён сверху, ниже вопросы пакета
 *   («От HR / От себя») и счётчик просмотренных;
 * - **после скрининга** (вставлена и разобрана расшифровка) — разбор реального разговора. Пакет
 *   подготовки, рассказ и счётчик уходят: прогнозные вопросы и заготовленный монолог перестают
 *   что-либо значить, когда есть реальные вопросы и реальные ответы, и раньше просто оттесняли
 *   разбор вниз экрана. Вернуть их — кнопкой «Подготовка» в шапке.
 *
 * Ниже в обоих состояниях — лента чата подготовки (`prep_chat`, stage="screening" — общий бэкенд
 * с Техничками). Композер снизу переключает «Агент» (обычный чат; он же разбирает вставленную
 * чужую переписку) / «Расшифровка» (транскрипт HR-скрининга, синхронно видна в Техничках через
 * тот же `useScreeningDebrief`). */
export function QuestionsChatPanel({
  vacancyId,
  job,
  hr,
  ask,
  hasContent = true,
  onGenerate,
  generating = false,
  progressLabel = null,
  pitch,
}: {
  vacancyId: string
  job: Job
  hr: QuestionSetConfig
  ask: QuestionSetConfig
  /** Пакет ещё не собран (VacancyPrep.has) - шапка вместо счётчика показывает CTA «Подготовиться». */
  hasContent?: boolean
  onGenerate?: () => void
  generating?: boolean
  /** Готовая строка статуса генерации (VacancyPrep считает по elapsedMs) - показываем в шапке
   * вместо отдельного full-width баннера, который раньше сдвигал блоки вниз. */
  progressLabel?: string | null
  /** «Рассказ об опыте» — закреплённое сообщение вверху ленты (план п.2). Нет пропа → баннер не
   * рендерится (пакета ещё не существует вовсе — внешний EmptyState уже это покрывает). */
  pitch?: {
    blocks: PitchBlock[]
    oralPitch: string
    whyCompany: string
    generatedAt?: string | null
    generating?: boolean
    onRebuild?: () => void
    rebuilding?: boolean
    onSave?: (text: string) => void
    saving?: boolean
  }
}) {
  const [qMode, setQMode] = useState<QuestionMode>("hr")
  const active = qMode === "hr" ? hr : ask
  const storageKey = `screening-reviewed:${qMode}:${vacancyId}`

  const [reviewed, setReviewed] = useState<Set<string>>(() => loadReviewed(storageKey))
  const [loadedKey, setLoadedKey] = useState(storageKey)
  if (storageKey !== loadedKey) {
    setLoadedKey(storageKey)
    setReviewed(loadReviewed(storageKey))
  }

  function markReviewed(q: PrepQuestionOut) {
    const key = q.text.trim()
    setReviewed((prev) => {
      if (prev.has(key)) return prev
      const next = new Set(prev)
      next.add(key)
      saveReviewed(storageKey, next)
      return next
    })
  }

  const reviewedCount = active.items.filter((q) => reviewed.has(q.text.trim())).length

  const selection = useMessageSelection()
  function switchQMode(next: QuestionMode) {
    if (next === qMode) return
    setQMode(next)
    selection.clear()
  }

  const questionById = useMemo(() => {
    const map = new Map<number, { kind: QuestionMode; q: PrepQuestionOut }>()
    for (const q of active.items)
      map.set(questionPseudoId(qMode, q.text.trim()), { kind: qMode, q })
    return map
  }, [active.items, qMode])

  const deleteQuestion = useDeleteScreeningQuestion()

  // ---- чат подготовки (общий бэкенд с Техничками, здесь всегда stage="screening") ----
  const { data: chatData, isLoading: chatLoading } = usePrepChat(vacancyId)
  const history = useMemo(() => chatData?.items ?? [], [chatData])
  const channels = useMemo(() => classifyPrepChatChannels(history), [history])
  const channelById = useMemo(() => {
    const map = new Map<number, ReturnType<typeof classifyPrepChatChannels>[number]>()
    history.forEach((m, i) => map.set(m.id, channels[i]))
    return map
  }, [history, channels])
  const messagesById = useMemo(() => new Map(history.map((m) => [m.id, m])), [history])
  const send = useSendPrepChat(vacancyId, "screening")
  const deleteMessage = useDeletePrepChatMessage(vacancyId)

  // ---- «В Telegram»: саммари этой переписки, продолжить разговор про вакансию там ----
  const { data: tgStatus, isLoading: tgStatusLoading } = useTelegramStatus()
  const pushChatSummary = usePushScreeningChatSummary()
  const tgLinked = Boolean(tgStatus?.linked)
  const tgSummaryBlocked = !tgLinked || tgStatusLoading || !vacancyId || pushChatSummary.isPending

  // ---- расшифровка (общий бэкенд с Техничками — stage="screening") ----
  const stagesQ = useInterviewStages(vacancyId)
  const hrScreeningStage = useMemo<InterviewStageOut | undefined>(
    () => stagesQ.data?.items?.find((s) => s.stage_type === "hr_screening"),
    [stagesQ.data],
  )
  const analyze = useAnalyzeDebrief(vacancyId)
  const { debrief: screeningDebrief } = useScreeningDebrief(vacancyId)
  const [transcriptDraft, setTranscriptDraft] = useState<{ text: string; nonce: number } | null>(
    null,
  )

  // ---- режимы композера + видимость каналов в ленте (глазики, UX8) ----
  const [composerMode, setComposerMode] = useState<ComposerMode>("agent")
  const [hideAgent, setHideAgent] = usePersistedBoolean("copilot.screening.hide-agent")
  const [hideDebrief, setHideDebrief] = usePersistedBoolean("copilot.screening.hide-debrief")
  const [contextExport, setContextExport] = useState<ContextExportPayload | null>(null)
  const [seenVacancyId, setSeenVacancyId] = useState(vacancyId)
  if (vacancyId !== seenVacancyId) {
    setSeenVacancyId(vacancyId)
    setContextExport(null)
  }
  const [contextMenuOpen, setContextMenuOpen] = useState(false)
  const exportContext = useExportContext(vacancyId, "screening")
  const sobesContext = useGenerateSobesContext(vacancyId, "screening")
  const contextBusy = exportContext.isPending || sobesContext.isPending
  // Состояние DebriefComposer (свой text/canAnalyze внутри) - нужно снаружи, чтобы отрисовать
  // кнопку «Анализ» в общем тулбаре вместо неё самой (RD-25→здесь: один ряд с переключателем).
  const [debriefState, setDebriefState] = useState<DebriefComposerState>({
    canAnalyze: false,
    analyzing: false,
    elapsedMs: 0,
  })

  const [text, setText] = useState("")
  const [replyTo, setReplyTo] = useState<ReplyTarget | null>(null)
  const [pendingDelete, setPendingDelete] = useState<{
    questionIds: number[]
    messageIds: number[]
  } | null>(null)

  function replyToQuestionText(questionText: string) {
    setComposerMode("agent")
    setText(questionText)
  }

  function targetIds(id: number): number[] {
    if (selection.selectedIds.size === 0) return [id]
    return Array.from(selection.selectedIds)
  }

  function copySelection(ids: number[]) {
    const parts: string[] = []
    const msgs = []
    for (const id of ids) {
      if (id < 0) {
        const entry = questionById.get(id)
        if (entry) {
          parts.push(
            entry.q.answer.trim()
              ? `Вопрос: ${entry.q.text}\n\nОтвет: ${entry.q.answer}`
              : entry.q.text,
          )
        }
      } else {
        const m = messagesById.get(id)
        if (m) msgs.push(m)
      }
    }
    if (msgs.length > 0) parts.push(formatPrepMessagesForCopy(msgs, channelById))
    const combined = parts.filter(Boolean).join("\n\n")
    selection.clear()
    if (!combined) return
    void navigator.clipboard.writeText(combined).then(
      () => toast.success(ids.length === 1 ? "Скопировано" : "Скопировано выделенное"),
      () => toast.error("Не удалось скопировать"),
    )
  }

  function requestDeleteSelection(ids: number[]) {
    if (ids.length === 0) return
    setPendingDelete({
      questionIds: ids.filter((id) => id < 0),
      messageIds: ids.filter((id) => id >= 0),
    })
  }

  async function confirmDelete() {
    if (!pendingDelete) return
    try {
      for (const qid of pendingDelete.questionIds) {
        const entry = questionById.get(qid)
        if (entry) {
          await deleteQuestion.mutateAsync({
            vacancyId,
            body: { kind: entry.kind, question: entry.q.text },
          })
        }
      }
      if (pendingDelete.messageIds.length > 0) {
        await deleteMessage.mutateAsync(pendingDelete.messageIds)
      }
      selection.clear()
    } catch {
      /* тосты уже показаны хуками мутаций */
    } finally {
      setPendingDelete(null)
    }
  }

  // ---- вложения (режим «Агент») ----
  const attachments = useAttachmentUpload()
  const fileInputRef = useRef<HTMLInputElement>(null)
  // Кнопка-скрепка живёт в общем тулбаре (не уезжает при смене режима, UX10) — в «Расшифровке»
  // клик дёргает файл-пикер DebriefComposer через его ручку.
  const debriefComposerRef = useRef<DebriefComposerHandle>(null)
  function openAttachPicker() {
    if (composerMode === "agent") fileInputRef.current?.click()
    else debriefComposerRef.current?.openFilePicker()
  }
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
  const paste = usePasteImages({
    onFiles: attachments.addFiles,
    queuedCount: attachments.items.length,
    disabled: send.isPending,
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
  const hasAttachments = attachments.attachmentIds.length > 0
  const canSend = !!vacancyId && !send.isPending && (trimmed.length > 0 || hasAttachments)

  function submit() {
    if (!canSend) return
    const body = buildPrepChatBody(
      job,
      "screening",
      [],
      trimmed,
      history,
      replyTo?.id,
      attachments.attachmentIds,
    )
    setText("")
    attachments.clear()
    setReplyTo(null)
    send.mutate(body)
  }

  function requestPrepContext() {
    setContextMenuOpen(false)
    setContextExport(null)
    exportContext.mutate(undefined, {
      onSuccess: (result) => {
        const text = result.text?.trim() ?? ""
        if (!text) {
          toast.message("Контекст пуст — сначала соберите подготовку к скринингу")
          return
        }
        setContextExport({
          kind: "prep",
          text,
          subtitle: `HR-скрининг · ${text.length.toLocaleString("ru-RU")} символов`,
        })
      },
    })
  }

  function requestSobesContext() {
    if (!vacancyId) return
    setContextMenuOpen(false)
    setContextExport(null)
    sobesContext.mutate(
      {
        stage: "screening",
        vacancy_text: job.vacancy_text,
        title: job.title,
        company: job.company,
        salary_text: job.salary_text,
        force: true,
      },
      {
        onSuccess: (result) => {
          const md = result.markdown?.trim()
          if (!result.available || !md) {
            toast.message("Не удалось собрать контекст — проверьте текст вакансии")
            return
          }
          const charCount = result.char_count ?? md.length
          const charLimit = result.char_limit ?? 3900
          setContextExport({
            kind: "sobes",
            text: md,
            subtitle: `HR-скрининг · ${charCount}/${charLimit} символов`,
          })
        },
      },
    )
  }

  const bottomRef = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" })
  }, [
    history.length,
    send.isPending,
    screeningDebrief,
    active.items.length,
    qMode,
    contextExport?.text,
    contextBusy,
  ])

  const shownMessages = hideAgent ? [] : history

  // Скрининг уже прошёл и разобран — экран переключается с подготовки на разбор. Пакет вопросов
  // и рассказ прячем (реальные вопросы и реальные ответы лежат в разборе), но не удаляем: кнопка
  // «Подготовка» в шапке возвращает их, если владелец хочет сравнить прогноз с реальностью.
  const debriefed = Boolean(screeningDebrief)
  const [showPrep, setShowPrep] = useState(false)
  const prepVisible = !debriefed || showPrep
  // Черновая разметка только что вставленного текста — пока LLM считает настоящую (иначе экран
  // на минуту замирает со спиннером вместо расшифровки, которую только что вставили).
  const draftTurns = useMemo(
    () => (analyze.pendingTranscript ? draftTranscriptTurns(analyze.pendingTranscript) : []),
    [analyze.pendingTranscript],
  )
  function restorePendingTranscript() {
    const text = analyze.pendingTranscript
    if (!text) return
    setTranscriptDraft({ text, nonce: Date.now() })
    setComposerMode("debrief")
    analyze.cancel()
  }

  return (
    <div className="flex h-full min-h-0 flex-col rounded-xl border bg-white">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 rounded-t-xl border-b px-5 py-3">
        <div className="flex items-center gap-2">
          {debriefed && (
            <span className="flex items-center gap-1.5 text-sm font-medium text-slate-600">
              <ListChecks className="size-4 text-slate-400" strokeWidth={2} />
              Разбор скрининга
            </span>
          )}
          {prepVisible && (
            <>
              <span className="text-sm font-medium text-slate-600">Вопросы</span>
              <div className="inline-flex rounded-lg border border-slate-200 bg-slate-50 p-0.5">
                {(["hr", "ask"] as const).map((m) => (
                  <button
                    key={m}
                    type="button"
                    onClick={() => switchQMode(m)}
                    aria-pressed={qMode === m}
                    className={cn(
                      "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                      qMode === m
                        ? "bg-slate-700 text-white"
                        : "text-slate-600 hover:bg-slate-200/60",
                    )}
                  >
                    {m === "hr" ? "От HR" : "От себя"}
                  </button>
                ))}
              </div>
              <HelpTip
                id={qMode === "hr" ? "screening.hr-questions" : "screening.ask-questions"}
              />
            </>
          )}
        </div>
        <div className="flex items-center gap-3">
          {progressLabel && (
            <span className="flex items-center gap-1.5 text-xs font-medium text-sky-700">
              <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />
              {progressLabel}
            </span>
          )}
          {debriefed && (
            <Button
              size="sm"
              variant="ghost"
              className="gap-1.5 text-xs text-slate-500"
              aria-pressed={showPrep}
              onClick={() => setShowPrep((v) => !v)}
            >
              <ChevronDown
                className={cn("size-3.5 transition-transform", showPrep && "rotate-180")}
                strokeWidth={2}
              />
              {showPrep ? "Скрыть подготовку" : "Подготовка"}
            </Button>
          )}
          {!debriefed && !hasContent && onGenerate && (
            <HelpTip id="screening.pack-generate" side="left">
              <Button
                size="sm"
                disabled={generating}
                onClick={onGenerate}
                aria-label="Подготовиться"
                className={cn(
                  screeningCtaClass,
                  "gap-1.5",
                  !generating && "animate-[pulse_2.4s_ease-in-out_infinite]",
                )}
              >
                <Sparkles className={cn("size-4", generating && "animate-pulse")} strokeWidth={2} />
                {generating ? "Собираю…" : "Подготовиться"}
              </Button>
            </HelpTip>
          )}
          {prepVisible && active.items.length > 0 && (
            <span
              className="text-xs font-medium tabular-nums text-slate-500"
              title="Просмотрено ответов / всего вопросов"
            >
              {reviewedCount}/{active.items.length} просмотрено
            </span>
          )}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {pitch && prepVisible && (
          <div className="sticky top-0 z-10">
            <PitchScript
              blocks={pitch.blocks}
              oralPitch={pitch.oralPitch}
              whyCompany={pitch.whyCompany}
              generatedAt={pitch.generatedAt}
              generating={pitch.generating}
              onRebuild={pitch.onRebuild}
              rebuilding={pitch.rebuilding}
              onSave={pitch.onSave}
              saving={pitch.saving}
            />
          </div>
        )}
        <div className="space-y-3 p-5">
        {!prepVisible || hideAgent ? null : active.loading && active.items.length === 0 ? (
          [0, 1, 2].map((i) => <SkeletonCard key={i} className="h-28" />)
        ) : active.items.length === 0 ? (
          <p className="rounded-xl border border-dashed border-slate-200 px-5 py-6 text-center text-sm text-slate-400">
            Пока нет вопросов
          </p>
        ) : (
          active.items.map((q, i) => {
            const pid = questionPseudoId(qMode, q.text.trim())
            return (
              <QuestionBubble
                key={pid}
                q={q}
                index={i + 1}
                onReveal={markReviewed}
                selected={selection.selectedIds.has(pid)}
                selecting={selection.isSelecting}
                onMouseDownSelect={(e) => {
                  if (e.button !== 0) return
                  selection.startPress(pid)
                }}
                onMouseEnterSelect={() => selection.enterDrag(pid)}
                onContextMenuSelect={() => selection.ensureSelected(pid)}
                onReply={() => replyToQuestionText(q.text)}
                onCopy={() =>
                  copyText(q.answer.trim() ? `Вопрос: ${q.text}\n\nОтвет: ${q.answer}` : q.text)
                }
                onDelete={() => requestDeleteSelection(targetIds(pid))}
              />
            )
          })
        )}

        {prepVisible && active.onAddMore && active.items.length > 0 && !hideAgent && (
          <div className="flex justify-center pt-1">
            <HelpTip id="screening.carousel-add" side="bottom">
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="gap-1.5"
                disabled={active.addMorePending}
                onClick={active.onAddMore}
              >
                {active.addMorePending ? (
                  <Loader2 className="size-4 animate-spin" strokeWidth={2} />
                ) : (
                  <Plus className="size-4" strokeWidth={2} />
                )}
                {active.addMorePending ? "Генерирую…" : "Вопросы"}
              </Button>
            </HelpTip>
          </div>
        )}

        {/* Разбор идёт (или упал) — вставленный текст сразу виден диалогом, шаги меняются, поле
            ввода при этом свободно: композер уже вернулся в «Агент». */}
        {!hideDebrief && (analyze.isPending || analyze.error) && (
          <DebriefProgress
            elapsedMs={analyze.elapsedMs}
            draftTurns={draftTurns}
            error={analyze.error}
            onRetry={analyze.retry}
            onRestoreText={restorePendingTranscript}
            onDismiss={analyze.cancel}
          />
        )}

        {!hideDebrief && screeningDebrief && (
          <DebriefReview
            result={screeningDebrief}
            linkedStage={hrScreeningStage}
            onEdit={() => {
              setTranscriptDraft({ text: screeningDebrief.transcript ?? "", nonce: Date.now() })
              setComposerMode("debrief")
            }}
            onReplyQuestion={replyToQuestionText}
          />
        )}
        {!hideDebrief &&
          !screeningDebrief &&
          !analyze.isPending &&
          !analyze.error &&
          composerMode === "debrief" && (
            <p className="rounded-xl border border-dashed border-slate-200 px-5 py-6 text-center text-sm text-slate-400">
              Расшифровки ещё нет — вставьте её в поле снизу, появится здесь же.
            </p>
          )}

        {contextBusy && (
          <div className="flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-2 text-sm text-slate-500">
            <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />
            Собираю контекст…
          </div>
        )}
        {contextExport && !contextBusy && (
          <ContextExportCard payload={contextExport} onDismiss={() => setContextExport(null)} />
        )}

        {!chatLoading &&
          shownMessages.map((m) => (
            <ChatBubble
              key={m.id}
              msg={m}
              channel={channelById.get(m.id) ?? "agent"}
              quoted={resolvePrepQuote(m, messagesById, channelById)}
              selected={selection.selectedIds.has(m.id)}
              selecting={selection.isSelecting}
              onMouseDownSelect={(e) => {
                if (e.button !== 0) return
                selection.startPress(m.id)
              }}
              onMouseEnterSelect={() => selection.enterDrag(m.id)}
              onContextMenuSelect={() => selection.ensureSelected(m.id)}
              onReply={() =>
                setReplyTo({
                  id: m.id,
                  label: m.role === "user" ? "Я" : "Агент",
                  body: m.content,
                  thumbUrl: m.attachments?.[0]?.thumb_url,
                })
              }
              onCopy={() => copySelection(targetIds(m.id))}
              onDelete={() => requestDeleteSelection(targetIds(m.id))}
            />
          ))}

        {send.isPending && (
          <div className="flex justify-start">
            <div className="flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-2 text-sm text-slate-500">
              <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />
              Готовлю ответ…
            </div>
          </div>
        )}
        <div ref={bottomRef} />
        </div>
      </div>

      <div
        className={cn(
          "flex shrink-0 flex-col border-t bg-white transition-colors",
          composerMode === "agent" &&
            paste.isDraggingOver &&
            "bg-sky-50 outline-dashed outline-2 -outline-offset-2 outline-sky-300",
        )}
        onPaste={composerMode === "agent" ? paste.onPaste : undefined}
        onDragEnter={composerMode === "agent" ? paste.onDragEnter : undefined}
        onDragOver={composerMode === "agent" ? paste.onDragOver : undefined}
        onDragLeave={composerMode === "agent" ? paste.onDragLeave : undefined}
        onDrop={composerMode === "agent" ? paste.onDrop : undefined}
      >
        <div className="flex flex-wrap items-center gap-1 p-3 pb-0">
          {selection.isSelecting ? (
            <SelectionToolbar
              count={selection.selectedIds.size}
              onCopy={() => copySelection(Array.from(selection.selectedIds))}
              onDelete={() => requestDeleteSelection(Array.from(selection.selectedIds))}
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
                <HelpTip id="tech.attachments" side="top">
                  <Button
                    size="icon"
                    variant="outline"
                    type="button"
                    aria-label="Приложить"
                    disabled={
                      !vacancyId ||
                      (composerMode === "agent" ? send.isPending : !!analyze.isPending)
                    }
                    onClick={openAttachPicker}
                  >
                    <Paperclip className="size-4" strokeWidth={2} />
                  </Button>
                </HelpTip>
                <div className="inline-flex items-center gap-1 rounded-xl bg-slate-100 p-1">
                  <ModeSegment
                    active={composerMode === "agent"}
                    onClick={() => setComposerMode("agent")}
                    icon={Sparkles}
                    label="Агент"
                    hidden={hideAgent}
                    onToggleHidden={() => setHideAgent((v) => !v)}
                    hideTitle="переписку с агентом"
                  />
                  <ModeSegment
                    active={composerMode === "debrief"}
                    onClick={() => setComposerMode("debrief")}
                    icon={FileSearch}
                    label="Расшифровка"
                    hidden={hideDebrief}
                    onToggleHidden={() => setHideDebrief((v) => !v)}
                    hideTitle="расшифровку"
                    done={debriefed}
                    doneTitle="Расшифровка скрининга уже разобрана"
                  />
                </div>
              </div>
              <div className="ml-auto flex shrink-0 items-center gap-1.5">
                <HelpTip id="screening.chat-summary-push" side="top">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="gap-1.5"
                    disabled={tgSummaryBlocked}
                    title={tgLinked ? undefined : "Сначала войдите токеном из бота (Аккаунт)"}
                    aria-label="Отправить резюме переписки в Telegram"
                    onClick={() => {
                      if (tgSummaryBlocked || !vacancyId) return
                      pushChatSummary.mutate(vacancyId)
                    }}
                  >
                    {pushChatSummary.isPending ? (
                      <Loader2 className="size-4 animate-spin" strokeWidth={2} />
                    ) : (
                      <Send className="size-4" strokeWidth={2} />
                    )}
                    В Telegram
                  </Button>
                </HelpTip>
                <DropdownMenu open={contextMenuOpen} onOpenChange={setContextMenuOpen}>
                  <HelpTip id="chat.copy-context" side="bottom">
                    <DropdownMenuTrigger asChild>
                      <Button
                        size="sm"
                        variant="outline"
                        className="gap-1.5"
                        disabled={contextBusy || !vacancyId}
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
                      onSelect={requestPrepContext}
                    >
                      <span className="text-sm font-medium text-foreground">Для внешнего ИИ</span>
                      <span className="text-xs text-muted-foreground">
                        Вакансия, рассказ и вопросы HR — вставить в другой чат
                      </span>
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      className="flex-col items-start gap-0.5 py-2"
                      onSelect={requestSobesContext}
                    >
                      <span className="text-sm font-medium text-foreground">Для собеса</span>
                      <span className="text-xs text-muted-foreground">
                        Шпаргалка на скрининг, до 3900 символов
                      </span>
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
                {composerMode === "agent" ? (
                  <Button
                    size="sm"
                    className="gap-1.5"
                    disabled={!canSend}
                    onClick={submit}
                    aria-label={send.isPending ? "Отправляю…" : "Отправить"}
                  >
                    {send.isPending ? (
                      <Loader2 className="size-4 animate-spin" strokeWidth={2} />
                    ) : (
                      <Send className="size-4" strokeWidth={2} />
                    )}
                    Отправить
                  </Button>
                ) : (
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
                )}
              </div>
            </>
          )}
        </div>

        {composerMode === "agent" ? (
          <>
            {replyTo && (
              <div className="mx-3 mt-2 flex items-center gap-2 rounded-lg border-l-2 border-sky-400 bg-sky-50/60 py-1.5 pl-2.5 pr-1.5">
                {replyTo.thumbUrl ? (
                  <img
                    src={replyTo.thumbUrl}
                    alt=""
                    className="size-5 shrink-0 rounded object-cover"
                  />
                ) : null}
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs font-medium text-sky-800">{replyTo.label}</p>
                  <p className="truncate text-xs text-slate-500">{replyTo.body}</p>
                </div>
                <button
                  type="button"
                  onClick={() => setReplyTo(null)}
                  aria-label="Убрать ответ"
                  className="rounded-md p-1 text-slate-400 transition-colors hover:bg-slate-200/60 hover:text-slate-600"
                >
                  ×
                </button>
              </div>
            )}

            {attachments.items.length > 0 && (
              <div className="px-3 pt-2">
                <AttachmentChips
                  items={attachments.items}
                  onRemove={attachments.remove}
                  onRetry={attachments.retry}
                  onOpen={openViewer}
                />
              </div>
            )}

            <div className="p-3">
              <Textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder={
                  !vacancyId
                    ? "Сначала выберите вакансию"
                    : "Спросите, как лучше ответить, попросите разобрать вопрос подробнее…"
                }
                disabled={!vacancyId || send.isPending}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                    e.preventDefault()
                    submit()
                  }
                }}
              />
            </div>
          </>
        ) : (
          <DebriefComposer
            ref={debriefComposerRef}
            job={job}
            stage="screening"
            analyze={analyze}
            interviewStageId={hrScreeningStage?.id ?? null}
            transcriptDraft={transcriptDraft}
            onAnalyzed={() => setTranscriptDraft(null)}
            onSubmitted={() => {
              setTranscriptDraft(null)
              setComposerMode("agent")
            }}
            onStateChange={setDebriefState}
            hideOwnAttachButton
          />
        )}

        {composerMode === "agent" && (
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
                  if (item) window.setTimeout(() => openCrop(item), 0)
                }}
              />
            ) : null}
          </>
        )}
      </div>

      <ConfirmDialog
        open={pendingDelete != null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null)
        }}
        title={
          pendingDelete
            ? `Удалить выделенное (${pendingDelete.questionIds.length + pendingDelete.messageIds.length})?`
            : "Удалить?"
        }
        description="Действие необратимо."
        onConfirm={() => void confirmDelete()}
      />
    </div>
  )
}
