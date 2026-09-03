import { useState } from "react"
import { Check, ChevronDown } from "lucide-react"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { cn } from "@/lib/utils"

// Select-box вид (рамка как у SelectTrigger), но мульти-выбор без закрытия попапа на каждый клик
// (UX4-8) — обычный `Select` закрывается после первого выбора, что неудобно, когда нужно отметить
// несколько вариантов подряд. Закрытие — явной кнопкой «Свернуть», кликом вне или Escape (Radix
// Popover из коробки).

export interface MultiSelectPopoverOption {
  value: string
  label: string
}

export function MultiSelectPopover({
  options,
  value,
  onChange,
  placeholder = "Выбрать",
  className,
  max,
  columns = 1,
}: {
  options: MultiSelectPopoverOption[]
  value: string[]
  onChange: (next: string[]) => void
  placeholder?: string
  className?: string
  /** Верхний предел выбранных значений; снятие галочки всегда разрешено. */
  max?: number
  /** Сколько колонок в раскрытом списке (длинные справочники — 2, чтобы не было одного
   *  высокого столбца, RD-6). */
  columns?: number
}) {
  const [open, setOpen] = useState(false)

  function toggle(v: string) {
    if (value.includes(v)) {
      onChange(value.filter((x) => x !== v))
      return
    }
    if (max != null && value.length >= max) return
    onChange([...value, v])
  }

  const labels = options.filter((o) => value.includes(o.value)).map((o) => o.label)
  const summary =
    labels.length === 0
      ? placeholder
      : labels.length <= 2
        ? labels.join(", ")
        : `${labels.length} выбрано`
  const atMax = max != null && value.length >= max

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            "flex h-9 w-full items-center justify-between gap-1.5 rounded-md border border-input bg-card px-3 text-sm text-foreground shadow-xs outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring",
            labels.length === 0 && "text-muted-foreground",
            className,
          )}
        >
          <span className="truncate">{summary}</span>
          <ChevronDown className="size-4 shrink-0 text-muted-foreground" strokeWidth={2} />
        </button>
      </PopoverTrigger>
      <PopoverContent className={cn("p-1.5", columns > 1 ? "w-[30rem]" : "w-72")} align="start">
        <div
          className={cn("gap-0.5", columns > 1 ? "grid grid-cols-2 grid-flow-col" : "space-y-0.5")}
          style={
            columns > 1
              ? { gridTemplateRows: `repeat(${Math.ceil(options.length / columns)}, auto)` }
              : undefined
          }
        >
          {options.map((opt) => {
            const on = value.includes(opt.value)
            const disabled = !on && atMax
            return (
              <button
                key={opt.value}
                type="button"
                disabled={disabled}
                onClick={() => toggle(opt.value)}
                className={cn(
                  "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors hover:bg-accent",
                  on ? "text-foreground" : "text-muted-foreground",
                  disabled && "cursor-not-allowed opacity-40 hover:bg-transparent",
                )}
              >
                <span
                  className={cn(
                    "flex size-3.5 shrink-0 items-center justify-center rounded border",
                    on
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-input text-transparent",
                  )}
                >
                  <Check className="size-3" strokeWidth={3} />
                </span>
                {opt.label}
              </button>
            )
          })}
        </div>
        <div className="mt-1 border-t pt-1.5">
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="w-full rounded-md px-2 py-1 text-center text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            Свернуть
          </button>
        </div>
      </PopoverContent>
    </Popover>
  )
}
