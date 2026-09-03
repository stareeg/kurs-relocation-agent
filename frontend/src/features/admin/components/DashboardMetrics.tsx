import type { DashboardMetric } from "@/features/admin/dashboard-metrics"

/**
 * Горизонтальная полоса метрик: крупное число, единица рядом, название снизу.
 */
export function DashboardMetrics({ items }: { items: readonly DashboardMetric[] }) {
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-7">
      {items.map((item) => (
        <div key={item.key} className="rounded-lg bg-slate-50 px-3 py-3">
          <div className="flex items-baseline gap-1">
            <span className="text-xl font-semibold tabular-nums text-slate-900">{item.value}</span>
            {item.unit ? <span className="text-xs text-slate-400">{item.unit}</span> : null}
          </div>
          <div className="mt-0.5 text-xs text-slate-500">{item.label}</div>
        </div>
      ))}
    </div>
  )
}
