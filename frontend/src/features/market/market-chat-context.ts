/**
 * Короткие текстовые сводки графиков «Рынка» для кнопки «Спросить» (Заход 6, п.9): текст
 * прикладывается в композер чата как убираемый контекст, отображается «как ответ на график» —
 * несколько ключевых чисел, которых агенту достаточно для ответа по существу, не полный дамп.
 *
 * Чистые функции — без БД и без React, тестируются отдельно от `MarketPage.tsx`.
 */
import type { OfferChance } from "@/api/market"
import type { CategoryBar } from "./charts/category-bars-geometry"
import type { LineMetricInput } from "./charts/line-chart-geometry"
import type { SalaryDistributionInput } from "./charts/salary-distribution-geometry"
import { formatMoneyShort } from "./market-stance"

export interface AskContext {
  title: string
  body: string
}

function barsLine(bars: readonly CategoryBar[]): string {
  return bars.map((b) => `${b.label} ${b.value}`).join(", ")
}

export function salaryAskContext(
  input: SalaryDistributionInput,
  periodLabel: string,
): AskContext | null {
  if (input.points.length === 0) return null
  const parts: string[] = [periodLabel]
  if (input.median != null) parts.push(`медиана ${formatMoneyShort(input.median)}`)
  if (input.p25 != null && input.p75 != null) {
    parts.push(`P25–P75 ${formatMoneyShort(input.p25)}–${formatMoneyShort(input.p75)}`)
  }
  if (input.targetMin != null && input.targetMax != null) {
    parts.push(
      `целевая вилка ${formatMoneyShort(input.targetMin)}–${formatMoneyShort(input.targetMax)}`,
    )
  }
  if (input.offers.length > 0) {
    parts.push(
      `офферы: ${input.offers.map((o) => `${o.company} ${formatMoneyShort(o.value)}`).join(", ")}`,
    )
  }
  return { title: "Зарплаты", body: parts.join(", ") + "." }
}

export function offerChanceAskContext(chance: OfferChance | undefined): AskContext | null {
  if (!chance || chance.components.length === 0) return null
  const factors = chance.components
    .map((c) => `${c.label} ${Math.round(c.contribution)} из ${Math.round(c.weight * 100)}`)
    .join(", ")
  const delta =
    chance.delta != null && chance.delta !== 0
      ? `, изменение за сутки ${chance.delta > 0 ? "+" : ""}${chance.delta}`
      : ""
  const preliminary = chance.preliminary ? " (предварительно, мало данных)" : ""
  return {
    title: "Шанс офферов",
    body: `Итог ${chance.score} из 100${preliminary}${delta}. Вклады факторов: ${factors}.`,
  }
}

export function funnelAskContext(
  bars: readonly CategoryBar[],
  periodLabel: string,
): AskContext | null {
  if (bars.length === 0) return null
  return { title: "Воронка", body: `${periodLabel}: ${barsLine(bars)}.` }
}

export function dropoutReasonsAskContext(bars: readonly CategoryBar[]): AskContext | null {
  if (bars.length === 0) return null
  return { title: "Причины в пропуске", body: `Пропущено вручную: ${barsLine(bars)}.` }
}

export function formatsAskContext(
  formatBars: readonly CategoryBar[],
  gradeBars: readonly CategoryBar[],
  roleBars: readonly CategoryBar[],
): AskContext | null {
  const parts: string[] = []
  if (formatBars.length > 0) parts.push(`формат — ${barsLine(formatBars)}`)
  if (gradeBars.length > 0) parts.push(`грейд — ${barsLine(gradeBars)}`)
  if (roleBars.length > 0) parts.push(`роль — ${barsLine(roleBars)}`)
  if (parts.length === 0) return null
  return { title: "Условия", body: parts.join("; ") + "." }
}

export function resumeReactionAskContext(metrics: readonly LineMetricInput[]): AskContext | null {
  const withData = metrics.filter((m) => m.latest != null)
  if (withData.length === 0) return null
  const parts = withData.map((m) => {
    const delta = m.delta != null && m.delta !== 0 ? ` (${m.delta > 0 ? "+" : ""}${m.delta})` : ""
    return `${m.label} ${m.latest}${delta}`
  })
  return { title: "Площадки", body: `${parts.join(", ")}.` }
}
