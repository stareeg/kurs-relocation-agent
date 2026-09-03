import { type ChangeEvent, useRef, useState } from "react"
import { ChipToggleGroup, type ChipOption } from "@/components/ui/chip-toggle-group"
import { SALARY_BASIS_OPTIONS } from "@/lib/resume-taxonomy"
import { cn } from "@/lib/utils"
import { PanelFieldLabel as FieldLabel } from "./panel-field"
import { usePatchResumeField, useResumeData } from "./use-resume"

const SALARY_CURRENCY_OPTS: ChipOption[] = [
  { value: "RUB", label: "₽" },
  { value: "USD", label: "$" },
  { value: "EUR", label: "€" },
]

function groupThousands(digits: string): string {
  return digits.replace(/\B(?=(\d{3})+(?!\d))/g, " ")
}

/** Живая разбивка по 3 знака (как OfferDraftCard) — без стрелок type=number. */
function GroupedSalaryInput({
  value,
  onChange,
  onCommit,
  ariaLabel,
}: {
  value: string
  onChange: (digits: string) => void
  onCommit: () => void
  ariaLabel: string
}) {
  const ref = useRef<HTMLInputElement>(null)

  function handleChange(e: ChangeEvent<HTMLInputElement>) {
    const el = e.target
    const caret = el.selectionStart ?? el.value.length
    const digitsBeforeCaret = el.value.slice(0, caret).replace(/\D/g, "").length
    const digits = el.value.replace(/\D/g, "")
    onChange(digits)
    requestAnimationFrame(() => {
      if (!ref.current) return
      const formatted = groupThousands(digits)
      let seen = 0
      let pos = formatted.length
      for (let i = 0; i < formatted.length; i++) {
        if (formatted[i] !== " ") seen++
        if (seen === digitsBeforeCaret) {
          pos = i + 1
          break
        }
      }
      if (digitsBeforeCaret === 0) pos = 0
      ref.current.setSelectionRange(pos, pos)
    })
  }

  return (
    <input
      ref={ref}
      inputMode="numeric"
      value={groupThousands(value)}
      onChange={handleChange}
      onBlur={onCommit}
      onKeyDown={(e) => {
        if (e.key === "Enter") e.currentTarget.blur()
      }}
      placeholder="0"
      aria-label={ariaLabel}
      className={cn(
        "h-8 w-full min-w-0 rounded-md border border-slate-200 bg-white px-2 text-sm tabular-nums text-slate-800 shadow-xs outline-none transition-colors",
        "hover:bg-slate-50 focus-visible:ring-2 focus-visible:ring-slate-300",
      )}
    />
  )
}

/** Вилка и шкала налогов в подблоке «Зарплата». */
export function SalaryPrefsPanel() {
  const { data } = useResumeData()
  const patchField = usePatchResumeField()

  if (!data) return null

  const pos = data.position

  function patchPosition(p: {
    salary_min?: number | null
    salary_comfortable?: number | null
    salary_currency?: string
    salary_basis?: string
  }) {
    patchField.mutate({ position: p })
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-[1fr_1fr_auto] items-end gap-2">
        <CompactSalaryField
          label="Минимум"
          helpId="resume.salary-min"
          value={pos.salary_min ?? null}
          needsFill={pos.salary_min == null}
          onCommit={(v) => patchPosition({ salary_min: v })}
        />
        <CompactSalaryField
          label="Комфорт"
          helpId="resume.salary-comfort"
          value={pos.salary_comfortable ?? null}
          onCommit={(v) => patchPosition({ salary_comfortable: v })}
        />
        <div className="pb-px">
          <ChipToggleGroup
            options={SALARY_CURRENCY_OPTS}
            value={[pos.salary_currency || "RUB"]}
            onChange={([v]) => patchPosition({ salary_currency: v ?? "RUB" })}
            multiple={false}
            allowEmpty={false}
            className="shrink-0"
          />
        </div>
      </div>

      <div className="space-y-1.5">
        <FieldLabel helpId="resume.salary-basis">Налоги</FieldLabel>
        <ChipToggleGroup
          options={SALARY_BASIS_OPTIONS}
          value={pos.salary_basis ? [pos.salary_basis] : ["На руки"]}
          onChange={([v]) => patchPosition({ salary_basis: v ?? "На руки" })}
          multiple={false}
          allowEmpty={false}
        />
      </div>
    </div>
  )
}

function CompactSalaryField({
  label,
  helpId,
  value,
  onCommit,
  needsFill,
}: {
  label: string
  helpId: "resume.salary-min" | "resume.salary-comfort"
  value: number | null
  onCommit: (v: number | null) => void
  needsFill?: boolean
}) {
  const [digits, setDigits] = useState(value == null ? "" : String(value))
  const [prevValue, setPrevValue] = useState(value)

  if (value !== prevValue) {
    setPrevValue(value)
    setDigits(value == null ? "" : String(value))
  }

  function commit() {
    const next = digits.trim() === "" ? null : Number(digits)
    if (next !== null && Number.isNaN(next)) {
      setDigits(value == null ? "" : String(value))
      return
    }
    if (next === value) return
    onCommit(next)
  }

  return (
    <label className="block min-w-0 space-y-1">
      <FieldLabel helpId={helpId} needsFill={needsFill}>
        {label}
      </FieldLabel>
      <GroupedSalaryInput value={digits} onChange={setDigits} onCommit={commit} ariaLabel={label} />
    </label>
  )
}
