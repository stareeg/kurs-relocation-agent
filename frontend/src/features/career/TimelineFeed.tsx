import { useEffect, useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import {
  ArrowRightLeft,
  Briefcase,
  ChevronDown,
  FileText,
  FolderKanban,
  Gift,
  GraduationCap,
  History,
  Loader2,
  MapPin,
  Radar,
  Route,
  Send,
  TrendingUp,
  type LucideIcon,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { ChipToggleGroup, type ChipOption } from "@/components/ui/chip-toggle-group"
import { EmptyState, ErrorState } from "@/components/ui/empty-state"
import { Input } from "@/components/ui/input"
import { SectionCard } from "@/components/ui/section-card"
import { Skeleton } from "@/components/ui/skeleton"
import { parseDate } from "@/lib/format"
import { cn } from "@/lib/utils"
import { useCreateTimelineEntry, useTimeline } from "./use-career"
import type { ManualTimelineKind, TimelineEventView } from "@/api/career"

// Виды событий, которые владелец заводит руками (без "other" — техническое "другое", не выбор
// человека). Ключ для быстрого добавления в шапке блока (plans/career_redesign_2026_08_26.md).
const MANUAL_KIND_OPTIONS: ChipOption[] = [
  { value: "job_start", label: "Вышел на работу" },
  { value: "promotion", label: "Повышение" },
  { value: "project", label: "Проект" },
  { value: "certificate", label: "Сертификат" },
  { value: "relocation", label: "Переезд" },
]

// Форма, не цвет-ради-цвета (Этап 3.2): иконка только называет вид события, сигнал — отдельно.
const KIND_ICON: Record<string, LucideIcon> = {
  application: Send,
  stage: ArrowRightLeft,
  offer: Gift,
  job_start: Briefcase,
  promotion: TrendingUp,
  project: FolderKanban,
  certificate: GraduationCap,
  relocation: MapPin,
  other: FileText,
  search_mode: Radar,
  search_track: Route,
}

const KIND_PLURAL: Record<string, readonly [string, string, string]> = {
  application: ["отклик", "отклика", "откликов"],
  stage: ["переход этапа", "перехода этапа", "переходов этапа"],
  offer: ["оффер", "оффера", "офферов"],
  job_start: ["событие", "события", "событий"],
  promotion: ["событие", "события", "событий"],
  project: ["событие", "события", "событий"],
  certificate: ["событие", "события", "событий"],
  relocation: ["событие", "события", "событий"],
  other: ["событие", "события", "событий"],
  search_mode: ["переключение режима", "переключения режима", "переключений режима"],
  search_track: ["переключение трека", "переключения трека", "переключений трека"],
}

const DEFAULT_PLURAL: readonly [string, string, string] = ["событие", "события", "событий"]

function plural(count: number, forms: readonly [string, string, string]): string {
  const tail = count % 10
  const teen = count % 100 >= 11 && count % 100 <= 14
  if (!teen && tail === 1) return forms[0]
  if (!teen && tail >= 2 && tail <= 4) return forms[1]
  return forms[2]
}

// Решение владельца п.4 (plans/career_redesign_2026_08_26.md): порог свёртки — от 3 повторов.
const COLLAPSE_THRESHOLD = 3

// По умолчанию — 3 последних дня с событиями, «Показать ещё» раскрывает до 7 (пользовательский
// запрос той же сессии, что и Этап 5). Считаем в днях-с-событиями, не в календарных сутках —
// иначе при паузе в поиске лента выглядела бы пустой без единой строки.
const DAY_LIMIT_DEFAULT = 3
const DAY_LIMIT_EXPANDED = 7

// Зеркало FUNNEL_STATUS_RANK (core/kernel/schemas/funnel.py) — только для локального сигнала
// «регресс этапа назад» в ленте, не источник истины для воронки.
const STAGE_RANK: Record<string, number> = {
  Просмотр: 0,
  Отклик: 10,
  Скрининг: 30,
  Техничка: 50,
  Финал: 60,
  Оффер: 70,
  Отказ: -10,
  Архив: -20,
}

type EventTone = "strong" | "bad" | "warn" | null

const TONE_ICON_CLASS: Record<Exclude<EventTone, null>, string> = {
  strong: "bg-status-strong-soft text-status-strong-fg",
  bad: "bg-status-bad-soft text-status-bad-fg",
  warn: "bg-status-warn-soft text-status-warn-fg",
}

function payloadOf(ev: TimelineEventView): Record<string, unknown> {
  return (ev.payload ?? {}) as Record<string, unknown>
}

function eventTone(ev: TimelineEventView): EventTone {
  if (ev.kind === "offer") return "strong"
  if (ev.kind === "stage") {
    const payload = payloadOf(ev)
    const stage = String(payload.stage ?? "")
    const previous = String(payload.previous_stage ?? "")
    if (stage === "Отказ") return "bad"
    if (previous && stage in STAGE_RANK && previous in STAGE_RANK && STAGE_RANK[stage] < STAGE_RANK[previous]) {
      return "warn"
    }
  }
  return null
}

// `title` пишется на вставке как "<core> · <vacancy_id>" (timeline.py) — на чтении подменяем
// хвост на company/vacancy_title из Этапа 2.2, id остаётся фолбэком, если вакансия не резолвилась.
function splitTitle(ev: TimelineEventView): { core: string; label: string } {
  const vacancyId = String(payloadOf(ev).vacancy_id ?? "").trim()
  let core = ev.title
  if (vacancyId) {
    const suffix = ` · ${vacancyId}`
    if (core.endsWith(suffix)) core = core.slice(0, -suffix.length)
  }
  const named = [ev.company, ev.vacancy_title].filter(Boolean).join(", ")
  return { core, label: named || vacancyId }
}

function dayLabel(iso: string | null | undefined): string {
  const d = parseDate(iso)
  if (!d) return "Без даты"
  return d.toLocaleDateString("ru-RU", { day: "numeric", month: "short" })
}

function timeLabel(iso: string | null | undefined): string {
  const d = parseDate(iso)
  if (!d) return ""
  return d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })
}

type DayItem =
  | { type: "event"; event: TimelineEventView }
  | { type: "collapsed"; kind: string; events: TimelineEventView[] }

function groupByDay(events: TimelineEventView[]): [string, DayItem[]][] {
  const days = new Map<string, TimelineEventView[]>()
  for (const ev of events) {
    const key = dayLabel(ev.occurred_at)
    const bucket = days.get(key)
    if (bucket) bucket.push(ev)
    else days.set(key, [ev])
  }
  return [...days.entries()].map(([day, dayEvents]) => {
    const byKind = new Map<string, TimelineEventView[]>()
    const order: string[] = []
    for (const ev of dayEvents) {
      const bucket = byKind.get(ev.kind)
      if (bucket) bucket.push(ev)
      else {
        byKind.set(ev.kind, [ev])
        order.push(ev.kind)
      }
    }
    const items: DayItem[] = []
    for (const kind of order) {
      const evs = byKind.get(kind)!
      if (evs.length >= COLLAPSE_THRESHOLD) {
        items.push({ type: "collapsed", kind, events: evs })
      } else {
        for (const ev of evs) items.push({ type: "event", event: ev })
      }
    }
    items.sort((a, b) => {
      const at = a.type === "event" ? a.event.occurred_at : a.events[0].occurred_at
      const bt = b.type === "event" ? b.event.occurred_at : b.events[0].occurred_at
      return (parseDate(bt)?.getTime() ?? 0) - (parseDate(at)?.getTime() ?? 0)
    })
    return [day, items] as [string, DayItem[]]
  })
}

function EventTitle({ ev }: { ev: TimelineEventView }) {
  const navigate = useNavigate()
  const { core, label } = splitTitle(ev)
  return (
    <span className="min-w-0 text-slate-800">
      {core}
      {label ? (
        <>
          {" · "}
          {ev.href ? (
            <button
              type="button"
              onClick={() => navigate(ev.href!)}
              className="text-slate-900 underline decoration-slate-300 underline-offset-2 hover:decoration-slate-500"
            >
              {label}
            </button>
          ) : (
            <span className="text-slate-900">{label}</span>
          )}
        </>
      ) : null}
    </span>
  )
}

// Время и раскрывашка — слева от иконки (пользовательский запрос той же сессии, что и Этап 5):
// общая фиксированная ширина для обеих строк держит колонку иконок ровной.
const LEADING_SLOT = "flex w-10 shrink-0 items-center justify-start"

function EventRow({ ev }: { ev: TimelineEventView }) {
  const Icon = KIND_ICON[ev.kind] ?? FileText
  const tone = eventTone(ev)
  return (
    <li className="flex items-start gap-2.5 text-sm">
      <span className={cn(LEADING_SLOT, "mt-0.5 tabular-nums text-xs text-slate-400")}>
        {timeLabel(ev.occurred_at)}
      </span>
      <span
        className={cn(
          "mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full",
          tone ? TONE_ICON_CLASS[tone] : "bg-slate-100 text-slate-500",
        )}
      >
        <Icon className="size-3" strokeWidth={2} />
      </span>
      <span className="min-w-0 flex-1">
        <EventTitle ev={ev} />
        {tone === "warn" ? (
          <span className="ml-1.5 text-xs text-status-warn-fg">(регресс этапа)</span>
        ) : null}
      </span>
    </li>
  )
}

function CollapsedGroupRow({ kind, events }: { kind: string; events: TimelineEventView[] }) {
  const [expanded, setExpanded] = useState(false)
  const Icon = KIND_ICON[kind] ?? FileText
  const label = plural(events.length, KIND_PLURAL[kind] ?? DEFAULT_PLURAL)

  return (
    <li>
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-2.5 text-left text-sm text-slate-600 hover:text-slate-900"
      >
        <span className={LEADING_SLOT}>
          <ChevronDown
            className={cn("size-3.5 shrink-0 text-slate-400 transition-transform", expanded && "rotate-180")}
            strokeWidth={2}
          />
        </span>
        <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-slate-100 text-slate-500">
          <Icon className="size-3" strokeWidth={2} />
        </span>
        <span className="min-w-0 flex-1">
          {events.length} {label}
        </span>
      </button>
      {expanded ? (
        <ul className="ml-20 mt-1.5 space-y-1.5 border-l pl-3">
          {events.map((ev) => (
            <EventRow key={ev.id} ev={ev} />
          ))}
        </ul>
      ) : null}
    </li>
  )
}

// Быстрое добавление события (Этап 5): варианты видны сразу — клик по чипу открывает поле
// комментария и кнопку «Добавить» справа от него, без отдельной формы/модалки.
function QuickEventAdd() {
  const [kind, setKind] = useState<ManualTimelineKind | null>(null)
  const [comment, setComment] = useState("")
  const create = useCreateTimelineEntry()

  function submit() {
    if (!kind) return
    const label = MANUAL_KIND_OPTIONS.find((o) => o.value === kind)?.label ?? ""
    const title = comment.trim() || label
    if (!title) return
    create.mutate(
      { kind, title },
      {
        onSuccess: () => {
          setKind(null)
          setComment("")
        },
      },
    )
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <ChipToggleGroup
        size="sm"
        options={MANUAL_KIND_OPTIONS}
        value={kind ? [kind] : []}
        onChange={([v]) => setKind((v as ManualTimelineKind) ?? null)}
        multiple={false}
        allowEmpty
      />
      {kind ? (
        <>
          <Input
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Комментарий"
            className="h-8 w-36 text-xs"
            autoFocus
            onKeyDown={(e) => {
              if (e.key === "Enter") submit()
            }}
          />
          <Button type="button" size="sm" disabled={create.isPending} onClick={submit}>
            Добавить
          </Button>
        </>
      ) : null}
    </div>
  )
}

/**
 * Лента (Этап 3-5 плана редизайна «Карьеры»): группировка по дню, свёртка от 3 однотипных
 * событий за день, по умолчанию видны 3 последних дня с событиями — «Показать ещё» раскрывает
 * до 7 (страницы курсора доливаются в фоне, пока загруженных дней не хватает на выбранное окно).
 * Фильтр-чипы по kind убраны (не несли пользы) — их место в шапке занял быстрый выбор события.
 */
export function TimelineFeed() {
  const [dayLimit, setDayLimit] = useState(DAY_LIMIT_DEFAULT)

  const { data, isLoading, isError, refetch, fetchNextPage, hasNextPage, isFetchingNextPage } =
    useTimeline()

  const events = useMemo(() => data?.pages.flat() ?? [], [data])
  const groups = useMemo(() => groupByDay(events), [events])

  // Бэкенд отдаёт страницы по счётчику событий, не по дню — доливаем страницы в фоне, пока
  // загруженных дней меньше выбранного окна (3 или 7) и есть что грузить дальше. `data` в
  // условии — иначе до первого ответа `hasNextPage` оптимистично true и эффект долбит
  // fetchNextPage параллельно с ещё не завершившимся начальным запросом.
  const needsMoreDays = Boolean(data) && groups.length < dayLimit && hasNextPage
  useEffect(() => {
    if (needsMoreDays && !isFetchingNextPage) {
      void fetchNextPage()
    }
  }, [needsMoreDays, isFetchingNextPage, fetchNextPage])

  const visibleGroups = groups.slice(0, dayLimit)
  const canExpand =
    dayLimit < DAY_LIMIT_EXPANDED && (groups.length > dayLimit || hasNextPage || isFetchingNextPage)
  const expandPending = isFetchingNextPage && groups.length <= dayLimit

  const status = isLoading ? "loading" : isError ? "error" : "content"

  return (
    <SectionCard
      title="Лента"
      helpId="career.timeline"
      status={status}
      action={<QuickEventAdd />}
      loading={<Skeleton className="h-32 w-full rounded-lg" />}
      error={
        <ErrorState
          compact
          icon={History}
          title="Лента не загрузилась"
          note="Не удалось получить события — они на месте, их сейчас не видно."
          action={{ label: "Повторить", onClick: () => void refetch() }}
        />
      }
    >
      <div className="space-y-4">
        {!visibleGroups.length ? (
          <EmptyState
            icon={History}
            title="Пока пусто"
            note="Отклики, этапы, офферы и события появятся здесь по мере работы с вакансиями."
          />
        ) : (
          visibleGroups.map(([day, items]) => (
            <div key={day}>
              <p className="sticky top-0 z-10 bg-white/95 py-1 text-xs font-medium text-slate-500 backdrop-blur-sm">
                {day}
              </p>
              <ul className="space-y-1.5 pt-1">
                {items.map((item) =>
                  item.type === "collapsed" ? (
                    <CollapsedGroupRow key={`${day}:${item.kind}`} kind={item.kind} events={item.events} />
                  ) : (
                    <EventRow key={item.event.id} ev={item.event} />
                  ),
                )}
              </ul>
            </div>
          ))
        )}

        {canExpand ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setDayLimit(DAY_LIMIT_EXPANDED)}
            disabled={expandPending}
          >
            {expandPending ? <Loader2 className="size-3.5 animate-spin" strokeWidth={2} /> : null}
            Показать ещё
          </Button>
        ) : null}
      </div>
    </SectionCard>
  )
}
