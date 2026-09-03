import { useState } from "react"
import { Popover } from "radix-ui"
import { CalendarDays, ChevronLeft, ChevronRight, X } from "lucide-react"
import { cn } from "@/lib/utils"

// Фильтр по диапазону дат активности вакансий (та же дата, что на карточке: сдвиг статуса /
// отклик / оценка). UX как в aviasales: два клика по календарю задают range (старт → конец),
// между ними — подсветка; плюс быстрые пресеты.

const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

function toISO(d: Date): string {
  const m = String(d.getMonth() + 1).padStart(2, "0")
  const day = String(d.getDate()).padStart(2, "0")
  return `${d.getFullYear()}-${m}-${day}`
}
function parseISO(s: string): Date | null {
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})$/)
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : null
}
function fmtShort(s: string): string {
  const d = parseISO(s)
  if (!d) return ""
  return `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}`
}
function startOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), 1)
}
function sameDay(a: Date | null, b: Date | null): boolean {
  return !!a && !!b && a.getTime() === b.getTime()
}
function monthLabel(d: Date): string {
  return d.toLocaleDateString("ru-RU", { month: "long", year: "numeric" })
}

function triggerLabel(from: string, to: string): string {
  if (from && to) return `${fmtShort(from)} – ${fmtShort(to)}`
  if (from) return `с ${fmtShort(from)}`
  if (to) return `по ${fmtShort(to)}`
  return "Период"
}

export function DateRangeFilter({
  from,
  to,
  onChange,
}: {
  from: string
  to: string
  onChange: (from: string, to: string) => void
}) {
  const fromD = parseISO(from)
  const toD = parseISO(to)
  const active = !!from || !!to
  const [open, setOpen] = useState(false)
  const [month, setMonth] = useState(() => startOfMonth(toD ?? fromD ?? new Date()))
  // anchor — первый клик незавершённого диапазона; hover — для подсветки будущего конца.
  const [anchor, setAnchor] = useState<Date | null>(null)
  const [hover, setHover] = useState<Date | null>(null)

  // Эффективный диапазон для подсветки: либо выбираемый (anchor→hover), либо уже заданный.
  let lo: Date | null = fromD
  let hi: Date | null = toD
  if (anchor) {
    const other = hover ?? anchor
    lo = anchor <= other ? anchor : other
    hi = anchor <= other ? other : anchor
  }

  function clickDay(d: Date) {
    if (anchor) {
      const [a, b] = d < anchor ? [d, anchor] : [anchor, d]
      onChange(toISO(a), toISO(b))
      setAnchor(null)
      setHover(null)
    } else {
      setAnchor(d)
      setHover(d)
      onChange(toISO(d), toISO(d))
    }
  }

  function preset(days: number) {
    const end = new Date()
    end.setHours(0, 0, 0, 0)
    const start = new Date(end)
    start.setDate(start.getDate() - (days - 1))
    setAnchor(null)
    setHover(null)
    onChange(toISO(start), toISO(end))
  }

  function clear() {
    setAnchor(null)
    setHover(null)
    onChange("", "")
  }

  // Сетка месяца: ведущие пустоты до первого дня (неделя с понедельника), затем дни.
  const first = startOfMonth(month)
  const leading = (first.getDay() + 6) % 7
  const daysInMonth = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate()
  const cells: (Date | null)[] = [
    ...Array.from({ length: leading }, () => null),
    ...Array.from(
      { length: daysInMonth },
      (_, i) => new Date(month.getFullYear(), month.getMonth(), i + 1),
    ),
  ]

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <button
          type="button"
          className={cn(
            "flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400",
            active
              ? "border-slate-300 bg-slate-100 text-slate-900"
              : "border-slate-200 text-slate-500 hover:bg-slate-50",
          )}
        >
          <CalendarDays className="size-4 shrink-0 text-slate-400" strokeWidth={2} />
          <span className="tabular-nums">{triggerLabel(from, to)}</span>
          {active && (
            <X
              className="size-3.5 shrink-0 text-slate-400 hover:text-slate-700"
              strokeWidth={2}
              onClick={(e) => {
                e.stopPropagation()
                clear()
              }}
            />
          )}
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="start"
          sideOffset={6}
          className="z-50 w-72 rounded-xl border border-slate-200 bg-white p-3 shadow-lg"
        >
          <div className="flex items-center gap-1.5">
            {[
              { label: "7 дней", days: 7 },
              { label: "14 дней", days: 14 },
              { label: "30 дней", days: 30 },
            ].map((p) => (
              <button
                key={p.days}
                type="button"
                onClick={() => preset(p.days)}
                className="rounded-lg border border-slate-200 px-2 py-1 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-50"
              >
                {p.label}
              </button>
            ))}
            <button
              type="button"
              onClick={clear}
              className="ml-auto rounded-lg px-2 py-1 text-xs font-medium text-slate-400 transition-colors hover:text-slate-700"
            >
              Сбросить
            </button>
          </div>

          <div className="mt-3 flex items-center justify-between">
            <button
              type="button"
              aria-label="Прошлый месяц"
              onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))}
              className="flex size-7 items-center justify-center rounded-lg text-slate-500 transition-colors hover:bg-slate-100"
            >
              <ChevronLeft className="size-4" strokeWidth={2} />
            </button>
            <span className="text-sm font-medium capitalize text-slate-900">
              {monthLabel(month)}
            </span>
            <button
              type="button"
              aria-label="Следующий месяц"
              onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))}
              className="flex size-7 items-center justify-center rounded-lg text-slate-500 transition-colors hover:bg-slate-100"
            >
              <ChevronRight className="size-4" strokeWidth={2} />
            </button>
          </div>

          <div className="mt-2 grid grid-cols-7 gap-y-1 text-center">
            {WEEKDAYS.map((w) => (
              <span key={w} className="text-xs font-medium uppercase tracking-wide text-slate-400">
                {w}
              </span>
            ))}
            {cells.map((d, i) => {
              if (!d) return <span key={`b${i}`} />
              const isLo = sameDay(d, lo)
              const isHi = sameDay(d, hi)
              const inRange = !!lo && !!hi && d >= lo && d <= hi
              const isEdge = isLo || isHi
              return (
                <button
                  key={toISO(d)}
                  type="button"
                  onClick={() => clickDay(d)}
                  onMouseEnter={() => anchor && setHover(d)}
                  className={cn(
                    "mx-auto flex size-8 items-center justify-center rounded-lg text-sm tabular-nums transition-colors",
                    isEdge
                      ? "bg-slate-900 font-semibold text-white"
                      : inRange
                        ? "bg-slate-100 text-slate-900"
                        : "text-slate-600 hover:bg-slate-100",
                  )}
                >
                  {d.getDate()}
                </button>
              )
            })}
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}
