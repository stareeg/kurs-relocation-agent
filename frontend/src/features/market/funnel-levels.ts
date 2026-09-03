/**
 * Данные под «Воронку» (редизайн 2026-08-11, шаг 4 плана «Деньги»): раньше — плоская
 * гистограмма по ТЕКУЩЕМУ статусу вакансий (Отклики / Без ответа / Скрининг / Техничка /
 * Финал / Оффер), без привязки к шкале периода сверху. Теперь — активность ЗА ПЕРИОД:
 * сколько вакансий получили скрининг/техничку/оффер и сколько диалогов было активно внутри
 * выбранного окна (`MarketOverview.funnel_period`, бэк уже отдаёт готовые короткие корзины).
 *
 * Правка 2026-08-14: Диалоги — базовая корзина воронки (100%), от неё бэк считает pct
 * Скринингов/Техничек/Финалов/Офферов. Бэк отдаёт Диалоги ПЕРВЫМ столбцом, порядок тут
 * сохраняется 1-в-1. Добавлена Финалы (раньше было 3 стадии — скрининги/технички/офферы).
 *
 * Старый двухуровневый `FunnelLevel[]` (`MarketOverview.funnel`) остался в контракте — его ещё
 * читает график «Воронка во времени» через `market_snapshot.py`, просто эта карточка на него
 * больше не смотрит.
 *
 * Чистая подготовка — без БД и без React, тестируется отдельно от `MarketPage.tsx`.
 */
import type { MarketBucket } from "@/api/market"
import type { CategoryBar } from "./charts/category-bars-geometry"

export type FunnelFlatBar = CategoryBar

/** `funnel_period` → столбики `CategoryBars`. Короткие подписи уже готовы на бэке. */
export function funnelBars(buckets: readonly MarketBucket[] | undefined): FunnelFlatBar[] {
  if (!buckets || buckets.length === 0) return []
  return buckets.map((b) => ({ key: b.label, label: b.label, value: b.count, pct: b.pct }))
}

/** Сводная строка шапки «Воронки»: `100% Диалоги -> 50% Скрининги -> 25% Технички -> 10% Финалы`.
 *
 * Диалоги — база (100%), от неё считаются pct остальных (правка 2026-08-14). Строка читается
 * как воронка конверсии: «из 100% заведённых диалогов до скрининга дошли 50% и т.д.».
 * Берёт Офферы/Финалы по наличию — если корзины нет на бэке, в строку не попадает.
 * Показывает до 4 столбцов (Диалоги → Скрининги → Технички → Финалы), Офферы опускаем —
 * иначе строка в шапке слишком длинная, а Офферы и так видны на самом графике. */
export function funnelHeaderSummary(buckets: readonly MarketBucket[] | undefined): string {
  if (!buckets || buckets.length === 0) return ""
  const byLabel = new Map(buckets.map((b) => [b.label, b]))
  const order = ["Диалоги", "Скрининги", "Технички", "Финалы"]
  const parts: string[] = []
  for (const label of order) {
    const b = byLabel.get(label)
    if (!b) continue
    parts.push(`${Math.round(b.pct)}% ${b.label}`)
  }
  return parts.join(" → ")
}
