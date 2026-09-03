import { useCallback, useEffect, useMemo, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { Loader2, SearchX } from "lucide-react"
import { toast } from "sonner"
import { ApiError } from "@/api/client"
import { fetchJobByVacancyId, type Job } from "@/api/jobs"
import { Button } from "@/components/ui/button"
import { EmptyState } from "@/components/ui/empty-state"
import { usePersistedRouteState } from "@/lib/use-persisted-route-state"
import { bucketByStage, type BoardColumn } from "./funnel"
import {
  filterJobs,
  filtersActive,
  sortJobs,
  effectiveJobFilters,
  type JobFilters,
  type SortKey,
} from "./use-job-filters"
import { JobsToolbar, type JobsView } from "./JobsToolbar"
import { JobsBoard } from "./JobsBoard"
import { JobsList } from "./JobsList"
import { JobDetailDrawer } from "./JobDetailDrawer"
import { useSearchTrack } from "@/features/career/search-track"

// «Фильтры обнулили выдачу» (отличается от пустой воронки в JobsPage — там вакансий нет вообще).
function FilteredEmpty({ onReset }: { onReset: () => void }) {
  return (
    <EmptyState
      variant="filtered"
      icon={SearchX}
      title="Ничего не найдено"
      note="Под текущие фильтры нет вакансий."
      action={{ label: "Сбросить фильтры", onClick: onReset }}
    />
  )
}

// Полоса догрузки (L-30): под доской/списком, когда сервер отдал не всё за один курсор. Тотал —
// точный (column_counts с бэка), только пока фильтры не сужают выдачу (иначе он не про то, что
// реально на экране — тот же приём, что activeCount в JobsPage).
function LoadMoreBar({
  loadedCount,
  totalCount,
  hasMore,
  loading,
  onLoadMore,
}: {
  loadedCount: number
  totalCount?: number
  hasMore: boolean
  loading: boolean
  onLoadMore: () => void
}) {
  if (!hasMore) return null
  return (
    <div className="flex shrink-0 items-center justify-center gap-3 border-t bg-background py-2.5">
      {totalCount != null && (
        <span className="text-xs tabular-nums text-slate-400">
          Показано {loadedCount} из {totalCount}
        </span>
      )}
      <Button variant="outline" size="sm" onClick={onLoadMore} disabled={loading}>
        {loading ? <Loader2 className="size-3.5 animate-spin" strokeWidth={2} /> : null}
        {loading ? "Загрузка…" : "Показать ещё"}
      </Button>
    </div>
  )
}

// Рабочий стол вакансий (JS-1.3): тулбар фильтров + доска или список + общий дровер. Фильтры
// держит JobsPage (нужны для счётчика в шапке) и прокидывает сюда. Сортировка — общий выбор
// тулбара (скор/дата, убыв./возр.), применяется и к доске (внутри колонок), и к списку.
export function JobsWorkspace({
  jobs,
  filters,
  update,
  reset,
  activeCount,
  columnCounts,
  hasMore = false,
  loadingMore = false,
  onLoadMore,
}: {
  jobs: Job[]
  filters: JobFilters
  update: <K extends keyof JobFilters>(key: K, value: JobFilters[K]) => void
  reset: () => void
  activeCount?: number
  // Точные тоталы по колонкам с бэка (L-30) — только на первой странице курсора; доска показывает
  // их вместо длины уже догруженного массива, пока фильтры не активны (см. JobsBoard).
  columnCounts?: Record<string, number>
  hasMore?: boolean
  loadingMore?: boolean
  onLoadMore?: () => void
}) {
  const navigate = useNavigate()
  // Deep-link из расширения: /jobs/:vacancyId открывает дровер (hh id или gm_*).
  const { vacancyId } = useParams<{ vacancyId?: string }>()
  // Вид (доска/список) — F-09: sessionStorage вкладки вместо модульного синглтона, переживает F5.
  const [viewRaw, setViewRaw] = usePersistedRouteState<JobsView>({
    storageKey: "jobs-view",
    fallback: "board",
  })
  const view = viewRaw ?? "board"
  // Сортировка — тот же приём, что вид: sessionStorage вкладки, переживает переход в другой раздел
  // и обратно (UI-запрошено явно — до этого была захардкожена по виду).
  const [sortRaw, setSort] = usePersistedRouteState<SortKey>({
    storageKey: "jobs-sort",
    fallback: "date_desc",
  })
  const sort = sortRaw ?? "date_desc"
  const [selectedId, setSelectedId] = useState<number | null>(null)

  const { data: searchTracks } = useSearchTrack()
  const secondJobOn = Boolean(searchTracks?.second_job_enabled)
  const filtered = useMemo(
    () => filterJobs(jobs, effectiveJobFilters(filters, secondJobOn)),
    [jobs, filters, secondJobOn],
  )
  const groupByTrack = secondJobOn && !filters.track
  const sorted = useMemo(
    () => sortJobs(filtered, sort, { groupByTrack }),
    [filtered, sort, groupByTrack],
  )
  const columns = useMemo(() => bucketByStage(sorted), [sorted])
  const listJobs = sorted
  // Бейджи колонок (L-30): без фильтров — точный тотал с бэка (не зависит от того, что уже
  // догружено курсором); с фильтрами — то же, что раньше: длина отфильтрованно-догруженного
  // среза, иначе бейдж расходится с реально показанными карточками (зеркалит activeCount выше).
  const filtersOn = filtersActive(effectiveJobFilters(filters, secondJobOn))
  const badgeCounts: Partial<Record<BoardColumn, number>> = useMemo(() => {
    if (!filtersOn && columnCounts) return columnCounts as Partial<Record<BoardColumn, number>>
    return Object.fromEntries(columns.map((c) => [c.stage, c.jobs.length]))
  }, [filtersOn, columnCounts, columns])
  const totalAll =
    !filtersOn && columnCounts ? Object.values(columnCounts).reduce((a, b) => a + b, 0) : undefined
  const open = useCallback((job: Job) => setSelectedId(job.id ?? null), [])

  // Пришли по deep-link `/jobs/:vacancyId` — подобрать вакансию по vacancy_id и открыть дровер.
  // Подстройка состояния во время рендера (паттерн React без эффекта): срабатывает на смену
  // параметра и на догрузку списка вакансий, открывает каждую целевую вакансию один раз. Сброс при
  // снятии параметра (закрытие дровера) позволяет переоткрыть ту же вакансию по повторному deep-link.
  const [openedForVacancy, setOpenedForVacancy] = useState<string | null>(null)
  if (!vacancyId) {
    if (openedForVacancy !== null) setOpenedForVacancy(null)
  } else if (vacancyId !== openedForVacancy) {
    const match = jobs.find((j) => j.vacancy_id === vacancyId)
    if (match?.id != null) {
      setOpenedForVacancy(vacancyId)
      setSelectedId(match.id)
    }
  }

  // F-08: вакансии из deep-link нет среди уже догруженных страниц курсора (ссылка из расширения
  // на вакансию за пределами автодогрузки, или до того, как она успела подъехать) — точечный
  // запрос по vacancy_id вместо тишины. `pendingLookup` держит его выключенным, как только
  // вакансия найдена локально или лукап уже начат/завершён для этого vacancyId.
  const pendingLookup = vacancyId != null && vacancyId !== openedForVacancy
  const { data: lookedUpJob, error: lookupError } = useQuery({
    queryKey: ["jobs", "by-vacancy", vacancyId],
    queryFn: () => fetchJobByVacancyId(vacancyId as string),
    enabled: pendingLookup,
    retry: false,
    staleTime: Infinity,
  })
  if (pendingLookup && lookedUpJob?.id != null) {
    setOpenedForVacancy(vacancyId)
    setSelectedId(lookedUpJob.id)
  }
  // Точечный запрос не нашёл вакансию (или упал) — явное сообщение и снятие параметра, иначе
  // тост повторялся бы на каждом рендере, пока deep-link висит в URL.
  useEffect(() => {
    if (!pendingLookup || !lookupError) return
    toast.error(
      lookupError instanceof ApiError && lookupError.status === 404
        ? `Вакансия ${vacancyId} не найдена`
        : "Не удалось найти вакансию",
    )
    navigate("/jobs", { replace: true })
  }, [pendingLookup, lookupError, vacancyId, navigate])

  // Открытую вакансию ищем в полном списке (не в отфильтрованном): правка фильтров при открытом
  // дровере его не схлопнет, а после правки полей свежий объект из кэша долетит в дровер.
  // Если она пришла из точечного лукапа (F-08) и ещё не долетела до догруженных страниц —
  // используем её напрямую, а не отфильтрованный `jobs`.
  const selected = useMemo(() => {
    const fromBoard = jobs.find((j) => j.id === selectedId) ?? null
    if (fromBoard) return fromBoard
    return lookedUpJob?.id === selectedId ? lookedUpJob : null
  }, [jobs, selectedId, lookedUpJob])

  // В доске статус = колонка, и его чипы скрыты. Чтобы при возврате из списка не остался невидимый
  // фильтр статуса, сбрасываем его при входе в доску. Вид запоминаем в синглтоне.
  const changeView = useCallback(
    (next: JobsView) => {
      setViewRaw(next)
      if (next === "board") update("statuses", [])
    },
    [update, setViewRaw],
  )

  return (
    <>
      <JobsToolbar
        jobs={jobs}
        filters={filters}
        onChange={update}
        onReset={reset}
        view={view}
        onViewChange={changeView}
        sort={sort}
        onSortChange={setSort}
        activeCount={activeCount}
      />
      {filtered.length === 0 ? (
        <FilteredEmpty onReset={reset} />
      ) : view === "board" ? (
        <JobsBoard columns={columns} onOpen={open} columnCounts={badgeCounts} />
      ) : (
        <JobsList jobs={listJobs} onOpen={open} />
      )}
      {onLoadMore && (
        <LoadMoreBar
          loadedCount={jobs.length}
          totalCount={totalAll}
          hasMore={hasMore}
          loading={loadingMore}
          onLoadMore={onLoadMore}
        />
      )}
      <JobDetailDrawer
        job={selected}
        onOpenChange={(o) => {
          if (o) return
          setSelectedId(null)
          // Снять deep-link параметр, иначе эффект переоткроет дровер на следующем обновлении кэша.
          if (vacancyId) navigate("/jobs", { replace: true })
        }}
      />
    </>
  )
}
