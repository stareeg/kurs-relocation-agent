import { useMemo, useState } from "react"
import { AlertTriangle, ChevronDown } from "lucide-react"
import type { AdminSpendGroup } from "@/api/admin"
import { Button } from "@/components/ui/button"
import { ErrorState } from "@/components/ui/empty-state"
import { SectionCard } from "@/components/ui/section-card"
import { SegmentedControl } from "@/components/ui/segmented-control"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { CategoryBars } from "@/features/market/charts"
import { usd } from "@/features/admin/admin-format"
import {
  cacheHitLabel,
  filterSpendByModel,
  findSpendRow,
  orderSpendRows,
  shortModelSlug,
  spendBarsInput,
  spendModelKeys,
  spendTooltipLines,
  visibleSpendRows,
} from "@/features/admin/admin-spend"
import { SpendMetricsTable } from "@/features/admin/components/SpendMetricsTable"
import { StackedSpendBars } from "@/features/admin/components/StackedSpendBars"
import { useAdminSpend } from "@/features/admin/use-admin"
import { cn } from "@/lib/utils"

const SPEND_OPTIONS: { value: AdminSpendGroup; label: string }[] = [
  { value: "day", label: "По дням" },
  { value: "feature", label: "По фичам" },
  { value: "account", label: "По людям" },
]

const SPEND_DAYS = 14

/**
 * «Деньги» на Пульте: итоги в шапке, столбики по дням складываются из моделей.
 */
export function SpendCard({ enabled }: { enabled: boolean }) {
  const [open, setOpen] = useState(true)
  const [groupBy, setGroupBy] = useState<AdminSpendGroup>("day")
  const [model, setModel] = useState("all")

  const totals = useAdminSpend(enabled, SPEND_DAYS, "day")
  const detail = useAdminSpend(enabled && open, SPEND_DAYS, groupBy)

  const summary = totals.data
  const ordered = orderSpendRows(detail.data?.rows ?? [], groupBy)
  const modelKeys = spendModelKeys(ordered)
  const filtered = groupBy === "day" ? filterSpendByModel(ordered, model) : ordered
  const rows = visibleSpendRows(filtered, groupBy)
  const bars = spendBarsInput(rows)
  const hasSpend = rows.some((row) => row.cost_usd > 0)
  const cacheLabel = cacheHitLabel(summary?.cache_hit_rate, summary?.cache_calls ?? 0)
  const modelFilterKeys = useMemo(
    () => (model === "all" ? modelKeys : modelKeys.filter((key) => key === model)),
    [model, modelKeys],
  )

  return (
    <SectionCard
      title="Деньги"
      helpId="admin.spend"
      meta={
        summary ? (
          <span className="truncate text-sm font-semibold tabular-nums text-slate-800">
            {usd(summary.today_usd)} сегодня · {usd(summary.month_usd)} за месяц · прогноз{" "}
            {usd(summary.forecast_month_usd)}
            {summary.cache_calls > 0 ? ` · ${cacheLabel}` : ""}
          </span>
        ) : undefined
      }
      action={
        <Button
          size="sm"
          variant="ghost"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
        >
          {open ? "Свернуть" : "Подробнее"}
          <ChevronDown className={cn("size-4 transition-transform", open && "rotate-180")} strokeWidth={2} />
        </Button>
      }
      status={
        !open ? "content" : detail.isError ? "error" : detail.isLoading ? "loading" : "content"
      }
      refreshing={open && detail.isFetching && !detail.isLoading}
      loading={<Skeleton className="h-40 w-full" />}
      error={
        <ErrorState
          compact
          icon={AlertTriangle}
          title="Расход не загрузился"
          note="Не удалось получить разрез LLM."
          action={{ label: "Повторить", onClick: () => void detail.refetch() }}
        />
      }
    >
      {open ? (
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <SegmentedControl<AdminSpendGroup>
              ariaLabel="Разрез расхода"
              options={SPEND_OPTIONS}
              value={groupBy}
              onChange={(next) => {
                setGroupBy(next)
                setModel("all")
              }}
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
          {hasSpend ? (
            <>
              {groupBy === "day" ? (
                <StackedSpendBars rows={rows} modelKeys={modelFilterKeys} height={160} />
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
            <p className="text-sm text-slate-400">Нет трат за выбранное окно.</p>
          )}
        </div>
      ) : null}
    </SectionCard>
  )
}
