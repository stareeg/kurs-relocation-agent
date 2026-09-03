/**
 * Данные под «Причины в пропуске» (было «Что режет поток», редизайн 2026-08-11): раньше —
 * разбивка по жёстким гейтам скоринга (что автоматически отсекает вакансию), теперь — реальные
 * причины, которыми владелец сам пометил вакансию при ручном пропуске (`skip_reason` на
 * `skipped_vacancies`, единый канон `core.domains.opportunities.skip_reasons`, те же шесть
 * причин, что в чипе пропуска на карточке вакансии). Бэк уже считал их для LLM-фич
 * (`MarketOverview.dropout_reasons`), просто график их не показывал.
 *
 * Короткие подписи вместо канонических строк («Не та роль (IC vs рук)» → «Роль»,
 * «Не тот стек/домен» → «Домен», «Избегать компанию» → «Компания») — порядок столбцов
 * зафиксирован (Зарплата/Формат/Грейд/Роль/Домен/Компания), не порядок канона бэка.
 *
 * Чистая подготовка — без БД и без React, тестируется отдельно от `MarketPage.tsx`.
 */
import type { SkipReasonCount } from "@/api/market"
import type { CategoryBar } from "./charts/category-bars-geometry"

const SHORT_LABELS: Readonly<Record<string, string>> = {
  "Низкая зарплата": "Зарплата",
  "Не тот формат": "Формат",
  "Низкий грейд": "Грейд",
  "Не та роль (IC vs рук)": "Роль",
  "Не тот стек/домен": "Домен",
  "Избегать компанию": "Компания",
}

const DISPLAY_ORDER = [
  "Низкая зарплата",
  "Не тот формат",
  "Низкий грейд",
  "Не та роль (IC vs рук)",
  "Не тот стек/домен",
  "Избегать компанию",
] as const

/** Столбики `CategoryBars` в порядке Зарплата/Формат/Грейд/Роль/Домен/Компания. Пустые (0)
 * категории не рисуем — как и остальные графики «Рынка». */
export function dropoutReasonBars(reasons: readonly SkipReasonCount[] | undefined): CategoryBar[] {
  if (!reasons || reasons.length === 0) return []
  const byReason = new Map(reasons.map((r) => [r.reason, r.count]))
  const bars: CategoryBar[] = []
  for (const canon of DISPLAY_ORDER) {
    const count = byReason.get(canon) ?? 0
    if (count > 0) {
      bars.push({ key: canon, label: SHORT_LABELS[canon] ?? canon, value: count })
    }
  }
  return bars
}
