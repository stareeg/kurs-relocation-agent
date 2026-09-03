import type { AdminSpendRow } from "@/api/admin"
import { msLabel, pctLabel, tokens, usd } from "@/features/admin/admin-format"
import { spendRowLabel } from "@/features/admin/admin-spend"

/**
 * Таблица разреза: деньги, кэш, p50/p95, доля повторов — то, чего нет на столбиках.
 */
export function SpendMetricsTable({ rows }: { rows: readonly AdminSpendRow[] }) {
  const visible = rows.filter((row) => row.calls > 0)
  if (visible.length === 0) return null
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-xs font-medium text-slate-500">
          <tr>
            <th className="py-1 pr-3">Разрез</th>
            <th className="py-1 pr-3 text-right">$</th>
            <th className="py-1 pr-3 text-right">Вызовы</th>
            <th className="py-1 pr-3 text-right">Кэш</th>
            <th className="py-1 pr-3 text-right">p50</th>
            <th className="py-1 pr-3 text-right">p95</th>
            <th className="py-1 text-right">Повторы</th>
          </tr>
        </thead>
        <tbody>
          {visible.map((row) => (
            <tr key={row.key} className="border-t">
              <td className="max-w-[12rem] truncate py-1.5 pr-3 text-slate-700" title={row.key}>
                {spendRowLabel(row.key)}
              </td>
              <td className="py-1.5 pr-3 text-right tabular-nums text-slate-800">{usd(row.cost_usd)}</td>
              <td className="py-1.5 pr-3 text-right tabular-nums text-slate-500">{tokens(row.calls)}</td>
              <td className="py-1.5 pr-3 text-right tabular-nums text-slate-500">
                {pctLabel(row.cache_hit_rate)}
              </td>
              <td className="py-1.5 pr-3 text-right tabular-nums text-slate-500">
                {msLabel(row.median_ms)}
              </td>
              <td className="py-1.5 pr-3 text-right tabular-nums text-slate-500">{msLabel(row.p95_ms)}</td>
              <td className="py-1.5 text-right tabular-nums text-slate-500">
                {pctLabel(row.retry_share)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
