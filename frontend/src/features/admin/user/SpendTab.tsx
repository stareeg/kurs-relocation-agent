import { useState } from "react"
import { ChipToggleGroup } from "@/components/ui/chip-toggle-group"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { CategoryBars } from "@/features/market/charts"
import type { AdminSpendGroup } from "@/api/admin"
import { useAdminSpend } from "@/features/admin/use-admin"
import {
  cacheHitLabel,
  filterSpendByModel,
  findSpendRow,
  orderSpendRows,
  shortModelSlug,
  spendBarsInput,
  spendModelKeys,
  spendRowLabel,
  spendTooltipLines,
  visibleSpendRows,
} from "@/features/admin/admin-spend"
import { usd } from "@/features/admin/admin-format"
import { SectionTitle } from "@/components/ui/section-title"
import { SpendMetricsTable } from "@/features/admin/components/SpendMetricsTable"
import { StackedSpendBars } from "@/features/admin/components/StackedSpendBars"

const SPEND_OPTIONS = [
  { value: "day", label: "По дням" },
  { value: "feature", label: "По фичам" },
]

/**
 * Те же разрезы, что на обзоре, но по одному человеку. Топ фич — отдельным списком.
 */
export function SpendTab({ accountId }: { accountId: number }) {
  const [groupBy, setGroupBy] = useState<AdminSpendGroup>("day")
  const [model, setModel] = useState("all")
  const spend = useAdminSpend(true, 14, groupBy, accountId)
  const features = useAdminSpend(true, 14, "feature", accountId)
  const ordered = orderSpendRows(spend.data?.rows ?? [], groupBy)
  const modelKeys = spendModelKeys(ordered)
  const filtered = groupBy === "day" ? filterSpendByModel(ordered, model) : ordered
  const rows = visibleSpendRows(filtered, groupBy)
  const bars = spendBarsInput(rows)
  const top = visibleSpendRows(features.data?.rows ?? [], "feature").slice(0, 5)
  const legendKeys = model === "all" ? modelKeys : modelKeys.filter((key) => key === model)

  return (
    <div className="space-y-4">
      {spend.data ? (
        <div className="overflow-x-auto rounded-lg bg-slate-50 p-2.5">
          <table className="w-full text-sm">
            <thead className="text-left text-xs font-medium text-slate-500">
              <tr>
                <th className="py-1 pr-3">Показатель</th>
                <th className="py-1 text-right">Значение</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-t border-slate-200/80">
                <td className="py-1.5 pr-3 text-slate-500">Сегодня</td>
                <td className="py-1.5 text-right tabular-nums text-slate-800">
                  {usd(spend.data.today_usd)}
                </td>
              </tr>
              <tr className="border-t border-slate-200/80">
                <td className="py-1.5 pr-3 text-slate-500">За месяц</td>
                <td className="py-1.5 text-right tabular-nums text-slate-800">
                  {usd(spend.data.month_usd)}
                </td>
              </tr>
              <tr className="border-t border-slate-200/80">
                <td className="py-1.5 pr-3 text-slate-500">Прогноз</td>
                <td className="py-1.5 text-right tabular-nums text-slate-800">
                  {usd(spend.data.forecast_month_usd)}
                </td>
              </tr>
              <tr className="border-t border-slate-200/80">
                <td className="py-1.5 pr-3 text-slate-500">Кэш</td>
                <td className="py-1.5 text-right tabular-nums text-slate-800">
                  {cacheHitLabel(spend.data.cache_hit_rate, spend.data.cache_calls)}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <ChipToggleGroup
          multiple={false}
          allowEmpty={false}
          value={[groupBy]}
          onChange={(next) => {
            setGroupBy((next[0] as AdminSpendGroup) || "day")
            setModel("all")
          }}
          options={SPEND_OPTIONS}
        />
        {groupBy === "day" && modelKeys.length > 0 ? (
          <Select value={model} onValueChange={setModel}>
            <SelectTrigger aria-label="Модель">
              <SelectValue placeholder="Все модели" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Все модели</SelectItem>
              {modelKeys.map((key) => (
                <SelectItem key={key} value={key}>
                  {shortModelSlug(key)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : null}
      </div>
      {spend.isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : rows.some((row) => row.cost_usd > 0) ? (
        <>
          {groupBy === "day" ? (
            <StackedSpendBars rows={rows} modelKeys={legendKeys} height={160} />
          ) : (
            <CategoryBars
              input={bars}
              height={160}
              barClassName="fill-slate-400"
              hoveredBarClassName="fill-slate-600"
              formatTooltip={(bar) => spendTooltipLines(findSpendRow(rows, bar.key), bar.label)}
            />
          )}
          <SpendMetricsTable rows={rows} />
        </>
      ) : (
        <p className="text-sm text-slate-400">Нет трат за 14 дней.</p>
      )}
      <div>
        <div className="mb-1.5">
          <SectionTitle>Топ фич</SectionTitle>
        </div>
        {top.length === 0 ? (
          <p className="text-sm text-slate-400">Вызовов не было.</p>
        ) : (
          <ul className="space-y-1 text-sm">
            {top.map((row) => (
              <li key={row.key} className="flex justify-between gap-2">
                <span className="truncate text-slate-600">{spendRowLabel(row.key)}</span>
                <span className="tabular-nums text-slate-800">{usd(row.cost_usd)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
