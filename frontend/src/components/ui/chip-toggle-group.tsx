import { cn } from "@/lib/utils"

// Группа кнопок-чипов с переключением (мульти- или одиночный выбор). Замена выпадашкам-фильтрам:
// один клик — вкл/выкл, видно сразу всё (CLAUDE.md UX — быстрые кнопки вместо select-боксов). UI-0.
// Выбор хранится как массив значений (для single — 0/1 элемент). Пустой массив = «любой».

export type ChipOption = {
  value: string
  label: string
  // Пастельная заливка активного чипа (статусы/вердикты). Без неё — нейтральные токены.
  activeClass?: string
}

export function ChipToggleGroup({
  options,
  value,
  onChange,
  multiple = true,
  allowEmpty = true,
  size = "sm",
  className,
}: {
  options: ChipOption[]
  value: string[]
  onChange: (next: string[]) => void
  multiple?: boolean
  allowEmpty?: boolean
  size?: "sm" | "md"
  className?: string
}) {
  function toggle(v: string) {
    const has = value.includes(v)
    if (multiple) {
      onChange(has ? value.filter((x) => x !== v) : [...value, v])
      return
    }
    // Одиночный: повторный клик по активному снимает выбор только если разрешён пустой.
    onChange(has ? (allowEmpty ? [] : value) : [v])
  }

  return (
    <div className={cn("flex flex-wrap items-center gap-1", className)}>
      {options.map((opt) => {
        const on = value.includes(opt.value)
        return (
          <button
            key={opt.value}
            type="button"
            aria-pressed={on}
            onClick={() => toggle(opt.value)}
            className={cn(
              "rounded-lg border font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              size === "sm" ? "px-2 py-1 text-xs" : "px-2.5 py-1.5 text-sm",
              on
                ? (opt.activeClass ?? "border-border bg-border/70 text-foreground")
                : "border-border text-muted-foreground hover:bg-accent",
            )}
          >
            {opt.label}
          </button>
        )
      })}
    </div>
  )
}
