import { useMemo } from "react"
import {
  AlertTriangle,
  Check,
  CircleDashed,
  Clock,
  Loader2,
  ShieldQuestion,
  Wrench,
  X,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import type { AgentEvent, AgentRunStatus } from "@/api/agent"
import { extractChanges, type PlanChange, type RunView } from "./use-agent-runs"

// Блок запуска агента в чате (A-3, минимум для демонстрации критерия «пауза →
// рестарт → продолжение»): цель, план, лента событий, карточка подтверждения и итог.
// Развитый экран (аккордеон, react-flow по OQ-30) придёт с U-1.

const STOP_REASON_TEXT: Record<string, string> = {
  answered: "ответ получен",
  plan_exhausted: "план исчерпан",
  step_limit: "предел шагов",
  replan_limit: "предел перестроек",
  model_budget: "исчерпан бюджет модели",
  model_error: "сбой модели",
  model_schema: "сбой схемы модели",
}

const STATUS_LABEL: Record<AgentRunStatus, string> = {
  queued: "в очереди",
  running: "выполняется",
  waiting_approval: "ждёт подтверждения",
  done: "готово",
  failed: "ошибка",
  cancelled: "отменено",
}

function statusColor(status: AgentRunStatus): string {
  if (status === "done") return "text-emerald-600"
  if (status === "failed") return "text-rose-600"
  if (status === "waiting_approval") return "text-amber-600"
  return "text-slate-500"
}

const PLAN_CHANGE_LABEL: Record<string, string> = {
  rebuild: "Пересборка",
  continue: "Правка",
  finish: "Завершение",
}

function diffLineColor(line: string): string {
  if (line.startsWith("+")) return "text-emerald-600"
  if (line.startsWith("-")) return "text-slate-400 line-through"
  return "text-slate-600"
}

function PlanChanges({ changes }: { changes: PlanChange[] }) {
  if (changes.length === 0) return null
  return (
    <div className="mt-2 space-y-1.5 rounded-lg bg-white/60 p-2">
      <div className="flex items-center gap-1.5 text-xs font-medium text-slate-500">
        <CircleDashed className="size-3 text-violet-500" />
        Изменения плана
      </div>
      {changes.map((change) => (
        <div key={change.id} className="space-y-0.5">
          <div className="text-xs font-medium text-slate-600">
            {PLAN_CHANGE_LABEL[change.action] ?? change.action}
            {change.reason ? `: ${change.reason}` : ""}
          </div>
          {change.changes.map((line, i) => (
            <div key={i} className={cn("text-xs", diffLineColor(line))}>
              {line}
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

function eventLine(ev: AgentEvent): string | null {
  const p = ev.payload as Record<string, unknown>
  switch (ev.type) {
    case "run_started":
      return null // заголовок блока и так показывает цель
    case "node_timing":
      return null // метрики p90 (OQ-29) в ленте не рисуем
    case "plan_created":
      return "План составлен"
    case "step_started":
      return `Шаг ${String(p.index ?? "")}: ${String(p.title ?? p.step_id ?? "")}`
    case "tool_called": {
      const subagent = p.subagent as string | undefined
      const label = subagent ? `Субагент ${subagent}` : "Инструмент"
      return `${label}: ${String(p.summary ?? p.tool ?? "")}`
    }
    case "observation":
      return null // сводка уже видна в tool_called
    case "plan_changed": {
      const reason = typeof p.reason === "string" && p.reason ? `: ${p.reason}` : ""
      const action = String(p.action ?? "")
      if (action === "rebuild") return `План пересобран${reason}`
      if (action === "finish") return `Итог принят${reason}`
      return extractChanges(p.diff).length > 0
        ? `План скорректирован${reason}`
        : `План сверен${reason}`
    }
    case "step_checked":
      return p.done === true ? "Шаг закрыт" : "Шаг не закрыт"
    case "needs_confirmation":
      return "Действие ждёт подтверждения"
    case "confirmation_resolved":
      return p.approved === true ? "Подтверждено" : "Отклонено"
    case "done":
      return null
    case "failed":
      return "Запуск упал"
    default:
      return null
  }
}

function eventIcon(ev: AgentEvent) {
  const cls = "size-3 shrink-0 text-slate-400"
  switch (ev.type) {
    case "tool_called":
      return <Wrench className={cn(cls, "text-sky-500")} />
    case "needs_confirmation":
      return <ShieldQuestion className={cn(cls, "text-amber-500")} />
    case "plan_changed":
      return <CircleDashed className={cn(cls, "text-violet-500")} />
    case "step_checked":
      return ev.payload.done === true ? (
        <Check className={cn(cls, "text-emerald-500")} />
      ) : (
        <X className={cn(cls, "text-rose-500")} />
      )
    case "failed":
      return <AlertTriangle className={cn(cls, "text-rose-500")} />
    default:
      return <CircleDashed className={cls} />
  }
}

function CardParams({ view }: { view: RunView }) {
  const params = (view.card?.params ?? {}) as Record<string, unknown>
  const entries = Object.entries(params).filter(([, v]) => v != null && String(v).length > 0)
  return (
    <div className="mt-1.5 space-y-0.5 text-xs text-slate-600">
      {entries.map(([key, value]) => (
        <div key={key} className="truncate">
          <span className="font-medium text-slate-500">{key}: </span>
          {String(value)}
        </div>
      ))}
    </div>
  )
}

export function AgentRunView({
  view,
  onApprove,
}: {
  view: RunView
  onApprove?: (runId: number, approved: boolean) => void
}) {
  const status = view.status
  const lines = useMemo(
    () =>
      view.events
        .map((ev) => ({ ev, text: eventLine(ev) }))
        .filter((l): l is { ev: AgentEvent; text: string } => l.text != null),
    [view.events],
  )
  const waiting = status === "waiting_approval" && view.card != null

  return (
    <div className="flex justify-start">
      <div className="flex w-full max-w-[85%] flex-col rounded-2xl rounded-bl-sm bg-violet-100 px-3.5 py-2.5 text-sm">
        <div className="flex items-center gap-1.5 text-xs font-medium text-slate-500">
          {status === "running" || status === "queued" ? (
            <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />
          ) : status === "waiting_approval" ? (
            <ShieldQuestion className="size-3.5 text-amber-500" strokeWidth={2} />
          ) : status === "done" ? (
            <Check className="size-3.5 text-emerald-600" strokeWidth={2} />
          ) : (
            <AlertTriangle className="size-3.5 text-rose-600" strokeWidth={2} />
          )}
          <span className={cn("font-semibold", statusColor(status))}>
            Агент — {STATUS_LABEL[status]}
            {status === "done" && view.run.stop_reason && view.run.stop_reason !== "answered"
              ? ` (${STOP_REASON_TEXT[view.run.stop_reason] ?? view.run.stop_reason})`
              : ""}
          </span>
        </div>

        <div className="mt-1 whitespace-pre-wrap break-words text-slate-800">{view.run.goal}</div>

        {view.plan && view.plan.length > 0 ? (
          <div className="mt-2 space-y-1">
            {view.plan.map((step) => (
              <div key={step.id} className="flex items-center gap-1.5 text-xs text-slate-600">
                {step.status === "done" ? (
                  <Check className="size-3 shrink-0 text-emerald-600" strokeWidth={2} />
                ) : step.status === "dropped" ? (
                  <X className="size-3 shrink-0 text-slate-400" strokeWidth={2} />
                ) : (
                  <CircleDashed className="size-3 shrink-0 text-slate-400" strokeWidth={2} />
                )}
                <span
                  className={cn(
                    (step.status === "done" || step.status === "dropped") &&
                      "text-slate-400 line-through",
                  )}
                >
                  {step.title}
                  {step.status === "dropped" ? " (снят)" : ""}
                </span>
              </div>
            ))}
          </div>
        ) : null}

        <PlanChanges changes={view.planChanges} />

        {lines.length > 0 ? (
          <div className="mt-2 max-h-40 space-y-0.5 overflow-y-auto rounded-lg bg-white/60 p-2">
            {lines.map(({ ev, text }) => (
              <div key={ev.id} className="flex items-start gap-1.5 text-xs text-slate-600">
                {eventIcon(ev)}
                <span className="min-w-0 break-words">{text}</span>
              </div>
            ))}
          </div>
        ) : null}

        {waiting ? (
          <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 p-2.5">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-amber-700">
              <ShieldQuestion className="size-3.5" strokeWidth={2} />
              Подтвердите действие: {view.card?.action}
            </div>
            <CardParams view={view} />
            {onApprove ? (
              <div className="mt-2 flex gap-2">
                <Button
                  size="sm"
                  className="h-7 px-3 text-xs"
                  onClick={() => onApprove(view.run.id, true)}
                >
                  Да, выполнить
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="h-7 px-3 text-xs"
                  onClick={() => onApprove(view.run.id, false)}
                >
                  Нет
                </Button>
              </div>
            ) : null}
          </div>
        ) : null}

        {view.answer ? (
          <div className="mt-2 whitespace-pre-wrap break-words text-slate-800">{view.answer}</div>
        ) : null}
        {view.error ? (
          <div className="mt-2 flex items-start gap-1.5 text-xs text-rose-600">
            <AlertTriangle className="mt-0.5 size-3 shrink-0" />
            <span className="min-w-0 break-words">{view.error}</span>
          </div>
        ) : null}

        <div className="mt-1 flex items-center gap-1 text-[10px] text-slate-400">
          <Clock className="size-2.5" />
          шагов: {view.events.filter((e) => e.type === "step_started").length}
        </div>
      </div>
    </div>
  )
}
