import { useState, type ReactNode } from "react"
import { format, isValid, parseISO } from "date-fns"
import { Button } from "@/components/ui/button"
import { Calendar } from "@/components/ui/calendar"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"

// Быстрый попап «дата + время» под конкретный кейс (перенос даты/времени собеса) — `DatePicker`
// (components/ui/date-picker.tsx) специально без времени, на нём завязаны три другие
// гранулярности (день/месяц/год), трогать не нужно. Значение — ISO-строка с таймзоной, как
// `scheduled_at` у InterviewStage; собирается из локальной даты/времени пользователя.
export function DateTimePopover({
  value,
  onChange,
  trigger,
}: {
  value: string | null | undefined
  onChange: (iso: string) => void
  trigger: ReactNode
}) {
  const [open, setOpen] = useState(false)
  const [date, setDate] = useState<Date>(() => initialDate(value))
  const [time, setTime] = useState<string>(() => format(initialDate(value), "HH:mm"))

  // Пересинхронизируем черновик с текущим value при каждом открытии — не в эффекте (лишний
  // ререндер), а прямо в обработчике смены состояния попапа.
  function handleOpenChange(next: boolean) {
    if (next) {
      const d = initialDate(value)
      setDate(d)
      setTime(format(d, "HH:mm"))
    }
    setOpen(next)
  }

  function save() {
    const [hh, mm] = time.split(":").map(Number)
    const combined = new Date(date)
    combined.setHours(hh || 0, mm || 0, 0, 0)
    onChange(combined.toISOString())
    setOpen(false)
  }

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>{trigger}</PopoverTrigger>
      <PopoverContent className="w-auto space-y-3 p-3">
        <Calendar mode="single" selected={date} onSelect={(d) => d && setDate(d)} />
        <div className="flex items-center gap-2">
          <input
            type="time"
            value={time}
            onChange={(e) => setTime(e.target.value)}
            className="h-9 flex-1 rounded-md border border-input bg-card px-2.5 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          <Button size="sm" onClick={save}>
            Сохранить
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  )
}

function initialDate(value: string | null | undefined): Date {
  const parsed = value ? parseISO(value) : undefined
  return parsed && isValid(parsed) ? parsed : new Date()
}
