import { Check, Loader2, Plus, Trash2, X } from "lucide-react"
import { useState } from "react"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { formatEventLabel } from "@/lib/format"
import { cn } from "@/lib/utils"
import {
  CHAIN_ADDABLE_STAGE_TYPES,
  CHAIN_STAGE_LABELS,
  preferUniqueHrScreeningStages,
} from "@/features/tech/stages"
import {
  useAddInterviewStage,
  useDeleteInterviewStage,
  useInterviewStages,
  usePatchInterviewStage,
} from "@/features/tech/use-interview-stages"

// Компактное дерево этапов вакансии внутри рельса Техничек («подзадачи», см. plan п.1c) — то же
// хранилище, что у StageChain.tsx::StageChainFull (левая колонка дровера/шапки Чатов), но без
// drag-переупорядочивания: держит блок под карточкой не «огромным». Переупорядочить порядок
// этапов по-прежнему можно там, где StageChainFull используется как раньше.
//
// Переход воронки («Финал»/«Оффер») — в RailFunnelActions под карточкой, не над списком этапов:
// кнопка над этапами перекрывала сами этапы и дублировала «Пройдено».
export function VacancyStagesInline({
  vacancyId,
  activeStageType,
  activeStageId,
  onSelect,
}: {
  vacancyId: string
  activeStageType: string
  activeStageId?: number | null
  onSelect: (stageType: string, id: number) => void
}) {
  const { data, isLoading } = useInterviewStages(vacancyId)
  const addStage = useAddInterviewStage(vacancyId)
  const deleteStage = useDeleteInterviewStage(vacancyId)
  const patchStage = usePatchInterviewStage(vacancyId)
  const [pickerOpen, setPickerOpen] = useState(false)

  const stages = preferUniqueHrScreeningStages(data?.items ?? [])

  function toggleCompleted(stageId: number, currentStatus: string) {
    patchStage.mutate({
      stageId,
      body: { status: currentStatus === "completed" ? "scheduled" : "completed" },
    })
  }

  return (
    <div className="space-y-1.5">
      <div className="space-y-1 border-l border-slate-200 pl-1.5">
        {isLoading ? (
          <p className="py-1 text-xs text-slate-400">Загружаю…</p>
        ) : stages.length === 0 ? (
          <p className="py-1 text-xs text-slate-400">Этапов пока нет.</p>
        ) : (
          stages.map((s) => {
            const active =
              activeStageId != null ? s.id === activeStageId : s.stage_type === activeStageType
            const completed = s.status === "completed"
            const failed = s.status === "failed"
            const dateLabel = formatEventLabel(s.scheduled_at)
            return (
              <div
                key={s.id}
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
                  "group flex cursor-pointer items-center gap-2 rounded-md px-1.5 py-1.5 text-xs outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-slate-400",
                  active
                    ? "bg-slate-900 text-white"
                    : completed
                      ? "bg-emerald-50 text-slate-600 hover:bg-emerald-100"
                      : failed
                        ? "bg-rose-50 text-slate-600 hover:bg-rose-100"
                        : "text-slate-600 hover:bg-slate-100",
                )}
              >
                {failed ? (
                  <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-rose-100">
                    <X className="size-3.5 text-rose-600" strokeWidth={2.5} />
                  </span>
                ) : (
                  <button
                    type="button"
                    title={completed ? "Снять отметку «пройден»" : "Отметить пройденным"}
                    aria-label={completed ? "Снять отметку «пройден»" : "Отметить пройденным"}
                    onClick={(e) => {
                      e.stopPropagation()
                      toggleCompleted(s.id, s.status)
                    }}
                    className={cn(
                      "flex size-5 shrink-0 items-center justify-center rounded-full border transition-colors",
                      completed
                        ? "border-emerald-300 bg-emerald-100"
                        : active
                          ? "border-slate-400 hover:border-emerald-300"
                          : "border-slate-300 hover:border-emerald-400",
                    )}
                  >
                    {completed && <Check className="size-3.5 text-emerald-600" strokeWidth={3} />}
                  </button>
                )}
                <span className="min-w-0 flex-1 truncate">{s.stage_label}</span>
                {dateLabel && (
                  <span className={cn("shrink-0", active ? "text-slate-300" : "text-slate-400")}>
                    {dateLabel}
                  </span>
                )}
                <button
                  type="button"
                  title="Удалить этап"
                  onClick={(e) => {
                    e.stopPropagation()
                    deleteStage.mutate(s.id)
                  }}
                  className={cn(
                    "flex size-4 shrink-0 items-center justify-center rounded-full bg-rose-100 text-rose-600 hover:bg-rose-200 hover:text-rose-700",
                    active && "bg-rose-500/30 text-rose-50 hover:bg-rose-500/50 hover:text-white",
                  )}
                >
                  <Trash2 className="size-3" strokeWidth={2} />
                </button>
              </div>
            )
          })
        )}
        <DropdownMenu open={pickerOpen} onOpenChange={setPickerOpen}>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-left text-xs font-medium text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
            >
              {addStage.isPending ? (
                <Loader2 className="size-3 shrink-0 animate-spin" strokeWidth={2} />
              ) : (
                <Plus className="size-3 shrink-0" strokeWidth={2} />
              )}
              Добавить этап
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent className="w-48" align="start">
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
      </div>
    </div>
  )
}
