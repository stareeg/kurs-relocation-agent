import { useState } from "react"
import { AlertTriangle, Check, ChevronRight, Loader2, Pencil, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { COVER_NOTE_MAX, COVER_NOTE_MIN, type AgentApprovalEdits } from "@/api/agent"
import { cn } from "@/lib/utils"
import type { PlanChange, RunPlanItem, RunView } from "./use-agent-runs"
import {
  ACTION_LABEL,
  PARAM_LABEL,
  PLAN_CHANGE_LABEL,
  plural,
  vacancyName,
  type LogRow,
  type VacancyRef,
} from "./run-summary"

// Части запуска агента, общие для карточки в ленте и правой панели (U-5): план с текущим
// шагом и раскрытием вызовов, журнал событий, изменения плана «было/стало», карточка
// подтверждения действия.

function LogMarker({ kind }: { kind: LogRow["kind"] }) {
  if (kind === "tool-error" || kind === "judge-fail")
    return <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-status-bad-fg" strokeWidth={2} />
  if (kind === "check" || kind === "judge-ok")
    return <Check className="mt-0.5 size-3.5 shrink-0 text-status-strong-fg" strokeWidth={2} />
  return <span className="mt-[7px] size-1.5 shrink-0 rounded-full bg-slate-300" />
}

export function RunLog({ rows }: { rows: LogRow[] }) {
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
              row.kind === "tool-error" && "-mx-2 rounded-md bg-status-bad-soft px-2 py-1",
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

export function Plan({
  plan,
  currentId,
  live,
  rowsByStep,
}: {
  plan: RunPlanItem[]
  currentId: string | null
  live: boolean
  rowsByStep: Map<string, LogRow[]>
}) {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set())
  const toggle = (id: string) =>
    setExpanded((cur) => {
      const next = new Set(cur)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  return (
    <ol className="space-y-1">
      {plan.map((step, i) => {
        const state =
          step.status === "done"
            ? "done"
            : step.status === "dropped"
              ? "dropped"
              : live && step.id === currentId
                ? "current"
                : "todo"
        const rows = rowsByStep.get(step.id) ?? []
        const calls = rows.filter((r) => r.kind === "tool" || r.kind === "tool-error").length
        const hasError = rows.some((r) => r.kind === "tool-error" || r.kind === "judge-fail")
        const open = expanded.has(step.id)
        const label = (
          <>
            <StepMarker state={state} n={i + 1} />
            <span
              className={cn(
                "min-w-0 flex-1 pt-px",
                state === "current" && "font-medium text-foreground",
                state === "todo" && "text-foreground",
                state === "done" && "text-muted-foreground",
                state === "dropped" && "text-muted-foreground line-through",
              )}
            >
              {step.title}
              {state === "dropped" ? " (снят)" : ""}
            </span>
          </>
        )
        return (
          <li key={step.id}>
            {rows.length > 0 ? (
              <button
                type="button"
                className="flex w-full items-start gap-2.5 rounded-md py-0.5 text-left text-sm hover:bg-muted/60"
                aria-expanded={open}
                onClick={() => toggle(step.id)}
              >
                {label}
                <span
                  className={cn(
                    "flex shrink-0 items-center gap-1 pt-px text-xs tabular-nums",
                    hasError ? "text-status-bad-fg" : "text-muted-foreground",
                  )}
                >
                  {calls > 0 ? `${calls} ${plural(calls, "вызов", "вызова", "вызовов")}` : "детали"}
                  <ChevronRight
                    className={cn("size-3.5 transition-transform", open && "rotate-90")}
                    strokeWidth={2}
                  />
                </span>
              </button>
            ) : (
              <div className="flex items-start gap-2.5 py-0.5 text-sm">{label}</div>
            )}
            {open ? (
              <div className="mb-2 ml-[1.875rem] mt-1 border-l border-border pl-3">
                <RunLog rows={rows} />
              </div>
            ) : null}
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

export function PlanChanges({ changes }: { changes: PlanChange[] }) {
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
            <div key={i} className={cn("break-words font-mono text-xs", diffLineColor(line))}>
              {line}
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

export function ConfirmCard({
  view,
  onApprove,
  vacancies,
  onOpenVacancy,
}: {
  view: RunView
  onApprove?: (runId: number, approved: boolean, edits?: AgentApprovalEdits) => void
  vacancies?: Map<string, VacancyRef>
  onOpenVacancy?: (vacancyId: string) => void
}) {
  const [busy, setBusy] = useState(false)
  const action = view.card?.action ?? ""
  const params = (view.card?.params ?? {}) as Record<string, unknown>
  const entries = Object.entries(params).filter(([, v]) => v != null && String(v).length > 0)
  // Три ответа (PLAN 3.2): «да», «изменить» (текст для работодателя — до «да»), «нет».
  const original = typeof params.cover_note === "string" ? params.cover_note : null
  const editable = action === "queue_application" && original != null
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(original ?? "")
  const length = draft.trim().length
  const draftOk = length >= COVER_NOTE_MIN && length <= COVER_NOTE_MAX
  const changed = draft.trim() !== (original ?? "").trim()

  const decide = (approved: boolean) => {
    if (!onApprove || busy) return
    if (approved && editing && !draftOk) return
    setBusy(true)
    const edits = approved && editing && changed ? { cover_note: draft.trim() } : undefined
    onApprove(view.run.id, approved, edits)
  }

  return (
    <div className="rounded-xl border border-status-warn-line bg-status-warn-soft p-4">
      <div className="text-xs font-medium uppercase tracking-wider text-status-warn-fg">
        Нужно ваше подтверждение
      </div>
      <div className="mt-1 text-sm font-semibold text-foreground">
        {ACTION_LABEL[action] ?? action}
      </div>
      <dl className="mt-3 space-y-2">
        {entries.map(([key, value]) => {
          const ref = key === "vacancy_id" ? vacancies?.get(String(value)) : undefined
          if (key === "cover_note" && editing) {
            return (
              <div key={key}>
                <dt className="text-xs text-muted-foreground">
                  <label htmlFor={`cover-note-${view.run.id}`}>{PARAM_LABEL[key] ?? key}</label>
                </dt>
                <dd className="mt-1">
                  <Textarea
                    id={`cover-note-${view.run.id}`}
                    value={draft}
                    autoFocus
                    disabled={busy}
                    maxLength={COVER_NOTE_MAX + 200}
                    className="min-h-24 bg-card text-sm"
                    onChange={(e) => setDraft(e.target.value)}
                  />
                  <div
                    className={cn(
                      "mt-1 text-xs tabular-nums",
                      draftOk ? "text-muted-foreground" : "text-status-bad-fg",
                    )}
                  >
                    {length} из {COVER_NOTE_MAX} знаков
                    {length < COVER_NOTE_MIN ? ` · не короче ${COVER_NOTE_MIN}` : ""}
                  </div>
                </dd>
              </div>
            )
          }
          return (
            <div key={key}>
              <dt className="text-xs text-muted-foreground">{PARAM_LABEL[key] ?? key}</dt>
              <dd className="mt-0.5 whitespace-pre-wrap break-words text-sm text-foreground">
                {ref ? (
                  <button
                    type="button"
                    className="text-left font-medium text-sky-700 underline decoration-sky-300 underline-offset-2 hover:text-sky-800"
                    onClick={() => onOpenVacancy?.(String(value))}
                  >
                    {vacancyName(ref)}
                  </button>
                ) : (
                  String(value)
                )}
              </dd>
            </div>
          )
        })}
      </dl>
      {onApprove ? (
        <div className="mt-4 flex flex-wrap gap-2">
          <Button size="sm" disabled={busy || (editing && !draftOk)} onClick={() => decide(true)}>
            {busy ? <Loader2 className="size-3.5 animate-spin" strokeWidth={2} /> : null}
            {editing && changed ? "Да, с этим текстом" : "Да, выполнить"}
          </Button>
          {editable ? (
            editing ? (
              <Button
                size="sm"
                variant="outline"
                disabled={busy}
                onClick={() => {
                  setEditing(false)
                  setDraft(original ?? "")
                }}
              >
                Вернуть текст агента
              </Button>
            ) : (
              <Button size="sm" variant="outline" disabled={busy} onClick={() => setEditing(true)}>
                <Pencil className="size-3.5" strokeWidth={2} />
                Изменить текст
              </Button>
            )
          ) : null}
          <Button size="sm" variant="outline" disabled={busy} onClick={() => decide(false)}>
            Отклонить
          </Button>
        </div>
      ) : null}
    </div>
  )
}
