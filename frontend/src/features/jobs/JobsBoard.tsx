import { useMemo, useRef, useState } from "react"
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core"
import { useVirtualizer } from "@tanstack/react-virtual"
import { Eye, EyeOff } from "lucide-react"
import type { Job } from "@/api/jobs"
import { HelpTip } from "@/components/ui/help-tip"
import { OnboardingHint } from "@/components/ui/tooltip"
import { ONBOARDING_HINT_IDS, useOnboardingHints } from "@/lib/use-onboarding-hints"
import { cn, usePopMotion, useListAppearMotion } from "@/lib/utils"
import { JobCard } from "./JobCard"
import { resolveStage, SKIPPED_COLUMN, type BoardColumn, type Column } from "./funnel"
import { useHiddenColumns } from "./use-board-columns"
import { useUpdateJobStage } from "./use-job-stage"
import { useSkipJob, useUnskipJob } from "./use-skip"

const FIRST_CARD_HINT = "Откройте карточку — там разбор вакансии, брифинг и письмо."

// «Пропущено» копит сотни вакансий при потоке откликов — в колонке держим только свежий хвост,
// остальное прячем за «показать ещё» (клиентский кап поверх уже догруженного курсором среза,
// L-30 — не то же самое, что общая догрузка страниц внизу доски). UX-рефактор.
const SKIPPED_VISIBLE = 12
const POP_MS = 160
// Виртуализация (P-07) окупается только на длинных колонках; на типичных 5-15 карточках она
// лишь тратит цикл на измерение — ниже порога рендерим как раньше, простым map.
const VIRTUALIZE_THRESHOLD = 30

// Карточка-источник перетаскивания. Слушатели на обёртке — distance-порог сенсора (ниже) различает
// короткий клик (открыть дровер, JS-1.2) и перетаскивание (сменить стадию, JS-1.1).
function DraggableCard({
  job,
  onOpen,
  appearClass,
  showFirstCardHint,
  onDismissFirstCardHint,
}: {
  job: Job
  onOpen: (job: Job) => void
  appearClass?: string
  showFirstCardHint?: boolean
  onDismissFirstCardHint?: () => void
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: String(job.id),
    data: { job },
  })
  const card = (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      className={cn("touch-none", isDragging && "opacity-40")}
    >
      <JobCard job={job} onOpen={onOpen} className={appearClass} />
    </div>
  )
  if (!showFirstCardHint || !onDismissFirstCardHint) return card
  return (
    <OnboardingHint
      open
      onDismiss={onDismissFirstCardHint}
      side="right"
      align="center"
      content={FIRST_CARD_HINT}
    >
      {card}
    </OnboardingHint>
  )
}

// Колонка-приёмник. Подсветка рамкой при наведении перетаскиваемой карточки (шаг 48).
function DroppableColumn({
  col,
  onOpen,
  onHide,
  firstJobKey,
  showFirstCardHint,
  onDismissFirstCardHint,
  itemClass,
  appearKey,
  popClassFor,
  count,
}: {
  col: Column
  onOpen: (job: Job) => void
  onHide: (col: BoardColumn) => void
  firstJobKey: string | null
  showFirstCardHint: boolean
  onDismissFirstCardHint: () => void
  itemClass: (index: number) => string
  appearKey: number
  popClassFor: (id: string, fallbackClass?: string) => string
  // Точный тотал колонки (L-30), когда он есть — иначе длина уже догруженного среза (col.jobs).
  count: number
}) {
  const { setNodeRef, isOver } = useDroppable({ id: col.stage })
  // «Пропущено» — терминальная второстепенная колонка: приглушённый фон отделяет её от воронки.
  const isSkipped = col.stage === SKIPPED_COLUMN
  const [expanded, setExpanded] = useState(false)
  // В «Пропущено» рендерим только свежий хвост, пока пользователь сам не раскроет всё.
  const capped = isSkipped && !expanded && col.jobs.length > SKIPPED_VISIBLE
  const visible = capped ? col.jobs.slice(0, SKIPPED_VISIBLE) : col.jobs
  const hiddenCount = col.jobs.length - visible.length

  // Виртуализация (P-07): колонка держит только окно из ~140px-карточек в DOM — колонка
  // с сотнями вакансий не кладёт INP. Droppable — на всей секции (см. ниже), не на карточках,
  // поэтому окно рендера не мешает dnd-kit различать колонку-приёмник.
  const scrollRef = useRef<HTMLDivElement | null>(null)
  // @tanstack/react-virtual намеренно возвращает нестабильные функции на каждый рендер; React
  // Compiler просто пропускает мемоизацию этого компонента, поведение корректно (issue известна
  // апстриму, не наш баг).
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: visible.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 140,
    overscan: 6,
    getItemKey: (index) =>
      `${String(visible[index]!.id ?? visible[index]!.vacancy_id)}-${appearKey}`,
  })
  const virtualRows = virtualizer.getVirtualItems()

  return (
    <section ref={setNodeRef} className="flex w-64 shrink-0 flex-col">
      <div className="mb-3 flex items-center justify-between px-1">
        <h2 className="inline-flex items-center gap-1 text-xs font-semibold uppercase tracking-wider text-slate-500">
          {col.stage}
          {isSkipped && <HelpTip id="jobs.skipped-expander" />}
        </h2>
        <div className="flex items-center gap-1.5">
          <span className="text-lg font-semibold tabular-nums text-slate-600">{count}</span>
          <button
            type="button"
            onClick={() => onHide(col.stage)}
            aria-label={`Скрыть колонку «${col.stage}»`}
            className="text-slate-300 transition-colors hover:text-slate-500"
          >
            <EyeOff className="size-3.5" strokeWidth={2} />
          </button>
        </div>
      </div>
      <div
        ref={scrollRef}
        className={cn(
          "min-h-24 flex-1 space-y-2 overflow-y-auto rounded-xl pr-1 transition-colors duration-200",
          isSkipped && "bg-slate-50/80 p-1.5",
          isOver && "bg-slate-100/80 ring-2 ring-slate-400",
        )}
      >
        {col.jobs.length === 0 ? (
          <p className="px-1 text-xs text-slate-300">—</p>
        ) : (
          <>
            {visible.length <= VIRTUALIZE_THRESHOLD ? (
              visible.map((job, index) => {
                const key = String(job.id ?? job.vacancy_id)
                const isFirst = firstJobKey != null && key === firstJobKey
                return (
                  <DraggableCard
                    key={`${key}-${appearKey}`}
                    job={job}
                    onOpen={onOpen}
                    appearClass={popClassFor(key, itemClass(index))}
                    showFirstCardHint={isFirst && showFirstCardHint}
                    onDismissFirstCardHint={isFirst ? onDismissFirstCardHint : undefined}
                  />
                )
              })
            ) : (
              <div
                style={{ position: "relative", height: virtualizer.getTotalSize(), width: "100%" }}
              >
                {virtualRows.map((row) => {
                  const job = visible[row.index]!
                  const key = String(job.id ?? job.vacancy_id)
                  const isFirst = firstJobKey != null && key === firstJobKey
                  return (
                    <div
                      key={row.key}
                      ref={virtualizer.measureElement}
                      data-index={row.index}
                      style={{
                        position: "absolute",
                        top: 0,
                        left: 0,
                        width: "100%",
                        paddingBottom: 8,
                        transform: `translateY(${row.start}px)`,
                      }}
                    >
                      <DraggableCard
                        job={job}
                        onOpen={onOpen}
                        appearClass={popClassFor(key, itemClass(row.index))}
                        showFirstCardHint={isFirst && showFirstCardHint}
                        onDismissFirstCardHint={isFirst ? onDismissFirstCardHint : undefined}
                      />
                    </div>
                  )
                })}
              </div>
            )}
            {capped && (
              <button
                type="button"
                onClick={() => setExpanded(true)}
                className="w-full rounded-lg border border-dashed border-slate-200 py-1.5 text-xs font-medium text-slate-500 transition-colors hover:bg-white"
              >
                Показать ещё {hiddenCount}
              </button>
            )}
            {isSkipped && expanded && col.jobs.length > SKIPPED_VISIBLE && (
              <button
                type="button"
                onClick={() => setExpanded(false)}
                className="w-full rounded-lg py-1.5 text-xs font-medium text-slate-400 transition-colors hover:text-slate-600"
              >
                Свернуть
              </button>
            )}
          </>
        )}
      </div>
    </section>
  )
}

// Kanban-доска с перетаскиванием карточек между стадиями (JS-1.1). Колонки и дровер приходят сверху
// из JobsWorkspace (общий дровер для доски и списка, JS-1.3); клик по карточке зовёт onOpen.
export function JobsBoard({
  columns,
  onOpen,
  columnCounts,
}: {
  columns: Column[]
  onOpen: (job: Job) => void
  // Бейджи колонок (L-30): точные тоталы с бэка, когда фильтры не сужают выдачу; иначе — длина
  // отфильтрованно-догруженного среза (см. JobsWorkspace.badgeCounts).
  columnCounts?: Partial<Record<BoardColumn, number>>
}) {
  const [active, setActive] = useState<Job | null>(null)
  const pop = usePopMotion(POP_MS)
  const stageMutation = useUpdateJobStage()
  const skipMutation = useSkipJob()
  const unskipMutation = useUnskipJob()
  const { hidden, hide, show } = useHiddenColumns()
  const { shouldShow, dismissHint } = useOnboardingHints()
  const visibleColumns = columns.filter((c) => !hidden.has(c.stage))
  const hiddenColumns = columns.filter((c) => hidden.has(c.stage))
  // Состав доски без порядка по колонкам: фильтры меняют set → fade; DnD между колонками — нет.
  const listSig = useMemo(
    () =>
      columns
        .flatMap((c) => c.jobs.map((j) => String(j.id ?? j.vacancy_id)))
        .sort()
        .join("\0"),
    [columns],
  )
  const appear = useListAppearMotion(listSig)

  // FR2-30: якорь «первая вакансия» — первая карточка слева направо по видимым колонкам.
  let firstJobKey: string | null = null
  for (const col of visibleColumns) {
    const job = col.jobs[0]
    if (job) {
      firstJobKey = String(job.id ?? job.vacancy_id)
      break
    }
  }
  const showFirstCardHint = firstJobKey != null && shouldShow(ONBOARDING_HINT_IDS.jobsFirstCard)
  const onDismissFirstCardHint = () => dismissHint(ONBOARDING_HINT_IDS.jobsFirstCard)
  // Порог 6px: короткий клик по карточке открывает ссылку на площадку, движение начинает drag.
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }))

  function onDragStart(e: DragStartEvent) {
    setActive((e.active.data.current?.job as Job | undefined) ?? null)
  }

  function onDragEnd(e: DragEndEvent) {
    setActive(null)
    const job = e.active.data.current?.job as Job | undefined
    const target = e.over?.id as BoardColumn | undefined
    if (!job || job.id == null || !target) return
    const wasSkipped = Boolean(job.skipped)
    const jobKey = String(job.id)

    // Дроп в «Пропущено» = решение «не подавать» (POST /skip), ортогонально статусу воронки.
    if (target === SKIPPED_COLUMN) {
      if (!wasSkipped) {
        skipMutation.mutate({ id: job.id })
        pop.trigger(jobKey)
      }
      return
    }

    // Дроп в этап воронки. Если тащили из «Пропущено» — сначала снимаем пропуск (DELETE /skip),
    // затем, если этап отличается от текущего статуса, двигаем стадию (карточка ляжет туда, куда
    // бросили). Сравнение по resolveStage, чтобы дроп в ту же колонку не слал лишний PATCH.
    if (wasSkipped) {
      unskipMutation.mutate({ id: job.id })
      if (resolveStage(job.status) !== target) {
        stageMutation.mutate({ id: job.id, stage: target })
      }
      pop.trigger(jobKey)
      return
    }
    if (resolveStage(job.status) === target) return
    stageMutation.mutate({ id: job.id, stage: target })
    pop.trigger(jobKey)
  }

  return (
    <DndContext sensors={sensors} onDragStart={onDragStart} onDragEnd={onDragEnd}>
      <div className="flex min-h-0 flex-1 flex-col">
        {hiddenColumns.length > 0 && (
          <div className="flex shrink-0 flex-wrap items-center gap-2 border-b bg-slate-50/60 px-6 py-2">
            <span className="text-xs font-medium text-slate-400">Скрыто:</span>
            {hiddenColumns.map((col) => (
              <button
                key={col.stage}
                type="button"
                onClick={() => show(col.stage)}
                className="flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-500 transition-colors hover:bg-slate-100"
              >
                <Eye className="size-3" strokeWidth={2} />
                {col.stage}
              </button>
            ))}
          </div>
        )}
        <div className="flex min-h-0 flex-1 gap-4 overflow-x-auto px-6 pb-6 pt-3">
          {visibleColumns.map((col) => (
            <DroppableColumn
              key={col.stage}
              col={col}
              onOpen={onOpen}
              onHide={hide}
              firstJobKey={firstJobKey}
              showFirstCardHint={showFirstCardHint}
              onDismissFirstCardHint={onDismissFirstCardHint}
              itemClass={appear.itemClass}
              appearKey={appear.appearKey}
              popClassFor={pop.classFor}
              count={columnCounts?.[col.stage] ?? col.jobs.length}
            />
          ))}
        </div>
      </div>
      <DragOverlay>{active ? <JobCard job={active} /> : null}</DragOverlay>
    </DndContext>
  )
}
