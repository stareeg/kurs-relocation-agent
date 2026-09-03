/**
 * Каркас «Рынка» (редизайн 2026-08-09, правка 2026-08-09): гистограммы по категориям
 * (CategoryBars) вместо всех бывших «полос из кусков» (SegmentedBar). Блок «Зарплатная
 * планка» (лестничная диаграмма контрфактов-ступеней смягчения) удалён целиком — наезжал
 * подписями и не рассказывал цельной истории. Контрфакт остаётся в тултипе столбца зарплаты/
 * формата (одна ступень, не весь блок).
 *
 * Лейаут читается как одна история рынка, тремя рядами:
 *  1. Где стою — Зарплаты | Шанс офферов (композит + вклады)
 *  2. Поток — Воронка | Причины в пропуске
 *  3. Реакция рынка — Форматы работы | Площадки (во времени)
 * Под графиками — чат по ситуации (MarketChat).
 *
 * Снесены секционные обёртки MarketStance/ResumeReactionSection/GatesFlow/Funnel/NextSteps
 * — каркас рулит графиками напрямую через примитивы из `./charts`.
 */
import { useState } from "react"
import { AlertTriangle, Eye, EyeOff } from "lucide-react"
import { ErrorState } from "@/components/ui/empty-state"
import { usePersistedBoolean } from "@/lib/use-persisted-boolean"
import { AskAboutButton } from "./AskAboutButton"
import {
  CategoryBars,
  formatSalaryShort,
  LineChart,
  SalaryDistribution,
  type CategoryBar,
} from "./charts"
import { MarketChat } from "./MarketChat"
import { MarketEmpty } from "./MarketEmpty"
import { SectionCard } from "@/components/ui/section-card"
import { PeriodRangeSlider } from "./PeriodRangeSlider"
import { funnelBars, funnelHeaderSummary } from "./funnel-levels"
import { dropoutReasonBars } from "./dropout-reasons"
import { formatBoundaryDate } from "./period-range"
import { formatFxRate } from "./format"
import { useSearchTrack } from "@/features/career/search-track"
import {
  dropoutReasonsAskContext,
  formatsAskContext,
  funnelAskContext,
  offerChanceAskContext,
  resumeReactionAskContext,
  salaryAskContext,
  type AskContext,
} from "./market-chat-context"
import { offerChanceFactorBars, offerChanceFactorTooltipValue } from "./offer-chance"
import {
  gradeLevelBars,
  roleNicheBars,
  salaryDistributionInput,
  workFormatBars,
} from "./market-stance"
import { lineChartInputFromPoints } from "./resume-reaction"
import { useMarketOverview, useResumeStats } from "./use-market-data"
import { cn } from "@/lib/utils"

type OnAskAbout = (ctx: AskContext) => void

// --- Ряд 1: Где стою ---

function SalaryCard({ className, onAskAbout }: { className?: string; onAskAbout: OnAskAbout }) {
  const { data, isLoading, isError, refetch } = useMarketOverview()
  const supply = data?.money?.supply
  const hasSalary = Boolean(supply?.available && supply.salary_points?.length)

  const status = isLoading
    ? ("loading" as const)
    : isError
      ? ("error" as const)
      : !hasSalary
        ? ("empty" as const)
        : ("content" as const)

  // Период — реально выбранный диапазон шкалы сверху (не бэковый `window_days` — тот фиксирован
  // константой и не соответствует выбору пользователя, отсюда и убранная из шапки подпись «N дней»).
  const periodLabel =
    data?.from_days != null && data?.to_days != null
      ? `${formatBoundaryDate(data.from_days)} – ${formatBoundaryDate(data.to_days)}`
      : "за период"
  const askCtx =
    status === "content" && supply
      ? salaryAskContext(
          salaryDistributionInput(supply, data?.money?.live_offers ?? []),
          `${supply.measured} вак., ${periodLabel}`,
        )
      : null

  return (
    <SectionCard
      id="gde-stoyu"
      title="Зарплаты"
      helpId="market.stance"
      className={className}
      meta={
        hasSalary && supply ? (
          <div className="flex min-w-0 items-baseline gap-3 border-l border-slate-200 pl-3">
            <span className="text-lg leading-none font-semibold tabular-nums tracking-tight text-slate-900">
              {supply.measured} вак.
            </span>
            {supply.salary_median_net != null ? (
              <span className="flex items-baseline gap-1">
                <span className="text-sm leading-none font-medium tabular-nums text-slate-500">
                  {formatSalaryShort(supply.salary_median_net)}
                </span>
                <span className="text-xs leading-none text-slate-400">медиана</span>
              </span>
            ) : null}
          </div>
        ) : null
      }
      action={askCtx ? <AskAboutButton onClick={() => onAskAbout(askCtx)} /> : null}
      status={status}
      empty={<MarketEmpty sectionId="gde-stoyu" />}
      error={
        <ErrorState
          compact
          icon={AlertTriangle}
          title="Не загрузилось"
          note="Не удалось загрузить зарплаты."
          action={{ label: "Повторить", onClick: () => void refetch() }}
        />
      }
    >
      {status === "content" && supply ? (
        <SalaryDistribution
          input={salaryDistributionInput(supply, data.money?.live_offers ?? [])}
        />
      ) : null}
    </SectionCard>
  )
}

/** Валютные ставки второго трека (Э3.3): своя шкала, без перевода в рубли. */
function FxRatesCard({ className }: { className?: string }) {
  const { data: tracks } = useSearchTrack()
  const { data, isLoading, isError, refetch } = useMarketOverview()
  if (!tracks?.second_job_enabled) return null

  const scale = data?.money?.fx_rates
  const ready = (scale?.buckets ?? []).filter((b) => b.enough_data && b.median_mid != null)
  const hasScale = Boolean(scale?.available && scale.buckets.length)
  const status = isLoading
    ? ("loading" as const)
    : isError
      ? ("error" as const)
      : ready.length === 0
        ? ("empty" as const)
        : ("content" as const)

  const emptyNote =
    hasScale && ready.length === 0
      ? `Мало наблюдений (${scale!.buckets.map((b) => `${b.n} в ${b.currency}`).join(", ")}) — нужно ${scale!.min_n} в одной валюте, без перевода в рубли.`
      : undefined

  return (
    <SectionCard
      id="stavki-valyuta"
      title="Ставки"
      helpId="market.fx-rates"
      className={className}
      meta={
        ready.length === 1 && ready[0].median_mid != null ? (
          <div className="flex min-w-0 items-baseline gap-3 border-l border-slate-200 pl-3">
            <span className="text-lg leading-none font-semibold tabular-nums tracking-tight text-slate-900">
              {formatFxRate(ready[0].median_mid, ready[0].currency, ready[0].rate_period)}
            </span>
            <span className="text-xs leading-none text-slate-400">
              {ready[0].n} наблюдений в {ready[0].currency}
            </span>
          </div>
        ) : null
      }
      status={status}
      empty={<MarketEmpty sectionId="stavki-valyuta" note={emptyNote} />}
      error={
        <ErrorState
          compact
          icon={AlertTriangle}
          title="Не загрузилось"
          note="Не удалось загрузить валютные ставки."
          action={{ label: "Повторить", onClick: () => void refetch() }}
        />
      }
    >
      {status === "content" ? (
        <ul className="space-y-2">
          {ready.map((b) => (
            <li key={`${b.currency}-${b.rate_period}`} className="flex items-baseline justify-between gap-3">
              <span className="text-lg font-semibold tabular-nums tracking-tight text-slate-900">
                {b.median_mid != null ? formatFxRate(b.median_mid, b.currency, b.rate_period) : "—"}
              </span>
              <span className="text-xs text-slate-400">
                {b.n} наблюдений в {b.currency}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </SectionCard>
  )
}

/** Шанс офферов: сводка + вклады факторов (гистограмма). */
function OfferChanceCard({
  className,
  onAskAbout,
}: {
  className?: string
  onAskAbout: OnAskAbout
}) {
  const { data, isLoading, isError, refetch } = useMarketOverview()

  const chance = data?.offer_chance
  const components = chance?.components ?? []
  const factorBars = offerChanceFactorBars(components)
  const hasContent = factorBars.length > 0

  const status = isLoading
    ? ("loading" as const)
    : isError
      ? ("error" as const)
      : !hasContent
        ? ("empty" as const)
        : ("content" as const)

  const askCtx = status === "content" ? offerChanceAskContext(chance) : null

  const delta = chance?.delta ?? null
  const showDelta = delta != null && delta !== 0
  const deltaUp = (delta ?? 0) > 0

  return (
    <SectionCard
      id="shans-offera"
      title="Шанс офферов"
      helpId="market.stance"
      className={className}
      meta={
        chance ? (
          <div className="flex min-w-0 items-baseline gap-2 border-l border-slate-200 pl-3">
            <span className="text-lg leading-none font-semibold tabular-nums tracking-tight text-slate-900">
              {chance.score}
            </span>
            {showDelta ? (
              <span
                className={cn(
                  "inline-flex items-center gap-0.5 text-xs leading-none font-semibold tabular-nums",
                  deltaUp ? "text-status-strong-fg" : "text-status-bad-fg",
                )}
              >
                <span aria-hidden>{deltaUp ? "▲" : "▼"}</span>
                {Math.abs(delta)}
              </span>
            ) : null}
            {chance.preliminary ? (
              <span className="shrink-0 text-xs leading-none text-status-warn-fg">
                предварительно
              </span>
            ) : null}
          </div>
        ) : null
      }
      action={askCtx ? <AskAboutButton onClick={() => onAskAbout(askCtx)} /> : null}
      status={status}
      empty={<MarketEmpty sectionId="shans-offera" />}
      error={
        <ErrorState
          compact
          icon={AlertTriangle}
          title="Не загрузилось"
          note="Не удалось загрузить шанс офферов."
          action={{ label: "Повторить", onClick: () => void refetch() }}
        />
      }
    >
      {status === "content" && chance && factorBars.length > 0 ? (
        <CategoryBars
          input={{ rows: factorBars, unit: "из 100", yMax: 100 }}
          height={180}
          barClassName="fill-slate-400"
          hoveredBarClassName="fill-slate-600"
          formatTooltip={(bar) => {
            const c = components.find((x) => x.key === bar.key)
            return c
              ? [{ label: c.label, value: offerChanceFactorTooltipValue(c) }]
              : [{ label: bar.label, value: `${bar.value} из 100` }]
          }}
        />
      ) : null}
    </SectionCard>
  )
}

// --- Ряд 2: Поток ---

function FunnelCard({ className, onAskAbout }: { className?: string; onAskAbout: OnAskAbout }) {
  const { data, isLoading, isError, refetch } = useMarketOverview()
  const rows = funnelBars(data?.funnel_period)
  const hasContent = rows.length > 0

  const status = isLoading
    ? ("loading" as const)
    : isError
      ? ("error" as const)
      : !hasContent
        ? ("empty" as const)
        : ("content" as const)

  const periodLabel =
    data?.from_days != null && data?.to_days != null
      ? `${formatBoundaryDate(data.from_days)} – ${formatBoundaryDate(data.to_days)}`
      : "за период"
  const askCtx = status === "content" ? funnelAskContext(rows, periodLabel) : null
  // Сводная строка шапки: «100% Диалоги → 50% Скрининги → 25% Технички → 10% Финалы».
  const headerSummary = status === "content" ? funnelHeaderSummary(data?.funnel_period) : ""

  return (
    <SectionCard
      id="voronka"
      title="Воронка"
      helpId="market.funnel"
      className={className}
      meta={
        headerSummary ? (
          <div className="flex min-w-0 items-baseline border-l border-slate-200 pl-3">
            <span className="text-xs leading-none font-medium tabular-nums text-slate-600 truncate">
              {headerSummary}
            </span>
          </div>
        ) : null
      }
      action={askCtx ? <AskAboutButton onClick={() => onAskAbout(askCtx)} /> : null}
      status={status}
      empty={<MarketEmpty sectionId="voronka" />}
      error={
        <ErrorState
          compact
          icon={AlertTriangle}
          title="Не загрузилось"
          note="Не удалось загрузить воронку."
          action={{ label: "Повторить", onClick: () => void refetch() }}
        />
      }
    >
      {status === "content" ? (
        <CategoryBars
          input={{ rows, showPercent: true }}
          height={180}
          barClassName="fill-slate-400"
        />
      ) : null}
    </SectionCard>
  )
}

function DropoutReasonsCard({
  className,
  onAskAbout,
}: {
  className?: string
  onAskAbout: OnAskAbout
}) {
  const { data, isLoading, isError, refetch } = useMarketOverview()
  const bars = dropoutReasonBars(data?.dropout_reasons)
  const hasContent = bars.length > 0

  const status = isLoading
    ? ("loading" as const)
    : isError
      ? ("error" as const)
      : !hasContent
        ? ("empty" as const)
        : ("content" as const)

  const askCtx = status === "content" ? dropoutReasonsAskContext(bars) : null

  return (
    <SectionCard
      id="chto-rezhet-potok"
      title="Причины в пропуске"
      helpId="market.gates"
      className={className}
      action={askCtx ? <AskAboutButton onClick={() => onAskAbout(askCtx)} /> : null}
      status={status}
      empty={<MarketEmpty sectionId="chto-rezhet-potok" />}
      error={
        <ErrorState
          compact
          icon={AlertTriangle}
          title="Не загрузилось"
          note="Не удалось загрузить причины пропуска."
          action={{ label: "Повторить", onClick: () => void refetch() }}
        />
      }
    >
      {status === "content" ? (
        <CategoryBars
          input={{ rows: bars, unit: "вак.", showPercent: true }}
          height={180}
          barClassName="fill-slate-400"
        />
      ) : null}
    </SectionCard>
  )
}

// --- Ряд 3: Реакция рынка ---

/** Одна колонка совмещённой визуализации «Условия»: подпись + мини-гистограмма
 * (или честный «нет данных», если у этого среза пусто, а у соседних — есть).
 * Графики растянуты по высоте блока (правка 2026-08-14): раньше фиксированная высота 140px
 * делала левые колонки визуально ниже правой (Роль с длинными подписями съедала место). */
function FormatMiniColumn({
  title,
  bars,
  height,
}: {
  title: string
  bars: CategoryBar[]
  height: number
}) {
  return (
    <div className="min-w-0 flex flex-col">
      <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
        {title}
      </div>
      {bars.length > 0 ? (
        <CategoryBars
          input={{ rows: bars, showPercent: true }}
          height={height}
          barClassName="fill-slate-400"
        />
      ) : (
        <div className="flex items-center text-xs text-slate-400" style={{ height }}>
          Нет данных
        </div>
      )}
    </div>
  )
}

/** Формат/Грейд по умолчанию; «Роль» — по глазику у заголовка (как «Агент» в чате). Три графика
 * в одном блоке теснились: поэтому Формат+Грейд и Роль — взаимоисключающие виды, не small
 * multiples в одну строку. Шкала столбцов — доли (%). */
function FormatsCard({ className, onAskAbout }: { className?: string; onAskAbout: OnAskAbout }) {
  const { data, isLoading, isError, refetch } = useMarketOverview()
  const [showRole, setShowRole] = usePersistedBoolean("copilot.market.conditions.show-role")
  const supply = data?.money?.supply
  const formatBars = supply ? workFormatBars(supply.work_formats) : []
  const gradeBars = gradeLevelBars(data?.grade_levels)
  const roleBars = roleNicheBars(data?.role_niches)
  const visibleFormatBars = showRole ? [] : formatBars
  const visibleGradeBars = showRole ? [] : gradeBars
  const visibleRoleBars = showRole ? roleBars : []
  const hasContent =
    visibleFormatBars.length > 0 || visibleGradeBars.length > 0 || visibleRoleBars.length > 0

  const status = isLoading
    ? ("loading" as const)
    : isError
      ? ("error" as const)
      : !hasContent
        ? ("empty" as const)
        : ("content" as const)

  const askCtx =
    status === "content"
      ? formatsAskContext(visibleFormatBars, visibleGradeBars, visibleRoleBars)
      : null

  return (
    <SectionCard
      id="formats"
      title="Условия"
      helpId="market.stance"
      className={className}
      meta={
        <div className="inline-flex items-center gap-0.5 rounded-lg bg-slate-100 p-1">
          <span className="flex items-center gap-1.5 rounded-lg py-1.5 pl-2.5 pr-1 text-sm font-medium text-slate-900">
            Роль
          </span>
          <button
            type="button"
            onClick={() => setShowRole((v) => !v)}
            aria-label={showRole ? "Скрыть график «Роль»" : "Показать график «Роль»"}
            title={showRole ? "Скрыть график «Роль»" : "Показать график «Роль»"}
            className="rounded-md p-1.5 text-slate-400 transition-colors hover:bg-slate-200/70 hover:text-slate-600"
          >
            {showRole ? (
              <Eye className="size-3.5" strokeWidth={2} />
            ) : (
              <EyeOff className="size-3.5" strokeWidth={2} />
            )}
          </button>
        </div>
      }
      action={askCtx ? <AskAboutButton onClick={() => onAskAbout(askCtx)} /> : null}
      status={status}
      empty={<MarketEmpty sectionId="formats" />}
      error={
        <ErrorState
          compact
          icon={AlertTriangle}
          title="Не загрузилось"
          note="Не удалось загрузить условия рынка."
          action={{ label: "Повторить", onClick: () => void refetch() }}
        />
      }
    >
      {status === "content" ? (
        <div className={showRole ? "grid grid-cols-1" : "grid grid-cols-1 gap-5 sm:grid-cols-2"}>
          {showRole ? (
            <FormatMiniColumn title="Роль" bars={visibleRoleBars} height={180} />
          ) : (
            <>
              <FormatMiniColumn title="Формат" bars={visibleFormatBars} height={180} />
              <FormatMiniColumn title="Грейд" bars={visibleGradeBars} height={180} />
            </>
          )}
        </div>
      ) : null}
    </SectionCard>
  )
}

/** Площадки: показы / просмотры резюме во времени (линейный график, план п.6 — приглашения
 * убраны, они уже видны в «Воронке»/«Шансе офферов»). Последние значения — в шапке блока
 * (`meta`), не врезаны в тело графика — там раньше наезжали друг на друга. */
function ResumeReactionCard({
  className,
  onAskAbout,
}: {
  className?: string
  onAskAbout: OnAskAbout
}) {
  const { data, isLoading, isError, refetch } = useResumeStats()
  const points = data?.available ? (data.points ?? []) : []
  const chart = lineChartInputFromPoints(points)
  const hasContent = chart.metrics.some((m) => m.points.length > 0)

  const status = isLoading
    ? ("loading" as const)
    : isError
      ? ("error" as const)
      : !hasContent
        ? ("empty" as const)
        : ("content" as const)

  const askCtx = status === "content" ? resumeReactionAskContext(chart.metrics) : null

  return (
    <SectionCard
      id="otklik-rynka"
      title="Площадки"
      helpId="market.stance"
      className={className}
      meta={
        status === "content" ? (
          <div className="flex min-w-0 items-baseline gap-3 border-l border-slate-200 pl-3">
            {chart.metrics.map((m) =>
              m.latest != null ? (
                <span key={m.key} className="flex items-baseline gap-1">
                  <span className="text-sm leading-none font-medium tabular-nums text-slate-700">
                    {m.latest}
                  </span>
                  <span className="text-xs leading-none text-slate-400">{m.label}</span>
                </span>
              ) : null,
            )}
          </div>
        ) : null
      }
      action={askCtx ? <AskAboutButton onClick={() => onAskAbout(askCtx)} /> : null}
      status={status}
      empty={<MarketEmpty sectionId="otklik-rynka" />}
      error={
        <ErrorState
          compact
          icon={AlertTriangle}
          title="Не загрузилось"
          note="Не удалось загрузить отклик резюме."
          action={{ label: "Повторить", onClick: () => void refetch() }}
        />
      }
    >
      {status === "content" ? <LineChart input={{ metrics: chart.metrics }} /> : null}
    </SectionCard>
  )
}

// --- Каркас страницы ---

/**
 * Каркас «Рынка» (редизайн 2026-08-09): двухколоночная сетка, читается тремя рядами —
 * Где стою / Поток / Реакция рынка. Под графиками — чат по ситуации.
 */
export function MarketPage() {
  // Контекст «Спросить» (Заход 6, п.9): один слот на страницу — новый клик по кнопке графика
  // заменяет предыдущий контекст, не копит очередь вложений графиков.
  const [askContext, setAskContext] = useState<AskContext | null>(null)

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-x-hidden">
      <div
        id="screen-start-market"
        className="min-w-0 flex-1 overflow-y-auto overflow-x-hidden overscroll-contain"
      >
        {/* Шкала периода — в обычном потоке страницы, не закреплена (открепили: использовалась
            редко, закреплять было не нужно). */}
        <div className="px-6 pb-3 pt-6">
          <PeriodRangeSlider />
        </div>

        {/* Ряд 1 — где стою: зарплаты | шанс офферов. */}
        <div className="grid grid-cols-1 gap-4 px-6 pt-6 lg:grid-cols-2">
          <div className="flex min-w-0 flex-col gap-4">
            <SalaryCard className="min-w-0" onAskAbout={setAskContext} />
            <FxRatesCard className="min-w-0" />
          </div>
          <OfferChanceCard className="min-w-0" onAskAbout={setAskContext} />
        </div>
        {/* Ряд 2 — поток: воронка | что режет поток. */}
        <div className="grid grid-cols-1 gap-4 px-6 pt-4 lg:grid-cols-2">
          <FunnelCard className="min-w-0" onAskAbout={setAskContext} />
          <DropoutReasonsCard className="min-w-0" onAskAbout={setAskContext} />
        </div>
        {/* Ряд 3 — реакция рынка: форматы | отклик резюме во времени. */}
        <div className="grid grid-cols-1 gap-4 px-6 pt-4 lg:grid-cols-2">
          <FormatsCard className="min-w-0" onAskAbout={setAskContext} />
          <ResumeReactionCard className="min-w-0" onAskAbout={setAskContext} />
        </div>

        {/* Чат — в общем потоке страницы, под всеми графиками (не закреплённая снизу панель). */}
        <MarketChat askContext={askContext} onClearAskContext={() => setAskContext(null)} />
      </div>
    </div>
  )
}
