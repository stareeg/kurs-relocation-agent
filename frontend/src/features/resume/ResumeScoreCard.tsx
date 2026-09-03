import { useState, memo } from "react"
import { Check, ChevronDown, ChevronsLeft, TrendingDown, TrendingUp, X } from "lucide-react"
import type { ResumeGapReport, ResumeScoreBreakdown } from "@/api/resume"
import { HelpTip } from "@/components/ui/help-tip"
import { Progress } from "@/components/ui/progress"
import { Skeleton } from "@/components/ui/skeleton"
import { OnboardingHint } from "@/components/ui/tooltip"
import type { HelpTextId } from "@/lib/help-texts"
import { useCountUp } from "@/lib/use-count-up"
import { ONBOARDING_HINT_IDS, useOnboardingHints } from "@/lib/use-onboarding-hints"
import { cn } from "@/lib/utils"
import { InternationalProfileCard } from "./InternationalProfileCard"
import { ResumeCollapseButton } from "./ResumeCollapseButton"
import { MarketScopePanel } from "./MarketScopePanel"
import { ScoringSubblock } from "./panel-field"
import { ScoreFixList } from "./ScoreFixList"
import {
  roleFitFixesFromScore,
  writingFixesFromScore,
  type ScoreFixItem,
} from "./resume-score-fixes"
import {
  availableSubscaleCount,
  formatSubscaleScore,
  subscaleWeight,
} from "./resume-score-display"
import {
  CompanyTypesField,
  GradePrefsField,
  RolePrefsField,
  SchedulePrefsField,
} from "./PositionPrefsPanel"
import { SalaryPrefsPanel } from "./SalaryPrefsPanel"
import { SearchModePanel } from "./SearchModePanel"
import { SearchProfilePanel } from "./SearchProfilePanel"
import { SearchTrackPanel } from "./SearchTrackPanel"
import { SkillsPanel } from "./skills/SkillsPanel"
import { useResumeGap, useResumeScoreHistory } from "./use-resume"

// Балл резюме 0-100 (вклад 4 компонент, FR2-46) + спойлеры с рецептом (FR2-47) + ats-fit (FR2-34).

type SubscaleKey = keyof Pick<
  ResumeScoreBreakdown,
  "structure" | "market_coverage" | "writing" | "role_fit"
>

/** Текст внутри спойлера (развёрнуто). HelpTip на шкале - краткая версия из help-texts (FR2-49). */
const SUBSCALES: {
  key: SubscaleKey
  label: string
  helpId: HelpTextId
  blurb?: string
  layout?: "blocks" | "demand" | "fixes"
}[] = [
  {
    key: "structure",
    label: "Каркас",
    helpId: "resume.score-structure",
    layout: "blocks",
  },
  {
    key: "market_coverage",
    label: "Навыки",
    helpId: "resume.score-market",
    layout: "demand",
  },
  {
    key: "writing",
    label: "Формулировки",
    helpId: "resume.score-writing",
    layout: "fixes",
  },
  {
    key: "role_fit",
    label: "Релевантность роли",
    helpId: "resume.score-role-fit",
    layout: "fixes",
  },
]

function toneBar(v: number): string {
  if (v >= 75) return "bg-emerald-400"
  if (v >= 50) return "bg-amber-400"
  return "bg-rose-400"
}

function toneRing(v: number): string {
  if (v >= 75) return "text-emerald-600"
  if (v >= 50) return "text-amber-600"
  return "text-rose-600"
}

type RecipeItem = { text: string; ok?: boolean; id?: string }

/** Короткие подписи мини-блоков каркаса — полный label остаётся в title. */
const STRUCTURE_SHORT: Record<string, string> = {
  full_name: "ФИО",
  contacts: "Контакты",
  title: "Должность",
  experience: "Опыт",
  dates: "Даты опыта",
  education: "Образование",
  skills: "Навыки",
  about: "Обо мне",
}

function recipeFor(key: SubscaleKey, score: ResumeScoreBreakdown): RecipeItem[] {
  if (key === "structure") {
    const checks = score.details?.structure ?? []
    if (checks.length) {
      return checks.map((c) => ({
        text: STRUCTURE_SHORT[c.id] ?? c.label,
        ok: c.ok,
        id: c.id,
      }))
    }
    return score.structure >= 75 ? [] : [{ text: "Дозаполните пустые блоки каркаса", ok: false }]
  }
  if (key === "market_coverage") {
    return []
  }
  return []
}

function StructureBlocks({ items }: { items: RecipeItem[] }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((item) => {
        const ok = item.ok === true
        const fail = item.ok === false
        return (
          <span
            key={item.id ?? item.text}
            title={item.text}
            className={cn(
              "inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-xs font-medium leading-none",
              ok && "border-emerald-200/90 bg-emerald-50 text-emerald-800",
              fail && "border-rose-200/80 bg-rose-50 text-rose-800",
              !ok && !fail && "border-slate-200 bg-white text-slate-600",
            )}
          >
            {ok ? (
              <Check className="size-3 shrink-0 text-emerald-500" strokeWidth={2.5} />
            ) : fail ? (
              <X className="size-3 shrink-0 text-rose-400" strokeWidth={2.5} />
            ) : null}
            {item.text}
          </span>
        )
      })}
    </div>
  )
}

function SubscaleRow({
  label,
  value,
  weight,
  helpId,
  items,
  layout,
  scoreFixes,
  fixesPending,
}: {
  label: string
  value: number | null
  weight: number
  helpId: HelpTextId
  items: RecipeItem[]
  layout?: "blocks" | "demand" | "fixes"
  scoreFixes?: ScoreFixItem[]
  fixesPending?: boolean
}) {
  const [open, setOpen] = useState(false)
  const hasGaps = items.some((i) => i.ok !== true)

  // Нет данных по рынку: не рисуем 0/25 — пользователь читает это как «плохое резюме».
  if (value == null) {
    return (
      <div className="space-y-1.5">
        <div className="flex items-baseline justify-between gap-2">
          <div className="inline-flex min-w-0 items-center gap-1.5 text-sm text-slate-700">
            <span className="pl-5">{label}</span>
            <HelpTip id="resume.score-market-pending" />
          </div>
        </div>
        <p className="pl-5 text-xs leading-relaxed text-slate-400">
          Пока не считаем — мало оценённых вакансий
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <div className="inline-flex min-w-0 items-center gap-1.5 text-sm text-slate-700">
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            className="inline-flex items-center gap-1.5 text-left hover:text-slate-900"
          >
            <ChevronDown
              className={cn(
                "size-3.5 shrink-0 text-slate-400 transition-transform duration-200",
                open && "rotate-180",
              )}
              strokeWidth={2}
            />
            {label}
          </button>
          <HelpTip id={helpId} />
        </div>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="text-sm font-medium tabular-nums text-slate-900"
          title={`${formatSubscaleScore(value, weight)} в общий балл резюме`}
        >
          {formatSubscaleScore(value, weight)}
        </button>
      </div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="block w-full"
      >
        <Progress
          value={Math.max(value, 3)}
          className="h-1.5"
          indicatorClassName={cn("transition-all duration-200", toneBar(value))}
        />
      </button>
      {open && (
        <div className="space-y-2 rounded-lg bg-slate-50/80 px-3 py-2.5">
          {layout === "demand" ? (
            <SkillsPanel />
          ) : layout === "fixes" ? (
            <ScoreFixList fixes={scoreFixes ?? []} weight={weight} pending={fixesPending} />
          ) : (
            <>
              {items.length > 0 ? (
                layout === "blocks" ? (
                  <StructureBlocks items={items} />
                ) : null
              ) : null}
              {!hasGaps && items.length === 0 && (
                <p className="flex items-center gap-1.5 text-sm text-emerald-700">
                  <Check className="size-3 shrink-0" strokeWidth={2} />
                  По этой шкале критичных дыр нет
                </p>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}

function CardSkeleton() {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4">
        <Skeleton className="size-16 rounded-full" />
        <Skeleton className="h-4 w-32" />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-10 rounded-lg" />
        ))}
      </div>
    </div>
  )
}

// Обёртка: оси поиска в левой панели. Балл живёт в основной колонке (`ResumeScoreBlock`).
export function ResumeScoreCard({ onCollapsePanel }: { onCollapsePanel?: () => void }) {
  const collapseBtn = onCollapsePanel ? (
    <button
      type="button"
      onClick={onCollapsePanel}
      title="Свернуть панель"
      aria-label="Свернуть панель"
      className="flex size-7 shrink-0 items-center justify-center rounded-md border border-slate-200 bg-slate-50 text-slate-500 shadow-xs transition-colors hover:border-slate-300 hover:bg-slate-100 hover:text-slate-700"
    >
      <ChevronsLeft className="size-4" strokeWidth={2} />
    </button>
  ) : undefined

  return (
    <section className="space-y-3">
      {/* Три карточки с подписями над ними — одна картина поиска. */}
      <ScoringSubblock title="Скоринг" action={collapseBtn}>
        <SearchModePanel />
        <MarketScopePanel />
        <SearchTrackPanel />
        <SchedulePrefsField />
        <RolePrefsField />
        <GradePrefsField />
      </ScoringSubblock>
      <ScoringSubblock title="Зарплата">
        <SalaryPrefsPanel />
      </ScoringSubblock>
      <ScoringSubblock title="Компании">
        <CompanyTypesField />
        <SearchProfilePanel />
      </ScoringSubblock>
      <InternationalProfileCard />
    </section>
  )
}

/** Балл резюме — в основной колонке над спойлером «Профиль». */
export const ResumeScoreBlock = memo(function ResumeScoreBlock() {
  const { data: report, isLoading } = useResumeGap()
  const score = report?.score
  const blocked = report?.score_blocked
  return (
    <section className="overflow-hidden rounded-xl border bg-white">
      {isLoading && !score && !blocked ? (
        <div className="p-5">
          <CardSkeleton />
        </div>
      ) : blocked && report ? (
        <div className="p-5">
          <ScoreBlockedBanner hints={report.score_block_hints ?? []} />
        </div>
      ) : score && report ? (
        <div className="p-5">
          <ResumeScoreCardBody report={report} />
        </div>
      ) : null}
      <div className="border-t p-2">
        <ResumeCollapseButton />
      </div>
    </section>
  )
})

function ScoreBlockedBanner({ hints }: { hints: string[] }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-1.5 text-base font-semibold text-slate-900">
        Балл резюме
        <HelpTip id="resume.score-title" />
      </div>
      <div className="rounded-lg border border-amber-200/90 bg-amber-50/80 px-4 py-3">
        <p className="text-sm font-medium text-amber-950">
          Сначала заполните критерии поиска в панели слева
        </p>
        <p className="mt-1 text-xs leading-relaxed text-amber-900/90">
          Без них оценка резюме будет неточной — мы не знаем, под какую роль и рынок вы ищете.
        </p>
        <ul className="mt-2.5 space-y-1">
          {hints.map((hint) => (
            <li key={hint} className="text-xs leading-snug text-amber-900/85">
              — {hint}
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

function ResumeScoreCardBody({ report }: { report: ResumeGapReport }) {
  const score = report.score!
  const meta = report.score_meta
  const { data: history } = useResumeScoreHistory()
  const { shouldShow, dismissHint } = useOnboardingHints()

  const series = history ?? []
  const prev = series.length >= 2 ? series[series.length - 2] : null
  const delta = prev ? score.total - prev.total : null
  const showScoreReadyHint = shouldShow(ONBOARDING_HINT_IDS.resumeScoreReady)
  const { display: totalDisplay, flash: totalFlash } = useCountUp(score.total)
  const weight = subscaleWeight(availableSubscaleCount(score))

  const scoreHeading = (
    <div className="flex items-center gap-1.5 text-base font-semibold text-slate-900">
      Балл резюме
      <HelpTip id="resume.score-title" />
    </div>
  )

  return (
    <div>
      <div className="flex items-center gap-3">
        <div className="flex shrink-0 items-center gap-2">
          <div className="flex size-14 items-center justify-center rounded-full bg-slate-50">
            <span
              className={cn(
                "text-xl font-semibold tabular-nums transition-colors duration-200",
                totalFlash === "up" && "text-emerald-600",
                totalFlash === "down" && "text-rose-600",
                !totalFlash && toneRing(score.total),
              )}
            >
              {totalDisplay ?? score.total}
            </span>
          </div>
          {delta != null && (
            <span
              className={cn(
                "inline-flex shrink-0 items-center gap-0.5 text-sm font-medium tabular-nums",
                delta > 0 ? "text-emerald-600" : delta < 0 ? "text-rose-600" : "text-slate-400",
              )}
              title="Сдвиг с прошлого сохранения"
            >
              {delta > 0 ? (
                <TrendingUp className="size-3.5" strokeWidth={2} />
              ) : delta < 0 ? (
                <TrendingDown className="size-3.5" strokeWidth={2} />
              ) : null}
              {delta > 0 ? `+${delta}` : delta}
            </span>
          )}
        </div>
        <div className="flex min-w-0 flex-1 items-center justify-between gap-2">
          {showScoreReadyHint ? (
            <OnboardingHint
              open
              onDismiss={() => dismissHint(ONBOARDING_HINT_IDS.resumeScoreReady)}
              side="left"
              align="center"
              content="Балл резюме пересчитан по текущему тексту. Шкалы ниже — что подтянуть."
            >
              {scoreHeading}
            </OnboardingHint>
          ) : (
            scoreHeading
          )}
        </div>
      </div>

      <div className="mt-4 space-y-2.5">
        {SUBSCALES.map((s) => (
          <SubscaleRow
            key={s.key}
            label={s.label}
            value={score[s.key]}
            weight={weight}
            helpId={s.helpId}
            layout={s.layout}
            items={recipeFor(s.key, score)}
            scoreFixes={
              s.key === "writing"
                ? writingFixesFromScore(score)
                : s.key === "role_fit"
                  ? roleFitFixesFromScore(score)
                  : undefined
            }
            fixesPending={
              (s.key === "writing" || s.key === "role_fit") &&
              (s.key === "writing"
                ? writingFixesFromScore(score)
                : roleFitFixesFromScore(score)
              ).length === 0 &&
              Boolean(meta?.stale || meta?.refreshing)
            }
          />
        ))}
      </div>
    </div>
  )
}
