import { useState, type ReactNode } from "react"
import { AlertTriangle, ChevronRight, Loader2, RotateCcw, Square } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { MarkdownView, type QuoteAction } from "@/components/markdown-view"
import type { AgentApprovalEdits } from "@/api/agent"
import { cn } from "@/lib/utils"
import type { RunView } from "./use-agent-runs"
import { ConfirmCard } from "./run-parts"
import {
  ACTION_LABEL,
  STATUS,
  STOP_REASON_TEXT,
  TERMINAL,
  currentActivity,
  findQuoteVacancy,
  fmtClock,
  fmtDuration,
  planProgress,
  plural,
  runVacancies,
  summarize,
  vacancyName,
  type VacancyRef,
} from "./run-summary"
import { useNow } from "./use-now"
import { useSteadyActivity } from "./use-steady-activity"

// Запуск агента в ленте (U-5, PLAN 3.2): одна компактная строка «Шаг 2 из 5 · читает условия
// Kestrel Analytics» с полосой по плану, пока агент работает; после итога — ответ, вердикт
// судьи и карточка подтверждения. План, вызовы, вакансии и журнал — в правой панели «Ход
// работы», строка «Ход работы · N действий» открывает её на этом запуске.

export function AgentRunCard({
  view,
  showGoal = false,
  selected = false,
  vacancies,
  onShowWork,
  onApprove,
  onOpenVacancy,
  onRetry,
  retryDisabled = false,
  onStop,
}: {
  view: RunView
  showGoal?: boolean
  /** Этот запуск сейчас открыт в панели. */
  selected?: boolean
  vacancies?: Map<string, VacancyRef>
  onShowWork?: (runId: number) => void
  onApprove?: (runId: number, approved: boolean, edits?: AgentApprovalEdits) => void
  /** Открыть карточку вакансии; `quote` — подсветить цитату в её тексте. */
  onOpenVacancy?: (vacancyId: string, quote?: string) => void
  onRetry?: (goal: string) => void
  retryDisabled?: boolean
  /** «Стоп» (A-9) у идущего запуска и у ждущего подтверждения. */
  onStop?: (runId: number) => Promise<void> | void
}) {
  const status = view.status
  const terminal = TERMINAL.includes(status)
  const working = status === "running" || status === "queued"
  const waiting = status === "waiting_approval" && view.card != null
  const summary = summarize(view.events)
  const progress = planProgress(view.plan, summary.currentStepId, !terminal)
  const activity = useSteadyActivity(
    working ? currentActivity(view.events, vacancies) : null,
    working,
    view.run.id,
  )
  const now = useNow(!terminal)
  const startedMs = view.run.created_at ? Date.parse(view.run.created_at) : view.createdAtMs
  const st = STATUS[status]
  const [stopping, setStopping] = useState(false)
  function stop() {
    if (!onStop || stopping) return
    setStopping(true)
    void Promise.resolve(onStop(view.run.id)).catch(() => setStopping(false))
  }

  const stopReason =
    view.run.stop_reason && view.run.stop_reason !== "answered" && view.run.stop_reason !== "cancelled"
      ? (STOP_REASON_TEXT[view.run.stop_reason] ?? view.run.stop_reason)
      : null
  const durationMs =
    terminal && view.run.created_at && view.run.updated_at
      ? Date.parse(view.run.updated_at) - Date.parse(view.run.created_at)
      : NaN
  const clock = terminal
    ? fmtDuration(durationMs)
    : Number.isFinite(startedMs)
      ? fmtClock(now - startedMs)
      : ""
  const stepLine =
    progress.total > 0 ? `Шаг ${progress.current} из ${progress.total}` : null

  let headline: ReactNode
  if (terminal) {
    headline = (
      <>
        <span className={cn("font-medium", st.tone)}>{st.label}</span>
        {stopReason ? <span className="text-muted-foreground"> · {stopReason}</span> : null}
        {summary.stepsTaken > 0 ? (
          <span className="text-muted-foreground">
            {" "}
            · {summary.stepsTaken} {plural(summary.stepsTaken, "шаг", "шага", "шагов")}
          </span>
        ) : null}
      </>
    )
  } else if (status === "waiting_approval") {
    headline = (
      <>
        <span className={cn("font-medium", st.tone)}>{st.label}</span>
        {stepLine ? <span className="text-muted-foreground"> · {stepLine}</span> : null}
      </>
    )
  } else if (stepLine) {
    const doing = activity ?? progress.currentTitle
    headline = (
      <>
        <span className="font-medium text-foreground">{stepLine}</span>
        {doing ? <span className="text-muted-foreground"> · {doing}</span> : null}
      </>
    )
  } else {
    headline = <span className="font-medium text-foreground">Составляет план</span>
  }

  // На узком экране — только «Ход работы ›», иначе статус в строке обрезается.
  // Цитаты «…» в ответе ведут к месту в тексте вакансии (как цитаты оценки в «Вакансиях»):
  // ищем сначала среди вакансий запуска, потом по всей базе аккаунта.
  const preferred = view.answer ? runVacancies(view, summary, vacancies).map((v) => v.id) : []
  const quoteAction: QuoteAction | undefined =
    view.answer && onOpenVacancy && vacancies
      ? (quote) => {
          const vid = findQuoteVacancy(quote, vacancies, preferred)
          return vid ? () => onOpenVacancy(vid, quote) : null
        }
      : undefined

  const workCount =
    summary.actions > 0
      ? ` · ${summary.actions} ${plural(summary.actions, "действие", "действия", "действий")}`
      : ""

  return (
    <div className="space-y-3">
      {showGoal ? (
        <div className="whitespace-pre-wrap break-words text-base text-foreground">{view.run.goal}</div>
      ) : null}

      <div
        className={cn(
          "rounded-xl border bg-card px-4 py-2.5 shadow-sm transition-colors",
          selected ? "border-slate-300" : "border-border",
        )}
      >
        <div className="flex items-center gap-3">
          <span className={cn("size-2 shrink-0 rounded-full", st.dot)} />
          <div className="min-w-0 flex-1 truncate text-sm" aria-live="polite">
            {headline}
          </div>
          {summary.toolErrors > 0 ? (
            <span className="hidden shrink-0 text-xs text-status-bad-fg sm:inline">
              {summary.toolErrors}{" "}
              {plural(summary.toolErrors, "ошибка инструмента", "ошибки инструментов", "ошибок инструментов")}
              {status === "done" ? " — обработано" : ""}
            </span>
          ) : null}
          {clock ? (
            // На узком экране секундомер уступает место строке шага.
            <span className="hidden shrink-0 text-xs text-muted-foreground tabular-nums sm:inline">
              {clock}
            </span>
          ) : null}
          {!terminal && onStop ? (
            <button
              type="button"
              className="flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
              aria-label="Остановить запуск"
              title="Остановить: агент запишет, что успел сделать; действие без «да» не выполнится"
              disabled={stopping}
              onClick={stop}
            >
              {stopping ? (
                <Loader2 className="size-3 animate-spin" strokeWidth={2} />
              ) : (
                <Square className="size-3" strokeWidth={2.5} />
              )}
              Стоп
            </button>
          ) : null}
          {onShowWork ? (
            <button
              type="button"
              className="flex shrink-0 items-center gap-0.5 text-xs text-muted-foreground hover:text-foreground"
              aria-label={`Ход работы${workCount}`}
              onClick={() => onShowWork(view.run.id)}
            >
              <span>
                Ход работы
                {workCount ? <span className="hidden sm:inline">{workCount}</span> : null}
              </span>
              <ChevronRight className="size-3.5" strokeWidth={2} />
            </button>
          ) : null}
        </div>
        {!terminal && progress.total > 0 ? (
          <Progress
            value={progress.pct}
            aria-label={stepLine ?? "Прогресс плана"}
            className="mt-2 h-1"
          />
        ) : null}
      </div>

      {waiting ? (
        <ConfirmCard
          view={view}
          onApprove={onApprove}
          vacancies={vacancies}
          onOpenVacancy={onOpenVacancy}
        />
      ) : null}

      {view.answer ? <MarkdownView markdown={view.answer} chat quoteAction={quoteAction} /> : null}

      {summary.autoActions.map((a) => {
        const vid = typeof a.params.vacancy_id === "string" ? a.params.vacancy_id : null
        const ref = vid ? vacancies?.get(vid) : undefined
        return (
          <div key={a.id} className="text-sm text-muted-foreground">
            Подтверждено автоматически: {ACTION_LABEL[a.action] ?? a.action}
            {ref ? ` · ${vacancyName(ref)}` : vid ? ` · ${vid}` : ""}
          </div>
        )
      })}

      {view.error ? (
        <div className="flex items-start gap-2 rounded-lg bg-status-bad-soft px-3 py-2 text-sm text-status-bad-fg">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" strokeWidth={2} />
          <span className="min-w-0 break-words">{view.error}</span>
        </div>
      ) : null}

      {summary.finalVerdict ? (
        <div
          className={cn(
            "text-sm",
            summary.finalVerdict.verdict === "pass"
              ? "text-status-strong-fg"
              : summary.finalVerdict.verdict === "fail"
                ? "text-status-bad-fg"
                : "text-muted-foreground",
          )}
        >
          {summary.finalVerdict.verdict === "pass"
            ? "Судья: итог подтверждён цитатами инструментов"
            : summary.finalVerdict.verdict === "fail"
              ? `Судья: итог не принят${summary.finalVerdict.reason ? ` — ${summary.finalVerdict.reason}` : ""}`
              : "Судья: итог не проверялся"}
        </div>
      ) : null}

      {terminal && onRetry ? (
        <Button
          size="sm"
          variant="outline"
          className="gap-1.5"
          disabled={retryDisabled}
          onClick={() => onRetry(view.run.goal)}
        >
          <RotateCcw className="size-3.5" strokeWidth={2} />
          {status === "done" ? "Запустить заново" : "Повторить"}
        </Button>
      ) : null}
    </div>
  )
}
