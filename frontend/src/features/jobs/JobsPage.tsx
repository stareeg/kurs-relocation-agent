import { useEffect, useMemo, useRef } from "react"
import { useSearchParams } from "react-router-dom"
import { Kanban } from "lucide-react"
import { EmptyState, ErrorState } from "@/components/ui/empty-state"
import { Skeleton, SkeletonCard } from "@/components/ui/skeleton"
import { OnboardingHint } from "@/components/ui/tooltip"
import { ONBOARDING_HINT_IDS, useOnboardingHints } from "@/lib/use-onboarding-hints"
import { isResumeFilled } from "@/features/resume/resume-filled"
import { useResumeData } from "@/features/resume/use-resume"
import { useAppSettings } from "@/features/settings/use-settings"
import { countActiveJobs } from "./funnel"
import { useActiveJobsCount, useJobs } from "./use-jobs"
import { JobsWorkspace } from "./JobsWorkspace"
import {
  filterJobs,
  filtersActive,
  filtersFromSearchParams,
  FILTER_PARAM_KEYS,
  useJobFilters,
  effectiveJobFilters,
} from "./use-job-filters"
import { useSearchTrack } from "@/features/career/search-track"

function BoardSkeleton() {
  return (
    <div className="flex gap-4 p-6">
      {[0, 1, 2, 3].map((c) => (
        <div key={c} className="w-64 shrink-0 space-y-3">
          <Skeleton className="h-4 w-24" />
          {[0, 1].map((i) => (
            <SkeletonCard key={i} className="h-20" />
          ))}
        </div>
      ))}
    </div>
  )
}

export function JobsPage() {
  const {
    data: jobs,
    isLoading,
    isError,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
    columnCounts,
    refetch,
  } = useJobs()
  const { data: appSettings } = useAppSettings()
  const { data: resume } = useResumeData()
  const { data: activeCountData } = useActiveJobsCount()
  const { filters, update, reset, applyFilters } = useJobFilters()
  const { data: searchTracks } = useSearchTrack()
  const { shouldShow, dismissHint } = useOnboardingHints()

  // L-01: ссылка из «Рынка» (и других разделов) сеет фильтры доски через query-параметры —
  // применяем один раз при заходе на страницу и убираем их из адреса, чтобы дальше фильтрами
  // управлял только тулбар (тот же приём стрип-после-применения, что и deep-link вакансии).
  const [searchParams, setSearchParams] = useSearchParams()
  const appliedDeepLinkRef = useRef(false)
  useEffect(() => {
    if (appliedDeepLinkRef.current) return
    appliedDeepLinkRef.current = true
    const partial = filtersFromSearchParams(searchParams)
    if (!partial) return
    applyFilters(partial)
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        for (const key of FILTER_PARAM_KEYS) next.delete(key)
        return next
      },
      { replace: true },
    )
  }, [searchParams, applyFilters, setSearchParams])
  const hasJobs = (jobs?.length ?? 0) > 0
  const showExtensionOnboarding =
    Boolean(appSettings?.openrouter_key_configured) &&
    Boolean(resume && isResumeFilled(resume)) &&
    !hasJobs

  // Счётчик: без фильтров — точное число с бэка (не зависит от limit выборки); с фильтрами —
  // активные среди отфильтрованных на клиенте.
  const secondJobOn = Boolean(searchTracks?.second_job_enabled)
  const activeCount = useMemo(() => {
    const applied = effectiveJobFilters(filters, secondJobOn)
    if (filtersActive(applied)) return countActiveJobs(filterJobs(jobs ?? [], applied))
    return activeCountData?.count ?? countActiveJobs(jobs ?? [])
  }, [jobs, filters, secondJobOn, activeCountData?.count])

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {isLoading ? (
        <BoardSkeleton />
      ) : isError ? (
        <ErrorState
          icon={Kanban}
          title="Воронка недоступна"
          note="Не удалось загрузить вакансии."
          action={{ label: "Повторить", onClick: () => void refetch() }}
        />
      ) : !hasJobs ? (
        <OnboardingHint
          open={shouldShow(ONBOARDING_HINT_IDS.jobsExtension)}
          onDismiss={() => dismissHint(ONBOARDING_HINT_IDS.jobsExtension)}
          side="bottom"
          align="center"
          content="Новые вакансии попадают сюда через расширение Chrome: откройте вакансию на hh.ru или getmatch.ru и оцените её в панели справа."
        >
          <div id="screen-start-jobs" className="flex min-h-0 flex-1 flex-col">
            <EmptyState
              icon={Kanban}
              title="Вакансий пока нет"
              note={
                showExtensionOnboarding
                  ? "Ключ и резюме на месте — осталось установить расширение и оценить первую вакансию на hh.ru или getmatch.ru."
                  : "Оцени вакансию через расширение или чат — она появится в воронке."
              }
              action={
                showExtensionOnboarding
                  ? { label: "Установите расширение", to: "/extension" }
                  : { label: "Обновить", onClick: () => void refetch() }
              }
            />
          </div>
        </OnboardingHint>
      ) : (
        <JobsWorkspace
          jobs={jobs ?? []}
          filters={filters}
          update={update}
          reset={reset}
          activeCount={activeCount}
          columnCounts={columnCounts}
          hasMore={Boolean(hasNextPage)}
          loadingMore={isFetchingNextPage}
          onLoadMore={() => void fetchNextPage()}
        />
      )}
    </div>
  )
}
