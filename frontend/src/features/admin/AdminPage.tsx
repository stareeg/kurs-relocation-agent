import { useCallback, useMemo } from "react"
import { Shield } from "lucide-react"
import { Navigate, useNavigate, useParams, useSearchParams } from "react-router-dom"
import { useAuthStatusQuery } from "@/features/auth/use-auth-status"
import { ErrorState } from "@/components/ui/empty-state"
import type { SegmentOption } from "@/components/ui/segmented-control"
import { useAdminAttention, useAdminPeople, useAdminSummary } from "@/features/admin/use-admin"
import { buildAttentionItems, buildVerdict } from "@/features/admin/attention"
import { buildHealthItems } from "@/features/admin/admin-health"
import {
  adminFiltersToParams,
  adminPersonPath,
  adminRedirectPath,
  adminSectionPath,
  parseAdminAccountId,
  parseAdminFilters,
  parseAdminUserTab,
  peopleApiStatus,
  resolveAdminSection,
  withPreservedTab,
  type AdminFilters,
  type AdminSection,
  type AdminUserTab,
  DEFAULT_ADMIN_USER_TAB,
} from "@/features/admin/admin-filters"
import { AdminHeader } from "@/features/admin/components/AdminHeader"
import { DashboardSection } from "@/features/admin/sections/DashboardSection"
import { JournalSection } from "@/features/admin/sections/JournalSection"
import { SystemSection } from "@/features/admin/sections/SystemSection"
import { UserDrawer } from "@/features/admin/user/UserDrawer"

const SECTIONS: readonly SegmentOption<AdminSection>[] = [
  { value: "dashboard", label: "Пульт" },
  { value: "system", label: "Действия" },
  { value: "journal", label: "Журнал" },
]

/**
 * Каркас операторской консоли: шапка-вердикт, три раздела, карточка человека.
 *
 * Пульт — голый `/admin`, Действия и Журнал — свои адреса, карточка — `/admin/person/12`.
 * Старые пять вкладок (`/admin/overview`, `/admin/people`, `/admin/keys`) приводит к новым
 * `adminRedirectPath`, чтобы закладки не отдавали 404. Ссылка воспроизводит экран, F5 не
 * сбрасывает выбор, «назад» закрывает карточку, а не раздел.
 *
 * Раздел десктоп-онли (§2.9): ниже 1024 px — честная заглушка вместо попытки ужать таблицы и
 * фильтры в ширину телефона.
 */
export function AdminPage() {
  const { data: authStatus } = useAuthStatusQuery()
  const isAdmin = Boolean(authStatus?.is_admin)
  const params = useParams<{ section?: string; accountId?: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()

  const redirectTo = adminRedirectPath(params.section, params.accountId, searchParams.toString())
  const section = resolveAdminSection(params.section)
  const filters = parseAdminFilters(searchParams)
  const selectedId = parseAdminAccountId(params.accountId)
  const userTab = parseAdminUserTab(searchParams)

  const summary = useAdminSummary(isAdmin)
  const attention = useAdminAttention(isAdmin)
  const people = useAdminPeople(isAdmin, {
    q: filters.q,
    status: peopleApiStatus(filters),
    onboarding: filters.onboarding,
    signal: filters.signal,
    sort: filters.sort,
  })

  // Вердикт считается, только когда приехали обе витрины. На пустых данных `buildVerdict`
  // честно вернул бы «Всё живо · дел нет» — и первую секунду после открытия раздел уверял бы,
  // что всё хорошо, ещё не спросив об этом сервер. При неполной сводке (`degraded`) фразы тоже
  // нет: над шапкой уже висит полоса, которая называет причину.
  const known = Boolean(summary.data && attention.data && !summary.data.degraded)
  const verdict = useMemo(
    () =>
      known
        ? buildVerdict(buildHealthItems(summary.data?.health), buildAttentionItems(attention.data))
        : undefined,
    [known, summary.data?.health, attention.data],
  )

  const goto = useCallback(
    (next: AdminSection) => {
      if (next === section) return
      navigate(adminSectionPath(next))
    },
    [navigate, section],
  )

  const setFilters = useCallback(
    (next: AdminFilters) =>
      setSearchParams(withPreservedTab(adminFiltersToParams(next), searchParams), { replace: true }),
    [searchParams, setSearchParams],
  )

  const setUserTab = useCallback(
    (next: AdminUserTab) => {
      const nextParams = new URLSearchParams(searchParams)
      if (next === DEFAULT_ADMIN_USER_TAB) nextParams.delete("tab")
      else nextParams.set("tab", next)
      setSearchParams(nextParams, { replace: true })
    },
    [searchParams, setSearchParams],
  )

  const openAccount = useCallback(
    (accountId: number) => navigate(adminPersonPath(accountId, searchParams.toString())),
    [navigate, searchParams],
  )

  const closeAccount = useCallback(() => {
    const next = new URLSearchParams(searchParams)
    next.delete("tab")
    const suffix = next.toString()
    const path = adminSectionPath(section)
    navigate(suffix ? `${path}?${suffix}` : path)
  }, [navigate, searchParams, section])

  if (redirectTo) {
    return <Navigate to={redirectTo} replace />
  }

  if (!isAdmin) {
    return (
      <div className="flex flex-1 items-center justify-center p-8">
        <p className="text-sm text-slate-500">Этот раздел доступен только оператору установки.</p>
      </div>
    )
  }

  if (summary.isError && people.isError) {
    return (
      <ErrorState
        icon={Shield}
        title="Сводка не загрузилась"
        note="Не удалось получить состояние установки."
        action={{
          label: "Повторить",
          onClick: () => {
            void summary.refetch()
            void people.refetch()
          },
        }}
      />
    )
  }

  const data = summary.data
  const rows = people.data?.items ?? []
  const refreshing = summary.isFetching || people.isFetching || attention.isFetching

  return (
    <>
      <div className="flex flex-1 items-center justify-center p-8 lg:hidden">
        <p className="max-w-xs text-center text-sm text-slate-500">
          Раздел рассчитан на широкий экран — откройте его на компьютере.
        </p>
      </div>

      <div className="hidden min-h-0 flex-1 flex-col overflow-hidden lg:flex">
        {data?.degraded && (
          <div className="shrink-0 border-b border-status-warn-line bg-status-warn-soft px-6 py-2 text-sm text-status-warn-fg">
            Сводка неполная: {data.degraded_reason || "часть запросов не ответила"}.
          </div>
        )}

        <AdminHeader
          sections={SECTIONS}
          section={section}
          onSection={goto}
          verdict={verdict}
          onVerdictClick={section === "dashboard" ? undefined : () => goto("dashboard")}
          updatedAt={summary.dataUpdatedAt}
          refreshing={refreshing}
          onRefresh={() => {
            void summary.refetch()
            void people.refetch()
            void attention.refetch()
          }}
        />

        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          <div className="min-h-0 flex-1 overflow-auto">
            {section === "journal" ? (
              <JournalSection
                enabled={isAdmin}
                searchParams={searchParams}
                onSearchParams={(next) => setSearchParams(next, { replace: true })}
              />
            ) : section === "system" ? (
              <SystemSection
                enabled={isAdmin}
                searchParams={searchParams}
                onSearchParams={(next) => setSearchParams(next, { replace: true })}
              />
            ) : (
              <DashboardSection
                enabled={isAdmin}
                people={rows}
                loading={people.isLoading}
                fetching={people.isFetching && !people.isLoading}
                selectedId={selectedId}
                onSelect={openAccount}
                filters={filters}
                onFiltersChange={setFilters}
              />
            )}
          </div>
        </div>

        <UserDrawer
          accountId={selectedId}
          onClose={closeAccount}
          people={rows}
          tab={userTab}
          onTabChange={setUserTab}
        />
      </div>
    </>
  )
}
