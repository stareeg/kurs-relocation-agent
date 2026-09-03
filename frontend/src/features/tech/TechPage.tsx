import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useLocation } from "react-router-dom"
import { toast } from "sonner"
import {
  AlarmClock,
  ChevronDown,
  Headset,
  ListTodo,
  ListTree,
  Loader2,
  Plus,
  Sparkles,
  Target,
  X,
} from "lucide-react"
import type { PrepQuestionOut } from "@/api/prep"
import type { DebriefResult } from "@/api/debrief"
import { CollapsibleRail } from "@/components/job/CollapsibleRail"
import { RailFunnelActions } from "@/components/job/RailFunnelActions"
import { VacancyCardRail } from "@/components/job/VacancyCardRail"
import { VacancyStagesInline } from "@/components/job/VacancyStagesInline"
import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { EmptyState } from "@/components/ui/empty-state"
import { SkeletonCard } from "@/components/ui/skeleton"
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { cn } from "@/lib/utils"
import { usePersistedBoolean } from "@/lib/use-persisted-boolean"
import { pluralMessages, type ReplyTarget } from "@/components/chat/composer-widgets"
import { useJobs } from "@/features/jobs/use-jobs"
import { useMessageSelection } from "@/features/jobs/use-message-selection"
import { nextFunnelStage, resolveStage } from "@/features/jobs/funnel"
import { usePersistedRouteState } from "@/lib/use-persisted-route-state"
import {
  CHAIN_STAGE_LABELS,
  PREP_STAGES,
  mapChainStageToPrepStage,
  mapInterviewFormatToPrepStage,
  toPrepStage,
} from "@/features/tech/stages"
import { useInterviewStages } from "@/features/tech/use-interview-stages"
import { loadLastStage, saveLastStage } from "@/features/tech/use-last-stage"
import {
  useAnalyzeDebrief,
  useDebriefHistory,
  useDebriefStageIndex,
  useDeleteTranscriptTurns,
} from "@/features/tech/use-debrief"
import {
  usePrep,
  usePrepChat,
  useDeletePrepChatMessage,
  useExportContext,
  useGeneratePrep,
  useGeneratePrepTopics,
  useGenerateSobesContext,
  useRegeneratePrepPack,
  usePrepTopics,
  useReviewPrepTopics,
  useSavePrepPack,
  useSendPrepChat,
} from "./use-prep"
import { DebriefProgress, DebriefSection, transcriptTurnId } from "./DebriefSection"
import { PrepChat, PrepChatThread, type ContextExportPayload, type PrepView } from "./PrepChat"
import { PrepPackCard } from "./PrepPackCard"
import { ProgressPanel } from "./ProgressPanel"
import { useScreeningQuestions } from "@/features/screening/use-screening"
import { askQuestionCard, hrQuestionCard } from "@/features/screening/question-cards"
import {
  buildPrepChatBody,
  classifyPrepChatChannels,
  formatPrepMessagesForCopy,
  type PrepChatChannel,
} from "./prep-chat-shared"
import { draftTranscriptTurns } from "./debrief-review"
import { TranscriptMark } from "@/components/job/TranscriptMark"

const STAGES = PREP_STAGES
const HR_SCREENING = "hr_screening"

// «Разбор собеса» (бывший третий верхнеуровневый режим) переехал внутрь «Подготовки» - третий
// режим композера (Агент/Внешний ИИ/Расшифровка, см. PrepChat.tsx), а не отдельная вкладка: та
// же расшифровка дублировала контент, который уже виден в чате «Подготовки», и требовала
// отдельного захода вместо единого потока. Переключатель Подготовка/Темы убран (план п.5) —
// «Подготовка» теперь единственный/дефолтный вид, «Темы» (ProgressPanel) — выдвижная панель
// справа, открывается кнопкой в тулбаре PrepChat.

const HIDDEN_CATEGORIES = new Set(["questions_to_ask"])

function PrepSkeleton() {
  return (
    <div className="space-y-4">
      {[0, 1, 2].map((i) => (
        <SkeletonCard key={i} className="h-28" />
      ))}
    </div>
  )
}

function StageFrameworkCard({ steps }: { steps: string[] }) {
  const [collapsed, setCollapsed] = useState(false)
  if (steps.length === 0) return null
  return (
    <section className="rounded-xl border bg-slate-50/60 p-5">
      <button
        type="button"
        onClick={() => setCollapsed((c) => !c)}
        className="flex w-full min-w-0 items-center gap-2 text-left"
      >
        <ListTree className="size-4 shrink-0 text-slate-500" strokeWidth={2} />
        <h2 className="text-sm font-medium text-slate-900">Опорный каркас ответа</h2>
        <ChevronDown
          className={cn(
            "size-3.5 shrink-0 text-slate-400 transition-transform",
            collapsed && "-rotate-90",
          )}
          strokeWidth={2}
        />
      </button>
      {!collapsed && (
        <ol className="mt-3 space-y-1.5 border-t border-dashed pt-3 text-sm text-slate-600">
          {steps.map((step, i) => (
            <li key={i} className="flex gap-2">
              <span className="shrink-0 text-slate-400">{i + 1}.</span>
              <span>{step}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}

type TranscriptTurnRef = { debriefId: number; turnIndex: number; text: string }

// Реплики транскрипта по синтетическому id (transcriptTurnId) - для copySelection/
// confirmDeleteMessages, которые общий selection делит между реальными prep_chat-сообщениями и
// этими репликами (своей строки в БД у них нет).
function buildTurnById(debriefItems: DebriefResult[]): Map<number, TranscriptTurnRef> {
  const map = new Map<number, TranscriptTurnRef>()
  for (const r of debriefItems) {
    if (r.id == null) continue
    const debriefId = r.id
    const turns = r.analysis.transcript_turns ?? []
    for (let i = 0; i < turns.length; i++) {
      map.set(transcriptTurnId(debriefId, i), { debriefId, turnIndex: i, text: turns[i].text })
    }
  }
  return map
}

function hoursUntilSoon(iso: string | null): number | null {
  if (!iso) return null
  const diffMs = new Date(iso).getTime() - Date.now()
  if (diffMs <= 0 || diffMs > 24 * 3_600_000) return null
  return Math.round(diffMs / 3_600_000)
}

function UpcomingCallBanner({ hoursLeft }: { hoursLeft: number }) {
  const label = hoursLeft < 1 ? "меньше часа" : `${hoursLeft} ч`
  return (
    <section className="flex items-center gap-2 rounded-xl border border-rose-200 bg-rose-50/60 px-4 py-2.5">
      <AlarmClock className="size-4 shrink-0 text-rose-600" strokeWidth={2} />
      <p className="text-sm font-medium text-rose-700">Собес через {label}</p>
    </section>
  )
}

function FocusTopicsBanner({ topics, onClear }: { topics: string[]; onClear: () => void }) {
  return (
    <section className="rounded-xl border border-amber-200 bg-amber-50/40 p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <ListTodo className="mt-0.5 size-4 shrink-0 text-amber-700" strokeWidth={2} />
          <div className="space-y-2">
            <p className="text-sm font-medium text-slate-900">Фокус по разбору прошлого собеса</p>
            <div className="flex flex-wrap gap-2">
              {topics.map((t, i) => (
                <span
                  key={i}
                  className="rounded-lg border border-amber-200 bg-white px-2.5 py-1 text-sm text-slate-700"
                >
                  {t}
                </span>
              ))}
            </div>
            <p className="text-xs text-slate-500">
              Нажмите «Подготовиться» — сделаю упор на эти темы.
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={onClear}
          className="rounded-md p-1 text-slate-400 transition-colors hover:text-slate-600"
          aria-label="Убрать фокус"
        >
          <X className="size-4" strokeWidth={2} />
        </button>
      </div>
    </section>
  )
}

type TechNavState = { vacancyId?: string; stage?: string; focusTopics?: string[] }

export function TechPage() {
  const { data: jobs, isLoading: jobsLoading } = useJobs()
  const navState = (useLocation().state ?? null) as TechNavState | null
  // F-09: выбор — в URL (`?vacancy=`, переживает F5, шарится ссылкой), sessionStorage —
  // фолбэк-память между Скринингами и Техничками (тот же storageKey), пока в URL пусто.
  const [vacancyId, setVacancyIdRaw] = usePersistedRouteState<string>({
    param: "vacancy",
    storageKey: "prep-vacancy",
  })
  // Те же вакансии, что рельс сверху (VacancyCardRail sort="byStage", stageOrder Техничка/Финал) —
  // нужны отдельно от рельса, чтобы различить «в разделе нет вакансий вообще» и «есть, но не
  // выбрана» (D-09: разные пустые состояния, без редиректа на Воронку — он никогда не решал задачу
  // «здесь просто пусто»/«просто выбери сверху»).
  const techVacancies = useMemo(() => {
    const order: Record<string, number> = { Техничка: 0, Финал: 1 }
    return (jobs ?? []).filter((j) => !j.skipped).filter((j) => resolveStage(j.status) in order)
  }, [jobs])
  // Рельс (allowClosed) дописывает хвостом отказы — их нет в `techVacancies`, поэтому дефолт-эффект
  // ниже должен знать об этих id отдельно, иначе клик по отказной карточке тут же откатывается на
  // первую активную вакансию (баг: нельзя было зайти в отказ и вставить расшифровку).
  const closedTechVacancies = useMemo(
    () => (jobs ?? []).filter((j) => resolveStage(j.status) === "Отказ"),
    [jobs],
  )
  // FR3-44: один составной прогресс клика «Подготовиться».
  type PrepStep = "pending" | "done" | "error" | "skipped"
  const [prepRun, setPrepRun] = useState<{
    questions: PrepStep
    pack: PrepStep
    topics: PrepStep
  } | null>(null)
  // FR3-43: контекст появляется в ленте чата (не модалка); локально, не в истории LLM.
  const [contextExport, setContextExport] = useState<ContextExportPayload | null>(null)
  const selection = useMessageSelection()
  const [replyTo, setReplyTo] = useState<ReplyTarget | null>(null)
  const [pendingDeleteIds, setPendingDeleteIds] = useState<number[] | null>(null)
  // RD-25: «Ответить» на вопросе из Разбора собеса — вопрос встаёт в композер «Подготовки»
  // готовым текстом (а не фиктивным reply_to_message_id: бэкенд ждёт реальный id реплики чата),
  // владелец дополняет/правит и отправляет в общий чат подготовки — там агент разбирает тему.
  const [debriefQuestionSeed, setDebriefQuestionSeed] = useState<string | null>(null)
  const setVacancyId = useCallback(
    (next: string | null) => {
      setVacancyIdRaw(next)
      setContextExport(null)
      setPrepRun(null)
      selection.clear()
      setReplyTo(null)
      setPendingDeleteIds(null)
      setDebriefQuestionSeed(null)
    },
    [setVacancyIdRaw, selection],
  )
  // Заход через location.state (без URL-параметра) — применяем один раз, дальше приоритет
  // у URL/сессии.
  const [navConsumed, setNavConsumed] = useState(false)
  if (!navConsumed && navState?.vacancyId && vacancyId == null) {
    setNavConsumed(true)
    setVacancyId(navState.vacancyId)
  }
  // Дефолт: если выбора нет или он больше не на экране — первая вакансия из рельса Техничек.
  useEffect(() => {
    if (jobsLoading || techVacancies.length === 0) return
    const ids = new Set(
      [...techVacancies, ...closedTechVacancies].map((j) => j.vacancy_id).filter(Boolean) as string[],
    )
    if (vacancyId && ids.has(vacancyId)) return
    const first = techVacancies[0]?.vacancy_id
    // eslint-disable-next-line react-hooks/set-state-in-effect -- дефолт первый вакансии (FR3-52)
    if (first) setVacancyId(first)
  }, [jobsLoading, techVacancies, closedTechVacancies, vacancyId, setVacancyId])
  const [stage, setStage] = useState<string>(toPrepStage(navState?.stage))
  const [stageChosen, setStageChosen] = useState(!!navState?.stage)
  const [focusTopics, setFocusTopics] = useState<string[]>(navState?.focusTopics ?? [])
  // «Темы» (ProgressPanel) — выдвижная панель справа вместо вкладки (план п.5).
  const [topicsOpen, setTopicsOpen] = useState(false)
  const [prepView, setPrepView] = useState<PrepView>("questions")
  const [manualStageId, setManualStageId] = useState<number | null>(null)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  // UX8: глазики скрытия реплик, персистятся отдельно от Чатов (та же лента может содержать оба
  // канала одновременно, но контекст другой). Отдельного «глазика» для внешней переписки больше
  // нет — режим «Внешний ИИ» убран, старые реплики импорта гаснут вместе с «Агентом».
  const [hideAgent, setHideAgent] = usePersistedBoolean("copilot.tech.hide-agent")
  const [hideDebrief, setHideDebrief] = usePersistedBoolean("copilot.tech.hide-debrief")

  function selectStage(next: string) {
    setStage(next)
    setStageChosen(true)
  }

  const job = useMemo(
    () => (jobs ?? []).find((j) => j.vacancy_id === vacancyId) ?? null,
    [jobs, vacancyId],
  )

  // UX9: HR-скрининг в Техичках использует внутренний флаг `stage === "hr_screening"` для
  // UI-ветвления (кнопка «Подготовиться» скрыта и т.д.), но бэкенд prep/debrief оперирует
  // `PrepStage`, где HR-скрининг — это `"screening"`. Нормализуем stage для всех запросов к бэку,
  // чтобы не звать их с невалидным `"hr_screening"` (422) и чтобы разбор скрининга (хранится в БД
  // под `stage="screening"`) находился теми же хуками, что и для технических этапов.
  const isHrScreening = stage === HR_SCREENING
  const genStage = isHrScreening ? "screening" : stage
  const {
    data: prep,
    isLoading: prepLoading,
    isFetching,
  } = usePrep(vacancyId, genStage, job?.company)
  const generate = useGeneratePrep(vacancyId, genStage)
  const packRegenerate = useRegeneratePrepPack(vacancyId)
  const packSave = useSavePrepPack(vacancyId, genStage)
  const topicsGenerate = useGeneratePrepTopics(vacancyId, genStage)
  const topicsReview = useReviewPrepTopics(vacancyId, genStage)
  const { data: topicsData } = usePrepTopics(vacancyId, genStage)
  // HR-скрининг в Техичках читает уже собранный в разделе «Скрининги» пакет (hr_questions/groups),
  // ничего сам не генерирует. Маппится в PrepQuestionOut[] теми же hrQuestionCard/askQuestionCard,
  // что и QuestionsChatPanel Скринингов — единая форма для QuestionBubble в ленте.
  const { data: screeningQuestions } = useScreeningQuestions(isHrScreening ? vacancyId : null)
  /** Уже засчитанные раскрытия вопросов (по тексту) - не дублировать LLM-маппинг. */
  const reviewedQuestionKeys = useRef(new Set<string>())

  const exportContext = useExportContext(vacancyId, stage)
  const sobesContext = useGenerateSobesContext(vacancyId, stage)
  const deleteMessages = useDeletePrepChatMessage(vacancyId)
  const deleteTurns = useDeleteTranscriptTurns(vacancyId)
  const [chatSendState, setChatSendState] = useState<{
    isPending: boolean
    pendingContent: string | null
    pendingChannel: PrepChatChannel
    elapsedMs: number
  }>({
    isPending: false,
    pendingContent: null,
    pendingChannel: "agent",
    elapsedMs: 0,
  })
  const [contextMenuOpen, setContextMenuOpen] = useState(false)
  const contextBusy = exportContext.isPending || sobesContext.isPending

  function requestPrepContext() {
    setPrepView("questions")
    setContextMenuOpen(false)
    setContextExport(null)
    exportContext.mutate(undefined, {
      onSuccess: (result) => {
        const text = result.text?.trim() ?? ""
        if (!text) {
          toast.message("Контекст пуст — сначала соберите подготовку")
          return
        }
        setContextExport({
          kind: "prep",
          text,
          subtitle: `${stageLabel} · ${text.length.toLocaleString("ru-RU")} символов`,
        })
      },
    })
  }

  function requestSobesContext() {
    if (!vacancyId || !job) return
    setPrepView("questions")
    setContextMenuOpen(false)
    setContextExport(null)
    sobesContext.mutate(
      {
        stage: stage as never,
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
          const stagePart = result.stage_label || stage
          setContextExport({
            kind: "sobes",
            text: md,
            subtitle: `${stagePart} · ${charCount}/${charLimit} символов`,
          })
        },
      },
    )
  }

  const [newlyAddedTexts, setNewlyAddedTexts] = useState<Set<string>>(new Set())
  const highlightTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const flashNewQuestions = useCallback((added: PrepQuestionOut[]) => {
    if (added.length === 0) return
    setNewlyAddedTexts(new Set(added.map((q) => q.text)))
    if (highlightTimerRef.current) clearTimeout(highlightTimerRef.current)
    highlightTimerRef.current = setTimeout(() => setNewlyAddedTexts(new Set()), 2500)
  }, [])

  const { data: chatData } = usePrepChat(vacancyId)
  const moreQuestions = useSendPrepChat(vacancyId, stage, flashNewQuestions)
  function requestMoreQuestions() {
    if (!job || !vacancyId) return
    // П.5a: если к этапу уже привязана реальная расшифровка собеса, просим агента держаться
    // тем/стиля реального собеседования (разбор виден в той же ленте выше) и не повторять те
    // вопросы. Контекст разбора (слабые темы/уже спрошенное) уже приходит в системный промпт
    // через gather_prep_context — здесь лишь подчёркиваем акцент на реальных темах.
    const message = hasRealDebriefForStage
      ? "Дайте ещё пачку вопросов по этому этапу — опирайтесь на реальные темы из разбора собеседования выше: вопросы по ним, смежным областям и темам, где ответ был слабым. Не повторяйте уже заданные вопросы и держитесь стиля реального собеседования."
      : "Дайте ещё пачку вопросов по этому этапу — не повторяйте то, что уже есть"
    const body = buildPrepChatBody(job, stage, focusTopics, message, chatData?.items ?? [])
    moreQuestions.mutate(body)
  }

  // Канал реплики (Агент/Внешний ИИ) по id — единый источник для ленты, копирования и фильтра
  // «глазик»; сам чат не хранит явного поля канала (см. classifyPrepChatChannels).
  const channelById = useMemo(() => {
    const items = chatData?.items ?? []
    const channels = classifyPrepChatChannels(items)
    return new Map(items.map((m, i) => [m.id, channels[i]]))
  }, [chatData])

  function copySelection(ids: number[]) {
    const idSet = new Set(ids)
    const selectedMessages = (chatData?.items ?? []).filter((m) => idSet.has(m.id))
    // Реплики транскрипта (id < 0, см. transcriptTurnId) - синтетический id, своей строки в БД
    // у них нет, поэтому текст берём из turnById, а не из chatData.
    const turnTexts = ids
      .map((id) => turnById.get(id)?.text)
      .filter((t): t is string => Boolean(t))
    const parts: string[] = []
    const msgText = formatPrepMessagesForCopy(selectedMessages, channelById)
    if (msgText) parts.push(msgText)
    if (turnTexts.length > 0) parts.push(turnTexts.join("\n"))
    const text = parts.join("\n\n")
    selection.clear()
    if (!text) return
    navigator.clipboard.writeText(text).then(
      () => toast.success(ids.length === 1 ? "Сообщение скопировано" : "Сообщения скопированы"),
      () => toast.error("Не удалось скопировать"),
    )
  }

  function requestDeleteSelection(ids: number[]) {
    if (ids.length === 0) return
    setPendingDeleteIds(ids)
  }

  async function confirmDeleteMessages() {
    if (!pendingDeleteIds) return
    const messageIds = pendingDeleteIds.filter((id) => id >= 0)
    // Реплики транскрипта - «удаление» это точечная правка сохранённого текста расшифровки
    // (usePatchDebriefTranscript под капотом), не запись в prep_chat - отдельная мутация.
    const turnRefs = pendingDeleteIds
      .map((id) => turnById.get(id))
      .filter((t): t is TranscriptTurnRef => t != null)
    try {
      if (messageIds.length > 0) await deleteMessages.mutateAsync(messageIds)
      if (turnRefs.length > 0) {
        await deleteTurns.mutateAsync(
          turnRefs.map(({ debriefId, turnIndex }) => ({ debriefId, turnIndex })),
        )
      }
      selection.clear()
    } catch {
      /* тосты в хуках */
    } finally {
      setPendingDeleteIds(null)
    }
  }

  // Где по аккаунту уже есть разобранная расшифровка — один запрос на раздел, отметка в рельсе.
  const { data: stageIndex } = useDebriefStageIndex()
  const { data: stagesData } = useInterviewStages(vacancyId)
  // Формат привязан к вакансии: у другой вакансии своя цепочка. Дефолт при первом заходе на
  // вакансию — HR-скрининг (валиден для любой вакансии); если владелец уже выбирал этап здесь
  // раньше — восстанавливаем именно его (use-last-stage.ts), а не «ближайший ожидаемый
  // tech-этап» как было раньше: тот никогда не предлагал HR-скрининг и не помнил выбор между
  // заходами на вакансию.
  const [stageOwner, setStageOwner] = useState<string | null>(null)
  if (vacancyId && stagesData != null && stageOwner !== vacancyId) {
    const keepNavStage = stageOwner === null && Boolean(navState?.stage)
    setStageOwner(vacancyId)
    if (!keepNavStage) {
      const remembered = loadLastStage(vacancyId)
      const manualStageId =
        remembered?.manualStageId != null &&
        stagesData.items.some((s) => s.id === remembered.manualStageId)
          ? remembered.manualStageId
          : null
      setStage(remembered?.stage ?? HR_SCREENING)
      setStageChosen(true)
      setManualStageId(manualStageId)
    }
  }

  // Персист последнего выбора на вакансию — переживает переключение между вакансиями/разделами.
  useEffect(() => {
    if (!vacancyId) return
    saveLastStage(vacancyId, { stage, manualStageId })
  }, [vacancyId, stage, manualStageId])

  const upcomingStageAt = useMemo(() => {
    const matches = (stagesData?.items ?? []).filter(
      (s) => s.stage_type === stage && s.status === "scheduled" && s.scheduled_at,
    )
    if (matches.length === 0) return null
    const soonest = matches.reduce((a, b) =>
      new Date(a.scheduled_at!).getTime() < new Date(b.scheduled_at!).getTime() ? a : b,
    )
    return soonest.scheduled_at ?? null
  }, [stagesData, stage])
  const hoursUntilStage = hoursUntilSoon(upcomingStageAt)

  const analyze = useAnalyzeDebrief(vacancyId)
  // UX-этап: нормализованный ключ этапа, под которым разбор хранится в БД. HR-скрининг в
  // Техичках держит внутренний флаг hr_screening, но бэкенд разбора оперирует PrepStage, где
  // это "screening". Один ключ и для фильтра ленты (debriefItems), и для hasRealDebriefForStage,
  // и для stageFilter в DebriefSection — расшифровка скрининга не висит в «Теории» и наоборот.
  const debriefStage = isHrScreening ? "screening" : stage
  const { data: debriefHistory } = useDebriefHistory(vacancyId)
  // Только разборы выбранного этапа — расшифровка скрининга не висит в ленте «Теории» и наоборот.
  // UX-этап: визуально лента принадлежит одному этапу; под капотом контекст прошлых этапов
  // уходит в LLM суммаризацией (gather_prep_context), не дословно.
  const debriefItems = useMemo(
    () => (debriefHistory?.items ?? []).filter((r) => r.stage === debriefStage),
    [debriefHistory, debriefStage],
  )
  const turnById = buildTurnById(debriefItems)
  // Этапы цепочки, к которым можно привязать разбор выбранного формата. HR-скрининг включён:
  // разбор скрининга хранится в БД под stage="screening" и должен привязываться к своему этапу
  // цепочки (interview_stage_id) как любой другой — тогда он виден в DebriefSection и
  // подменяет мок-вопросы screening-пакета в ленте Техичек. mapChainStageToPrepStage(hr_screening)
  // фолбэчит на "theory", поэтому для HR-скрининга фильтруем по stage_type явно.
  const candidateDebriefStages = useMemo(() => {
    const chain = stagesData?.items ?? []
    if (isHrScreening) return chain.filter((s) => s.stage_type === HR_SCREENING)
    return chain.filter((s) => mapChainStageToPrepStage(s.stage_type) === stage)
  }, [stagesData, stage, isHrScreening])
  const debriefedStageIds = useMemo(
    () =>
      new Set(
        debriefItems.map((r) => r.interview_stage_id).filter((id): id is number => id != null),
      ),
    [debriefItems],
  )
  const suggestedDebriefStageId = useMemo(() => {
    const fresh = candidateDebriefStages.find(
      (s) => s.status === "scheduled" && !debriefedStageIds.has(s.id),
    )
    return fresh?.id ?? candidateDebriefStages[0]?.id ?? null
  }, [candidateDebriefStages, debriefedStageIds])
  const debriefStageInstanceId =
    manualStageId != null && candidateDebriefStages.some((s) => s.id === manualStageId)
      ? manualStageId
      : suggestedDebriefStageId

  const [transcriptDraft, setTranscriptDraft] = useState<{ text: string; nonce: number } | null>(
    null,
  )
  function editTranscript(text: string, stageOfResult: string) {
    setTranscriptDraft({ text, nonce: Date.now() })
    selectStage(stageOfResult)
    setPrepView("debrief")
  }
  // Черновая разметка вставленного текста на реплики — пока LLM считает настоящую (иначе экран
  // на минуту показывает один спиннер вместо расшифровки, которую только что вставили).
  const draftTurns = useMemo(
    () => (analyze.pendingTranscript ? draftTranscriptTurns(analyze.pendingTranscript) : []),
    [analyze.pendingTranscript],
  )
  // Задача разбора упала — вернуть текст в поле (композер очистился сразу после отправки, единственная
  // копия расшифровки живёт в самой задаче).
  function restorePendingTranscript() {
    const text = analyze.pendingTranscript
    if (!text) return
    setTranscriptDraft({ text, nonce: Date.now() })
    setPrepView("debrief")
    analyze.cancel()
  }
  function onDebriefAnalyzed(result: DebriefResult) {
    setManualStageId(null)
    // UX21: после разбора расшифровки HR-скрининга не уводим владельца на другой формат подготовки
    // (screening живёт в «Скринингах», у него нет PrepStage-проекции) — остаёмся на скрининге, чтобы
    // сразу показать подменённые реальными вопросами мок-вопросы в ленте Техичек.
    if (!isHrScreening) selectStage(mapInterviewFormatToPrepStage(result.analysis.interview_format))
  }

  // П.5a: после вставки реальной расшифровки этапа мок-вопросы теряют смысл (собеседование
  // прошло, реальные вопросы видны в DebriefSection той же ленты) — скрываем карточки вопросов.
  // debriefStage уже нормализован выше (hr_screening → screening) — тем же ключом, под которым
  // разбор хранится в БД; иначе существующий разбор не подменял бы моки.
  const hasRealDebriefForStage = debriefItems.some((r) => r.stage === debriefStage)
  // HR-скрининг: мок-вопросы — это screening-пакет (hr_questions/groups), отображаются теми же
  // карточками QuestionBubble, что и prep-вопросы тех. этапов. После разбора подменяются
  // реальными (hasRealDebriefForStage → пусто, в DebriefSection видны реальные вопросы).
  const screeningQuestionItems = useMemo<PrepQuestionOut[]>(() => {
    if (!isHrScreening || !screeningQuestions) return []
    const fromHr = (screeningQuestions.hr_questions ?? []).map(hrQuestionCard)
    const toHr = (screeningQuestions.groups ?? []).flatMap((g) =>
      (g.questions ?? []).filter((q) => q.question?.trim()).map((q) => askQuestionCard(q, g.title)),
    )
    return [...fromHr, ...toHr]
  }, [isHrScreening, screeningQuestions])
  const questionItems = hasRealDebriefForStage
    ? []
    : isHrScreening
      ? screeningQuestionItems
      : (prep?.questions ?? []).filter((q) => !HIDDEN_CATEGORIES.has(q.category))

  const hitRate = useMemo(() => {
    const qs = prep?.questions ?? []
    const matched = qs.filter((q) => q.outcome != null)
    if (matched.length === 0) return null
    const asked = matched.filter((q) => q.outcome === "asked").length
    return { asked, matched: matched.length }
  }, [prep])

  function vacancyContext() {
    if (!job) return null
    const hasScore = job.score && Object.keys(job.score).length > 0
    return {
      vacancy_text: job.vacancy_text,
      title: job.title,
      company: job.company,
      salary_text: job.salary_text,
      score: hasScore ? (job.score as never) : null,
    }
  }

  function runGenerate() {
    if (!job) return
    const context = vacancyContext()
    if (!context) return
    // Темы верхнеуровневые - генерим один раз на вакансию+этап; повторный клик не жжёт LLM.
    const needTopics = (topicsData?.items?.length ?? 0) === 0
    setPrepRun({
      questions: "pending",
      pack: "pending",
      topics: needTopics ? "pending" : "skipped",
    })

    const mark = (step: "questions" | "pack" | "topics", status: PrepStep) =>
      setPrepRun((cur) => (cur ? { ...cur, [step]: status } : cur))

    generate.mutate(
      { stage: stage as never, ...context, focus_topics: focusTopics },
      {
        onSuccess: (result) => {
          const added = (result.questions ?? []).filter((q) => !HIDDEN_CATEGORIES.has(q.category))
          flashNewQuestions(added)
          mark("questions", "done")
        },
        onError: () => mark("questions", "error"),
      },
    )
    // Бриф принимается сразу после генерации - без diff-ревью.
    packRegenerate.mutate(
      { stage: stage as never, ...context },
      {
        onSuccess: (res) => {
          packSave.mutate(
            { stage: stage as never, content: res.text, input_hash: res.input_hash },
            {
              onSuccess: () => mark("pack", "done"),
              onError: () => mark("pack", "error"),
            },
          )
        },
        onError: () => mark("pack", "error"),
      },
    )
    if (needTopics) {
      topicsGenerate.mutate(
        { stage: stage as never, ...context, force: false },
        {
          onSuccess: () => mark("topics", "done"),
          onError: () => mark("topics", "error"),
        },
      )
    }
  }

  function onRevealQuestion(q: PrepQuestionOut) {
    const key = q.text.trim()
    if (!key || reviewedQuestionKeys.current.has(key)) return
    reviewedQuestionKeys.current.add(key)
    // Фон: бэкенд мапит вопрос на каталог тем (LLM) и бампит уровень - UI не ждём.
    topicsReview.mutate({
      stage: stage as never,
      question_text: key,
      question_topic_hint: q.topic?.trim() || null,
      answer_excerpt: q.answer?.trim()?.slice(0, 800) || null,
    })
  }

  const hasQuestions = questionItems.length > 0
  const prepBusy =
    prepRun != null &&
    (prepRun.questions === "pending" || prepRun.pack === "pending" || prepRun.topics === "pending")
  const busy = prepBusy || generate.isPending
  const stageLabel =
    STAGES.find((s) => s.value === stage)?.label ?? CHAIN_STAGE_LABELS[stage] ?? stage
  const showComposer = Boolean(vacancyId)
  // Этап 1.1 плана `plans/ui_slop_cleanup_2026_08_25.md`: одна переменная и на вёрстку шапки,
  // и на текст пустого состояния. Раньше кнопку прятало условие `vacancyId && !isHrScreening`,
  // а пустое состояние всё равно писало «Нажми «Подготовиться» сверху» — текст ссылался на
  // элемент, которого в этой ветке нет, и выхода с экрана не оставалось.
  // Вопросы к HR-скринингу собирает раздел «Скрининги» (useScreeningQuestions выше), здесь их
  // только показывают, поэтому своей кнопки генерации тут и не должно быть.
  const hasPrepButton = Boolean(vacancyId) && !isHrScreening

  function prepStepMark(status: PrepStep): string {
    if (status === "pending") return "…"
    if (status === "done") return "✓"
    if (status === "skipped") return "—"
    return "!"
  }

  const prepProgressLabel = prepRun
    ? `Вопросы ${prepStepMark(prepRun.questions)} · Бриф ${prepStepMark(prepRun.pack)} · Темы ${prepStepMark(prepRun.topics)}`
    : null
  const prepDoneCount = prepRun
    ? (["questions", "pack", "topics"] as const).filter(
        (k) => prepRun[k] === "done" || prepRun[k] === "skipped",
      ).length
    : 0
  const prepTotalSteps = 3
  const prepAllSettled =
    prepRun != null &&
    prepRun.questions !== "pending" &&
    prepRun.pack !== "pending" &&
    prepRun.topics !== "pending"

  const hasTechVacancies = techVacancies.length > 0
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div id="screen-start-tech" className="flex min-h-0 flex-1">
        <CollapsibleRail storageKey="copilot.rail.tech.collapsed">
          <VacancyCardRail
            value={vacancyId}
            onChange={(j) => setVacancyId(j?.vacancy_id ?? null)}
            showGeneral={false}
            sort="byStage"
            stageOrder={["Техничка", "Финал"]}
            allowClosed
            closedIncludeSkipped={false}
            closedLimit={10}
            renderActions={(j) => {
              const next = nextFunnelStage(resolveStage(j.status))
              return (
                <RailFunnelActions
                  job={j}
                  nextStage={next}
                  nextLabel={next === "Финал" || next === "Оффер" ? next : undefined}
                />
              )
            }}
            renderMark={(j) => {
              // Технички: отметка про расшифровку ЛЮБОГО технического этапа этой вакансии —
              // рельс не знает про выбранный формат, а «есть ли вообще разбор» видно списком.
              const stages = stageIndex?.get(j.vacancy_id ?? "")
              const hasTechDebrief = stages ? [...stages].some((st) => st !== "screening") : false
              return <TranscriptMark done={hasTechDebrief} />
            }}
            renderExpanded={(j) => {
              const isSelected = j.vacancy_id === vacancyId
              return (
                <VacancyStagesInline
                  vacancyId={j.vacancy_id!}
                  activeStageType={isSelected ? stage : ""}
                  activeStageId={isSelected ? (manualStageId ?? debriefStageInstanceId) : undefined}
                  onSelect={(stageType, id) => {
                    const mapped =
                      stageType === HR_SCREENING ? HR_SCREENING : mapChainStageToPrepStage(stageType)
                    if (!isSelected) {
                      // Переключение на другую вакансию по клику её этапа — сохраняем выбор до
                      // смены vacancyId, иначе render-phase восстановление «последнего этапа»
                      // (stageOwner-эффект ниже) перезапишет именно этот клик забытым состоянием.
                      saveLastStage(j.vacancy_id!, { stage: mapped, manualStageId: id })
                      setVacancyId(j.vacancy_id!)
                      return
                    }
                    selectStage(mapped)
                    setManualStageId(id)
                  }}
                />
              )
            }}
          />
        </CollapsibleRail>

        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          {hasPrepButton && (
            <div className="space-y-1.5 border-b px-6 py-3">
              <div className="flex items-center justify-end gap-2">
                {prepView === "questions" && hitRate && (
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">
                    Прогноз попал {hitRate.asked}/{hitRate.matched}
                  </span>
                )}
                <Button
                  size="sm"
                  className="gap-1.5"
                  title={stageChosen ? undefined : "Сначала выберите формат собеса — в рельсе слева"}
                  disabled={!job || busy || !stageChosen || moreQuestions.isPending}
                  onClick={() => {
                    // П.5a: после расшифровки тоже идём в requestMoreQuestions (агент учитывает
                    // реальные вопросы из разбора), а не в первичную генерацию мок-пакета.
                    if (hasQuestions || hasRealDebriefForStage) requestMoreQuestions()
                    else runGenerate()
                  }}
                >
                  {busy || moreQuestions.isPending ? (
                    <Loader2 className="size-4 animate-spin" strokeWidth={2} />
                  ) : hasQuestions || hasRealDebriefForStage ? (
                    <Plus className="size-4" strokeWidth={2} />
                  ) : (
                    <Sparkles className="size-4" strokeWidth={2} />
                  )}
                  {prepBusy
                    ? `Готовлю ${prepDoneCount}/${prepTotalSteps}`
                    : moreQuestions.isPending
                      ? "Готовлю…"
                      : hasQuestions || hasRealDebriefForStage
                        ? "+ Вопросы"
                        : "Подготовиться"}
                </Button>
              </div>
              {/* Отдельной строкой, а не под кнопкой: раньше текст жил внутри правой колонки и,
                  появляясь, сдвигал «Подготовиться» вверх (строка выравнена по центру). */}
              {prepProgressLabel && (
                <p
                  className={cn(
                    "text-right text-xs tabular-nums text-slate-400",
                    prepAllSettled && "text-slate-500",
                  )}
                >
                  {prepProgressLabel}
                  {prepAllSettled ? " · готово" : ""}
                </p>
              )}
            </div>
          )}

          {!vacancyId ? (
            <EmptyState
              icon={Target}
              title={
                jobsLoading
                  ? "Здесь будет подготовка к собесу"
                  : hasTechVacancies
                    ? "Выберите вакансию слева"
                    : "Нет вакансий в Техничках"
              }
              note={
                jobsLoading
                  ? "Загружаю воронку…"
                  : hasTechVacancies
                    ? "Карточка вакансии — в рельсе слева."
                    : "Перетяните вакансию на этап «Техничка» в разделе «Вакансии»."
              }
            />
          ) : (
            <>
              <div ref={scrollRef} className="min-h-0 flex-1 overflow-auto">
                <div className="space-y-6 p-6">
                    {hoursUntilStage != null && <UpcomingCallBanner hoursLeft={hoursUntilStage} />}

                    {/* Prep-пакет (бриф/каркас) — только для тех. этапов и только ДО расшифровки.
                        HR-скрининг готовится в разделе «Скрининги», здесь у него только
                        мок-вопросы screening-пакета в ленте и композер «Расшифровка».
                        После разбора реальной расшифровки бриф («что спросят», слабые темы)
                        описывает уже прошедший собес прогнозом — он больше не помогает, а только
                        оттесняет вниз сам разбор; вернуть его можно, переключившись на этап без
                        расшифровки. */}
                    {!isHrScreening && !hasRealDebriefForStage && (
                      <PrepPackCard
                        job={job}
                        stage={stage}
                        regenerating={packRegenerate.isPending || packSave.isPending}
                        candidate={null}
                        onAccept={() => undefined}
                        onDiscard={() => undefined}
                        saving={packSave.isPending}
                      />
                    )}

                    {!isHrScreening && focusTopics.length > 0 && (
                      <FocusTopicsBanner topics={focusTopics} onClear={() => setFocusTopics([])} />
                    )}
                    {/* Опорный каркас — статичная шпаргалка под формат этапа. После вставки
                        реальной расшифровки собеседования каркас бесполезен: реальные вопросы и
                        ход разговора видны в DebriefSection той же ленты, абстрактный шаблон
                        ответа поверх них не добавляет ценности — скрываем. */}
                    {!isHrScreening && !hasRealDebriefForStage && (
                      <StageFrameworkCard steps={prep?.framework ?? []} />
                    )}

                    {/* RD-25→слияние: «Разбор собеса» переехал из отдельной вкладки сюда, в общую
                        ленту «Подготовки» - виден только когда есть что показать (сам разбор
                        никогда не был бы пуст ради пустого состояния, у которого теперь есть
                        собственный, более уместный, вход — режим «Расшифровка» в композере).
                        UX-этап: stageFilter сужает ленту до разборов выбранного формата —
                        расшифровка HR-скрининга не висит в «Теории», разбор «Теории» — в «Финале».
                        Контекст прошлых этапов не теряется: он уходит в LLM суммаризацией
                        (gather_prep_context), а не дословно в ленту. Переключиться на прошлый
                        этап — слева в цепочке, там разбор виден целиком. */}
                    {/* Идущий (или упавший) разбор — своей карточкой над историей: вставленный
                        текст сразу виден диалогом, статус меняется по шагам, поле ввода при этом
                        свободно (композер уже вернулся в «Агент»). */}
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

                    {/* RD-25→слияние: «Разбор собеса» переехал из отдельной вкладки сюда, в общую
                        ленту «Подготовки» - виден только когда есть что показать (сам разбор
                        никогда не был бы пуст ради пустого состояния, у которого теперь есть
                        собственный, более уместный, вход — режим «Расшифровка» в композере).
                        UX-этап: stageFilter сужает ленту до разборов выбранного формата —
                        расшифровка HR-скрининга не висит в «Теории», разбор «Теории» — в «Финале».
                        Контекст прошлых этапов не теряется: он уходит в LLM суммаризацией
                        (gather_prep_context), а не дословно в ленту. Переключиться на прошлый
                        этап — слева в цепочке, там разбор виден целиком. */}
                    {!hideDebrief && debriefItems.length > 0 && (
                      <DebriefSection
                        job={job}
                        setStage={selectStage}
                        onEditTranscript={editTranscript}
                        onReplyQuestion={(question) => {
                          // RD-25: ответ на реплике транскрипта. Фиктивный reply_to_message_id на
                          // бэкенде не пройдёт (FK на реальную реплику чата), поэтому текст
                          // встаёт в композер «Подготовки», а агент получает его полным
                          // контекстом.
                          setDebriefQuestionSeed(question)
                          setPrepView("questions")
                        }}
                        selection={selection}
                        onDeleteTurn={(debriefId, turnIndex) =>
                          requestDeleteSelection([transcriptTurnId(debriefId, turnIndex)])
                        }
                        stageFilter={debriefStage}
                      />
                    )}

                    {(busy || prepLoading || (isFetching && !prep)) &&
                    !hasQuestions &&
                    !contextBusy &&
                    !contextExport ? (
                      <PrepSkeleton />
                    ) : (
                      <>
                        {/* L-49: вопросы приезжают частями — реальная карусель, как только есть
                        первая часть, вместо ожидания второй половины (вопросов к HR). */}
                        {busy && hasQuestions && (
                          <div className="mb-3 flex items-center gap-2 rounded-lg border border-sky-200/80 bg-sky-50/60 px-3 py-2 text-sm text-sky-800">
                            <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />
                            Дособираю вопросы…
                          </div>
                        )}
                        <PrepChatThread
                          vacancyId={vacancyId}
                          questions={questionItems}
                          newlyAddedTexts={newlyAddedTexts}
                          pendingContent={chatSendState.pendingContent}
                          pendingChannel={chatSendState.pendingChannel}
                          isPending={chatSendState.isPending}
                          elapsedMs={chatSendState.elapsedMs}
                          scrollParentRef={scrollRef}
                          onRevealQuestion={onRevealQuestion}
                          contextExport={contextExport}
                          contextExportPending={contextBusy}
                          onDismissContextExport={() => setContextExport(null)}
                          hideAgent={hideAgent}
                          selection={selection}
                          onReply={setReplyTo}
                          onCopySelection={copySelection}
                          onDeleteSelection={requestDeleteSelection}
                        />
                      </>
                    )}

                    {!busy &&
                      !prepLoading &&
                      !hasQuestions &&
                      (chatData?.items?.length ?? 0) === 0 &&
                      !contextExport &&
                      !contextBusy && (
                        /* Без кнопки: «Подготовиться» уже стоит в шапке этого же экрана
                       (D-09) — две одинаковые кнопки на одном экране только путали.
                       Ветка HR-скрининга — исключение: кнопки в шапке нет вовсе
                       (`hasPrepButton`), поэтому отсылать к ней нельзя, и состояние ведёт
                       туда, где пакет действительно собирается (Этап 1.1). */
                        !hasPrepButton ? (
                          <EmptyState
                            icon={Headset}
                            title="Вопросы к HR-скринингу собираются в «Скринингах»"
                            note="Здесь готовятся технические этапы. Пакет под HR-скрининг этой вакансии делается в разделе «Скрининги» и появится здесь сам."
                            action={{
                              label: "Открыть в «Скринингах»",
                              to: `/screening?vacancy=${encodeURIComponent(vacancyId)}`,
                            }}
                          />
                        ) : (
                          <EmptyState
                            icon={Sparkles}
                            title="Вопросов под этап ещё нет"
                            note={
                              stageChosen
                                ? `Нажмите «Подготовиться» сверху — соберу набор под «${stageLabel}».`
                                : "Сначала выберите формат собеса слева — от него зависит набор вопросов."
                            }
                          />
                        )
                      )}
                </div>
              </div>
              {showComposer && (
                <PrepChat
                  job={job}
                  stage={stage}
                  focusTopics={focusTopics}
                  view={prepView}
                  onChangeView={setPrepView}
                  hideAgent={hideAgent}
                  onToggleHideAgent={() => setHideAgent((v) => !v)}
                  hideDebrief={hideDebrief}
                  onToggleHideDebrief={() => setHideDebrief((v) => !v)}
                  onOpenTopics={() => setTopicsOpen(true)}
                  analyze={analyze}
                  debriefInterviewStageId={debriefStageInstanceId}
                  debriefDone={hasRealDebriefForStage}
                  transcriptDraft={transcriptDraft}
                  onDebriefAnalyzed={onDebriefAnalyzed}
                  onDebriefSubmitted={() => setPrepView("questions")}
                  contextMenuOpen={contextMenuOpen}
                  onContextMenuOpenChange={setContextMenuOpen}
                  onRequestPrepContext={requestPrepContext}
                  onRequestSobesContext={requestSobesContext}
                  contextBusy={contextBusy}
                  contextDisabled={!job || !stageChosen}
                  replyTo={replyTo}
                  onClearReply={() => setReplyTo(null)}
                  selection={selection}
                  onCopySelection={() => copySelection(Array.from(selection.selectedIds))}
                  onRequestDeleteSelection={() =>
                    requestDeleteSelection(Array.from(selection.selectedIds))
                  }
                  onQuestions={flashNewQuestions}
                  onSendState={setChatSendState}
                  composerSeed={debriefQuestionSeed}
                />
              )}
            </>
          )}
        </div>
      </div>

      {/* «Темы» (ProgressPanel) — выдвижная панель вместо вкладки (план п.5), открывается кнопкой
          в тулбаре PrepChat (слева от «В Telegram»). */}
      <Sheet open={topicsOpen} onOpenChange={setTopicsOpen}>
        <SheetContent className="max-w-none" style={{ width: "min(100%, 32rem)" }}>
          <SheetHeader>
            <SheetTitle>Темы</SheetTitle>
          </SheetHeader>
          <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-6">
            {job && <ProgressPanel job={job} stage={stage} stageChosen={stageChosen} />}
          </div>
        </SheetContent>
      </Sheet>

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
        onConfirm={() => void confirmDeleteMessages()}
      />
    </div>
  )
}
