import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  approveAgentRun,
  cancelAgentRun,
  getAgentRun,
  listAgentRuns,
  replayAgentRunEvents,
  startAgentRun,
  streamAgentRunEvents,
  type AgentActionCard,
  type AgentApprovalEdits,
  type AgentEvent,
  type AgentRun,
  type AgentRunLimits,
  type AgentRunStatus,
  type AgentRunUsage,
} from "@/api/agent"
import { parseLimits, parseUsage } from "./run-usage"

// Запуски агента в главном чате (A-3): бэкенд живёт фоновой задачей, фронт читает
// события по SSE (догон + live) и умеет паузу/подтверждение. Восстановление экрана
// после перезагрузки — из БД (runs + replay), терминальные запуски не переподписываются.

export type RunPlanItem = {
  id: string
  title: string
  done_criteria?: string
  status?: string
}

// Изменение плана «было/стало» для экрана (A-4): строки вида «+ s3: …», «~ s2: a → b», «- s1: …».
export type PlanChange = {
  id: number
  action: string
  reason: string | null
  changes: string[]
}

export type RunView = {
  run: AgentRun
  createdAtMs: number
  status: AgentRunStatus
  answer: string | null
  error: string | null
  card: AgentActionCard | null
  plan: RunPlanItem[] | null
  note: string | null
  planChanges: PlanChange[]
  pendingRebuildReason: string | null
  events: AgentEvent[]
  live: boolean
  /** Последний снимок расхода (E-9): из событий, иначе из строки запуска. */
  usage?: AgentRunUsage | null
  /** Пределы запуска из `run_started` (E-9); у запусков до учёта токенов — нет. */
  limits?: AgentRunLimits | null
}

const TERMINAL: AgentRunStatus[] = ["done", "failed", "cancelled"]
// Панель «Ход работы» (U-5) считает вызовы и ошибки по всем событиям запуска: потолок —
// с запасом над лимитом replay (500), а не «последние N строк журнала», как раньше.
const VISIBLE_EVENT_CAP = 1000

function toEvent(e: { seq: number | null; data: Record<string, unknown> }): AgentEvent | null {
  const type = typeof e.data.type === "string" ? e.data.type : null
  if (type == null || e.seq == null) return null
  const payload = { ...e.data }
  delete payload.type
  return {
    id: e.seq,
    type,
    payload,
    node: typeof e.data.node === "string" ? (e.data.node as string) : null,
    duration_ms: typeof e.data.duration_ms === "number" ? e.data.duration_ms : null,
    created_at: null,
  }
}

/** Строки diff «было/стало» из payload (`diff.changes`) или пустой список. */
export function extractChanges(diff: unknown): string[] {
  if (diff == null || typeof diff !== "object") return []
  const changes = (diff as { changes?: unknown }).changes
  return Array.isArray(changes) ? changes.filter((c): c is string => typeof c === "string") : []
}

function withPlanChange(view: RunView, change: PlanChange): RunView {
  const next = { ...view, planChanges: [...view.planChanges, change] }
  if (change.reason != null) next.note = change.reason
  return next
}

function foldEvent(view: RunView, ev: AgentEvent): RunView {
  let next: RunView = {
    ...view,
    events: [...view.events.slice(-(VISIBLE_EVENT_CAP - 1)), ev],
  }
  const payload = ev.payload
  // Расход (E-9) едет снимком в `node_timing` и терминальных событиях: берём последний.
  const usage = parseUsage(payload.usage)
  if (usage) next.usage = usage
  switch (ev.type) {
    case "run_started":
      next.status = "running"
      next.limits = parseLimits(payload.limits) ?? next.limits ?? null
      break
    case "plan_created": {
      next.plan = Array.isArray(payload.plan) ? (payload.plan as RunPlanItem[]) : next.plan
      next.note = typeof payload.note === "string" ? payload.note : next.note
      // Пересборка (A-4): diff прежнего плана с новым приходит с plan_created
      // после решения rebuild — причина берём из stash события plan_changed.
      const rebuildChanges = extractChanges(payload.diff)
      if (rebuildChanges.length > 0) {
        next = withPlanChange(next, {
          id: ev.id,
          action: "rebuild",
          reason: next.pendingRebuildReason,
          changes: rebuildChanges,
        })
        next.pendingRebuildReason = null
      }
      break
    }
    case "plan_changed": {
      if (Array.isArray(payload.plan)) next.plan = payload.plan as RunPlanItem[]
      const action = typeof payload.action === "string" ? payload.action : "continue"
      const reason = typeof payload.reason === "string" && payload.reason ? payload.reason : null
      const changes = extractChanges(payload.diff)
      if (changes.length > 0) {
        next = withPlanChange(next, { id: ev.id, action, reason, changes })
      } else if (action === "rebuild") {
        // У пересборки своего diff нет — его отдаст следующий plan_created.
        next.pendingRebuildReason = reason
      }
      break
    }
    case "needs_confirmation":
      next.status = "waiting_approval"
      next.card = (payload.card as AgentActionCard | undefined) ?? null
      break
    case "confirmation_resolved":
      next.card = null
      break
    case "done":
      next.status = "done"
      next.answer = typeof payload.answer === "string" ? payload.answer : next.answer
      next.card = null
      next.live = false
      break
    case "cancelled":
      next.status = "cancelled"
      next.answer = typeof payload.answer === "string" ? payload.answer : next.answer
      next.card = null
      next.live = false
      break
    case "failed":
      next.status = "failed"
      next.error = typeof payload.error === "string" ? payload.error : "Запуск упал"
      next.card = null
      next.live = false
      break
  }
  return next
}

/** Запуск + его события → вид экрана (восстановление после перезагрузки, тесты свёртки). */
export function foldAll(run: AgentRun, events: AgentEvent[]): RunView {
  let view: RunView = {
    run,
    createdAtMs: run.created_at ? Date.parse(run.created_at) : Date.now(),
    status: run.status,
    answer: run.answer,
    error: run.error,
    card: null,
    plan: null,
    note: null,
    planChanges: [],
    pendingRebuildReason: null,
    events: [],
    live: !TERMINAL.includes(run.status),
    usage: parseUsage(run.usage),
    limits: null,
  }
  for (const ev of events) view = foldEvent(view, ev)
  // Статус из базы точнее фолда: терминальный run останется терминальным даже
  // если replay-событий не хватило (обрезка по limit).
  if (TERMINAL.includes(run.status)) {
    view.status = run.status
    view.live = false
  }
  return view
}

export function useAgentRuns(sessionId: number | null) {
  const [runs, setRuns] = useState<RunView[]>([])
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  useEffect(() => {
    if (sessionId == null) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- синхронизация с внешним хранилищем (запуски в БД), не производное состояние
      setRuns([])
      return
    }
    let cancelled = false
    void (async () => {
      try {
        const items = await listAgentRuns(sessionId)
        if (cancelled) return
        const views = await Promise.all(
          items.map(async (run) => {
            try {
              const events = await replayAgentRunEvents(run.id)
              return foldAll(run, events)
            } catch {
              return foldAll(run, [])
            }
          }),
        )
        if (cancelled) return
        // Запуск, стартовавший, пока список грузился, не теряем: сливаем по id.
        setRuns((cur) => {
          const ids = new Set(views.map((v) => v.run.id))
          const extra = cur.filter((r) => !ids.has(r.run.id) && r.run.session_id === sessionId)
          return [...views, ...extra].sort((a, b) => a.createdAtMs - b.createdAtMs)
        })
      } catch {
        if (!cancelled) setRuns([])
      }
    })()
    return () => {
      cancelled = true
    }
  }, [sessionId])

  // Живое следование: каждый незавершённый запуск держит SSE-подписку с ретраем;
  // терминал (done/error кадр) закрывает поток сам.
  useEffect(() => {
    const open = runs.filter((r) => r.live && !TERMINAL.includes(r.status))
    if (open.length === 0) return
    const controller = new AbortController()
    for (const view of open) {
      void (async () => {
        let cursor = view.events.length > 0 ? view.events[view.events.length - 1].id : 0
        for (;;) {
          try {
            await streamAgentRunEvents(view.run.id, cursor > 0 ? cursor : null, (e) => {
              const ev = toEvent(e)
              if (ev == null) return
              cursor = Math.max(cursor, ev.id)
              setRuns((cur) =>
                cur.map((r) => (r.run.id === view.run.id ? foldEvent(r, ev) : r)),
              )
            }, controller.signal)
            return // поток закрылся терминалом
          } catch (err) {
            if (controller.signal.aborted || !alive.current) return
            // Обрыв: убедимся, что запуск ещё не терминален, и переподпишемся.
            try {
              const fresh = await getAgentRun(view.run.id)
              if (TERMINAL.includes(fresh.status)) {
                setRuns((cur) =>
                  cur.map((r) =>
                    r.run.id === fresh.id
                      ? { ...r, status: fresh.status, answer: fresh.answer, error: fresh.error, live: false }
                      : r,
                  ),
                )
                return
              }
            } catch {
              /* сервер недоступен — ретрай ниже */
            }
            if (err instanceof Error && /404|401/.test(err.message)) return
            await new Promise((resolve) => setTimeout(resolve, 2000))
          }
        }
      })()
    }
    return () => controller.abort()
  }, [runs])

  const start = useCallback(async (goal: string, explicitSessionId?: number | null): Promise<boolean> => {
    try {
      // Первый запуск в новом диалоге: сессия только что создана, sessionId хука ещё старый.
      const run = await startAgentRun(goal, explicitSessionId ?? sessionId)
      const view = foldAll(run, [])
      setRuns((cur) => [...cur, view])
      return true
    } catch {
      return false
    }
  }, [sessionId])

  const approve = useCallback(
    async (runId: number, approved: boolean, edits?: AgentApprovalEdits): Promise<void> => {
    await approveAgentRun(runId, approved, edits)
    // Оптимистично снимаем карточку: live-стрим подтвердит статус.
    setRuns((cur) =>
      cur.map((r) =>
        r.run.id === runId
          ? { ...r, status: r.status === "waiting_approval" ? "running" : r.status, card: null }
          : r,
      ),
    )
    },
    [],
  )

  /** «Стоп» (A-9): ответ сервера уже терминальный — применяем сразу, SSE догонит событием. */
  const cancel = useCallback(async (runId: number): Promise<void> => {
    const fresh = await cancelAgentRun(runId)
    if (!TERMINAL.includes(fresh.status)) return
    setRuns((cur) =>
      cur.map((r) =>
        r.run.id === runId
          ? {
              ...r,
              run: { ...r.run, ...fresh },
              status: fresh.status,
              answer: fresh.answer ?? r.answer,
              card: null,
              live: false,
            }
          : r,
      ),
    )
  }, [])

  const hasActive = useMemo(
    () => runs.some((r) => !TERMINAL.includes(r.status)),
    [runs],
  )

  return { runs, start, approve, cancel, hasActive }
}

export type AgentRuns = ReturnType<typeof useAgentRuns>
