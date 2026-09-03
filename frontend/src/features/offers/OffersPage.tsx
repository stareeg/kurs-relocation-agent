import { useMemo } from "react"
import { Scale } from "lucide-react"
import { CollapsibleRail } from "@/components/job/CollapsibleRail"
import { RailChatButton } from "@/components/job/RailChatButton"
import { RailOfferActions } from "@/components/job/RailOfferActions"
import { VacancyCardRail } from "@/components/job/VacancyCardRail"
import { EmptyState, ErrorState } from "@/components/ui/empty-state"
import { Skeleton, SkeletonRail } from "@/components/ui/skeleton"
import { OnboardingHint } from "@/components/ui/tooltip"
import { usePersistedRouteState } from "@/lib/use-persisted-route-state"
import { ONBOARDING_HINT_IDS, useOnboardingHints } from "@/lib/use-onboarding-hints"
import { useJobs } from "@/features/jobs/use-jobs"
import { useOffers } from "./use-offers"
import { OffersChat } from "./OffersChat"
import { OffersRail } from "./OffersRail"

function OffersPageSkeleton() {
  return (
    <div className="space-y-3 p-6">
      <Skeleton className="h-9 w-80 rounded-lg" />
      <SkeletonRail className="gap-3" itemClassName="h-96 w-72" />
    </div>
  )
}

export function OffersPage() {
  const { data: offers, isLoading, isError, refetch } = useOffers()
  const { data: jobs } = useJobs()
  const { shouldShow, dismissHint } = useOnboardingHints()
  const hasOffers = (offers ?? []).length > 0
  // F-09/X-07: выбор — в URL (`?vacancy=`), чтобы переход из дровера вакансии («Оффер →»)
  // открывал раздел сразу на нужной вакансии, а не в общем виде.
  const [vacancyId, setVacancyId] = usePersistedRouteState<string>({
    param: "vacancy",
    storageKey: "offers-vacancy",
  })

  const offerIds = useMemo(() => new Set((offers ?? []).map((o) => o.vacancy_id)), [offers])
  const selectedJob = useMemo(
    () => (jobs ?? []).find((j) => j.vacancy_id === vacancyId) ?? null,
    [jobs, vacancyId],
  )
  const selectedNeedsOffer = Boolean(vacancyId && selectedJob && !offerIds.has(vacancyId))
  const draftJob = selectedNeedsOffer ? selectedJob : null

  if (isLoading) {
    return (
      <div className="flex min-h-0 flex-1 flex-col">
        <OffersPageSkeleton />
      </div>
    )
  }
  if (isError) {
    return (
      <div className="flex min-h-0 flex-1 flex-col">
        <div id="screen-start-offers" className="flex min-h-0 flex-1 flex-col">
          <ErrorState
            icon={Scale}
            title="Офферы сейчас не загрузились"
            note="Не удалось загрузить офферы."
            action={{ label: "Повторить", onClick: () => void refetch() }}
          />
        </div>
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-1">
      <CollapsibleRail storageKey="copilot.rail.offers.collapsed">
        <VacancyCardRail
          value={vacancyId}
          onChange={(j) => setVacancyId(j?.vacancy_id ?? null)}
          showGeneral={false}
          sort="byStage"
          stageOrder={["Оффер", "Финал"]}
          renderActions={(job) =>
            offerIds.has(job.vacancy_id ?? "") ? (
              <RailOfferActions vacancyId={job.vacancy_id!} />
            ) : (
              // Оффера ещё нет (черновик) — статусных кнопок нет, но вход в чат по вакансии
              // нужен так же, как в Скринингах/Техничках.
              <RailChatButton vacancyId={job.vacancy_id} />
            )
          }
        />
      </CollapsibleRail>

      <div id="screen-start-offers" className="flex min-h-0 min-w-0 flex-1 flex-col">
        <div className="min-h-0 flex-1 overflow-y-auto p-6">
          {hasOffers || draftJob ? (
            <OffersRail offers={offers ?? []} draftJob={draftJob} />
          ) : (
            <OnboardingHint
              open={shouldShow(ONBOARDING_HINT_IDS.offersEmpty)}
              onDismiss={() => dismissHint(ONBOARDING_HINT_IDS.offersEmpty)}
              side="top"
              align="center"
              content="Выберите вакансию в рельсе слева — появится карточка добавления."
            >
              <EmptyHint />
            </OnboardingHint>
          )}
        </div>
        <OffersChat />
      </div>
    </div>
  )
}

// Пустое состояние без офферов — тот же шаблон, что у EmptyState (D-09).
function EmptyHint() {
  return (
    <EmptyState
      icon={Scale}
      title="Здесь будут офферы в одном ряду"
        note="Выберите вакансию в рельсе слева — появится карточка добавления. Когда офферов станет несколько, спросите агента в чате ниже — он видит актуальные условия."
      action={{ label: "К воронке", to: "/jobs" }}
    />
  )
}
