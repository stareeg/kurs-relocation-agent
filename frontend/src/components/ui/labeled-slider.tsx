import { Slider } from "@/components/ui/slider"
import { Plus } from "lucide-react"

// Слайдер с подписанным текущим значением — замена `<Input type="number">` для полей-порогов
// (скор, лимиты в день): слайдер честнее для маленького диапазона допустимых значений, число
// рядом убирает необходимость лезть в спину курсора, чтобы понять, что выставлено. Один
// компонент на discovery- и auto-apply-карты (`PlatformPipelineSection.tsx`), не дублировать
// разметку «label + число + Slider» в каждом месте отдельно.
export function LabeledSlider({
  label,
  hint,
  value,
  valueLabel,
  onChange,
  min,
  max,
  step,
  disabled,
}: {
  label: string
  /** Подпись под названием — что означает выставленное значение. Нужна там, где одно число
   * задаёт границу между двумя исходами и без пояснения читается как «просто порог». */
  hint?: string
  value: number
  /** Что показать справа вместо голого числа — например вычисленный диапазон «спорная зона:
   * 65–75». По умолчанию — само `value`. */
  valueLabel?: React.ReactNode
  onChange: (value: number) => void
  min: number
  max: number
  step: number
  disabled?: boolean
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-2 text-xs text-slate-600">
        <span>{label}</span>
        <span className="flex items-center gap-1 text-lg font-bold tabular-nums text-slate-900">
          {valueLabel ?? value}
          <Plus className="size-3.5 text-slate-400" strokeWidth={2} />
        </span>
      </div>
      {hint && <p className="text-[11px] leading-tight text-slate-400">{hint}</p>}
      <Slider
        min={min}
        max={max}
        step={step}
        value={[value]}
        onValueChange={([v]) => onChange(v ?? value)}
        disabled={disabled}
        aria-label={label}
      />
    </div>
  )
}
