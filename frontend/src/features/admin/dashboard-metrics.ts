/**
 * Плитки «Метрики» на Пульте: числа, которые оператору нужны с первого взгляда.
 *
 * Здоровье процесса (бэкенд, миграции, воркер, очередь) на Действиях и в вердикте шапки —
 * здесь только нагрузка и деньги.
 */
import type { AdminSummary } from "@/api/admin"
import { uniqueModelSlugs } from "@/features/admin/admin-health"

export type DashboardMetric = {
  key: string
  value: string
  unit: string
  label: string
}

export function buildDashboardMetrics(summary: AdminSummary | undefined): DashboardMetric[] {
  if (!summary) return []
  return [
    { key: "keys", value: String(summary.pending_keys), unit: "шт", label: "Заявки" },
    { key: "people", value: String(summary.accounts_active), unit: "чел", label: "Люди" },
    { key: "seen", value: String(summary.seen_24h), unit: "чел", label: "За сутки" },
    { key: "errors", value: String(summary.errors_24h), unit: "шт", label: "Ошибки" },
    { key: "failed", value: String(summary.failed_tasks), unit: "шт", label: "Провалы" },
    { key: "today", value: summary.today_cost_usd.toFixed(2), unit: "$", label: "Сегодня" },
    {
      key: "month",
      value: (summary.month_cost_usd ?? 0).toFixed(2),
      unit: "$",
      label: "30 дней",
    },
  ]
}

export function dashboardModelLabels(summary: AdminSummary | undefined): string[] {
  return uniqueModelSlugs(summary?.health)
}
