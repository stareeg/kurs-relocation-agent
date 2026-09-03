import { useMemo, useState } from "react"
import { ChevronDown, History } from "lucide-react"
import type { Job } from "@/api/jobs"
import type { ScoreRevisionOut } from "@/api/score-revisions"
import { cn } from "@/lib/utils"
import { useScoreRevisions } from "./use-score-revisions"

// Тон бейджа ревизии: подтверждённая HR — акцентная, JD-первичная — нейтральная.
const BASIS_LABEL: Record<string, string> = { jd_only: "по вакансии", hr_confirmed: "по HR" }

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return ""
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ""
  return d.toLocaleString("ru-RU", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  })
}

function deltaTag(delta: number): { text: string; cls: string } | null {
  if (!delta) return null
  if (delta > 0) return { text: `+${delta}`, cls: "text-emerald-700" }
  return { text: `${delta}`, cls: "text-rose-700" }
}

/** Схлопнуть подряд идущие HR-ревизии с тем же скором и почти тем же текстом (шум LLM). */
function dedupeRevisions(items: ScoreRevisionOut[]): ScoreRevisionOut[] {
  const out: ScoreRevisionOut[] = []
  for (const rec of items) {
    const prev = out[out.length - 1]
    if (
      prev &&
      prev.basis === rec.basis &&
      prev.overall_score === rec.overall_score &&
      prev.delta === rec.delta &&
      normalizeRationale(prev.rationale) === normalizeRationale(rec.rationale)
    ) {
      continue
    }
    out.push(rec)
  }
  return out
}

function normalizeRationale(text: string): string {
  return text
    .toLowerCase()
    .replace(/[—–−]/g, "-")
    .replace(/\s+/g, " ")
    .replace(/\d+\s*→\s*\d+/g, "")
    .trim()
}

function RevisionRow({ rec }: { rec: ScoreRevisionOut }) {
  const d = deltaTag(rec.delta)
  return (
    <div className="space-y-1 rounded-lg bg-slate-50 p-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={cn(
            "inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium",
            rec.basis === "hr_confirmed"
              ? "border-slate-200 bg-white text-slate-700"
              : "border-slate-200 bg-white text-slate-600",
          )}
        >
          <span className="size-1.5 rounded-full bg-current" />
          {BASIS_LABEL[rec.basis] ?? rec.basis}
        </span>
        <span className="font-medium tabular-nums text-slate-900">{rec.overall_score}</span>
        {d && <span className={cn("text-xs font-medium tabular-nums", d.cls)}>{d.text}</span>}
        {rec.created_at && (
          <span className="ml-auto text-xs tabular-nums text-slate-400">
            {fmtDate(rec.created_at)}
          </span>
        )}
      </div>
      {rec.rationale.trim() && <p className="text-sm text-slate-600">{rec.rationale}</p>}
    </div>
  )
}

// Лента ревизий скоринга (JS-8.1): тот же спойлер-паттерн, что «Текст вакансии» / «Реальность удалёнки».
export function ScoreRevisions({ job }: { job: Job }) {
  const [open, setOpen] = useState(false)
  const { data } = useScoreRevisions(job.vacancy_id ?? null)
  const items = useMemo(() => dedupeRevisions(data?.items ?? []), [data?.items])
  if (items.length === 0) return null

  const baseline = [...items].reverse().find((r) => r.basis === "jd_only")
  // Сводка строится ТОЛЬКО по ленте (items[0] — последняя записанная ревизия), не по живому
  // job.overall_score: тот мог сдвинуться позже по другой причине (резюме/веса), и тогда стрелка
  // «57 → 95» при списке максимум до 63 выглядела бы как баг — вместо этого сноска ниже.
  const latest = items[0].overall_score
  const summary =
    baseline && baseline.overall_score !== latest
      ? `${baseline.overall_score} → ${latest}`
      : `${latest}`
  const liveDrifted = job.overall_score != null && job.overall_score !== latest

  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-500 hover:text-slate-700"
      >
        <ChevronDown
          className={cn("size-4 shrink-0 transition-transform", open && "rotate-180")}
          strokeWidth={2}
        />
        <History className="size-3.5 shrink-0" strokeWidth={2} />
        <span>История пересчёта скора</span>
        <span className="ml-auto rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-xs font-medium normal-case tracking-normal tabular-nums text-slate-600">
          {summary}
        </span>
        <span className="text-xs font-medium normal-case tracking-normal tabular-nums text-slate-400">
          {items.length}
        </span>
      </button>
      {open && (
        <div className="space-y-2">
          {liveDrifted && (
            <p className="text-xs text-slate-400">
              Текущий скор вакансии сейчас {job.overall_score} — сместился уже после этой записи, не
              по фактам HR.
            </p>
          )}
          {items.map((r, i) => (
            <RevisionRow key={r.id ?? i} rec={r} />
          ))}
        </div>
      )}
    </div>
  )
}
