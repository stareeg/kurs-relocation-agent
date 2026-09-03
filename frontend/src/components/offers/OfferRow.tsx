import { EditableCell } from "@/components/ui/editable-cell"
import { ChipToggleGroup, type ChipOption } from "@/components/ui/chip-toggle-group"
import { DatePicker } from "@/components/ui/date-picker"
import { BonusPctSlider } from "@/components/offers/BonusPctSlider"
import { CONTRACT_OPTS, BONUS_TYPE_OPTS, TAX_BASIS_OPTS, type RowDef } from "@/features/offers/rows"
import type { BonusPct } from "@/features/offers/bonus"

export type OfferRowValue = string | number | string[] | null

// One condition cell — chips vs editable vs slider. Shared by the offer card and the
// add-offer draft so the same field looks the same in both places.
export function OfferRow({
  row,
  value,
  onCommit,
  highlight,
  formatOptions,
  placeholder,
  readOnly,
}: {
  row: RowDef
  value: OfferRowValue
  onCommit: (next: OfferRowValue) => void
  highlight?: boolean
  formatOptions?: ChipOption[]
  // Row does not apply (e.g. office days when not hybrid) — dash, not an editor.
  placeholder?: boolean
  /** Display only (e.g. start date). */
  readOnly?: boolean
}) {
  if (row.key === "deadline") {
    const today = new Date()
    return (
      <DatePicker
        value={value ? String(value).slice(0, 10) : ""}
        onChange={(v) => onCommit(v ? new Date(v).toISOString() : null)}
        granularity="day"
        defaultMonth={value ? new Date(String(value)) : today}
        fromYear={today.getFullYear()}
        toYear={today.getFullYear() + 2}
        placeholder="Выбрать дату"
      />
    )
  }
  if (placeholder) {
    return <span className="px-1.5 text-sm text-slate-300">—</span>
  }
  if (readOnly) {
    if (value == null || value === "" || (Array.isArray(value) && value.length === 0)) {
      return <span className="px-1.5 text-sm text-slate-300">—</span>
    }
    const label =
      row.type === "date"
        ? (() => {
            const d = new Date(String(value))
            return Number.isNaN(d.getTime())
              ? String(value)
              : d.toLocaleDateString("ru-RU", { day: "numeric", month: "short", year: "numeric" })
          })()
        : Array.isArray(value)
          ? value.join(", ")
          : String(value)
    return <span className="px-1.5 text-sm tabular-nums text-slate-700">{label}</span>
  }
  if (row.type === "format") {
    return (
      <ChipToggleGroup
        options={formatOptions ?? []}
        value={[String(value ?? "unknown")]}
        onChange={(next) => onCommit(next[0] ?? "unknown")}
        multiple={false}
        allowEmpty={false}
      />
    )
  }
  if (row.type === "contract") {
    return (
      <ChipToggleGroup
        options={CONTRACT_OPTS}
        value={[String(value ?? "employment")]}
        onChange={(next) => onCommit(next[0] ?? "employment")}
        multiple={false}
        allowEmpty={false}
      />
    )
  }
  if (row.type === "bonus_types") {
    const selected = Array.isArray(value)
      ? value
      : value && value !== "none"
        ? [String(value)]
        : []
    return (
      <ChipToggleGroup
        options={BONUS_TYPE_OPTS}
        value={selected}
        onChange={(next) => onCommit(next)}
        multiple
        allowEmpty
      />
    )
  }
  if (row.type === "bonus_pct") {
    const n = typeof value === "number" ? value : value ? Number(value) : null
    return (
      <BonusPctSlider
        value={Number.isFinite(n) ? n : null}
        onCommit={(pct: BonusPct) => onCommit(pct)}
      />
    )
  }
  if (row.type === "tax_basis") {
    return (
      <ChipToggleGroup
        options={TAX_BASIS_OPTS}
        value={[String(value ?? "gross")]}
        onChange={(next) => onCommit(next[0] ?? "gross")}
        multiple={false}
        allowEmpty={false}
      />
    )
  }
  const cellValue = Array.isArray(value) ? value.join(", ") : value
  const cellType = row.type === "number" || row.type === "date" ? row.type : "text"
  return <EditableCell value={cellValue} type={cellType} highlight={highlight} onCommit={onCommit} />
}
