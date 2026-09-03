import { useMemo } from "react"
import { AlertTriangle } from "lucide-react"
import type { AdminUserRow } from "@/api/admin"
import { ErrorState } from "@/components/ui/empty-state"
import { SectionCard } from "@/components/ui/section-card"
import { Skeleton } from "@/components/ui/skeleton"
import { useAdminSummary } from "@/features/admin/use-admin"
import { buildDashboardMetrics } from "@/features/admin/dashboard-metrics"
import type { AdminFilters } from "@/features/admin/admin-filters"
import { DashboardMetrics } from "@/features/admin/components/DashboardMetrics"
import { SpendCard } from "@/features/admin/components/SpendCard"
import { PeopleSection } from "@/features/admin/sections/PeopleSection"

/**
 * Пульт: метрики во всю ширину, люди, деньги.
 */
export function DashboardSection({
  enabled,
  people,
  loading,
  fetching,
  selectedId,
  onSelect,
  filters,
  onFiltersChange,
}: {
  enabled: boolean
  people: readonly AdminUserRow[]
  loading: boolean
  fetching: boolean
  selectedId: number | null
  onSelect: (accountId: number) => void
  filters: AdminFilters
  onFiltersChange: (next: AdminFilters) => void
}) {
  const summary = useAdminSummary(enabled)
  const metrics = useMemo(() => buildDashboardMetrics(summary.data), [summary.data])

  return (
    <div className="flex flex-col gap-4 px-6 pb-6 pt-6">
      <SectionCard
        title="Метрики"
        helpId="admin.health"
        status={summary.isError ? "error" : metrics.length === 0 ? "loading" : "content"}
        refreshing={summary.isFetching}
        loading={<Skeleton className="h-20 w-full" />}
        error={
          <ErrorState
            compact
            icon={AlertTriangle}
            title="Метрики не загрузились"
            note="Не удалось получить состояние установки."
            action={{ label: "Повторить", onClick: () => void summary.refetch() }}
          />
        }
      >
        <DashboardMetrics items={metrics} />
      </SectionCard>

      <PeopleSection
        people={people}
        loading={loading}
        fetching={fetching}
        selectedId={selectedId}
        onSelect={onSelect}
        filters={filters}
        onFiltersChange={onFiltersChange}
        spendAlertUsd={summary.data?.spend_alert_usd ?? 0}
      />

      <SpendCard enabled={enabled} />
    </div>
  )
}
