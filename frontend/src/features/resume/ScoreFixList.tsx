import { Sparkles } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { useScoreFixApply } from "./resume-score-apply-context"
import type { ScoreFixItem } from "./resume-score-fixes"
import { subscalePointsLost } from "./resume-score-fixes"

export function ScoreFixList({
  fixes,
  weight,
  pending,
}: {
  fixes: ScoreFixItem[]
  weight: number
  pending?: boolean
}) {
  const applyFix = useScoreFixApply()

  if (pending) {
    return (
      <p className="text-sm leading-relaxed text-slate-500">
        Считаем детали оценки — обычно 10–30 секунд…
      </p>
    )
  }

  if (!fixes.length) {
    return (
      <p className="text-sm text-emerald-700">
        По этой шкале критичных правок нет — хорошая работа.
      </p>
    )
  }

  return (
    <ol className="space-y-3">
      {fixes.map((fix, step) => (
        <li
          key={`${fix.axis}-${fix.label}-${step}`}
          className="rounded-lg border border-slate-200/90 bg-white px-3 py-2.5 shadow-xs"
        >
          <div className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-1">
            <span className="text-sm font-semibold text-slate-900">
              {step + 1}. {fix.label}
            </span>
            <span className="rounded-md bg-rose-50 px-2 py-0.5 text-xs font-semibold tabular-nums text-rose-700">
              −{subscalePointsLost(fix, weight)} из {weight}
            </span>
          </div>
          {fix.current ? (
            <p className="mt-2 text-sm leading-snug text-slate-500 line-through">{fix.current}</p>
          ) : null}
          <p className={cn("text-sm leading-snug text-slate-900", fix.current && "mt-1")}>
            {fix.suggested}
          </p>
          {fix.why ? (
            <p className="mt-1.5 text-xs leading-snug text-slate-500">{fix.why}</p>
          ) : null}
          {applyFix ? (
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="mt-2.5 h-8 gap-1.5 border-sky-200 bg-sky-50 px-2.5 text-xs text-sky-900 hover:bg-sky-100"
              onClick={() => applyFix(fix)}
            >
              <Sparkles className="size-3" strokeWidth={2} />
              Применить
            </Button>
          ) : null}
        </li>
      ))}
    </ol>
  )
}
