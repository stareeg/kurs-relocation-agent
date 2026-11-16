import { useState } from "react"
import { AlertTriangle, Check, ChevronRight, Loader2, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { MarkdownView } from "@/components/markdown-view"
import { cn } from "@/lib/utils"
import type { AgentEvent, AgentRunStatus } from "@/api/agent"
import { extractChanges, type PlanChange, type RunPlanItem, type RunView } from "./use-agent-runs"

// Блок запуска агента в чате: статус, план с текущим шагом, карточка подтверждения,
// ответ (markdown) и свёрнутый «Ход работы» — события запуска, где ошибка инструмента
// видна отдельной строкой, а следом то, что агент сделал дальше. Полный экран
// (аккордеон, react-flow по OQ-30) придёт с U-1/U-4.

const STOP_REASON_TEXT: Record<string, string> = {
  plan_exhausted: "план исчерпан",
  step_limit: "достигнут лимит шагов",
  replan_limit: "достигнут лимит перестроек",
  model_budget: "исчерпан бюджет модели",
  model_error: "сбой модели",
  model_schema: "модель ответила не по схеме",
  judge_failed: "судья не принял итог",
}

const STATUS: Record<AgentRunStatus, { label: string; tone: string; dot: string }> = {
  queued: { label: "В очереди", tone: "text-muted-foreground", dot: "bg-slate-300" },
  running: {
    label: "Выполняется",
    tone: "text-status-info-fg",
    dot: "bg-status-info-dot animate-pulse",
  },
  waiting_approval: {
    label: "Ждёт подтверждения",
    tone: "text-status-warn-fg",
    dot: "bg-status-warn-dot animate-pulse",
  },
  done: { label: "Готово", tone: "text-status-strong-fg", dot: "bg-status-strong-dot" },
  failed: { label: "Ошибка", tone: "text-status-bad-fg", dot: "bg-status-bad-dot" },
  cancelled: { label: "Отменено", tone: "text-muted-foreground", dot: "bg-slate-300" },
}

const TOOL_LABEL: Record<string, string> = {
  read_profile: "Профиль",
  search_vacancies: "Поиск вакансий",
  read_work_terms: "Условия найма",
  score_vacancy: "Оценка вакансии",
  write_cover_letter: "Сопроводительное письмо",
  queue_application: "Отклик",
  task: "Субагент",
}

const SUBAGENT_LABEL: Record<string, string> = {
  country_researcher: "исследователь страны",
  vacancy_assessor: "оценщик вакансии",
}

const ACTION_LABEL: Record<string, string> = {
  queue_application: "Поставить отклик в очередь автооткликов",
}

const PARAM_LABEL: Record<string, string> = {
  vacancy_id: "Вакансия",
  cover_note: "Сообщение работодателю",
  lang: "Язык",
  query: "Запрос",
}

const PLAN_CHANGE_LABEL: Record<string, string> = {
  rebuild: "План пересобран",
  continue: "План скорректирован",
  finish: "План завершён",
}

const TERMINAL: AgentRunStatus[] = ["done", "failed", "cancelled"]

function toolLabel(tool: string): string {
  return TOOL_LABEL[tool] ?? tool
}

/** Сводка инструмента без технического префикса `tool:` / `task(роль):`. */
function cleanSummary(summary: string): string {
  return summary.replace(/^[a-z_]+(\([^)]*\))?:\s*/i, "")
}

function fmtDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return ""
  const sec = Math.round(ms / 1000)
  if (sec < 60) return `${sec} с`
  return `${Math.floor(sec / 60)} мин ${sec % 60} с`
}

function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return one
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few
  return many
}

type LogRow = {
  id: number
  kind: "step" | "tool" | "tool-error" | "plan" | "check" | "judge-ok" | "judge-fail" | "info"
  title: string
  detail?: string
}

function toLogRow(ev: AgentEvent): LogRow | null {
  const p = ev.payload as Record<string, unknown>
  const reason = typeof p.reason === "string" && p.reason ? p.reason : undefined
  switch (ev.type) {
    case "plan_created":
      return { id: ev.id, kind: "plan", title: "План составлен" }
    case "step_started":
      return {
        id: ev.id,
        kind: "step",
        title: `Шаг ${String(p.index ?? "")}`,
        detail: String(p.title ?? p.step_id ?? ""),
      }
    case "tool_called": {
      const tool = String(p.tool ?? "")
      const role = typeof p.subagent === "string" ? p.subagent : null
      const roleLabel = role ? (SUBAGENT_LABEL[role] ?? role) : null
      const title =
        tool === "task"
          ? `Субагент: ${roleLabel ?? "задача"}`
          : roleLabel
            ? `${roleLabel} → ${toolLabel(tool)}`
            : toolLabel(tool)
      if (p.ok === false) {
        const error = typeof p.error === "string" && p.error ? p.error : cleanSummary(String(p.summary ?? ""))
        return { id: ev.id, kind: "tool-error", title: `Ошибка инструмента · ${title}`, detail: error }
      }
      return { id: ev.id, kind: "tool", title, detail: cleanSummary(String(p.summary ?? "")) }
    }
    case "plan_changed": {
      const action = String(p.action ?? "")
      if (action === "rebuild") return { id: ev.id, kind: "plan", title: "План пересобран", detail: reason }
      if (action === "finish") return { id: ev.id, kind: "plan", title: "Итог принят", detail: reason }
      return {
        id: ev.id,
        kind: "plan",
        title: extractChanges(p.diff).length > 0 ? "План скорректирован" : "План сверен",
        detail: reason,
      }
    }
    case "step_checked":
      return p.done === true
        ? { id: ev.id, kind: "check", title: "Шаг закрыт" }
        : { id: ev.id, kind: "tool-error", title: "Шаг не закрыт", detail: reason }
    case "judge_verdict": {
      const verdict = String(p.verdict ?? "")
      const step = p.level === "step"
      const who = step ? "Самопроверка шага" : "Судья итога"
      if (verdict === "pass") return { id: ev.id, kind: "judge-ok", title: who, detail: "пройдена" }
      if (verdict === "fail") return { id: ev.id, kind: "judge-fail", title: who, detail: reason ?? "не пройдена" }
      return { id: ev.id, kind: "info", title: who, detail: "не проверяется" }
    }
    case "needs_confirmation":
      return { id: ev.id, kind: "info", title: "Действие ждёт подтверждения человека" }
    case "confirmation_resolved":
      return {
        id: ev.id,
        kind: p.approved === true ? "check" : "info",
        title: p.approved === true ? "Человек подтвердил действие" : "Человек отклонил действие",
      }
    case "failed":
      return { id: ev.id, kind: "tool-error", title: "Запуск упал", detail: typeof p.error === "string" ? p.error : undefined }
    default:
      return null
  }
}

function LogMarker({ kind }: { kind: LogRow["kind"] }) {
  if (kind === "tool-error" || kind === "judge-fail")
    return <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-status-bad-fg" strokeWidth={2} />
  if (kind === "check" || kind === "judge-ok")
    return <Check className="mt-0.5 size-3.5 shrink-0 text-status-strong-fg" strokeWidth={2} />
  return <span className="mt-[7px] size-1.5 shrink-0 rounded-full bg-slate-300" />
}

function RunLog({ rows }: { rows: LogRow[] }) {
  return (
    <ol className="space-y-1.5 text-sm">
      {rows.map((row) =>
        row.kind === "step" ? (
          <li key={row.id} className="pt-2 first:pt-0">
            <span className="font-medium text-foreground">{row.title}</span>
            {row.detail ? <span className="text-muted-foreground"> · {row.detail}</span> : null}
          </li>
        ) : (
          <li
            key={row.id}
            className={cn(
              "flex items-start gap-2",
              row.kind === "tool-error" && "rounded-md bg-status-bad-soft px-2 py-1 -mx-2",
            )}
          >
            <LogMarker kind={row.kind} />
            <span className="min-w-0 break-words">
              <span
                className={cn(
                  "font-medium",
                  row.kind === "tool-error" || row.kind === "judge-fail"
                    ? "text-status-bad-fg"
                    : "text-foreground",
                )}
              >
                {row.title}
              </span>
              {row.detail ? <span className="text-muted-foreground"> — {row.detail}</span> : null}
            </span>
          </li>
        ),
      )}
    </ol>
  )
}

function StepMarker({ state, n }: { state: "done" | "current" | "dropped" | "todo"; n: number }) {
  if (state === "done")
    return (
      <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-status-strong-soft text-status-strong-fg">
        <Check className="size-3" strokeWidth={2.5} />
      </span>
    )
  if (state === "current")
    return (
      <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-status-info-soft text-status-info-fg">
        <Loader2 className="size-3 animate-spin" strokeWidth={2.5} />
      </span>
    )
  if (state === "dropped")
    return (
      <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
        <X className="size-3" strokeWidth={2.5} />
      </span>
    )
  return (
    // вне шкалы D-07: цифра внутри кружка фиксированного размера
    <span className="flex size-5 shrink-0 items-center justify-center rounded-full border border-border text-[11px] font-medium text-muted-foreground tabular-nums">
      {n}
    </span>
  )
}

function Plan({ plan, currentId, live }: { plan: RunPlanItem[]; currentId: string | null; live: boolean }) {
  return (
    <ol className="space-y-1.5">
      {plan.map((step, i) => {
        const state =
          step.status === "done"
            ? "done"
            : step.status === "dropped"
              ? "dropped"
              : live && step.id === currentId
                ? "current"
                : "todo"
        return (
          <li key={step.id} className="flex items-start gap-2.5 text-sm">
            <StepMarker state={state} n={i + 1} />
            <span
              className={cn(
                "pt-px",
                state === "current" && "font-medium text-foreground",
                state === "todo" && "text-foreground",
                state === "done" && "text-muted-foreground",
                state === "dropped" && "text-muted-foreground line-through",
              )}
            >
              {step.title}
              {state === "dropped" ? " (снят)" : ""}
            </span>
          </li>
        )
      })}
    </ol>
  )
}

function diffLineColor(line: string): string {
  if (line.startsWith("+")) return "text-status-strong-fg"
  if (line.startsWith("-")) return "text-muted-foreground line-through"
  return "text-foreground"
}

function PlanChanges({ changes }: { changes: PlanChange[] }) {
  if (changes.length === 0) return null
  return (
    <div className="space-y-2 rounded-lg bg-muted px-3 py-2.5">
      {changes.map((change) => (
        <div key={change.id} className="space-y-0.5 text-sm">
          <div className="font-medium text-foreground">
            {PLAN_CHANGE_LABEL[change.action] ?? change.action}
            {change.reason ? (
              <span className="font-normal text-muted-foreground"> — {change.reason}</span>
            ) : null}
          </div>
          {change.changes.map((line, i) => (
            <div key={i} className={cn("font-mono text-xs", diffLineColor(line))}>
              {line}
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

function ConfirmCard({
  view,
  onApprove,
}: {
  view: RunView
  onApprove?: (runId: number, approved: boolean) => void
}) {
  const [busy, setBusy] = useState(false)
  const action = view.card?.action ?? ""
  const params = (view.card?.params ?? {}) as Record<string, unknown>
  const entries = Object.entries(params).filter(([, v]) => v != null && String(v).length > 0)
  const decide = (approved: boolean) => {
    if (!onApprove || busy) return
    setBusy(true)
    onApprove(view.run.id, approved)
  }
  return (
    <div className="rounded-lg border border-status-warn-line bg-status-warn-soft p-4">
      <div className="text-xs font-medium uppercase tracking-wider text-status-warn-fg">
        Нужно ваше подтверждение
      </div>
      <div className="mt-1 text-sm font-semibold text-foreground">
        {ACTION_LABEL[action] ?? action}
      </div>
      <dl className="mt-3 space-y-2">
        {entries.map(([key, value]) => (
          <div key={key}>
            <dt className="text-xs text-muted-foreground">{PARAM_LABEL[key] ?? key}</dt>
            <dd className="mt-0.5 whitespace-pre-wrap break-words text-sm text-foreground">
              {String(value)}
            </dd>
          </div>
        ))}
      </dl>
      {onApprove ? (
        <div className="mt-4 flex gap-2">
          <Button size="sm" disabled={busy} onClick={() => decide(true)}>
            Да, выполнить
          </Button>
          <Button size="sm" variant="outline" disabled={busy} onClick={() => decide(false)}>
            Отклонить
          </Button>
        </div>
      ) : null}
    </div>
  )
}

type RunSummary = {
  rows: LogRow[]
  stepsTaken: number
  toolErrors: number
  currentStepId: string | null
  finalVerdict: { verdict: string; reason: string | null } | null
}

function summarize(events: AgentEvent[]): RunSummary {
  const rows: LogRow[] = []
  let stepsTaken = 0
  let toolErrors = 0
  let currentStepId: string | null = null
  let finalVerdict: RunSummary["finalVerdict"] = null
  for (const ev of events) {
    const row = toLogRow(ev)
    if (row) rows.push(row)
    if (ev.type === "step_started") {
      stepsTaken += 1
      currentStepId = String(ev.payload.step_id ?? "")
    }
    if (ev.type === "tool_called" && ev.payload.ok === false) toolErrors += 1
    if (ev.type === "judge_verdict" && ev.payload.level !== "step") {
      finalVerdict = {
        verdict: String(ev.payload.verdict ?? ""),
        reason: typeof ev.payload.reason === "string" ? ev.payload.reason : null,
      }
    }
  }
  return { rows, stepsTaken, toolErrors, currentStepId, finalVerdict }
}

export function AgentRunView({
  view,
  showGoal = false,
  onApprove,
}: {
  view: RunView
  showGoal?: boolean
  onApprove?: (runId: number, approved: boolean) => void
}) {
  const status = view.status
  const terminal = TERMINAL.includes(status)
  const [logOpen, setLogOpen] = useState<boolean | null>(null)
  const open = logOpen ?? !terminal

  const { rows, stepsTaken, toolErrors, currentStepId, finalVerdict } = summarize(view.events)

  const durationMs =
    terminal && view.run.created_at && view.run.updated_at
      ? Date.parse(view.run.updated_at) - Date.parse(view.run.created_at)
      : NaN
  const meta = [
    stepsTaken > 0 ? `${stepsTaken} ${plural(stepsTaken, "шаг", "шага", "шагов")}` : null,
    fmtDuration(durationMs) || null,
  ].filter(Boolean)
  const stopReason =
    view.run.stop_reason && view.run.stop_reason !== "answered"
      ? (STOP_REASON_TEXT[view.run.stop_reason] ?? view.run.stop_reason)
      : null
  const st = STATUS[status]
  const waiting = status === "waiting_approval" && view.card != null

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card shadow-sm">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border px-4 py-2.5">
        <span className={cn("flex items-center gap-2 text-sm font-medium", st.tone)}>
          <span className={cn("size-2 rounded-full", st.dot)} />
          Агент · {st.label}
        </span>
        {stopReason ? <span className="text-sm text-muted-foreground">{stopReason}</span> : null}
        <span className="ml-auto flex items-center gap-3 text-xs text-muted-foreground tabular-nums">
          {toolErrors > 0 ? (
            <span className="text-status-bad-fg">
              {toolErrors} {plural(toolErrors, "ошибка инструмента", "ошибки инструментов", "ошибок инструментов")}
              {terminal && status === "done" ? " — обработано" : ""}
            </span>
          ) : null}
          {meta.join(" · ")}
        </span>
      </div>

      <div className="space-y-4 px-4 py-4">
        {showGoal ? (
          <div className="whitespace-pre-wrap break-words text-base text-foreground">
            {view.run.goal}
          </div>
        ) : null}

        {view.plan && view.plan.length > 0 ? (
          <div>
            <div className="mb-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
              План
            </div>
            <Plan plan={view.plan} currentId={currentStepId} live={!terminal} />
          </div>
        ) : !terminal ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />
            Составляю план…
          </div>
        ) : null}

        <PlanChanges changes={view.planChanges} />

        {waiting ? <ConfirmCard view={view} onApprove={onApprove} /> : null}

        {view.answer ? (
          <div className="border-t border-border pt-4">
            <MarkdownView markdown={view.answer} chat />
          </div>
        ) : null}

        {view.error ? (
          <div className="flex items-start gap-2 rounded-lg bg-status-bad-soft px-3 py-2 text-sm text-status-bad-fg">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" strokeWidth={2} />
            <span className="min-w-0 break-words">{view.error}</span>
          </div>
        ) : null}

        {finalVerdict ? (
          <div
            className={cn(
              "text-sm",
              finalVerdict.verdict === "pass"
                ? "text-status-strong-fg"
                : finalVerdict.verdict === "fail"
                  ? "text-status-bad-fg"
                  : "text-muted-foreground",
            )}
          >
            {finalVerdict.verdict === "pass"
              ? "Судья: итог подтверждён цитатами инструментов"
              : finalVerdict.verdict === "fail"
                ? `Судья: итог не принят${finalVerdict.reason ? ` — ${finalVerdict.reason}` : ""}`
                : "Судья: итог не проверялся"}
          </div>
        ) : null}
      </div>

      {rows.length > 0 ? (
        <div className="border-t border-border bg-muted/40">
          <button
            type="button"
            className="flex w-full items-center gap-1.5 px-4 py-2 text-left text-sm text-muted-foreground hover:text-foreground"
            aria-expanded={open}
            onClick={() => setLogOpen(!open)}
          >
            <ChevronRight
              className={cn("size-4 transition-transform", open && "rotate-90")}
              strokeWidth={2}
            />
            Ход работы
            <span className="tabular-nums">· {rows.length}</span>
          </button>
          {open ? (
            <div className="px-4 pb-4">
              <RunLog rows={rows} />
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
