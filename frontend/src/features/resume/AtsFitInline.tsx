/**
 * FR2-34/35/37: инлайн-плашки ats-fit (текстовые правки) + плашка без рынка.
 * Навыки сюда не заходят: предложения по навыкам — это снимок спроса на момент расчёта,
 * они живут только в `SkillsPanel`.
 */
import { CheckCheck, Loader2, Sparkles } from "lucide-react"
import type { AtsFitAboutPatch, AtsFitExperiencePatch } from "@/api/resume"
import { Button } from "@/components/ui/button"
import { HelpTip } from "@/components/ui/help-tip"
import { cn } from "@/lib/utils"
import type { AtsFitTextProposal } from "./ats-fit-context"

export function AtsFitSummaryBar({
  pending,
  acceptedCount,
  totalOk,
  pendingCount,
  isPending,
  isError,
  hasResult,
  hasActionable,
  hasMarket = true,
  progress,
  onAcceptAll,
  onSkipAll,
  onClear,
}: {
  pending: AtsFitTextProposal[]
  acceptedCount: number
  totalOk: number
  pendingCount: number
  isPending: boolean
  isError: boolean
  hasResult: boolean
  hasActionable: boolean
  /** false → плашка FR2-37: подгонка без рынка (нет оценённых вакансий). */
  hasMarket?: boolean
  /** FR2-38: «3/6 блоков готово» во время стрима. */
  progress?: { done: number; total: number; label: string } | null
  onAcceptAll: () => void
  onSkipAll: () => void
  onClear: () => void
}) {
  if (!isPending && !isError && !hasResult) return null

  return (
    <div
      className={cn(
        "sticky top-0 z-10 space-y-2 rounded-xl border bg-white/95 p-3 shadow-sm backdrop-blur",
        isError ? "border-rose-200" : "border-emerald-200",
      )}
    >
      {isPending && (
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
          <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />
          {progress && progress.total > 0 ? (
            <span>
              <span className="tabular-nums font-medium text-slate-700">
                {progress.done}/{progress.total}
              </span>{" "}
              блоков готово
              {progress.label ? <span className="text-slate-400"> · {progress.label}</span> : null}
            </span>
          ) : (
            <span>Подгоняю резюме под ATS — обычно 30–90 секунд…</span>
          )}
        </div>
      )}
      {isError && !isPending && (
        <p className="text-xs text-rose-700">
          Не удалось подогнать (нет ключа OpenRouter или лимит). Попробуйте ещё раз с кнопки
          в боковой панели.
        </p>
      )}
      {!isPending && hasResult && !hasMarket && (
        <div className="flex items-start gap-1.5 rounded-lg bg-amber-50/70 px-3 py-2 text-xs text-amber-900">
          <p className="min-w-0 flex-1 leading-relaxed">
            Оценённых вакансий нет: подгонка без учёта рынка. Оцените вакансии расширением —
            рекомендации станут точнее
          </p>
          <HelpTip id="resume.ats-fit-no-market" side="left" showIcon />
        </div>
      )}
      {!isPending && hasResult && hasActionable && (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-1.5 text-sm text-slate-800">
              <Sparkles className="size-3.5 text-emerald-600" strokeWidth={2} />
              <span>
                Под ATS:{" "}
                <span className="tabular-nums font-medium text-slate-900">
                  {acceptedCount}/{totalOk}
                </span>{" "}
                принято
                {pendingCount > 0 && (
                  <span className="text-slate-500"> · осталось {pendingCount}</span>
                )}
              </span>
            </div>
            <div className="ml-auto flex flex-wrap items-center gap-2">
              {pendingCount > 0 && (
                <>
                  <Button type="button" size="sm" onClick={onAcceptAll}>
                    <CheckCheck className="size-3.5" strokeWidth={2} />
                    Принять всё
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="text-slate-500"
                    onClick={onSkipAll}
                  >
                    Пропустить всё
                  </Button>
                </>
              )}
              {pendingCount === 0 && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="text-slate-500"
                  onClick={onClear}
                >
                  Скрыть панель
                </Button>
              )}
            </div>
          </div>
          {pending.length > 0 && (
            <p className="mt-2 text-xs text-slate-400">
              Правки текста — зелёными плашками у блоков опыта и «Обо мне» ниже.
            </p>
          )}
        </>
      )}
      {!isPending && !isError && hasResult && !hasActionable && (
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs text-slate-500">
            Нечего применять: блоки пустые или пайплайн их пропустил. Заполните опыт и нажмите снова.
          </p>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="shrink-0 text-slate-500"
            onClick={onClear}
          >
            Скрыть
          </Button>
        </div>
      )}
    </div>
  )
}

export function AtsFitProposalBanner({
  proposal,
  onAccept,
  onSkip,
}: {
  proposal: AtsFitTextProposal
  onAccept: () => void
  onSkip: () => void
}) {
  return (
    <div className="mt-2 rounded-lg border border-emerald-200 bg-emerald-50/40 p-3">
      <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-emerald-700">
        <Sparkles className="size-3.5" strokeWidth={2} />
        Подгонка под ATS — проверьте и примите
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-md bg-white/70 p-2">
          <div className="mb-1 text-xs font-medium uppercase tracking-wider text-slate-500">
            Было
          </div>
          <p className="whitespace-pre-wrap text-xs leading-relaxed text-slate-500">
            {proposal.original.trim() || "пусто"}
          </p>
        </div>
        <div className="rounded-md bg-white/70 p-2">
          <div className="mb-1 text-xs font-medium uppercase tracking-wider text-emerald-700">
            Станет
          </div>
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-700">
            {proposal.proposed}
          </p>
        </div>
      </div>
      <div className="mt-3 flex items-center gap-2">
        <Button type="button" size="sm" onClick={onAccept}>
          Принять
        </Button>
        <Button type="button" variant="ghost" size="sm" className="text-slate-500" onClick={onSkip}>
          Пропустить
        </Button>
      </div>
    </div>
  )
}

export function AtsFitBlockStatus({
  patch,
}: {
  patch: AtsFitExperiencePatch | AtsFitAboutPatch | undefined
}) {
  if (!patch) return null
  if (patch.status === "skipped" && patch.skip_reason) {
    return <p className="mt-2 text-xs text-slate-400">{patch.skip_reason}</p>
  }
  if (patch.status === "error" && patch.error) {
    return <p className="mt-2 text-xs text-rose-600">Не удалось подогнать блок: {patch.error}</p>
  }
  return null
}
