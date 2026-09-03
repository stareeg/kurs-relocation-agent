import { cn } from "@/lib/utils"

/**
 * Сегмент-переключатель одного выбора: пилюли на общем сером треке.
 *
 * Отличие от `ChipToggleGroup` — тот про «набор фильтров» (несколько независимых чипов,
 * пустой набор = «любой»), а этот про «одно из N» и читается как один контрол, а не как
 * россыпь кнопок. Заведён на Этапе 0 редизайна админки: там одиночный выбор рисовался
 * тёмной пилюлей `bg-slate-900` на голом фоне, из-за чего вкладки, период и уровень лога
 * выглядели одинаково важными и одинаково «нажатыми».
 *
 * Активный — белый на сером треке (тише тёмного), как в шапке блока сравнения на «Рынке».
 */
export type SegmentOption<T extends string = string> = {
  value: T
  label: string
  /** Мелкая приписка справа от подписи: счётчик, единица. */
  hint?: string
  title?: string
  disabled?: boolean
}

const TRACK: Record<"sm" | "md" | "lg", string> = {
  sm: "gap-0.5 rounded-lg p-0.5",
  md: "gap-0.5 rounded-lg p-1",
  lg: "h-11 gap-1 rounded-xl p-1",
}

const ITEM: Record<"sm" | "md" | "lg", string> = {
  sm: "rounded-md px-2 py-1 text-xs",
  md: "rounded-md px-3 py-1.5 text-sm",
  lg: "rounded-lg px-3.5 text-sm",
}

export function SegmentedControl<T extends string = string>({
  options,
  value,
  onChange,
  size = "md",
  ariaLabel,
  className,
}: {
  options: readonly SegmentOption<T>[]
  value: T
  onChange: (next: T) => void
  size?: "sm" | "md" | "lg"
  ariaLabel?: string
  className?: string
}) {
  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className={cn("inline-flex items-center bg-slate-100", TRACK[size], className)}
    >
      {options.map((option) => {
        const on = option.value === value
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={on}
            disabled={option.disabled}
            title={option.title}
            onClick={() => onChange(option.value)}
            className={cn(
              "inline-flex shrink-0 items-center gap-1.5 font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-40",
              ITEM[size],
              on ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-800",
            )}
          >
            {option.label}
            {option.hint ? (
              <span className="tabular-nums text-slate-400">{option.hint}</span>
            ) : null}
          </button>
        )
      })}
    </div>
  )
}
