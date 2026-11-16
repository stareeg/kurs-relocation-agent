import { useState, type ReactNode } from "react"
import { AlertTriangle, Check, ChevronRight, PanelRightClose } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { scoreTone } from "@/features/jobs/funnel"
import { cn } from "@/lib/utils"
import type { RunView } from "./use-agent-runs"
import { Plan, PlanChanges, RunLog } from "./run-parts"
import {
  STATUS,
  TERMINAL,
  fmtClock,
  fmtDuration,
  planProgress,
  plural,
  runVacancies,
  summarize,
  type ToolStat,
  type VacancyRef,
} from "./run-summary"
import { useNow } from "./use-now"

// Правая панель «Ход работы» (U-5, раскладка Claude Cowork): подробности выбранного запуска —
// план с прогрессом и снятыми шагами, вакансии запуска с баллом, вызовы по инструментам с
// ошибками, память агента (с M-1) и полный журнал событий. В ленте остаётся только
// компактная карточка. Пустые секции показываются с нулём, а не прячутся.

function PanelSection({
  title,
  count,
  countTone,
  defaultOpen = true,
  children,
}: {
  title: string
  count: ReactNode
  countTone?: string
  defaultOpen?: boolean
  children: ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <section className="border-b border-border last:border-b-0">
      <button
        type="button"
        aria-expanded={open}
        className="flex w-full items-center gap-1.5 px-4 py-2.5 text-left hover:bg-muted/40"
        onClick={() => setOpen(!open)}
      >
        <ChevronRight
          className={cn("size-3.5 shrink-0 text-muted-foreground transition-transform", open && "rotate-90")}
          strokeWidth={2}
        />
        <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          {title}
        </span>
        <span className={cn("ml-auto text-xs tabular-nums text-muted-foreground", countTone)}>
          {count}
        </span>
      </button>
      {open ? <div className="px-4 pb-4">{children}</div> : null}
    </section>
  )
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="text-sm text-muted-foreground">{children}</p>
}

function ToolRow({ stat }: { stat: ToolStat }) {
  // Упавший инструмент раскрыт сразу: ошибка — то, ради чего панель открывают.
  const [open, setOpen] = useState(stat.errors > 0)
  const n = stat.calls.length
  return (
    <li>
      <button
        type="button"
        aria-expanded={open}
        className="-mx-2 flex w-[calc(100%+1rem)] items-center gap-2 rounded-md px-2 py-1 text-left text-sm hover:bg-muted/60"
        onClick={() => setOpen(!open)}
      >
        <span className="min-w-0 flex-1 truncate text-foreground">{stat.label}</span>
        <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
          {n} {plural(n, "вызов", "вызова", "вызовов")}
        </span>
        {stat.errors > 0 ? (
          <span className="shrink-0 text-xs text-status-bad-fg tabular-nums">
            {stat.errors} {plural(stat.errors, "ошибка", "ошибки", "ошибок")}
          </span>
        ) : null}
        <ChevronRight
          className={cn("size-3.5 shrink-0 text-muted-foreground transition-transform", open && "rotate-90")}
          strokeWidth={2}
        />
      </button>
      {open ? (
        <ol className="mb-1 ml-1 mt-1 space-y-1.5 border-l border-border pl-3">
          {stat.calls.map((call) => (
            <li
              key={call.id}
              className={cn(
                "flex items-start gap-2 text-xs",
                !call.ok && "-mx-1 rounded-md bg-status-bad-soft px-1 py-0.5",
              )}
            >
              {call.ok ? (
                <Check className="mt-px size-3 shrink-0 text-status-strong-fg" strokeWidth={2} />
              ) : (
                <AlertTriangle className="mt-px size-3 shrink-0 text-status-bad-fg" strokeWidth={2} />
              )}
              <span
                className={cn(
                  "min-w-0 break-words",
                  call.ok ? "line-clamp-2 text-muted-foreground" : "text-status-bad-fg",
                )}
                title={call.ok ? call.text : undefined}
              >
                {call.role ? <span className="font-medium">{call.role}: </span> : null}
                {call.ok ? call.text || "ок" : `Ошибка: ${call.text}`}
              </span>
            </li>
          ))}
        </ol>
      ) : null}
    </li>
  )
}

export function AgentWorkPanel({
  view,
  runIndex,
  runCount,
  vacancies,
  onOpenVacancy,
  onClose,
}: {
  view: RunView | null
  runIndex?: number
  runCount?: number
  vacancies?: Map<string, VacancyRef>
  onOpenVacancy?: (vacancyId: string) => void
  /** Свернуть панель (на широком экране); в шторке закрывает её крестик. */
  onClose?: () => void
}) {
  const terminal = view ? TERMINAL.includes(view.status) : true
  const now = useNow(!terminal)
  const summary = summarize(view?.events ?? [])
  const progress = planProgress(view?.plan ?? null, summary.currentStepId, !terminal)
  const items = view ? runVacancies(view, summary, vacancies) : []

  let meta = ""
  if (view) {
    const started = view.run.created_at ? Date.parse(view.run.created_at) : view.createdAtMs
    const clock = terminal
      ? view.run.created_at && view.run.updated_at
        ? fmtDuration(Date.parse(view.run.updated_at) - Date.parse(view.run.created_at))
        : ""
      : Number.isFinite(started)
        ? fmtClock(now - started)
        : ""
    meta = [
      summary.stepsTaken > 0
        ? `${summary.stepsTaken} ${plural(summary.stepsTaken, "шаг", "шага", "шагов")}`
        : null,
      clock || null,
    ]
      .filter(Boolean)
      .join(" · ")
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-10 shrink-0 items-center gap-2 border-b border-border pl-4 pr-2">
        <span className="text-sm font-semibold text-foreground">Ход работы</span>
        {onClose ? (
          <Button
            size="icon"
            variant="ghost"
            className="ml-auto size-8 text-muted-foreground"
            aria-label="Свернуть панель «Ход работы»"
            onClick={onClose}
          >
            <PanelRightClose className="size-4" strokeWidth={2} />
          </Button>
        ) : null}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {view ? (
          <div className="space-y-1.5 border-b border-border px-4 py-3">
            <div className="flex items-center gap-2 text-xs">
              <span className={cn("size-2 shrink-0 rounded-full", STATUS[view.status].dot)} />
              <span className={cn("font-medium", STATUS[view.status].tone)}>
                {STATUS[view.status].label}
              </span>
              {runCount != null && runCount > 1 && runIndex != null ? (
                <span className="text-muted-foreground">
                  · запуск {runIndex} из {runCount}
                </span>
              ) : null}
              {meta ? (
                <span className="ml-auto text-muted-foreground tabular-nums">{meta}</span>
              ) : null}
            </div>
            <p className="line-clamp-3 text-sm text-foreground" title={view.run.goal}>
              {view.run.goal}
            </p>
          </div>
        ) : (
          <div className="border-b border-border px-4 py-3">
            <Empty>
              В этом диалоге ещё нет запусков. Опишите задачу внизу экрана — здесь появятся план,
              вакансии и вызовы инструментов.
            </Empty>
          </div>
        )}

        <PanelSection
          title="План"
          count={progress.total > 0 ? `${progress.done} из ${progress.total}` : "0"}
        >
          {view?.plan && view.plan.length > 0 ? (
            <div className="space-y-3">
              <Progress value={progress.pct} aria-label="Прогресс плана" className="h-1" />
              <Plan
                key={view.run.id}
                plan={view.plan}
                currentId={summary.currentStepId}
                live={!terminal}
                rowsByStep={summary.rowsByStep}
              />
              <PlanChanges changes={view.planChanges} />
            </div>
          ) : (
            <Empty>{view && !terminal ? "Агент составляет план…" : "Плана нет."}</Empty>
          )}
        </PanelSection>

        <PanelSection title="Вакансии" count={items.length}>
          {items.length > 0 ? (
            <ul className="space-y-0.5">
              {items.map((v) => (
                <li key={v.id}>
                  <button
                    type="button"
                    className="-mx-2 flex w-[calc(100%+1rem)] items-center gap-3 rounded-md px-2 py-1.5 text-left hover:bg-muted/60"
                    title="Открыть карточку вакансии"
                    onClick={() => onOpenVacancy?.(v.id)}
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm text-foreground">{v.ref.title}</span>
                      {v.ref.company ? (
                        <span className="block truncate text-xs text-muted-foreground">
                          {v.ref.company}
                        </span>
                      ) : null}
                    </span>
                    {v.score != null ? (
                      <span
                        className={cn("shrink-0 text-sm font-semibold tabular-nums", scoreTone(v.score))}
                        title={v.scoredInRun ? "Балл, который агент поставил в этом запуске" : "Балл вакансии в базе"}
                      >
                        {Math.round(v.score)}
                      </span>
                    ) : (
                      <span className="shrink-0 text-xs text-muted-foreground">без балла</span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <Empty>Агент ещё не открывал вакансии.</Empty>
          )}
        </PanelSection>

        <PanelSection
          title="Инструменты"
          count={
            summary.toolErrors > 0
              ? `${summary.actions} · ${summary.toolErrors} ${plural(summary.toolErrors, "ошибка", "ошибки", "ошибок")}`
              : summary.actions
          }
          countTone={summary.toolErrors > 0 ? "text-status-bad-fg" : undefined}
        >
          {summary.tools.length > 0 ? (
            <ul className="space-y-0.5">
              {summary.tools.map((stat) => (
                <ToolRow key={`${view?.run.id ?? 0}:${stat.key}`} stat={stat} />
              ))}
            </ul>
          ) : (
            <Empty>Вызовов инструментов пока нет.</Empty>
          )}
        </PanelSection>

        <PanelSection title="Память" count={0}>
          <Empty>
            Агент пока не запоминает факты между запусками. Здесь появятся факты о вас, которые он
            сохранит, и их можно будет забыть.
          </Empty>
        </PanelSection>

        <PanelSection title="Журнал" count={summary.rows.length} defaultOpen={false}>
          {summary.rows.length > 0 ? <RunLog rows={summary.rows} /> : <Empty>Событий нет.</Empty>}
        </PanelSection>
      </div>
    </div>
  )
}
