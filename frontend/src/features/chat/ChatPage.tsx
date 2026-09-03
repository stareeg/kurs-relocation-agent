import { useCallback, useMemo, useState } from "react"
import { ArrowLeft } from "lucide-react"
import { toast } from "sonner"
import type { Job } from "@/api/jobs"
import type { Note } from "@/api/notes"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { usePersistedRouteState } from "@/lib/use-persisted-route-state"
import { useJobs } from "@/features/jobs/use-jobs"
import { resolveStage } from "@/features/jobs/funnel"
import { resolveSourceGroup } from "@/features/jobs/source"
import {
  useArchiveConversation,
  useConversations,
  useDeleteConversation,
  usePinConversation,
} from "@/features/chat/use-conversations"
import { useDeleteNote, useNotes } from "@/features/chat/use-notes"
import { ChatsEmptyPane, ChatsSidebar, type ChatSelection } from "./ChatsSidebar"
import { ContextConversationPane } from "./ContextConversationPane"
import { NewContextConversationPane } from "./NewContextConversationPane"
import {
  defaultOutreachDraft,
  NewVacancyConversationPane,
  type OutreachDraftFields,
} from "./NewVacancyConversationPane"
import { VacancyConversationPane } from "./VacancyConversationPane"

// FR3-58: черновик формы «Новая вакансия» — не выбор и не вид/раскладка, персист вне
// F-09 (модульный синглтон остаётся: значение эфемерно намеренно, шарить его ссылкой смысла нет).
let persistedOutreachDraft: OutreachDraftFields = defaultOutreachDraft()

const SOURCE_BY_GROUP = {
  hh: "vacancy_page",
  getmatch: "getmatch",
  habr: "habr",
  telegram: "telegram_channel",
} as const

export function ChatPage() {
  // F-09: выбор — в URL, sessionStorage только фолбэк, пока в URL пусто. `vacancy` — тот же
  // параметр, что уже публикуют ссылки из воронки/StageChain (`/chat?vacancy=...`); `panel` —
  // для двух более редких выборов (новая вакансия / контекст), которых раньше не было в URL
  // вообще.
  const [vacancyId, setVacancyIdParam] = usePersistedRouteState<string>({
    param: "vacancy",
    storageKey: "chat-vacancy",
  })
  const [panel, setPanelParam] = usePersistedRouteState<string>({
    param: "panel",
    storageKey: "chat-panel",
  })

  const selection: ChatSelection = useMemo(() => {
    if (vacancyId) return { kind: "vacancy", vacancyId }
    if (panel === "new") return { kind: "new-vacancy" }
    if (panel === "new-context") return { kind: "new-context" }
    if (panel?.startsWith("context:")) {
      const noteId = Number(panel.slice("context:".length))
      if (Number.isFinite(noteId)) return { kind: "context", noteId }
    }
    return { kind: "empty" }
  }, [vacancyId, panel])

  const setSelection = useCallback(
    (s: ChatSelection) => {
      if (s.kind === "vacancy") {
        setPanelParam(null)
        setVacancyIdParam(s.vacancyId)
      } else if (s.kind === "context") {
        setVacancyIdParam(null)
        setPanelParam(`context:${s.noteId}`)
      } else if (s.kind === "new-vacancy") {
        setVacancyIdParam(null)
        setPanelParam("new")
      } else if (s.kind === "new-context") {
        setVacancyIdParam(null)
        setPanelParam("new-context")
      } else {
        setVacancyIdParam(null)
        setPanelParam(null)
      }
    },
    [setVacancyIdParam, setPanelParam],
  )

  const [outreachDraft, setOutreachDraftState] =
    useState<OutreachDraftFields>(persistedOutreachDraft)
  const setOutreachDraft = useCallback((draft: OutreachDraftFields) => {
    persistedOutreachDraft = draft
    setOutreachDraftState(draft)
  }, [])
  const [archiveMode, setArchiveMode] = useState(false)

  const { data: jobs, refetch: refetchJobs } = useJobs()
  const {
    data: convData,
    isError: conversationsError,
    refetch: refetchConversations,
  } = useConversations(archiveMode)
  const jobsByVacancyId = useMemo(() => {
    const map = new Map<string, Job>()
    for (const j of jobs ?? []) {
      if (j.vacancy_id) map.set(j.vacancy_id, j)
    }
    return map
  }, [jobs])
  // Отказ/Пропуск вакансии автоматически уводит её диалог в Архив Чатов (thread.status /
  // фильтр по job). Ручное архивирование диалога дополнительно решает LLM: Отказ vs Пропущено.
  const conversations = useMemo(() => {
    const items = convData?.items ?? []
    const isAutoArchived = (c: (typeof items)[number]) => {
      const job = jobsByVacancyId.get(c.vacancy_id)
      if (!job) return false
      return job.skipped || resolveStage(job.status) === "Отказ"
    }
    const isArchived = (c: (typeof items)[number]) => c.status === "archived" || isAutoArchived(c)
    return archiveMode ? items.filter(isArchived) : items.filter((c) => !isArchived(c))
  }, [convData, archiveMode, jobsByVacancyId])
  const archiveConversation = useArchiveConversation()
  const deleteConversation = useDeleteConversation()
  const pinConversation = usePinConversation()
  const { data: notes, isLoading: notesLoading } = useNotes("")
  const contexts = useMemo(() => notes ?? [], [notes])
  const deleteNote = useDeleteNote()
  // F-09-style фолбэк: свежесозданный контекст мог ещё не долететь в `contexts` (инвалидация
  // react-query асинхронна) — показываем его сразу, как `job`-заглушку для новой вакансии.
  const [justCreatedContext, setJustCreatedContext] = useState<Note | null>(null)

  const clearSelection = useCallback(() => {
    setSelection({ kind: "empty" })
  }, [setSelection])

  const openNewVacancy = useCallback(() => {
    setSelection({ kind: "new-vacancy" })
  }, [setSelection])

  const openNewContext = useCallback(() => {
    setSelection({ kind: "new-context" })
  }, [setSelection])

  const onContextCreated = useCallback(
    (note: Note) => {
      setJustCreatedContext(note)
      if (note.id != null) setSelection({ kind: "context", noteId: note.id })
    },
    [setSelection],
  )

  const selectContext = useCallback(
    (noteId: number) => {
      setSelection({ kind: "context", noteId })
    },
    [setSelection],
  )

  const deleteContext = useCallback(
    (noteId: number) => {
      const wasActive = selection.kind === "context" && selection.noteId === noteId
      deleteNote.mutate(noteId, {
        onSuccess: () => {
          if (wasActive) {
            const rest = contexts.filter((n) => n.id !== noteId)
            if (rest[0]?.id != null) {
              setSelection({ kind: "context", noteId: rest[0].id })
            } else {
              clearSelection()
            }
          }
        },
      })
    },
    [deleteNote, selection, contexts, setSelection, clearSelection],
  )

  const selectVacancy = useCallback(
    (vacancyId: string) => {
      setSelection({ kind: "vacancy", vacancyId })
    },
    [setSelection],
  )

  const onVacancyCreated = useCallback(
    (vacancyId: string) => {
      setOutreachDraft(defaultOutreachDraft())
      void refetchJobs()
      // Привязка к уже известной вакансии (FR2-87) зовёт import/open мимо react-query — без
      // явного рефетча тред, только что созданный в БД, не появлялся в списке диалогов слева.
      void refetchConversations()
      selectVacancy(vacancyId)
    },
    [refetchJobs, refetchConversations, selectVacancy, setOutreachDraft],
  )

  const archiveThread = useCallback(
    (threadId: number) => {
      const target = conversations.find((c) => c.id === threadId)
      const wasActive =
        target != null && selection.kind === "vacancy" && selection.vacancyId === target.vacancy_id
      archiveConversation.mutate(
        { threadId, status: "archived" },
        {
          onSuccess: () => {
            if (wasActive) clearSelection()
          },
        },
      )
    },
    [archiveConversation, conversations, selection, clearSelection],
  )

  const restoreThread = useCallback(
    (threadId: number) => {
      const target = conversations.find((c) => c.id === threadId)
      const job = target ? jobsByVacancyId.get(target.vacancy_id) : undefined
      // corner_case_1: диалог архивируется по решению воронки (Отказ/Пропущено) — снятие флага
      // на самом треде вернуть его в «Активные» не может, пока жива причина (job.status/skipped).
      // Раньше тут всегда показывался успех, хотя тред тут же снова попадал в архив следующей же
      // синхронизацией/перерендером — честный тост вместо тихого мёртвого пути.
      const funnelBlocksRestore =
        job != null && (job.skipped || resolveStage(job.status) === "Отказ")
      const wasActive =
        target != null && selection.kind === "vacancy" && selection.vacancyId === target.vacancy_id
      archiveConversation.mutate(
        { threadId, status: "active" },
        {
          onSuccess: () => {
            if (funnelBlocksRestore) {
              toast.message(
                `Вакансия «${target?.company || target?.vacancy_id}» всё ещё в статусе ` +
                  `«${job?.skipped ? "Пропущено" : "Отказ"}» — чат вернётся в активные, только ` +
                  `если вернуть саму вакансию в воронку (раздел «Вакансии»).`,
              )
              return
            }
            toast.success("Диалог возвращён в активные")
            if (wasActive) clearSelection()
          },
        },
      )
    },
    [archiveConversation, conversations, selection, clearSelection, jobsByVacancyId],
  )

  const toggleThreadPin = useCallback(
    (threadId: number, pinned: boolean) => {
      pinConversation.mutate({ threadId, pinned })
    },
    [pinConversation],
  )

  const deleteVacancyThread = useCallback(
    (threadId: number) => {
      const wasActive =
        selection.kind === "vacancy" &&
        conversations.some((c) => c.id === threadId && c.vacancy_id === selection.vacancyId)
      deleteConversation.mutate(threadId, {
        onSuccess: () => {
          if (wasActive) clearSelection()
        },
      })
    },
    [deleteConversation, selection, conversations, clearSelection],
  )

  const selectedVacancyId = selection.kind === "vacancy" ? selection.vacancyId : null
  const selectedContext =
    selection.kind === "context"
      ? (contexts.find((n) => n.id === selection.noteId) ??
        (justCreatedContext?.id === selection.noteId ? justCreatedContext : null))
      : null
  const thread = selectedVacancyId
    ? conversations.find((c) => c.vacancy_id === selectedVacancyId)
    : undefined
  const job: Job | null = selectedVacancyId
    ? (jobs?.find((j) => j.vacancy_id === selectedVacancyId) ??
      ({
        vacancy_id: selectedVacancyId,
        company: thread?.company,
        source: SOURCE_BY_GROUP[resolveSourceGroup(undefined, selectedVacancyId)],
      } as unknown as Job))
    : null

  // На телефоне (Safari iPhone) сайдбар раньше был `hidden md:flex` — список чатов
  // не существовал. Список на всю ширину, пока нет выбора; тред — с кнопкой «К списку».
  const showThread = selection.kind !== "empty"

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex min-h-0 flex-1">
        <ChatsSidebar
          className={showThread ? "hidden md:flex" : "flex"}
          selection={selection}
          contexts={contexts}
          contextsLoading={notesLoading}
          conversations={conversations}
          conversationsError={conversationsError}
          onRetryConversations={() => void refetchConversations()}
          jobsByVacancyId={jobsByVacancyId}
          archiveMode={archiveMode}
          onToggleArchiveMode={() => setArchiveMode((v) => !v)}
          onArchiveConversation={archiveThread}
          onRestoreConversation={restoreThread}
          onNewVacancy={openNewVacancy}
          onNewContext={openNewContext}
          onSelectContext={selectContext}
          onDeleteContext={deleteContext}
          onSelectVacancy={selectVacancy}
          onDeleteVacancy={deleteVacancyThread}
          onTogglePinVacancy={toggleThreadPin}
        />
        <div
          className={cn(
            "min-h-0 min-w-0 flex-1 flex-col",
            showThread ? "flex" : "hidden md:flex",
          )}
        >
          {showThread ? (
            <div className="flex shrink-0 items-center gap-1 border-b border-slate-200/80 px-2 py-1.5 md:hidden">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-8 gap-1.5 px-2 text-slate-600"
                onClick={() => setSelection({ kind: "empty" })}
              >
                <ArrowLeft className="size-4" strokeWidth={2} />
                К списку
              </Button>
            </div>
          ) : null}
          {selection.kind === "new-vacancy" ? (
            <NewVacancyConversationPane
              draft={outreachDraft}
              onDraftChange={setOutreachDraft}
              onCreated={onVacancyCreated}
            />
          ) : selection.kind === "new-context" ? (
            <NewContextConversationPane onCreated={onContextCreated} />
          ) : selection.kind === "vacancy" && selectedVacancyId && job ? (
            <VacancyConversationPane
              key={selectedVacancyId}
              vacancyId={selectedVacancyId}
              job={job}
              thread={thread}
            />
          ) : selection.kind === "context" && selectedContext ? (
            <ContextConversationPane key={selectedContext.id} note={selectedContext} />
          ) : (
            <ChatsEmptyPane />
          )}
        </div>
      </div>
    </div>
  )
}
