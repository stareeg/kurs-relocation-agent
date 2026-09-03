import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"
import { useVirtualizer } from "@tanstack/react-virtual"
import {
  AlertTriangle,
  Archive,
  Briefcase,
  CalendarClock,
  Copy,
  Inbox,
  Library,
  Loader2,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Pin,
  Plus,
  Power,
  Trash2,
} from "lucide-react"
import { type ConvThread, conversationListSubtitle, conversationTitle } from "@/api/conversations"
import type { Job } from "@/api/jobs"
import type { Note } from "@/api/notes"
import { formatEventLabel } from "@/lib/format"
import { cn } from "@/lib/utils"
import { usePersistedBoolean, usePersistedString } from "@/lib/use-persisted-boolean"
import { ONBOARDING_HINT_IDS, useOnboardingHints } from "@/lib/use-onboarding-hints"
import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { EmptyState, ErrorState } from "@/components/ui/empty-state"
import { ScrollArea } from "@/components/ui/scroll-area"
import { StatusChip } from "@/components/ui/status-chip"
import { OnboardingHint } from "@/components/ui/tooltip"
import { resolveStage, type FunnelStage, needsVacancyText, scoreTone } from "@/features/jobs/funnel"
import { resolveSourceGroup } from "@/features/jobs/source"
import { SourceIcon } from "@/features/jobs/SourceIcon"
import { VacancyTextNeededMark } from "@/features/jobs/VacancyTextNeededMark"
import { useActiveContexts } from "@/features/chat/use-active-contexts"
import { useCopyDialog } from "@/features/chat/use-conversations"
import { clipChatListTitle, fmtChatWhen } from "./fmt-chat-when"

export type ChatSelection =
  | { kind: "empty" }
  | { kind: "new-vacancy" }
  | { kind: "new-context" }
  | { kind: "context"; noteId: number }
  | { kind: "vacancy"; vacancyId: string }

export type ChatListTab = "vacancies" | "contexts"

// eslint-disable-next-line react-refresh/only-export-components -- утилита рядом с сайдбаром
export { fmtChatWhen } from "./fmt-chat-when"

const DRAG_MIME = "application/x-chat-thread"
const VIRTUALIZE_THRESHOLD = 40

function funnelLabel(job: Job | undefined): FunnelStage | "Пропущено" {
  if (!job) return "Просмотр"
  if (job.skipped) return "Пропущено"
  return resolveStage(job.status)
}

function StageBadge({ stage }: { stage: string }) {
  return <span className="max-w-full truncate text-xs font-medium text-slate-700">{stage}</span>
}

const REMINDER_THRESHOLD_DAYS = 4

function silenceDays(iso?: string | null): number | null {
  if (!iso) return null
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return null
  return Math.floor((Date.now() - then) / 86_400_000)
}

function isFuture(iso?: string | null): boolean {
  if (!iso) return false
  const t = new Date(iso).getTime()
  return !Number.isNaN(t) && t > Date.now()
}

function NextStageBadge({ at }: { at?: string | null }) {
  const label = formatEventLabel(at)
  if (!label) return null
  return (
    <StatusChip tone="info" className="rounded px-1.5 py-0.5 text-xs leading-none">
      <CalendarClock className="size-3 shrink-0" strokeWidth={2} />
      {label}
    </StatusChip>
  )
}

function ReminderChip() {
  return (
    <span className="inline-flex items-center rounded border border-rose-200 bg-rose-50 px-1.5 py-0.5 text-xs font-medium leading-none text-rose-700">
      пора напомнить
    </span>
  )
}

function rowClass(active: boolean): string {
  return cn(
    "w-full min-w-0 overflow-hidden rounded-lg px-2 py-1.5 text-left text-sm transition-all duration-200",
    active ? "bg-slate-100 text-slate-900" : "text-slate-600 hover:bg-slate-50",
  )
}

const RAIL_BTN = "h-7 w-7 min-w-7 gap-0 px-0 has-[>svg]:px-0 shadow-none"

function ListTabToggle({
  value,
  onChange,
}: {
  value: ChatListTab
  onChange: (next: ChatListTab) => void
}) {
  const item = (tab: ChatListTab, icon: typeof Briefcase, label: string) => {
    const on = value === tab
    return (
      <button
        type="button"
        onClick={() => onChange(tab)}
        className={cn(
          "flex min-w-0 flex-1 items-center justify-center gap-1 rounded-lg py-1.5 text-sm font-medium transition-colors",
          on ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:bg-slate-200/60",
        )}
      >
        {icon === Briefcase ? (
          <Briefcase className="size-3.5 shrink-0" strokeWidth={2} />
        ) : (
          <Library className="size-3.5 shrink-0" strokeWidth={2} />
        )}
        <span className="truncate">{label}</span>
      </button>
    )
  }
  return (
    <div className="inline-flex min-w-0 flex-1 items-center gap-0.5 rounded-xl bg-slate-100 p-1">
      {item("vacancies", Briefcase, "Вакансии")}
      {item("contexts", Library, "Контексты")}
    </div>
  )
}

function ConversationRow({
  c,
  active,
  job,
  onSelect,
  onRequestDelete,
  onCopyDialog,
  onTogglePin,
  copyPending,
  style,
  measureRef,
  dataIndex,
}: {
  c: ConvThread
  active: boolean
  job: Job | undefined
  onSelect: () => void
  onRequestDelete: () => void
  onCopyDialog: () => void
  onTogglePin: () => void
  copyPending?: boolean
  style?: React.CSSProperties
  measureRef?: (node: HTMLLIElement | null) => void
  dataIndex?: number
}) {
  const sourceGroup = resolveSourceGroup(job?.source, c.vacancy_id)
  const title = conversationTitle(c)
  const companyLine = conversationListSubtitle(c)
  const stage = funnelLabel(job)
  const callScheduled = isFuture(c.next_stage_at)
  const isDead =
    c.status === "archived" || Boolean(job?.skipped) || resolveStage(job?.status) === "Отказ"
  const waitingDays =
    !isDead && c.last_hr_kind === "hr_out" && !callScheduled ? silenceDays(c.last_hr_at) : null
  const needsReminder = waitingDays != null && waitingDays >= REMINDER_THRESHOLD_DAYS
  const when = fmtChatWhen(c.last_message_at)
  return (
    <li ref={measureRef} data-index={dataIndex} className="flex min-w-0 flex-col gap-0.5" style={style}>
      <button
        type="button"
        draggable
        onDragStart={(e) => {
          e.dataTransfer.setData(DRAG_MIME, String(c.id))
          e.dataTransfer.effectAllowed = "move"
        }}
        onClick={onSelect}
        className={rowClass(active)}
      >
        <span className="flex min-w-0 items-start gap-2 overflow-hidden">
          <span className="mt-0.5 flex w-8 shrink-0 flex-col items-center gap-0.5">
            <SourceIcon group={sourceGroup} size={16} />
            {needsVacancyText(job) ? (
              <VacancyTextNeededMark size="sm" />
            ) : job?.overall_score != null ? (
              <span
                className={cn(
                  "text-sm font-semibold leading-none tabular-nums",
                  scoreTone(job.overall_score),
                )}
              >
                {job.overall_score}
              </span>
            ) : (
              <span className="text-sm font-semibold leading-none text-slate-300">—</span>
            )}
          </span>
          <span className="min-w-0 flex-1 space-y-0.5 overflow-hidden">
            <span className="grid w-full min-w-0 grid-cols-[minmax(0,1fr)_auto] items-baseline gap-1.5 overflow-hidden">
              <span className="min-w-0 truncate text-sm font-semibold" title={title}>
                {clipChatListTitle(title)}
              </span>
              <span className="whitespace-nowrap text-xs font-medium tabular-nums text-slate-500">
                {when || "\u00a0"}
              </span>
            </span>
            {companyLine ? (
              <span className="block truncate text-xs text-slate-400" title={companyLine}>
                {companyLine}
              </span>
            ) : null}
            <span className="flex min-w-0 flex-wrap items-center gap-1">
              <StageBadge stage={stage} />
              {!isDead ? <NextStageBadge at={c.next_stage_at} /> : null}
              {needsReminder ? <ReminderChip /> : null}
            </span>
          </span>
        </span>
      </button>
      <div className="flex min-w-0 items-center gap-2 overflow-hidden px-2">
        <span className="w-8 shrink-0" aria-hidden />
        <div className="flex min-w-0 flex-1 items-center justify-between gap-2 overflow-hidden">
          <div className="flex min-w-0 flex-nowrap items-center gap-1">
            <Button
              type="button"
              size="sm"
              variant="outline"
              title={c.pinned ? "Открепить" : "Закрепить"}
              aria-label={c.pinned ? "Открепить" : "Закрепить"}
              className={cn(
                RAIL_BTN,
                c.pinned
                  ? "border-amber-200 bg-amber-50 text-amber-800 hover:bg-amber-100"
                  : "border-slate-200 bg-slate-50 text-slate-600 hover:bg-slate-100",
              )}
              onClick={(e) => {
                e.stopPropagation()
                onTogglePin()
              }}
            >
              <Pin className="size-3.5" strokeWidth={2} fill={c.pinned ? "currentColor" : "none"} />
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              title="Копировать диалог с HR"
              aria-label="Копировать"
              disabled={copyPending}
              className={cn(
                RAIL_BTN,
                "border-slate-200 bg-slate-50 text-slate-700 hover:bg-slate-100",
              )}
              onClick={(e) => {
                e.stopPropagation()
                onCopyDialog()
              }}
            >
              {copyPending ? (
                <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />
              ) : (
                <Copy className="size-3.5" strokeWidth={2} />
              )}
            </Button>
          </div>
          <Button
            type="button"
            size="sm"
            variant="outline"
            title="Удалить разговор"
            aria-label="Удалить разговор"
            className={cn(
              RAIL_BTN,
              "shrink-0 border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100",
            )}
            onClick={(e) => {
              e.stopPropagation()
              onRequestDelete()
            }}
          >
            <Trash2 className="size-3.5" strokeWidth={2} />
          </Button>
        </div>
      </div>
    </li>
  )
}

export function ChatsSidebar({
  selection,
  contexts,
  contextsLoading,
  conversations,
  conversationsError,
  onRetryConversations,
  jobsByVacancyId,
  archiveMode,
  onToggleArchiveMode,
  onArchiveConversation,
  onRestoreConversation,
  onNewVacancy,
  onNewContext,
  onSelectContext,
  onDeleteContext,
  onSelectVacancy,
  onDeleteVacancy,
  onTogglePinVacancy,
  className,
}: {
  selection: ChatSelection
  contexts: Note[]
  contextsLoading?: boolean
  conversations: ConvThread[]
  conversationsError?: boolean
  onRetryConversations: () => void
  jobsByVacancyId: Map<string, Job>
  archiveMode: boolean
  onToggleArchiveMode: () => void
  onArchiveConversation: (threadId: number) => void
  onRestoreConversation: (threadId: number) => void
  onNewVacancy: () => void
  onNewContext: () => void
  onSelectContext: (noteId: number) => void
  onDeleteContext: (noteId: number) => void
  onSelectVacancy: (vacancyId: string) => void
  onDeleteVacancy: (threadId: number) => void
  onTogglePinVacancy: (threadId: number, pinned: boolean) => void
  /** Visibility/layout from ChatPage — on mobile the list must not stay `hidden md:flex`. */
  className?: string
}) {
  const [dragOverFooter, setDragOverFooter] = useState(false)
  const [listCollapsed, setListCollapsed] = usePersistedBoolean("copilot.chat-list.collapsed")
  const [listTab, setListTab] = usePersistedString<ChatListTab>(
    "copilot.chat-list.tab",
    "vacancies",
  )
  const [pendingDelete, setPendingDelete] = useState<
    { kind: "context"; id: number } | { kind: "vacancy"; id: number } | null
  >(null)
  const { isActive: isContextActive, toggle: toggleContext } = useActiveContexts()

  // На узком экране icon-rail бесполезен — всегда полный список (Safari/iPhone).
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return
    const mq = window.matchMedia("(max-width: 767px)")
    const expandOnMobile = () => {
      if (mq.matches) setListCollapsed(false)
    }
    expandOnMobile()
    mq.addEventListener("change", expandOnMobile)
    return () => mq.removeEventListener("change", expandOnMobile)
  }, [setListCollapsed])
  const copyDialog = useCopyDialog()
  const { shouldShow, dismissHint } = useOnboardingHints()
  const showTelegramHint = shouldShow(ONBOARDING_HINT_IDS.chatTelegramPaste)
  const dismissTelegramHint = () => dismissHint(ONBOARDING_HINT_IDS.chatTelegramPaste)
  const telegramHintContent =
    "HR написал в Telegram? Создайте «Новую вакансию» и вставьте переписку целиком — можно со старыми сообщениями для контекста."

  useEffect(() => {
    if (selection.kind === "context" || selection.kind === "new-context") {
      setListTab("contexts")
    } else if (selection.kind === "vacancy" || selection.kind === "new-vacancy") {
      setListTab("vacancies")
    }
  }, [selection.kind, setListTab])

  const showVacancies = listTab === "vacancies"
  const showArchive = showVacancies
  const sortedConversations = useMemo(() => {
    const ms = (t: ConvThread) =>
      t.last_message_at ? new Date(t.last_message_at).getTime() : -Infinity
    return [...conversations].sort((a, b) => Number(b.pinned) - Number(a.pinned) || ms(b) - ms(a))
  }, [conversations])

  const viewportRef = useRef<HTMLDivElement | null>(null)
  const listTopRef = useRef<HTMLUListElement | null>(null)
  const [scrollMargin, setScrollMargin] = useState(0)
  useLayoutEffect(() => {
    const container = viewportRef.current
    const marker = listTopRef.current
    if (!container || !marker) return
    setScrollMargin(marker.getBoundingClientRect().top - container.getBoundingClientRect().top)
  }, [
    archiveMode,
    contextsLoading,
    contexts.length,
    conversationsError,
    sortedConversations.length,
    listTab,
  ])
  // eslint-disable-next-line react-hooks/incompatible-library
  const rowVirtualizer = useVirtualizer({
    count: sortedConversations.length,
    getScrollElement: () => viewportRef.current,
    estimateSize: () => 84,
    overscan: 8,
    scrollMargin,
    getItemKey: (index) => sortedConversations[index]!.id,
  })

  function handleFooterDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragOverFooter(false)
    const raw = e.dataTransfer.getData(DRAG_MIME)
    const threadId = Number(raw)
    if (threadId <= 0) return
    if (archiveMode) onRestoreConversation(threadId)
    else onArchiveConversation(threadId)
  }

  const footerLabel = archiveMode ? "Активные" : "Архив"
  const FooterIcon = archiveMode ? Inbox : Archive
  const footerBtnClass = archiveMode
    ? cn(
        "border-sky-200 bg-sky-50/80 text-sky-700 hover:bg-sky-100/90",
        "ring-2 ring-sky-200 ring-offset-1",
        dragOverFooter && "bg-sky-100 ring-2 ring-sky-300",
      )
    : cn(
        "border-rose-100 bg-rose-50/80 text-rose-700 hover:bg-rose-100/90",
        dragOverFooter && "bg-rose-100 ring-2 ring-rose-300",
      )
  const footerDropHint = archiveMode
    ? "Перетащите сюда, чтобы вернуть в активные"
    : "Перетащите сюда, чтобы архивировать"

  const newVacancyBtn = (
    <OnboardingHint
      open={showTelegramHint}
      onDismiss={dismissTelegramHint}
      side="right"
      align="start"
      content={telegramHintContent}
    >
      <Button
        type="button"
        size="sm"
        id="screen-start-chat"
        className="h-8 w-full min-w-0 justify-start gap-1.5 px-2"
        onClick={onNewVacancy}
      >
        <Plus className="size-3.5 shrink-0" strokeWidth={2} />
        <span className="truncate">Новая вакансия</span>
      </Button>
    </OnboardingHint>
  )
  const newContextBtn = (
    <Button
      type="button"
      size="sm"
      className="h-8 w-full min-w-0 justify-start gap-1.5 px-2"
      onClick={onNewContext}
    >
      <Plus className="size-3.5 shrink-0" strokeWidth={2} />
      <span className="truncate">Новый контекст</span>
    </Button>
  )

  const vacancyList = conversationsError ? (
    <div className="px-1">
      <ErrorState
        compact
        icon={AlertTriangle}
        title="Диалоги не загрузились"
        note="Не удалось загрузить диалоги."
        action={{ label: "Повторить", onClick: onRetryConversations }}
      />
    </div>
  ) : conversations.length === 0 ? (
    <p className="px-2 py-1.5 text-xs text-slate-400">
      {archiveMode ? "Архив пуст" : "Разговоров пока нет"}
    </p>
  ) : sortedConversations.length <= VIRTUALIZE_THRESHOLD ? (
    <ul ref={listTopRef} className="min-w-0 space-y-2 pb-2">
      {sortedConversations.map((c) => (
        <ConversationRow
          key={c.id}
          c={c}
          active={selection.kind === "vacancy" && selection.vacancyId === c.vacancy_id}
          job={jobsByVacancyId.get(c.vacancy_id)}
          onSelect={() => onSelectVacancy(c.vacancy_id)}
          onRequestDelete={() => setPendingDelete({ kind: "vacancy", id: c.id })}
          onCopyDialog={() =>
            copyDialog.mutate({ vacancyId: c.vacancy_id, contactName: c.contact_name })
          }
          onTogglePin={() => onTogglePinVacancy(c.id, !c.pinned)}
          copyPending={copyDialog.isPending && copyDialog.variables?.vacancyId === c.vacancy_id}
        />
      ))}
    </ul>
  ) : (
    <ul
      ref={listTopRef}
      className="pb-2"
      style={{ position: "relative", height: rowVirtualizer.getTotalSize(), width: "100%" }}
    >
      {rowVirtualizer.getVirtualItems().map((row) => {
        const c = sortedConversations[row.index]!
        return (
          <ConversationRow
            key={row.key}
            c={c}
            active={selection.kind === "vacancy" && selection.vacancyId === c.vacancy_id}
            job={jobsByVacancyId.get(c.vacancy_id)}
            onSelect={() => onSelectVacancy(c.vacancy_id)}
            onRequestDelete={() => setPendingDelete({ kind: "vacancy", id: c.id })}
            onCopyDialog={() =>
              copyDialog.mutate({ vacancyId: c.vacancy_id, contactName: c.contact_name })
            }
            onTogglePin={() => onTogglePinVacancy(c.id, !c.pinned)}
            copyPending={copyDialog.isPending && copyDialog.variables?.vacancyId === c.vacancy_id}
            measureRef={rowVirtualizer.measureElement}
            dataIndex={row.index}
            style={{
              position: "absolute",
              top: 0,
              left: 0,
              width: "100%",
              paddingBottom: 2,
              transform: `translateY(${row.start - scrollMargin}px)`,
            }}
          />
        )
      })}
    </ul>
  )

  const contextList = contextsLoading ? (
    <p className="px-2 py-1.5 text-xs text-slate-400">Загрузка…</p>
  ) : contexts.length === 0 ? (
    <p className="px-2 py-1.5 text-xs text-slate-400">Контекстов пока нет</p>
  ) : (
    <ul className="space-y-2 pb-2">
      {contexts.map((n) => {
        if (n.id == null) return null
        const active = selection.kind === "context" && selection.noteId === n.id
        const contextOn = isContextActive(n.id)
        const ctxTitle = n.title.trim() || "Без названия"
        const ctxWhen = fmtChatWhen(n.updated_at ?? n.created_at)
        return (
          <li key={n.id} className="flex min-w-0 flex-col gap-0.5">
            <button
              type="button"
              onClick={() => onSelectContext(n.id!)}
              className={cn(
                rowClass(active),
                contextOn && "bg-emerald-50/60 ring-1 ring-inset ring-emerald-200",
              )}
            >
              <span className="flex min-w-0 items-baseline gap-2 overflow-hidden">
                <span className="min-w-0 flex-1 truncate font-medium" title={ctxTitle}>
                  {ctxTitle}
                </span>
                <span className="shrink-0 text-xs font-medium tabular-nums text-slate-500">
                  {ctxWhen || "\u00a0"}
                </span>
              </span>
            </button>
            <div className="flex min-w-0 items-center justify-between gap-2 overflow-hidden pl-2">
              <Button
                type="button"
                size="sm"
                variant="outline"
                title={contextOn ? "Выключить контекст" : "Включить контекст"}
                aria-label={contextOn ? "Выкл" : "Вкл"}
                className={cn(
                  RAIL_BTN,
                  contextOn
                    ? "border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100"
                    : "border-slate-200 bg-slate-50 text-slate-600 hover:bg-slate-100",
                )}
                onClick={(e) => {
                  e.stopPropagation()
                  toggleContext(n.id!)
                }}
              >
                <Power className="size-3.5" strokeWidth={2} />
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                title="Удалить контекст"
                aria-label="Удалить контекст"
                className={cn(
                  RAIL_BTN,
                  "shrink-0 border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100",
                )}
                onClick={(e) => {
                  e.stopPropagation()
                  setPendingDelete({ kind: "context", id: n.id! })
                }}
              >
                <Trash2 className="size-3.5" strokeWidth={2} />
              </Button>
            </div>
          </li>
        )
      })}
    </ul>
  )

  const confirm = (
    <ConfirmDialog
      open={pendingDelete != null}
      onOpenChange={(open) => {
        if (!open) setPendingDelete(null)
      }}
      title={pendingDelete?.kind === "context" ? "Удалить контекст?" : "Удалить разговор?"}
      description={
        pendingDelete?.kind === "context"
          ? "Диалог будет потерян."
          : "Разговор и все его сообщения будут удалены."
      }
      onConfirm={() => {
        if (pendingDelete?.kind === "context") onDeleteContext(pendingDelete.id)
        else if (pendingDelete?.kind === "vacancy") onDeleteVacancy(pendingDelete.id)
        setPendingDelete(null)
      }}
    />
  )

  if (listCollapsed) {
    return (
      <aside
        className={cn(
          "hidden h-full min-h-0 w-10 shrink-0 flex-col overflow-hidden border-r bg-background md:flex",
          className,
        )}
      >
        <div className="flex shrink-0 justify-center border-b py-2">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-8 text-slate-500"
            title="Развернуть список диалогов"
            onClick={() => setListCollapsed(false)}
          >
            <PanelLeftOpen className="size-4" strokeWidth={2} />
          </Button>
        </div>
        <div className="flex flex-1 flex-col items-center gap-1 py-2">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className={cn(
              "size-8",
              showVacancies ? "bg-white text-slate-900 shadow-sm" : "text-slate-500",
            )}
            title="Вакансии"
            onClick={() => setListTab("vacancies")}
          >
            <Briefcase className="size-4" strokeWidth={2} />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className={cn(
              "size-8",
              !showVacancies ? "bg-white text-slate-900 shadow-sm" : "text-slate-500",
            )}
            title="Контексты"
            onClick={() => setListTab("contexts")}
          >
            <Library className="size-4" strokeWidth={2} />
          </Button>
          {showVacancies ? (
            <OnboardingHint
              open={showTelegramHint}
              onDismiss={dismissTelegramHint}
              side="right"
              align="center"
              content={telegramHintContent}
            >
              <Button
                type="button"
                variant="ghost"
                size="icon"
                id="screen-start-chat"
                className="size-8 text-slate-500"
                title="Новая вакансия"
                onClick={onNewVacancy}
              >
                <Plus className="size-4" strokeWidth={2} />
              </Button>
            </OnboardingHint>
          ) : (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="size-8 text-slate-500"
              title="Новый контекст"
              onClick={onNewContext}
            >
              <Plus className="size-4" strokeWidth={2} />
            </Button>
          )}
        </div>
        {showArchive ? (
          <div className="shrink-0 border-t p-1">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className={cn(
                "size-8",
                archiveMode ? "bg-sky-50 text-sky-700 ring-1 ring-sky-200" : "text-rose-600",
              )}
              title={footerLabel}
              onClick={onToggleArchiveMode}
            >
              <FooterIcon className="size-4" strokeWidth={2} />
            </Button>
          </div>
        ) : null}
        {confirm}
      </aside>
    )
  }

  return (
    <aside
      className={cn(
        "flex h-full min-h-0 w-full shrink-0 flex-col overflow-hidden border-r bg-background md:w-[17.6rem]",
        className,
      )}
    >
      <div className="flex shrink-0 items-center gap-1 border-b px-2 py-2">
        <ListTabToggle value={listTab} onChange={setListTab} />
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="size-7 shrink-0 text-slate-500"
          title="Свернуть список диалогов"
          onClick={() => setListCollapsed(true)}
        >
          <PanelLeftClose className="size-3.5" strokeWidth={2} />
        </Button>
      </div>

      {(!showVacancies || !archiveMode) && (
        <div className="shrink-0 border-b px-2 py-2">
          {showVacancies ? newVacancyBtn : newContextBtn}
        </div>
      )}

      <ScrollArea
        className="min-h-0 min-w-0 flex-1 overflow-x-hidden"
        viewportClassName="overflow-x-hidden px-2 [&>div]:!block [&>div]:!min-w-0 [&>div]:!max-w-full"
        viewportRef={viewportRef}
      >
        {showVacancies ? vacancyList : contextList}
      </ScrollArea>

      {showArchive ? (
        <div className="shrink-0 border-t p-3">
          <button
            type="button"
            title={footerDropHint}
            onClick={onToggleArchiveMode}
            onDragOver={(e) => {
              e.preventDefault()
              setDragOverFooter(true)
            }}
            onDragLeave={() => setDragOverFooter(false)}
            onDrop={handleFooterDrop}
            className={cn(
              "flex w-full min-w-0 items-center justify-center gap-2 rounded-md border px-2 py-2 text-sm font-medium transition-colors",
              footerBtnClass,
            )}
          >
            <FooterIcon className="size-4 shrink-0" strokeWidth={2} />
            <span className="truncate">{footerLabel}</span>
          </button>
        </div>
      ) : null}

      {confirm}
    </aside>
  )
}

export function ChatsEmptyPane() {
  return (
    <div className="flex min-h-0 flex-1 flex-col items-center justify-center bg-background">
      <EmptyState
        icon={MessageSquare}
        title="Выберите диалог"
        note="Откройте вакансию или контекст в списке — или создайте новый."
      />
    </div>
  )
}
