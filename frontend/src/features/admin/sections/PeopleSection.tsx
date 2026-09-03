import { useMemo } from "react"
import { Loader2 } from "lucide-react"
import type { AdminUserRow } from "@/api/admin"
import { SectionCard } from "@/components/ui/section-card"
import { StatusChip } from "@/components/ui/status-chip"
import { AdminTable, type AdminColumn } from "@/features/admin/components/AdminTable"
import { AdminSearch } from "@/features/admin/components/AdminSearch"
import { PersonRowActions } from "@/features/admin/components/PersonRowActions"
import { PeopleFilters } from "@/features/admin/components/PeopleFilters"
import { PlatformAutomationDots } from "@/features/admin/components/PlatformAutomationDots"
import { StatusMark } from "@/features/admin/components/StatusMark"
import {
  DEFAULT_ADMIN_FILTERS,
  adminFiltersActive,
  isProblemPerson,
  toggleAdminSort,
  type AdminFilters,
  type AdminSortColumn,
} from "@/features/admin/admin-filters"
import { atHandle, relativeSeen, roleLabel, usd } from "@/features/admin/admin-format"
import { personHoverTitle } from "@/features/admin/person-title"
import { cn } from "@/lib/utils"

/**
 * Блок «Люди»: поиск и фильтр в шапке, список обновляется тем же шагом, что сводка (20 с).
 */
export function PeopleSection({
  people,
  loading,
  fetching = false,
  selectedId,
  onSelect,
  filters,
  onFiltersChange,
  spendAlertUsd = 0,
}: {
  people: readonly AdminUserRow[]
  loading: boolean
  fetching?: boolean
  selectedId: number | null
  onSelect: (accountId: number) => void
  filters: AdminFilters
  onFiltersChange: (next: AdminFilters) => void
  spendAlertUsd?: number
}) {
  const rows = useMemo(
    () => (filters.scope === "problem" ? people.filter((user) => isProblemPerson(user)) : people),
    [people, filters.scope],
  )
  const filtered = adminFiltersActive(filters)

  const columns: AdminColumn<AdminUserRow>[] = [
    {
      key: "person",
      title: "Человек",
      className: "max-w-[10rem]",
      render: (user) => <PersonCell user={user} spendAlertUsd={spendAlertUsd} />,
    },
    {
      key: "key",
      title: "Ключ",
      className: "w-16",
      render: (user) => (
        <StatusMark
          ok={user.has_openrouter_key}
          label={keyMarkLabel(user)}
        />
      ),
    },
    {
      key: "resume",
      title: "Резюме",
      className: "w-16",
      render: (user) => (
        <StatusMark ok={user.has_resume} label={user.has_resume ? "резюме есть" : "резюме нет"} />
      ),
    },
    {
      key: "extension",
      title: "Расширение",
      className: "w-24",
      render: (user) => (
        <StatusMark
          ok={user.extension_confirmed}
          label={user.extension_confirmed ? "расширение есть" : "расширения нет"}
        />
      ),
    },
    {
      key: "seen",
      title: "Был",
      sortable: true,
      sortKey: "last_seen",
      className: "w-20",
      render: (user) => (
        <span className="tabular-nums text-slate-600">{relativeSeen(user.last_seen_at)}</span>
      ),
    },
    {
      key: "automation",
      title: "Авто",
      className: "w-28",
      render: (user) => <PlatformAutomationDots pipeline={user.pipeline} />,
    },
    {
      key: "activity24",
      title: "24 ч",
      align: "right",
      className: "w-20",
      render: (user) => {
        const viewed = user.pipeline?.viewed_24h ?? 0
        const applied = user.pipeline?.applied_24h ?? 0
        if (viewed === 0 && applied === 0) return <span className="text-slate-300">—</span>
        return (
          <span
            className="tabular-nums text-slate-600"
            title={`Просмотрено ${viewed}, откликов ${applied} за 24 ч`}
          >
            {viewed}
            {" / "}
            <span className={applied > 0 ? "font-medium text-emerald-700" : undefined}>
              {applied}
            </span>
          </span>
        )
      },
    },
    {
      key: "jobs",
      title: "Вакансии",
      align: "right",
      sortable: true,
      sortKey: "jobs",
      className: "w-20",
      render: (user) => <span className="tabular-nums">{user.active_jobs}</span>,
    },
    {
      key: "cost_today",
      title: "Сегодня, $",
      align: "right",
      sortable: true,
      sortKey: "cost_today",
      className: "w-24",
      render: (user) => <span className="tabular-nums">{usd(user.today_cost_usd)}</span>,
    },
    {
      key: "cost_month",
      title: "30 дней, $",
      align: "right",
      sortable: true,
      sortKey: "cost_month",
      render: (user) => <span className="tabular-nums">{usd(user.month_cost_usd)}</span>,
    },
    {
      key: "errors",
      title: "Ошибки",
      align: "right",
      sortable: true,
      sortKey: "errors",
      render: (user) => (
        <span
          className={cn(
            "tabular-nums",
            user.errors_24h > 0 ? "text-status-bad-fg" : "text-slate-500",
          )}
        >
          {user.errors_24h}
        </span>
      ),
    },
  ]

  return (
    <SectionCard
      title="Люди"
      action={
        <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">
          <AdminSearch
            className="w-56"
            compact
            value={filters.q}
            onChange={(q) => onFiltersChange({ ...filters, q })}
          />
          <PeopleFilters filters={filters} onChange={onFiltersChange} />
          {fetching && <Loader2 className="size-4 animate-spin text-slate-400" />}
        </div>
      }
      status="content"
    >
      <div className="-mx-4 -mb-4 overflow-x-auto">
        <AdminTable
          rows={rows}
          columns={columns}
          rowKey={(user) => user.account_id}
          selectedKey={selectedId}
          onSelect={(user) => onSelect(user.account_id)}
          loading={loading}
          sort={filters.sort}
          onSort={(column: AdminSortColumn) =>
            onFiltersChange({ ...filters, sort: toggleAdminSort(filters.sort, column) })
          }
          renderActions={(user) => <PersonRowActions user={user} />}
          rowClassName={(user) => (user.spend_alert ? "bg-status-warn-soft" : undefined)}
          empty={
            filtered
              ? {
                  title: "Никто не подошёл",
                  note: "Снимите фильтр или измените поиск.",
                  action: {
                    label: "Сбросить фильтр",
                    onClick: () => onFiltersChange(DEFAULT_ADMIN_FILTERS),
                  },
                }
              : { title: "Аккаунтов нет", note: "Пока никто не привязал Telegram." }
          }
        />
      </div>
    </SectionCard>
  )
}

function keyMarkLabel(user: AdminUserRow): string {
  if (!user.has_openrouter_key) return "ключа нет"
  const origin =
    user.key_origin === "admin" ? "выдан вами" : user.key_origin === "self" ? "свой" : "есть"
  const hint = user.key_hint ? ` ${user.key_hint}` : ""
  return `${origin}${hint}`
}

function PersonCell({
  user,
  spendAlertUsd,
}: {
  user: AdminUserRow
  spendAlertUsd: number
}) {
  return (
    <div
      className={cn(
        "flex min-w-0 max-w-[10rem] items-center gap-1.5 font-medium text-slate-800",
        user.status !== "active" && "opacity-60",
      )}
      title={personHoverTitle(user)}
    >
      <span className="truncate">{atHandle(user.telegram_username)}</span>
      {user.role === "owner" ? (
        <StatusChip tone="info">{roleLabel(user.role)}</StatusChip>
      ) : null}
      {user.status !== "active" ? (
        <StatusChip tone="bad" title={user.disabled_reason || undefined}>
          отключён
        </StatusChip>
      ) : null}
      {user.spend_alert ? (
        <StatusChip
          tone="warn"
          title={`За месяц ${usd(user.spend_month_usd)} при пороге ${usd(spendAlertUsd)}`}
        >
          порог
        </StatusChip>
      ) : null}
    </div>
  )
}
