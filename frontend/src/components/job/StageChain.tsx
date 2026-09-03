import { useMemo, useState } from "react"
import {
  DndContext,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core"
import { Check, FileSearch, GripVertical, MessageSquare, Plus, Trash2, X } from "lucide-react"
import { useNavigate, type NavigateFunction } from "react-router-dom"
import { cn } from "@/lib/utils"
import { formatEventLabel } from "@/lib/format"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  CHAIN_ADDABLE_STAGE_TYPES,
  CHAIN_STAGE_LABELS,
  preferUniqueHrScreeningStages,
} from "@/features/tech/stages"
import { useDebriefHistory } from "@/features/tech/use-debrief"
import {
  useAddInterviewStage,
  useDeleteInterviewStage,
  useInterviewStages,
  usePatchInterviewStage,
  useReorderInterviewStages,
} from "@/features/tech/use-interview-stages"
import type { InterviewStageOut } from "@/api/interview-stages"
import type { FunnelStage } from "@/features/jobs/funnel"
import { canAddInterviewStage, stageChainBlockedReason } from "./stage-chain-gate"

// Цепочка этапов собеса конкретной вакансии (RD-19): interview_stages как первоклассный веб-объект.
// Два вида одних и тех же данных: StageChainFull — степпер левой панели Техничек (клик = выбор
// контекста подготовки, добавить/убрать/переставить перетаскиванием этап); StageChainPills —
// подписанные пилюли (V-09: стадию видно без наведения) — в шапке дровера вакансии и в шапке
// диалога Чатов (UX7, `nowrap`). Toggle-поведение (клик = пройден ↔ не пройден) одинаковое у обоих.

// Одна строка цепочки — источник и приёмник drag-and-drop одновременно (перетаскивание меняет
// местами позицию этой строки с той, над которой отпустили). Хук на элемент — своя функция-компонент.
function DraggableStageRow({
  stage: s,
  active,
  hasTranscript,
  onSelect,
  onDelete,
  onToggleComplete,
  onToggleFailed,
  navigate,
  vacancyId,
}: {
  stage: InterviewStageOut
  active: boolean
  hasTranscript: boolean
  onSelect: (stageType: string, id: number) => void
  onDelete: (id: number) => void
  onToggleComplete: (id: number, currentStatus: string) => void
  onToggleFailed: (id: number, currentStatus: string) => void
  navigate: NavigateFunction
  vacancyId: string
}) {
  const { attributes, listeners, setNodeRef: setDragRef, isDragging } = useDraggable({ id: s.id })
  const { setNodeRef: setDropRef, isOver } = useDroppable({ id: s.id })
  const dateLabel = formatEventLabel(s.scheduled_at)
  const completed = s.status === "completed"
  const failed = s.status === "failed"

  return (
    <div
      ref={(node) => {
        setDragRef(node)
        setDropRef(node)
      }}
      role="button"
      tabIndex={0}
      title={`Готовиться к этапу «${s.stage_label}»`}
      onClick={() => onSelect(s.stage_type, s.id)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault()
          onSelect(s.stage_type, s.id)
        }
      }}
      className={cn(
        "group cursor-pointer rounded-lg p-1.5 outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-slate-400",
        active
          ? "bg-slate-900 text-white"
          : completed
            ? "bg-emerald-50 text-slate-600 hover:bg-emerald-100"
            : failed
              ? "bg-rose-50 text-slate-600 hover:bg-rose-100"
              : "text-slate-600 hover:bg-slate-100",
        isDragging && "opacity-40",
        isOver && !isDragging && "ring-2 ring-inset ring-slate-300",
      )}
    >
      <div className="flex items-center gap-2">
        <button
          type="button"
          aria-label="Перетащить, чтобы переставить"
          {...attributes}
          {...listeners}
          onClick={(e) => e.stopPropagation()}
          className={cn(
            "flex size-8 shrink-0 cursor-grab items-center justify-center rounded-md border touch-none active:cursor-grabbing",
            active
              ? "border-slate-600 bg-slate-800 text-slate-300 hover:text-white"
              : "border-slate-200 bg-white text-slate-400 hover:border-slate-300 hover:text-slate-600",
          )}
        >
          <GripVertical className="size-4" strokeWidth={2} />
        </button>
        <div className="min-w-0 flex-1 text-left">
          <span className="flex min-w-0 items-center gap-1.5">
            <span className="truncate text-sm font-medium">{s.stage_label}</span>
            {hasTranscript && (
              <button
                type="button"
                aria-label="К этапу привязан разбор транскрипта"
                title="К этому этапу привязан разбор транскрипта"
                onClick={(e) => {
                  e.stopPropagation()
                  onSelect(s.stage_type, s.id)
                }}
                className={cn(
                  "flex size-5 shrink-0 items-center justify-center rounded",
                  active
                    ? "text-slate-300 hover:text-white"
                    : "text-slate-400 hover:text-slate-600",
                )}
              >
                <FileSearch className="size-3.5" strokeWidth={2} />
              </button>
            )}
            {s.source_message_id != null && (
              <button
                type="button"
                aria-label="Этап из переписки — открыть диалог"
                title="Этап пришёл из переписки с HR"
                onClick={(e) => {
                  e.stopPropagation()
                  navigate(`/chat?vacancy=${encodeURIComponent(vacancyId)}`)
                }}
                className={cn(
                  "flex size-5 shrink-0 items-center justify-center rounded",
                  active
                    ? "text-slate-300 hover:text-white"
                    : "text-slate-400 hover:text-slate-600",
                )}
              >
                <MessageSquare className="size-3.5" strokeWidth={2} />
              </button>
            )}
          </span>
          {dateLabel && (
            <span className={cn("block text-xs", active ? "text-slate-300" : "text-slate-400")}>
              {dateLabel}
            </span>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Button
            type="button"
            variant="outline"
            size="xs"
            aria-pressed={completed}
            title={completed ? "Снять отметку «пройден»" : "Отметить пройденным"}
            onClick={(e) => {
              e.stopPropagation()
              onToggleComplete(s.id, s.status)
            }}
            className={cn(
              completed &&
                "border-emerald-300 bg-emerald-50 text-emerald-800 hover:bg-emerald-100 hover:text-emerald-900",
              active &&
                !completed &&
                "border-slate-600 bg-slate-800 text-slate-200 hover:bg-slate-700",
            )}
          >
            Пройден
          </Button>
          <Button
            type="button"
            variant="outline"
            size="xs"
            aria-pressed={failed}
            title={failed ? "Снять отметку «завален»" : "Отметить заваленным"}
            onClick={(e) => {
              e.stopPropagation()
              onToggleFailed(s.id, s.status)
            }}
            className={cn(
              failed &&
                "border-rose-300 bg-rose-50 text-rose-800 hover:bg-rose-100 hover:text-rose-900",
              active &&
                !failed &&
                "border-slate-600 bg-slate-800 text-slate-200 hover:bg-slate-700",
            )}
          >
            Завален
          </Button>
          <Button
            type="button"
            variant="outline"
            size="xs"
            aria-label="Удалить этап"
            title="Удалить этап"
            onClick={(e) => {
              e.stopPropagation()
              onDelete(s.id)
            }}
            className={cn(
              "border-rose-200 text-rose-700 hover:bg-rose-50 hover:text-rose-800",
              active && "border-rose-400/40 bg-slate-800 text-rose-200 hover:bg-rose-950/40",
            )}
          >
            <Trash2 className="size-3" strokeWidth={2} />
            Удалить
          </Button>
        </div>
      </div>
    </div>
  )
}

export function StageChainFull({
  vacancyId,
  activeStageType,
  activeStageId,
  onSelect,
  className,
  funnelStatus,
  skipped = false,
  onPromoteToScreening,
}: {
  vacancyId: string
  activeStageType: string
  // UX3-27: если передан, подсветка идёт по конкретному экземпляру этапа, не по формату (иначе
  // все этапы одного формата — например две «Техничка» на разные даты — подсвечивались бы разом).
  activeStageId?: number | null
  onSelect: (stageType: string, id: number) => void
  // V-08: дровер вакансии встраивает ту же цепочку вертикальным блоком вкладки «Работа», а не
  // рельсом слева от композера Техничек — ширина/бордер/собственный скролл переопределяются отсюда.
  className?: string
  // Гейт «Добавить этап» по статусу воронки (см. STAGE_ADDABLE_FUNNEL) — не передан → без гейта
  // (Технички уже сами показывают только Техничка/Финал, гейт там всегда true).
  funnelStatus?: FunnelStage
  skipped?: boolean
  // Этап 1.2 плана `plans/ui_slop_cleanup_2026_08_25.md`: перевод вакансии на «Скрининг» прямо
  // отсюда. Раньше на месте кнопки стояла бледная надпись «Сначала переместите на этап
  // «Скрининг»», а само перемещение делалось карточкой на доске — которую в дровере закрывает
  // этот же дровер. Хозяин действия — вызывающий (у него есть job.id и мутация стадии), цепочка
  // о воронке ничего не знает. Не передан — остаётся прежняя поясняющая строка.
  onPromoteToScreening?: () => void
}) {
  const { data, isLoading } = useInterviewStages(vacancyId)
  const addStage = useAddInterviewStage(vacancyId)
  const deleteStage = useDeleteInterviewStage(vacancyId)
  const patchStage = usePatchInterviewStage(vacancyId)
  const reorder = useReorderInterviewStages(vacancyId)
  // UX2-9: те же разборы, что видит DebriefSection — только чтобы знать, у каких этапов уже есть
  // привязанный транскрипт (маленькая иконка), без нового запроса вне react-query кэша.
  const debriefQ = useDebriefHistory(vacancyId)
  const [pickerOpen, setPickerOpen] = useState(false)
  const navigate = useNavigate()
  // distance-порог отличает клик по ручке от начала перетаскивания.
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }))

  const stages = preferUniqueHrScreeningStages(data?.items ?? [])
  const debriefedStageIds = useMemo(
    () =>
      new Set(
        (debriefQ.data?.items ?? [])
          .map((r) => r.interview_stage_id)
          .filter((id): id is number => id != null),
      ),
    [debriefQ.data],
  )
  // DBR-5: раньше здесь считался жёлтый/зелёный/красный кружок resolution по последнему разбору
  // этапа. Кружок убран (см. комментарий у DraggableStageRow) — маппинг больше не нужен.

  const canAddStage = canAddInterviewStage(funnelStatus, skipped)
  // Причина, из-за которой перевод на «Скрининг» не поможет (`null` — поможет, показываем кнопку).
  const promoteBlocked = stageChainBlockedReason(funnelStatus, skipped)

  function onDragEnd(e: DragEndEvent) {
    const overId = e.over?.id
    if (overId == null || e.active.id === overId) return
    const ids = stages.map((s) => s.id)
    const from = ids.indexOf(e.active.id as number)
    const to = ids.indexOf(overId as number)
    if (from === -1 || to === -1) return
    const next = [...ids]
    const [moved] = next.splice(from, 1)
    next.splice(to, 0, moved)
    reorder.mutate(next)
  }

  return (
    <nav className={cn("w-48 shrink-0 space-y-1 overflow-y-auto border-r p-3", className)}>
      {isLoading ? (
        <p className="px-3 py-2 text-xs text-slate-400">Загружаю…</p>
      ) : stages.length === 0 ? (
        <p className="px-3 py-2 text-xs text-slate-400">
          Цепочка пуста — добавьте первый этап собеса этой вакансии.
        </p>
      ) : (
        <DndContext sensors={sensors} onDragEnd={onDragEnd}>
          <div className="space-y-1">
            {stages.map((s) => (
              <DraggableStageRow
                key={s.id}
                stage={s}
                active={
                  activeStageId != null ? s.id === activeStageId : s.stage_type === activeStageType
                }
                hasTranscript={debriefedStageIds.has(s.id)}
                onSelect={onSelect}
                onDelete={(id) => deleteStage.mutate(id)}
                onToggleComplete={(id, currentStatus) =>
                  patchStage.mutate({
                    stageId: id,
                    body: { status: currentStatus === "completed" ? "scheduled" : "completed" },
                  })
                }
                onToggleFailed={(id, currentStatus) =>
                  patchStage.mutate({
                    stageId: id,
                    body: { status: currentStatus === "failed" ? "scheduled" : "failed" },
                  })
                }
                navigate={navigate}
                vacancyId={vacancyId}
              />
            ))}
          </div>
        </DndContext>
      )}
      {!canAddStage ? (
        // Три разные причины, по которым цепочку вести нельзя, и у каждой свой выход: слишком
        // ранний этап лечится переводом на «Скрининг» (кнопка ниже), пропуск — возвратом
        // в воронку, отказ — ничем. Раньше все три показывали одну бледную строку.
        promoteBlocked ? (
          <p className="px-3 py-2 text-sm leading-snug text-slate-400">{promoteBlocked}</p>
        ) : (
          <div className="space-y-1.5 px-3 py-2">
            <p className="text-sm leading-snug text-slate-500">
              Цепочка собесов ведётся начиная со «Скрининга».
            </p>
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="w-full"
              disabled={!onPromoteToScreening}
              onClick={onPromoteToScreening}
            >
              Перевести на «Скрининг»
            </Button>
          </div>
        )
      ) : (
        <DropdownMenu open={pickerOpen} onOpenChange={setPickerOpen}>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="flex w-full items-center gap-1.5 rounded-lg px-3 py-2 text-left text-sm font-medium text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
            >
              <Plus className="size-3.5" strokeWidth={2} />
              Добавить этап
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent className="w-48">
            {CHAIN_ADDABLE_STAGE_TYPES.filter(
              (t) => t !== "hr_screening" || !stages.some((s) => s.stage_type === "hr_screening"),
            ).map((t) => (
              <DropdownMenuItem
                key={t}
                onSelect={() => addStage.mutate({ stage_type: t, format: "unknown", notes: "" })}
              >
                {CHAIN_STAGE_LABELS[t]}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </nav>
  )
}

// Тултип и toggle-обработчик общие для компактных кружков и подписанных пилюль — отличается
// только то, что рисуется внутри значка.
function stageTip(s: InterviewStageOut): string {
  const dateLabel = formatEventLabel(s.scheduled_at)
  return [
    s.stage_label,
    dateLabel,
    s.status === "completed"
      ? "пройден — клик снять"
      : s.status === "cancelled"
        ? "отменён"
        : s.status === "failed"
          ? "не пройден"
          : "не пройден — клик отметить",
  ]
    .filter(Boolean)
    .join(" · ")
}

function stageToggleable(status: string): boolean {
  return status === "completed" || status === "scheduled" || status === "rescheduled"
}

// V-09/UX7: подписанные пилюли — раньше рядом жили безымянные нумерованные кружки
// (`StageChainCompact`, удалён — не сообщали ничего без наведения); теперь это единственный вид
// цепочки этапов вне левого рельса Техничек (дровер вакансии, шапка диалога Чатов). Тот же toggle
// по клику (пройден ↔ не пройден); пройденный этап помечен галочкой в самой пилюле, а не отдельным
// номером — подпись уже называет этап, порядковый номер тут не нужен.
export function StageChainPills({
  vacancyId,
  nowrap,
}: {
  vacancyId: string | null | undefined
  // Шапка диалога Чатов (V-09 → UX7): пилюли не переносятся на новую строку, ряд растёт влево,
  // подвигая заголовок вакансии (тот уже truncate-friendly) — вместо переноса под HR-контактом.
  nowrap?: boolean
}) {
  const { data } = useInterviewStages(vacancyId ?? null)
  const patchStage = usePatchInterviewStage(vacancyId ?? null)
  const stages = preferUniqueHrScreeningStages(data?.items ?? [])
  if (stages.length === 0) return null

  const nextId = stages.find((s) => s.status === "scheduled" || s.status === "rescheduled")?.id

  return (
    <div className={cn("inline-flex items-center gap-1", nowrap ? "flex-nowrap" : "flex-wrap")}>
      {stages.map((s) => {
        const canToggle = stageToggleable(s.status)
        const tip = stageTip(s)
        const pending = s.status === "scheduled" || s.status === "rescheduled"
        const className = cn(
          "inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium leading-none transition-all duration-200",
          s.status === "completed" && "bg-emerald-50 text-emerald-700",
          s.status === "cancelled" && "bg-slate-100 text-slate-400 line-through",
          s.status === "failed" && "bg-rose-50 text-rose-600",
          pending && s.id === nextId && "bg-amber-50 text-amber-700",
          pending && s.id !== nextId && "border border-slate-200 text-slate-500",
          canToggle &&
            "cursor-pointer hover:ring-2 hover:ring-slate-300/80 hover:ring-offset-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-1",
          canToggle && s.status === "completed" && "hover:ring-emerald-300/80",
          canToggle && pending && "hover:ring-amber-300/80",
          patchStage.isPending && "pointer-events-none opacity-70",
        )
        const content = (
          <>
            {s.status === "completed" && <Check className="size-3 shrink-0" strokeWidth={2.5} />}
            {s.status === "failed" && <X className="size-3 shrink-0" strokeWidth={2.5} />}
            <span className="truncate">{s.stage_label}</span>
          </>
        )
        if (!canToggle) {
          return (
            <span key={s.id} title={tip} className={className}>
              {content}
            </span>
          )
        }
        return (
          <button
            key={s.id}
            type="button"
            title={tip}
            aria-label={
              s.status === "completed"
                ? `${s.stage_label}: снять отметку «пройден»`
                : `${s.stage_label}: отметить пройденным`
            }
            disabled={patchStage.isPending}
            onClick={(e) => {
              e.stopPropagation()
              e.preventDefault()
              patchStage.mutate({
                stageId: s.id,
                body: { status: s.status === "completed" ? "scheduled" : "completed" },
              })
            }}
            className={className}
          >
            {content}
          </button>
        )
      })}
    </div>
  )
}
