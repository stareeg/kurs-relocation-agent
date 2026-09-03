import { useEffect, useMemo } from "react"
import {
  useInfiniteQuery,
  useQuery,
  useQueryClient,
  type InfiniteData,
  type QueryClient,
} from "@tanstack/react-query"
import {
  fetchActiveJobsCount,
  fetchJobsPage,
  fetchJobStageCounts,
  type Job,
  type JobsPageResponse,
} from "@/api/jobs"
import { useLiveEventsConnected } from "@/app/use-live-invalidation"

const PAGE_SIZE = 200
// Автодогрузка страниц (L-30) идёт сама, пока их не больше этого числа (~4000 вакансий) — на
// реальном объёме владельца (сотни) это 1-3 быстрых запроса подряд, и фильтры/поиск/бейджи колонок
// видят весь набор сразу, как до пагинации. Выше потолка — дальше только вручную («Показать ещё»),
// иначе первый визит на действительно большой доске бил бы по SLO открытия страницы.
const AUTO_LOAD_PAGES = 20

// Вакансии воронки (L-30: курсорная пагинация вместо одного `limit` на клиент). Чат на SSE done
// инвалидирует ["jobs"] (5.2) — после скоринга/синка статусов канбан освежается; staleTime
// умеренный. L-45: живой канал `/api/events/stream` инвалидирует ["jobs"] на VacancyScored/
// ApplicationStageChanged/HrMessageReceived/OfferReceived — фиксированный refetchInterval
// остаётся только фолбэком, пока канал не подключён. `data` остаётся плоским списком уже
// догруженных страниц (как раньше был Job[]) — все текущие потребители (AppShell, чат,
// техничка, офферы, скрининг, доска) не меняются; доска дополнительно берёт
// hasNextPage/fetchNextPage/columnCounts из того же хука.
export function useJobs() {
  const liveConnected = useLiveEventsConnected()
  const query = useInfiniteQuery({
    queryKey: ["jobs"],
    queryFn: ({ pageParam }: { pageParam: string | undefined }) =>
      fetchJobsPage({ cursor: pageParam, limit: PAGE_SIZE }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    staleTime: 20_000,
    refetchInterval: liveConnected ? false : 30_000,
  })
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = query
  const pageCount = query.data?.pages.length ?? 0
  useEffect(() => {
    if (hasNextPage && !isFetchingNextPage && pageCount < AUTO_LOAD_PAGES) {
      void fetchNextPage()
    }
  }, [hasNextPage, isFetchingNextPage, pageCount, fetchNextPage])
  const jobs = useMemo(() => query.data?.pages.flatMap((p) => p.jobs), [query.data])
  // column_counts приходит только на первой странице (см. fetchJobsPage) — берём её оттуда.
  const columnCounts = query.data?.pages[0]?.column_counts ?? undefined
  return { ...query, data: jobs, columnCounts }
}

// Фон досчитывает вилку зарплаты после скоринга (estimate_pending) и по завершении публикует
// VacancyScored, который сам инвалидирует ["jobs"] (см. use-live-invalidation) — но пока канал
// разорван/переподключается, это единственный фолбэк: без него шапка чата/дровер молча висят на
// «оценка…», если не открыт ровно тот экран, что успел заметить инвалидацию. Общий для дровера и
// диалога вакансии в Чатах — раньше жил только в дровере, поэтому в Чатах и повисало навечно.
export function usePendingSalaryRefresh(pending: boolean): void {
  const qc = useQueryClient()
  useEffect(() => {
    if (!pending) return
    const id = window.setInterval(() => {
      void qc.invalidateQueries({ queryKey: ["jobs"] })
    }, 2500)
    return () => window.clearInterval(id)
  }, [pending, qc])
}

export function useActiveJobsCount() {
  const liveConnected = useLiveEventsConnected()
  return useQuery({
    queryKey: ["jobs", "active-count"],
    queryFn: fetchActiveJobsCount,
    staleTime: 20_000,
    refetchInterval: liveConnected ? false : 30_000,
  })
}

// P-05: лёгкий бейдж «Скрининг» в шелле не должен тянуть всю доску (`useJobs()` — до 4000
// вакансий, AUTO_LOAD_PAGES). `/api/jobs/stage-counts` — тот же `count_jobs_by_column`, что
// раньше приезжал только внутри первой страницы `/api/jobs`.
export function useJobStageCounts() {
  const liveConnected = useLiveEventsConnected()
  return useQuery({
    queryKey: ["jobs", "stage-counts"],
    queryFn: fetchJobStageCounts,
    staleTime: 20_000,
    refetchInterval: liveConnected ? false : 30_000,
  })
}

// --- Оптимистичные апдейты кэша ["jobs"] вне хука (use-job-stage/use-skip/use-cover-letter/
// use-job-apply-fields) ---
// Реальная форма записи в кэше — InfiniteData<JobsPageResponse> (страницы), не плоский Job[]
// (L-30). Хелперы централизуют маппинг по страницам, чтобы 4 места оптимистичных апдейтов не
// дублировали структуру постранично.
export type JobsCacheData = InfiniteData<JobsPageResponse, string | undefined>

export function getJobsCache(qc: QueryClient): JobsCacheData | undefined {
  return qc.getQueryData<JobsCacheData>(["jobs"])
}

export function setJobsCache(qc: QueryClient, data: JobsCacheData | undefined) {
  qc.setQueryData<JobsCacheData>(["jobs"], data)
}

export function findJobInCache(qc: QueryClient, predicate: (job: Job) => boolean): Job | undefined {
  return getJobsCache(qc)
    ?.pages.flatMap((p) => p.jobs)
    .find(predicate)
}

// `map` — та же сигнатура, что раньше была у `Job[].map(...)`: вернуть job как есть, если он не
// целевой, иначе — обновлённую копию.
export function patchJobsCache(qc: QueryClient, map: (job: Job) => Job) {
  qc.setQueryData<JobsCacheData>(
    ["jobs"],
    (old) =>
      old && {
        ...old,
        pages: old.pages.map((page) => ({ ...page, jobs: page.jobs.map(map) })),
      },
  )
}

// Удаление вакансии (use-delete-job): убрать карточку из всех страниц кэша, не дожидаясь
// инвалидации ["jobs"] — та же оптимистичная схема, что patchJobsCache, только фильтр вместо map.
export function removeJobFromCache(qc: QueryClient, id: number) {
  qc.setQueryData<JobsCacheData>(
    ["jobs"],
    (old) =>
      old && {
        ...old,
        pages: old.pages.map((page) => ({
          ...page,
          jobs: page.jobs.filter((j) => j.id !== id),
        })),
      },
  )
}
