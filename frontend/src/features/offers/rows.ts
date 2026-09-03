import type { OfferUpdateRequest } from "@/api/offers"
import type { ChipOption } from "@/components/ui/chip-toggle-group"
import { hasBonusKind, type BonusKind } from "@/features/offers/bonus"

// Shared offer-condition rows: add-form, card, and (historically) the comparison matrix.
export type CellType =
  | "text"
  | "number"
  | "date"
  | "format"
  | "contract"
  | "bonus_types"
  | "bonus_pct"
  | "tax_basis"

export type RowDef = {
  key: keyof OfferUpdateRequest
  label: string
  type: CellType
  better?: "max"
}

export const ROWS: RowDef[] = [
  { key: "base_salary", label: "Оклад", type: "number", better: "max" },
  { key: "base_salary_tax_basis", label: "Налоги", type: "tax_basis" },
  { key: "work_format", label: "Формат", type: "format" },
  { key: "contract_type", label: "Вид договора", type: "contract" },
  { key: "bonus_types", label: "Тип премии", type: "bonus_types" },
  { key: "annual_bonus_pct", label: "Годовая, % от года", type: "bonus_pct" },
  { key: "quarterly_bonus_pct", label: "Квартальная, % от квартала", type: "bonus_pct" },
  { key: "bonus", label: "Премия, детали", type: "text" },
  { key: "signon", label: "Welcome-бонус", type: "number", better: "max" },
  { key: "equity", label: "Акции", type: "text" },
  { key: "vacation_days", label: "Отпуск, дней", type: "number", better: "max" },
  { key: "office_days_per_week", label: "Дней в офисе", type: "number" },
  { key: "location", label: "Локация", type: "text" },
  { key: "location_country", label: "Страна", type: "text" },
  { key: "deadline", label: "Дедлайн ответа", type: "date" },
  { key: "notes", label: "Подробности от HR", type: "text" },
]

/** Fields the user does not edit from the card. */
export const READONLY_ROW_KEYS = new Set<keyof OfferUpdateRequest>()

export const FORMAT_OPTS: ChipOption[] = [
  {
    value: "remote",
    label: "Удалёнка",
    activeClass: "border-emerald-200 bg-emerald-50 text-emerald-700",
  },
  { value: "hybrid", label: "Гибрид", activeClass: "border-amber-200 bg-amber-50 text-amber-700" },
  { value: "office", label: "Офис", activeClass: "border-rose-200 bg-rose-50 text-rose-700" },
  {
    value: "currency",
    label: "Валютка",
    activeClass: "border-violet-200 bg-violet-50 text-violet-700",
  },
]

export const CONTRACT_OPTS: ChipOption[] = [
  { value: "employment", label: "Трудовой" },
  { value: "gph", label: "ГПХ" },
  { value: "ip", label: "ИП" },
  { value: "self_employed", label: "Самозанятый" },
]

export const BONUS_TYPE_OPTS: ChipOption[] = [
  { value: "annual", label: "Годовая" },
  { value: "quarterly", label: "Квартальная" },
  { value: "kpi", label: "KPI" },
  { value: "welcome", label: "Welcome" },
  { value: "equity", label: "Акции" },
]

export const TAX_BASIS_OPTS: ChipOption[] = [
  { value: "gross", label: "До вычета" },
  { value: "net", label: "На руки" },
]

const BONUS_FIELD_KIND: Partial<Record<keyof OfferUpdateRequest, BonusKind>> = {
  annual_bonus_pct: "annual",
  quarterly_bonus_pct: "quarterly",
  bonus: "kpi",
  signon: "welcome",
  equity: "equity",
}

export function isOfferRowVisible(
  row: RowDef,
  offer: {
    bonus_types?: string[] | null
    bonus_type?: string | null
    work_format?: string | null
  },
): boolean {
  if (row.key === "office_days_per_week") return offer.work_format === "hybrid"
  if (row.key === "location_country") return offer.work_format === "currency"
  const kind = BONUS_FIELD_KIND[row.key]
  if (kind) return hasBonusKind(offer, kind)
  if (row.key === "deadline") return false
  return true
}

export function rowByKey(key: RowDef["key"]): RowDef | undefined {
  return ROWS.find((r) => r.key === key)
}

export function fieldValue(
  offer: Record<string, unknown>,
  key: keyof OfferUpdateRequest,
): string | number | null {
  const v = offer[key]
  if (v == null) return null
  return typeof v === "number" ? v : String(v)
}
