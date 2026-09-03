import * as React from "react"
import { ChevronLeft, ChevronRight, CalendarIcon } from "lucide-react"
import { format, parse, isValid } from "date-fns"
import { ru } from "date-fns/locale"

import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Calendar } from "@/components/ui/calendar"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"

// Три уровня точности (RD-2/5/6, план P-4): один компонент на всё приложение, чтобы
// день/месяц/год не разъехались по три разных виджета. Значение в модели — строка ISO-
// подстрока (YYYY-MM-DD / YYYY-MM / YYYY), парсинг только при открытии/выборе.
export type DateGranularity = "day" | "month" | "year"

const FORMAT_BY_GRANULARITY: Record<DateGranularity, string> = {
  day: "yyyy-MM-dd",
  month: "yyyy-MM",
  year: "yyyy",
}

const DISPLAY_FORMAT_BY_GRANULARITY: Record<DateGranularity, string> = {
  day: "d MMMM yyyy",
  month: "LLLL yyyy",
  year: "yyyy",
}

const MONTH_LABELS = [
  "Янв",
  "Фев",
  "Мар",
  "Апр",
  "Май",
  "Июн",
  "Июл",
  "Авг",
  "Сен",
  "Окт",
  "Ноя",
  "Дек",
]

function parseValue(value: string, granularity: DateGranularity): Date | undefined {
  if (!value) return undefined
  const parsed = parse(value, FORMAT_BY_GRANULARITY[granularity], new Date())
  return isValid(parsed) ? parsed : undefined
}

// Грид 4x3 месяцев + быстрый выбор года (клик по году → декада), без листания ±1.
function MonthGrid({ value, onSelect }: { value: Date | undefined; onSelect: (d: Date) => void }) {
  const initialYear = value?.getFullYear() ?? new Date().getFullYear()
  const [year, setYear] = React.useState(initialYear)
  const [pickingYear, setPickingYear] = React.useState(false)
  const [decadeStart, setDecadeStart] = React.useState(Math.floor(initialYear / 10) * 10 - 1)

  if (pickingYear) {
    const years = Array.from({ length: 12 }, (_, i) => decadeStart + i)
    return (
      <div className="w-56 space-y-3">
        <div className="flex items-center justify-between">
          <Button
            variant="ghost"
            size="icon-sm"
            className="text-muted-foreground"
            onClick={() => setDecadeStart((y) => y - 10)}
          >
            <ChevronLeft className="size-4" />
          </Button>
          <span className="text-sm font-medium text-foreground">
            {years[1]}–{years[10]}
          </span>
          <Button
            variant="ghost"
            size="icon-sm"
            className="text-muted-foreground"
            onClick={() => setDecadeStart((y) => y + 10)}
          >
            <ChevronRight className="size-4" />
          </Button>
        </div>
        <div className="grid grid-cols-3 gap-1.5">
          {years.map((y) => (
            <button
              key={y}
              type="button"
              onClick={() => {
                setYear(y)
                setPickingYear(false)
              }}
              className={cn(
                "rounded-md px-2 py-1.5 text-sm text-foreground hover:bg-accent",
                year === y && "bg-primary text-primary-foreground hover:bg-primary",
              )}
            >
              {y}
            </button>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="w-56 space-y-3">
      <div className="flex items-center justify-between">
        <Button
          variant="ghost"
          size="icon-sm"
          className="text-muted-foreground"
          onClick={() => setYear((y) => y - 1)}
        >
          <ChevronLeft className="size-4" />
        </Button>
        <button
          type="button"
          onClick={() => {
            setDecadeStart(Math.floor(year / 10) * 10 - 1)
            setPickingYear(true)
          }}
          className="rounded-md px-2 py-1 text-sm font-medium text-foreground hover:bg-accent"
          title="Выбрать год"
        >
          {year}
        </button>
        <Button
          variant="ghost"
          size="icon-sm"
          className="text-muted-foreground"
          onClick={() => setYear((y) => y + 1)}
        >
          <ChevronRight className="size-4" />
        </Button>
      </div>
      <div className="grid grid-cols-3 gap-1.5">
        {MONTH_LABELS.map((label, i) => {
          const selected = value?.getFullYear() === year && value?.getMonth() === i
          return (
            <button
              key={label}
              type="button"
              onClick={() => onSelect(new Date(year, i, 1))}
              className={cn(
                "rounded-md px-2 py-1.5 text-sm text-foreground hover:bg-accent",
                selected && "bg-primary text-primary-foreground hover:bg-primary",
              )}
            >
              {label}
            </button>
          )
        })}
      </div>
    </div>
  )
}
// Грид 4x3 годов, декада за раз.
function YearGrid({ value, onSelect }: { value: Date | undefined; onSelect: (d: Date) => void }) {
  const baseYear = value?.getFullYear() ?? new Date().getFullYear()
  const [decadeStart, setDecadeStart] = React.useState(Math.floor(baseYear / 10) * 10 - 1)
  const years = Array.from({ length: 12 }, (_, i) => decadeStart + i)
  return (
    <div className="w-56 space-y-3">
      <div className="flex items-center justify-between">
        <Button
          variant="ghost"
          size="icon-sm"
          className="text-muted-foreground"
          onClick={() => setDecadeStart((y) => y - 10)}
        >
          <ChevronLeft className="size-4" />
        </Button>
        <span className="text-sm font-medium text-foreground">
          {years[1]}–{years[10]}
        </span>
        <Button
          variant="ghost"
          size="icon-sm"
          className="text-muted-foreground"
          onClick={() => setDecadeStart((y) => y + 10)}
        >
          <ChevronRight className="size-4" />
        </Button>
      </div>
      <div className="grid grid-cols-3 gap-1.5">
        {years.map((y) => {
          const selected = value?.getFullYear() === y
          return (
            <button
              key={y}
              type="button"
              onClick={() => onSelect(new Date(y, 0, 1))}
              className={cn(
                "rounded-md px-2 py-1.5 text-sm text-foreground hover:bg-accent",
                selected && "bg-primary text-primary-foreground hover:bg-primary",
              )}
            >
              {y}
            </button>
          )
        })}
      </div>
    </div>
  )
}

export function DatePicker({
  value,
  onChange,
  granularity = "day",
  placeholder = "Выбрать дату",
  disabled,
  className,
  defaultMonth,
  fromYear,
  toYear,
}: {
  value: string
  onChange: (v: string) => void
  granularity?: DateGranularity
  placeholder?: string
  disabled?: boolean
  className?: string
  defaultMonth?: Date
  fromYear?: number
  toYear?: number
}) {
  const [open, setOpen] = React.useState(false)
  const date = parseValue(value, granularity)
  const today = new Date()
  // День: дропдауны год+месяц (дата рождения и т.п.) — без листания месяцев стрелками.
  const dayStartMonth =
    fromYear != null ? new Date(fromYear, 0) : new Date(today.getFullYear() - 100, 0)
  const dayEndMonth = toYear != null ? new Date(toYear, 11) : new Date(today.getFullYear(), 11)

  const select = (d: Date) => {
    onChange(format(d, FORMAT_BY_GRANULARITY[granularity]))
    setOpen(false)
  }

  return (
    <Popover open={disabled ? false : open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          disabled={disabled}
          className={cn(
            "flex h-9 w-full items-center gap-2 rounded-md border border-input bg-card px-2.5 text-sm text-foreground shadow-xs outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring",
            !date && "text-muted-foreground",
            disabled && "cursor-not-allowed opacity-50 hover:bg-card",
            className,
          )}
        >
          <CalendarIcon className="size-4 shrink-0 text-muted-foreground" strokeWidth={2} />
          <span className="truncate">
            {date
              ? format(date, DISPLAY_FORMAT_BY_GRANULARITY[granularity], { locale: ru })
              : placeholder}
          </span>
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-3">
        {granularity === "day" && (
          <Calendar
            mode="single"
            selected={date}
            onSelect={(d) => d && select(d)}
            defaultMonth={defaultMonth ?? date ?? new Date(today.getFullYear() - 25, 0)}
            captionLayout="dropdown"
            reverseYears
            startMonth={dayStartMonth}
            endMonth={dayEndMonth}
          />
        )}
        {granularity === "month" && <MonthGrid value={date} onSelect={select} />}
        {granularity === "year" && <YearGrid value={date} onSelect={select} />}
      </PopoverContent>
    </Popover>
  )
}
