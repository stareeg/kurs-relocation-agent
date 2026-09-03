import { useState } from "react"
import { LayoutGrid, List, RotateCcw, Search, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Slider } from "@/components/ui/slider"
import { ChipToggleGroup, type ChipOption } from "@/components/ui/chip-toggle-group"
import { HelpTip } from "@/components/ui/help-tip"
import { getHelpText } from "@/lib/help-texts"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { OnboardingHint } from "@/components/ui/tooltip"
import { ONBOARDING_HINT_IDS, useOnboardingHints } from "@/lib/use-onboarding-hints"
import { cn } from "@/lib/utils"
import { FUNNEL_STAGES } from "./funnel"
import { DateRangeFilter } from "./DateRangeFilter"
import {
  effectiveJobFilters,
  filtersActive,
  searchActive,
  type JobFilters,
  type SortKey,
} from "./use-job-filters"
import { TRACK_LABELS, type JobTrack } from "./use-job-track"
import type { Job } from "@/api/jobs"
import { SOURCE_GROUP_LABEL, SOURCE_GROUPS, sourceFilterEligible, type SourceGroup } from "./source"
import { SourceIcon } from "./SourceIcon"
import { useAnketaPendingIds, useAutoApplyManualReviewIds } from "@/features/settings/use-settings"
import { useSearchTrack } from "@/features/career/search-track"

const TRACK_FILTER_OPTIONS: ChipOption[] = [
  { value: "all", label: "Все" },
  { value: "primary", label: TRACK_LABELS.primary },
  { value: "second_job", label: TRACK_LABELS.second_job },
]

export type JobsView = "board" | "list"

const VIEWS: { value: JobsView; label: string; Icon: typeof LayoutGrid }[] = [
  { value: "board", label: "Доска", Icon: LayoutGrid },
  { value: "list", label: "Список", Icon: List },
]

const STATUS_OPTIONS: ChipOption[] = FUNNEL_STAGES.map((s) => ({ value: s, label: s }))

const SCORE_TICKS = [0, 20, 40, 60, 80, 100]

// UI-запрошено явно: сортировка вакансий по скору/дате, обе по убыванию и по возрастанию —
// компактный select на строке поиска (слева от переключалки Доска/Список).
const SORT_OPTIONS: { value: SortKey; label: string }[] = [
  { value: "score_desc", label: "Скор ↓" },
  { value: "score_asc", label: "Скор ↑" },
  { value: "date_desc", label: "Дата ↓" },
  { value: "date_asc", label: "Дата ↑" },
]

export function JobsToolbar({
  jobs,
  filters,
  onChange,
  onReset,
  view,
  onViewChange,
  sort,
  onSortChange,
  activeCount,
}: {
  jobs: Job[]
  filters: JobFilters
  onChange: <K extends keyof JobFilters>(key: K, value: JobFilters[K]) => void
  onReset: () => void
  view: JobsView
  onViewChange: (view: JobsView) => void
  sort: SortKey
  onSortChange: (sort: SortKey) => void
  activeCount?: number
}) {
  const { shouldShow, dismissHint } = useOnboardingHints()
  const showSourceFilter = sourceFilterEligible(jobs)
  const { data: searchTracks } = useSearchTrack()
  const showTrackFilter = Boolean(searchTracks?.second_job_enabled)
  const active = filtersActive(effectiveJobFilters(filters, showTrackFilter))
  const searching = searchActive(filters)
  // Фаза 7.5: очередь «на ручной разбор» автооткликов — раньше видна только внутри раскрытой
  // секции «Автоотклики» в «Расширении», теперь фильтр прямо на доске. Переиспользует `ids`
  // (тот же канал, что точечные списки из «Рынка», L-01) — включение снимает период, иначе
  // вакансия старше 7 дней («Просмотрено» может лежать давно) пропадала бы молча.
  const manualReviewIds = useAutoApplyManualReviewIds()
  const manualReviewOn =
    manualReviewIds.length > 0 &&
    filters.ids.length === manualReviewIds.length &&
    filters.ids.every((id) => manualReviewIds.includes(id))
  const toggleManualReview = () => {
    if (manualReviewOn) {
      onChange("ids", [])
      return
    }
    onChange("ids", manualReviewIds)
    onChange("scoredFrom", "")
    onChange("scoredTo", "")
  }
  // Фаза 3.3/3.4: очередь подтверждения владельца — анкета работодателя ИЛИ (с 3.4) простое
  // подтверждение письма в режиме «Тест» без анкеты. Тот же паттерн, что «На разборе
  // автооткликов» выше (фильтр по ids, снимает период по той же причине).
  const anketaPendingIds = useAnketaPendingIds()
  const anketaPendingOn =
    anketaPendingIds.length > 0 &&
    filters.ids.length === anketaPendingIds.length &&
    filters.ids.every((id) => anketaPendingIds.includes(id))
  const toggleAnketaPending = () => {
    if (anketaPendingOn) {
      onChange("ids", [])
      return
    }
    onChange("ids", anketaPendingIds)
    onChange("scoredFrom", "")
    onChange("scoredTo", "")
  }
  // Поиск применяется явно (кнопка / Enter), а не на каждый символ — на канбане остаются вакансии
  // под запрос только после применения. Черновик синхронизируем с внешним сбросом фильтров через
  // подстройку состояния во время рендера (паттерн React без эффекта).
  const [draft, setDraft] = useState(filters.search)
  const [lastSearch, setLastSearch] = useState(filters.search)
  if (filters.search !== lastSearch) {
    setLastSearch(filters.search)
    setDraft(filters.search)
  }
  const applySearch = () => onChange("search", draft.trim())
  const clearSearch = () => {
    setDraft("")
    onChange("search", "")
  }
  // Пустой filters.sources семантически значит «любой источник» (см. use-job-filters) — и по
  // умолчанию все площадки визуально выделены (правка 2026-08-19 п.3), а не выглядят как
  // «ничего не выбрано». Клик по одной сворачивает пустой массив в явный список остальных;
  // если явный список набирает всех обратно — схлопываем его назад в пустой (симметрично).
  const allSourcesSelected = filters.sources.length === 0
  const toggleSource = (g: SourceGroup) => {
    const current = allSourcesSelected ? SOURCE_GROUPS : filters.sources
    const has = current.includes(g)
    const next = has ? current.filter((x) => x !== g) : [...current, g]
    onChange(
      "sources",
      (next.length === SOURCE_GROUPS.length ? [] : next) as JobFilters["sources"],
    )
  }

  return (
    <div id="screen-start-jobs" className="shrink-0 space-y-3 border-b bg-background px-6 py-3">
      {/* Поиск — во всю ширину, заметный, применяется кнопкой/Enter; справа от него — источник,
          сортировка и переключалка вида. Сбросить (когда есть активные фильтры) — фиксированной
          строкой под переключалкой вида, у правого края, а не среди чипов фильтров ниже: так его
          проще найти взглядом и он не скачет по строке при появлении/исчезновении других чипов. */}
      <div className="flex items-start gap-2">
        <div className="relative flex-1">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400"
            strokeWidth={2}
          />
          <Input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") applySearch()
            }}
            placeholder="Поиск по вакансии, компании или ID"
            className="h-11 w-full rounded-xl pl-10 pr-9 text-base"
          />
          {draft && (
            <button
              type="button"
              onClick={clearSearch}
              aria-label="Очистить поиск"
              className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 transition-colors hover:text-slate-700"
            >
              <X className="size-4" strokeWidth={2} />
            </button>
          )}
        </div>

        {showSourceFilter && (
          <div
            role="group"
            aria-label="Источник"
            className="flex h-11 shrink-0 items-center gap-1 rounded-xl border border-slate-200 px-1.5"
          >
            {SOURCE_GROUPS.map((g) => {
              const on = allSourcesSelected || filters.sources.includes(g)
              return (
                <button
                  key={g}
                  type="button"
                  aria-pressed={on}
                  aria-label={`Источник: ${SOURCE_GROUP_LABEL[g]}`}
                  title={SOURCE_GROUP_LABEL[g]}
                  onClick={() => toggleSource(g)}
                  className={cn(
                    "flex size-8 items-center justify-center rounded-lg border transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400",
                    on
                      ? "border-slate-300 bg-slate-100 opacity-100 shadow-inner"
                      : "border-transparent opacity-40 hover:bg-slate-50 hover:opacity-70",
                  )}
                >
                  <SourceIcon group={g} />
                </button>
              )
            })}
          </div>
        )}

        <Select value={sort} onValueChange={(v) => onSortChange(v as SortKey)}>
          <SelectTrigger
            className="h-11 shrink-0 rounded-xl px-3 text-sm font-medium"
            aria-label="Сортировка"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SORT_OPTIONS.map((opt) => (
              <SelectItem key={opt.value} value={opt.value} className="font-medium">
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <div className="flex h-11 shrink-0 items-center gap-1 rounded-xl border border-slate-200 px-1">
          {/* Подсказка про расширение — только на пустой воронке (иначе назойливо на каждом заходе). */}
          <OnboardingHint
            open={jobs.length === 0 && shouldShow(ONBOARDING_HINT_IDS.jobsExtension)}
            onDismiss={() => dismissHint(ONBOARDING_HINT_IDS.jobsExtension)}
            side="bottom"
            align="end"
            content="Новые вакансии попадают сюда через расширение Chrome: откройте вакансию на hh.ru или getmatch.ru и оцените её в панели справа."
          >
            <Tabs value={view} onValueChange={(v) => onViewChange(v as JobsView)}>
              <TabsList className="h-auto bg-transparent p-0">
                {VIEWS.map(({ value, label, Icon }) => (
                  <TabsTrigger
                    key={value}
                    value={value}
                    aria-label={label}
                    title={
                      value === "board"
                        ? getHelpText("jobs.view-board")
                        : getHelpText("jobs.view-list")
                    }
                    className="px-3 py-2 data-[state=active]:bg-slate-900 data-[state=active]:text-white data-[state=active]:shadow-none"
                  >
                    <Icon className="size-4" strokeWidth={2} />
                    {label}
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>
          </OnboardingHint>
        </div>
      </div>

      {/* Фильтры — все чипы слева в одной строке, «Сбросить» фиксированно у правого края этой же
          строки (правка 2026-08-19): раньше кнопка стояла в стеке над переключалкой вида в первой
          строке и при появлении раздвигала первую строку по высоте, из-за чего фильтры ниже
          визуально «съезжали» на следующую строку. */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-1 flex-wrap items-center gap-x-3 gap-y-2">
          {activeCount != null && (
            <span className="inline-flex items-center gap-1.5 text-sm text-slate-500">
              <span className="text-lg font-semibold tabular-nums text-slate-900">{activeCount}</span>
              <span>активных</span>
              <HelpTip id="jobs.active-count" />
            </span>
          )}

          <span className="inline-flex items-center gap-1">
            <DateRangeFilter
              from={filters.scoredFrom}
              to={filters.scoredTo}
              onChange={(from, to) => {
                onChange("scoredFrom", from)
                onChange("scoredTo", to)
              }}
            />
            <HelpTip id="jobs.date-range" />
            {/* Поиск идёт по всей воронке (filterJobs игнорирует период при непустом запросе) —
                говорим это прямо, иначе выставленный период читается как активное ограничение. */}
            {searching && filters.scoredFrom !== "" && (
              <span className="text-xs text-slate-400">период не применён — идёт поиск</span>
            )}
          </span>

          {showTrackFilter && (
            <span className="inline-flex items-center gap-1">
              <ChipToggleGroup
                options={TRACK_FILTER_OPTIONS}
                value={[filters.track || "all"]}
                onChange={(next) => {
                  const raw = next[0] ?? "all"
                  onChange("track", raw === "all" ? "" : (raw as JobTrack))
                }}
                multiple={false}
                allowEmpty={false}
              />
              <HelpTip id="jobs.filter-track" />
            </span>
          )}

          {/* Скор — ползунок 0..100, шаг 10, с отсечками */}
          <div className="flex h-8 items-center gap-2.5">
            <span className="inline-flex w-auto shrink-0 items-center gap-1 text-sm font-medium tabular-nums text-slate-500">
              {filters.minScore > 0 ? `Скор от ${filters.minScore}` : "Скор от"}
              <HelpTip id="jobs.score-slider" />
            </span>
            <div className="w-44">
              <Slider
                min={0}
                max={100}
                step={10}
                value={[filters.minScore]}
                onValueChange={([v]) => onChange("minScore", v)}
                aria-label="Минимальный скор"
              />
              <div className="mt-1 flex justify-between px-0.5">
                {SCORE_TICKS.map((t) => (
                  <span key={t} className="text-xs tabular-nums text-slate-300">
                    {t}
                  </span>
                ))}
              </div>
            </div>
          </div>

          {manualReviewIds.length > 0 && (
            <span className="inline-flex items-center gap-1">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-pressed={manualReviewOn}
                onClick={toggleManualReview}
                className={cn(
                  "border",
                  manualReviewOn
                    ? "border-amber-300 bg-amber-100 text-amber-900 hover:bg-amber-200"
                    : "border-amber-200 bg-amber-50 text-amber-800 hover:bg-amber-100",
                )}
              >
                На разборе автооткликов ({manualReviewIds.length})
              </Button>
              <HelpTip id="jobs.auto-apply-review" />
            </span>
          )}

          {anketaPendingIds.length > 0 && (
            <span className="inline-flex items-center gap-1">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-pressed={anketaPendingOn}
                onClick={toggleAnketaPending}
                className={cn(
                  "border",
                  anketaPendingOn
                    ? "border-sky-300 bg-sky-100 text-sky-900 hover:bg-sky-200"
                    : "border-sky-200 bg-sky-50 text-sky-800 hover:bg-sky-100",
                )}
              >
                На подтверждении ({anketaPendingIds.length})
              </Button>
              <HelpTip id="jobs.anketa-pending" />
            </span>
          )}

          {/* Статус воронки — только в списке (в доске статус = колонка) */}
          {view === "list" && (
            <span className="inline-flex items-center gap-1">
              <ChipToggleGroup
                options={STATUS_OPTIONS}
                value={filters.statuses}
                onChange={(next) => onChange("statuses", next as JobFilters["statuses"])}
              />
              <HelpTip id="jobs.filter-chips" />
            </span>
          )}
        </div>

        {active && (
          <Button
            variant="ghost"
            size="sm"
            onClick={onReset}
            className="shrink-0 border border-rose-200 bg-rose-50 text-rose-600 hover:bg-rose-100 hover:text-rose-700"
          >
            <RotateCcw className="size-4" strokeWidth={2} />
            Сбросить
          </Button>
        )}
      </div>
    </div>
  )
}
