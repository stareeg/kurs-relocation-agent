/**
 * Агент — главный экран: диалоги слева (сервер, A-3), лента и композер справа.
 *
 * Два режима композера: «Агент» (по умолчанию) — сообщение уходит фоновым запуском графа
 * с планом, инструментами и подтверждением действий, ход работы виден в блоке запуска;
 * «Чат» — обычный стрим ответа модели с выбором тира и вложениями. Переписка с HR живёт
 * в дровере вакансии.
 *
 * Лента держится внизу, пока пользователь сам не отмотал вверх: ResizeObserver на
 * содержимом ловит и новые сообщения, и токены стрима, и события запуска.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { ArrowDown, Copy, Loader2, Menu, Paperclip, Send } from "lucide-react"
import { toast } from "sonner"
import { cn } from "@/lib/utils"
import { linkify } from "@/components/chat/linkify"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { SegmentedControl } from "@/components/ui/segmented-control"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { MarkdownView } from "@/components/markdown-view"
import { AttachmentChips } from "@/components/chat/attachments/AttachmentChips"
import { AttachmentGrid } from "@/components/chat/attachments/AttachmentGrid"
import { ImageCropper } from "@/components/chat/attachments/ImageCropper"
import {
  ACCEPTED_ATTACHMENT_MIME,
  isImageFile,
  usePasteImages,
} from "@/components/chat/attachments/use-paste-images"
import {
  useAttachmentUpload,
  type PendingAttachment,
} from "@/components/chat/attachments/use-attachment-upload"
import type { AttachmentOut } from "@/api/attachments"
import {
  useAgentConversation,
  type AgentChatMessage,
  type AgentChatTier,
} from "./use-agent-conversation"
import { useAgentSessions } from "./use-agent-sessions"
import { useAgentRuns, type RunView } from "./use-agent-runs"
import { AgentRunView, type VacancyRef } from "./AgentRunView"
import { useJobs } from "@/features/jobs/use-jobs"
import { JobDetailDrawer } from "@/features/jobs/JobDetailDrawer"
import type { Job } from "@/api/jobs"
import { AgentChatSessions } from "./AgentChatSessions"
import { appendAgentChatMessage, createAgentChat } from "@/api/agent"

const TIER_STORAGE_KEY = "copilot.agent-chat.tier"
const MODE_STORAGE_KEY = "copilot.agent-chat.mode"
const MIGRATED_KEY = "copilot.agent-chat.migrated-v2"

type ComposerMode = "agent" | "chat"

const MODE_OPTIONS = [
  { value: "agent", label: "Агент", title: "План, инструменты продукта, подтверждение действий" },
  { value: "chat", label: "Чат", title: "Обычный ответ модели без инструментов" },
] as const

const TIER_OPTIONS: { value: AgentChatTier; label: string }[] = [
  { value: "", label: "Авто" },
  { value: "advanced", label: "Умная" },
  { value: "basic", label: "Быстрая" },
]

// Цели для быстрого старта: обычный сценарий, сценарий с ошибкой инструмента
// (вакансии с таким id нет — агент должен заметить ошибку и найти замену) и действие
// с подтверждением человеком.
const EXAMPLE_GOALS = [
  "Найди удалённые вакансии backend с оплатой в валюте и оцени самую подходящую",
  "Проверь условия найма вакансии no-such-job; если её нет в базе, найди похожую и оцени",
  "Подбери лучшую вакансию под мой профиль, напиши короткое сопроводительное письмо и поставь отклик",
]

function loadTier(): AgentChatTier {
  try {
    const raw = localStorage.getItem(TIER_STORAGE_KEY)
    return raw === "advanced" || raw === "basic" ? raw : ""
  } catch {
    return ""
  }
}

function loadMode(): ComposerMode {
  try {
    return localStorage.getItem(MODE_STORAGE_KEY) === "chat" ? "chat" : "agent"
  } catch {
    return "agent"
  }
}

function store(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* ignore */
  }
}

function fmtTime(ms: number): string {
  const d = new Date(ms)
  const p = (n: number) => String(n).padStart(2, "0")
  const today = new Date()
  const sameDay =
    d.getFullYear() === today.getFullYear() &&
    d.getMonth() === today.getMonth() &&
    d.getDate() === today.getDate()
  const hm = `${p(d.getHours())}:${p(d.getMinutes())}`
  return sameDay ? hm : `${p(d.getDate())}.${p(d.getMonth() + 1)} ${hm}`
}

function copyText(text: string) {
  navigator.clipboard.writeText(text).then(
    () => toast.success("Скопировано"),
    () => toast.error("Не удалось скопировать"),
  )
}

function UserMessage({
  body,
  time,
  attachments = [],
}: {
  body: string
  time?: string
  attachments?: AttachmentOut[]
}) {
  return (
    <div className="flex flex-col items-end">
      <div className="max-w-[75%] rounded-2xl rounded-br-md bg-slate-100 px-4 py-2.5">
        {attachments.length > 0 ? <AttachmentGrid attachments={attachments} className="mb-1" /> : null}
        {body ? (
          <p className="whitespace-pre-wrap break-words text-base leading-relaxed text-foreground">
            {linkify(body)}
          </p>
        ) : null}
      </div>
      {time ? <span className="mt-1 text-xs text-muted-foreground tabular-nums">{time}</span> : null}
    </div>
  )
}

function AssistantMessage({
  body,
  time,
  error,
}: {
  body: string
  time?: string
  error?: boolean
}) {
  return (
    <div className="group">
      <div className={cn(error && "rounded-lg bg-status-bad-soft px-3 py-2 text-status-bad-fg")}>
        <MarkdownView markdown={body} chat />
      </div>
      <div className="mt-1.5 flex items-center gap-2 text-xs text-muted-foreground">
        {time ? <span className="tabular-nums">{time}</span> : null}
        <button
          type="button"
          className="flex items-center gap-1 opacity-0 transition-opacity hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100"
          onClick={() => copyText(body)}
        >
          <Copy className="size-3.5" strokeWidth={2} />
          Копировать
        </button>
      </div>
    </div>
  )
}

type ThreadItem =
  | { kind: "message"; at: number; message: AgentChatMessage }
  | { kind: "run"; at: number; view: RunView }

export function AgentChat() {
  const sessions = useAgentSessions()
  const refreshSessions = sessions.refresh
  const onUserPersisted = useCallback(() => void refreshSessions(), [refreshSessions])
  const conv = useAgentConversation(
    sessions.activeId,
    async () => {
      if (sessions.activeId != null) return sessions.activeId
      const created = await sessions.create()
      return created?.id ?? null
    },
    onUserPersisted,
  )
  const runs = useAgentRuns(sessions.activeId)
  const jobsQuery = useJobs()
  const jobs = jobsQuery.data
  const [openJob, setOpenJob] = useState<Job | null>(null)
  const [sessionsOpen, setSessionsOpen] = useState(false)

  // Вакансии аккаунта по id: название вместо id в карточке подтверждения и чипы
  // «Вакансии в запуске», клик открывает дровер вакансии прямо поверх чата.
  const vacancies = useMemo(() => {
    const map = new Map<string, VacancyRef>()
    for (const job of jobs ?? []) {
      if (job?.vacancy_id && job.title) map.set(job.vacancy_id, { title: job.title, company: job.company ?? null })
    }
    return map
  }, [jobs])

  function openVacancy(vacancyId: string) {
    const job = (jobs ?? []).find((j) => j?.vacancy_id === vacancyId)
    if (job) setOpenJob(job)
    else toast.error("Вакансии нет в базе аккаунта")
  }
  const [text, setText] = useState("")
  const [tier, setTier] = useState<AgentChatTier>(loadTier)
  const [mode, setMode] = useState<ComposerMode>(loadMode)
  const agentMode = mode === "agent"
  const attachments = useAttachmentUpload()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const composerRef = useRef<HTMLDivElement>(null)
  const [cropTarget, setCropTarget] = useState<{ key: string; attachment: AttachmentOut } | null>(
    null,
  )
  const paste = usePasteImages({
    onFiles: attachments.addFiles,
    queuedCount: attachments.items.length,
    disabled: attachments.isUploading,
  })

  // Разовый перенос старого localStorage-диалога в серверную сессию (A-3): один раз,
  // только если серверных сессий ещё нет и локальная история непуста.
  useEffect(() => {
    if (sessions.loading || sessions.sessions.length > 0) return
    let migrated: boolean
    try {
      migrated = localStorage.getItem(MIGRATED_KEY) === "1"
    } catch {
      migrated = false
    }
    if (migrated) return
    let legacy: AgentChatMessage[]
    try {
      const raw = localStorage.getItem("copilot.agent-chat.messages")
      legacy = raw ? (JSON.parse(raw) as AgentChatMessage[]).slice(-40) : []
    } catch {
      legacy = []
    }
    store(MIGRATED_KEY, "1")
    if (legacy.length === 0) return
    void (async () => {
      try {
        const session = await createAgentChat("Диалог из этого браузера")
        for (const m of legacy) {
          if (!m.content.trim()) continue
          await appendAgentChatMessage(session.id, m.role, m.content.trim())
        }
        await sessions.refresh()
        toast.success("Старая история чата перенесена на сервер")
      } catch {
        /* нет PG — история останется локальной копией */
      }
    })()
  }, [sessions])

  const hasMessages = conv.messages.length > 0 || conv.pending != null || runs.runs.length > 0

  const thread = useMemo<ThreadItem[]>(() => {
    const items: ThreadItem[] = [
      ...conv.messages.map((m) => ({ kind: "message", at: m.createdAt, message: m }) as ThreadItem),
      ...runs.runs.map((r) => ({ kind: "run", at: r.createdAtMs, view: r }) as ThreadItem),
    ]
    return items.sort((a, b) => a.at - b.at)
  }, [conv.messages, runs.runs])

  // Цель запуска уже видна репликой пользователя — в блоке запуска её не дублируем.
  const userTexts = useMemo(
    () => new Set(conv.messages.filter((m) => m.role === "user").map((m) => m.content.trim())),
    [conv.messages],
  )

  // ---------------------------------------------------------------- автоскролл
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const contentRef = useRef<HTMLDivElement | null>(null)
  const pinned = useRef(true)
  const [showDown, setShowDown] = useState(false)

  const scrollToBottom = useCallback((smooth = false) => {
    const el = scrollRef.current
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" })
  }, [])

  useEffect(() => {
    const content = contentRef.current
    if (!content) return
    const ro = new ResizeObserver(() => {
      if (pinned.current) scrollToBottom()
    })
    ro.observe(content)
    return () => ro.disconnect()
  }, [scrollToBottom])

  // Смена диалога — снова прилипаем к низу.
  useEffect(() => {
    pinned.current = true
    // eslint-disable-next-line react-hooks/set-state-in-effect -- сброс UI-флага при смене внешнего источника (диалог)
    setShowDown(false)
    scrollToBottom()
  }, [sessions.activeId, scrollToBottom])

  function onScroll() {
    const el = scrollRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80
    pinned.current = atBottom
    setShowDown(!atBottom)
  }

  const readyAttachments = useMemo(
    () =>
      attachments.items
        .filter((i): i is PendingAttachment & { attachment: AttachmentOut } => i.attachment != null)
        .map((i) => i.attachment),
    [attachments.items],
  )

  const agentBusy = agentMode && runs.hasActive
  const busy = conv.isRunning || agentBusy
  const canSend =
    !busy && (text.trim().length > 0 || (!agentMode && attachments.attachmentIds.length > 0))

  function send() {
    const t = text.trim()
    if (!canSend) return
    setText("")
    pinned.current = true
    if (agentMode) {
      void sendAgentRun(t)
      return
    }
    conv.askLlm(t, readyAttachments, tier)
    attachments.clear()
  }

  /** Режим «Агент»: цель → фоновый запуск (бэкенд сам пишет события в БД и SSE). */
  function retryRun(goal: string) {
    if (conv.isRunning || runs.hasActive) return
    pinned.current = true
    void sendAgentRun(goal)
  }

  async function sendAgentRun(goal: string) {
    const sid = sessions.activeId ?? (await sessions.create())?.id ?? null
    if (sid == null) {
      toast.error("Не удалось создать диалог — проверьте доступ к серверу")
      return
    }
    await conv.persistUser(goal, sid)
    const ok = await runs.start(goal, sid)
    if (!ok) toast.error("Запуск не стартовал — проверьте доступ к серверу")
  }

  function pickExample(goal: string) {
    setMode("agent")
    store(MODE_STORAGE_KEY, "agent")
    setText(goal)
    requestAnimationFrame(() => composerRef.current?.querySelector("textarea")?.focus())
  }

  return (
    <div className="flex min-h-0 flex-1 bg-background">
      <AgentChatSessions
        sessions={sessions}
        activeId={sessions.activeId}
        onSelect={(id) => sessions.setActiveId(id)}
        onCreate={() => sessions.setActiveId(null)}
        onDelete={(id) => void sessions.remove(id)}
      />

      {sessionsOpen ? (
        <div className="fixed inset-0 z-40 flex md:hidden">
          <AgentChatSessions
            className="flex h-full shadow-xl"
            sessions={sessions}
            activeId={sessions.activeId}
            onSelect={(id) => {
              sessions.setActiveId(id)
              setSessionsOpen(false)
            }}
            onCreate={() => {
              sessions.setActiveId(null)
              setSessionsOpen(false)
            }}
            onDelete={(id) => void sessions.remove(id)}
          />
          <button
            type="button"
            aria-label="Закрыть список диалогов"
            className="flex-1 bg-black/30"
            onClick={() => setSessionsOpen(false)}
          />
        </div>
      ) : null}

      <div className="relative flex min-h-0 min-w-0 flex-1 flex-col">
        <div className="flex shrink-0 items-center gap-2 border-b border-border px-4 py-2 md:hidden">
          <Button
            size="sm"
            variant="ghost"
            className="gap-1.5"
            onClick={() => setSessionsOpen(true)}
          >
            <Menu className="size-4" strokeWidth={2} />
            Диалоги
          </Button>
          <span className="min-w-0 truncate text-sm text-muted-foreground">
            {sessions.sessions.find((x) => x.id === sessions.activeId)?.title ?? "Новый диалог"}
          </span>
        </div>
        <div ref={scrollRef} onScroll={onScroll} className="min-h-0 flex-1 overflow-y-auto">
          <div ref={contentRef} className="mx-auto w-full max-w-5xl px-6 py-6">
            {hasMessages ? (
              <div className="space-y-6">
                {thread.map((item) =>
                  item.kind === "message" ? (
                    item.message.role === "user" ? (
                      <UserMessage
                        key={item.message.id}
                        body={item.message.content}
                        time={fmtTime(item.message.createdAt)}
                        attachments={item.message.attachments}
                      />
                    ) : (
                      <AssistantMessage
                        key={item.message.id}
                        body={item.message.content}
                        time={fmtTime(item.message.createdAt)}
                        error={item.message.error}
                      />
                    )
                  ) : (
                    <AgentRunView
                      key={`run-${item.view.run.id}`}
                      view={item.view}
                      showGoal={!userTexts.has(item.view.run.goal.trim())}
                      vacancies={vacancies}
                      onOpenVacancy={openVacancy}
                      onRetry={retryRun}
                      retryDisabled={conv.isRunning || runs.hasActive}
                      onApprove={(runId, approved) => {
                        pinned.current = true
                        void runs.approve(runId, approved).catch(() =>
                          toast.error("Не удалось передать решение"),
                        )
                      }}
                    />
                  ),
                )}
                {conv.pending ? (
                  <>
                    <UserMessage
                      body={conv.pending.question}
                      time={fmtTime(conv.pending.askedAt)}
                      attachments={conv.pending.attachments}
                    />
                    {conv.pending.answer ? (
                      <AssistantMessage body={conv.pending.answer} error={conv.pending.error} />
                    ) : conv.isRunning ? (
                      <div className="flex items-center gap-2 text-sm text-muted-foreground">
                        <Loader2 className="size-4 animate-spin" strokeWidth={2} />
                        Отвечаю…
                      </div>
                    ) : null}
                  </>
                ) : null}
              </div>
            ) : (
              <div className="mx-auto flex min-h-[50vh] max-w-2xl flex-col justify-center py-10">
                <h1 className="text-xl font-semibold tracking-tight text-foreground">
                  Агент по валютной удалёнке
                </h1>
                <p className="mt-2 text-base leading-relaxed text-muted-foreground">
                  Составляет план и выполняет его инструментами продукта: профиль, база вакансий,
                  условия найма, оценка, сопроводительное письмо. Отклик ставит в очередь только
                  после вашего подтверждения.
                </p>
                <div className="mt-6 text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  Попробуйте
                </div>
                <div className="mt-2 space-y-2">
                  {EXAMPLE_GOALS.map((goal) => (
                    <button
                      key={goal}
                      type="button"
                      className="block w-full rounded-lg border border-border bg-card px-4 py-3 text-left text-sm text-foreground transition-colors hover:border-slate-300 hover:bg-slate-50"
                      onClick={() => pickExample(goal)}
                    >
                      {goal}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        {showDown ? (
          <Button
            size="sm"
            variant="outline"
            className="absolute bottom-36 left-1/2 -translate-x-1/2 gap-1.5 rounded-full bg-card shadow-md"
            onClick={() => {
              pinned.current = true
              setShowDown(false)
              scrollToBottom(true)
            }}
          >
            <ArrowDown className="size-4" strokeWidth={2} />
            Вниз
          </Button>
        ) : null}

        <div className="shrink-0 bg-background">
          <div className="mx-auto w-full max-w-5xl px-6 pb-5 pt-2">
            <div
              ref={composerRef}
              className={cn(
                "space-y-2 rounded-2xl border border-border bg-card p-3 shadow-sm transition-colors focus-within:border-slate-300",
                paste.isDraggingOver &&
                  "bg-sky-50 outline-dashed outline-2 -outline-offset-2 outline-sky-300",
              )}
              onPaste={agentMode ? undefined : paste.onPaste}
              onDragEnter={agentMode ? undefined : paste.onDragEnter}
              onDragOver={agentMode ? undefined : paste.onDragOver}
              onDragLeave={agentMode ? undefined : paste.onDragLeave}
              onDrop={agentMode ? undefined : paste.onDrop}
            >
              {!agentMode && attachments.items.length > 0 ? (
                <AttachmentChips
                  items={attachments.items}
                  onRemove={attachments.remove}
                  onRetry={attachments.retry}
                  onOpen={(item) => {
                    if (!item.attachment || !isImageFile(item.file)) return
                    setCropTarget({ key: item.key, attachment: item.attachment })
                  }}
                />
              ) : null}
              <Textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder={
                  agentBusy
                    ? "Агент работает — дождитесь итога или подтвердите действие"
                    : agentMode
                      ? "Опишите задачу для агента"
                      : "Спросите модель"
                }
                className="max-h-48 min-h-12 resize-none border-0 bg-transparent p-1 text-base shadow-none focus-visible:ring-0 md:text-base"
                autoFocus
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                    e.preventDefault()
                    send()
                  }
                }}
              />
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <SegmentedControl
                    size="sm"
                    ariaLabel="Режим"
                    options={MODE_OPTIONS}
                    value={mode}
                    onChange={(next) => {
                      setMode(next)
                      store(MODE_STORAGE_KEY, next)
                    }}
                  />
                  {!agentMode ? (
                    <>
                      <Select
                        value={tier}
                        onValueChange={(v) => {
                          const next = v as AgentChatTier
                          setTier(next)
                          store(TIER_STORAGE_KEY, next)
                        }}
                      >
                        <SelectTrigger className="h-8 w-[110px] bg-transparent" aria-label="Модель">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {TIER_OPTIONS.map((o) => (
                            <SelectItem key={o.value} value={o.value}>
                              {o.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
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
                      <Button
                        size="icon"
                        variant="ghost"
                        type="button"
                        className="size-8 text-muted-foreground"
                        aria-label="Приложить файл"
                        disabled={conv.isRunning}
                        onClick={() => fileInputRef.current?.click()}
                      >
                        <Paperclip className="size-4" strokeWidth={2} />
                      </Button>
                    </>
                  ) : null}
                </div>
                <div className="flex items-center gap-3">
                  <span className="hidden text-xs text-muted-foreground md:inline">
                    Enter — отправить, Shift+Enter — новая строка
                  </span>
                  <Button
                    size="icon"
                    type="button"
                    className="size-8"
                    aria-label="Отправить"
                    disabled={!canSend}
                    onClick={send}
                  >
                    {busy ? (
                      <Loader2 className="size-4 animate-spin" strokeWidth={2} />
                    ) : (
                      <Send className="size-4" strokeWidth={2} />
                    )}
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <JobDetailDrawer
          job={openJob}
          onOpenChange={(open) => {
            if (!open) setOpenJob(null)
          }}
        />

        {cropTarget ? (
          <ImageCropper
            attachment={cropTarget.attachment}
            onOpenChange={(open) => {
              if (!open) setCropTarget(null)
            }}
            onCropped={(attachment) => {
              attachments.replace(cropTarget.key, attachment)
              setCropTarget(null)
            }}
          />
        ) : null}
      </div>
    </div>
  )
}
