import { useState } from "react"
import { DndContext, PointerSensor, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core"
import { SortableContext, arrayMove, rectSortingStrategy, useSortable } from "@dnd-kit/sortable"
import { CSS } from "@dnd-kit/utilities"
import { GripVertical, Loader2, RefreshCw, Sparkles, X } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { HelpTip } from "@/components/ui/help-tip"
import { MultiSelectPopover } from "@/components/ui/multi-select-popover"
import { MARKET_SEGMENT_SUGGESTIONS, RED_FLAG_OPTIONS } from "@/lib/resume-taxonomy"
import { cn } from "@/lib/utils"
import { buildExclude, MAX_PRIORITIES, nextSuggestState } from "./priority-suggest"
import {
  usePatchResumeField,
  useResumeData,
  useSearchProfileSuggestState,
  useSuggestSearchProfile,
} from "./use-resume"

// «Любые» — псевдо-опция «без фильтра»; в market_segment хранится пустой строкой.
const ANY_SEGMENT = "Любые"

/** Распарсить market_segment (одна строка, отрасли через запятую) в массив выбранных. */
function parseSegments(market: string): string[] {
  return (market || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
}

/** Склеить массив отраслей в market_segment. Пусто или только «Любые» → "". */
function joinSegments(segments: string[]): string {
  const real = segments.filter((s) => s !== ANY_SEGMENT)
  return real.join(", ")
}

/** Подблок «Компании»: Отрасли → Ред флаги → Приоритеты (типы компаний — поле выше).
 *
 * Приоритеты внизу: единственный блок переменной высоты, не должен раздвигать оси выше.
 * Целевые/избегаемые компании — на вкладке «Компании».
 */
export function SearchProfilePanel() {
  const { data } = useResumeData()
  const patchField = usePatchResumeField()
  const suggest = useSuggestSearchProfile()
  // Слайт и история показанного — в query-кэше: панель размонтируется при переключении вкладок,
  // а из useState подсказки терялись вместе с `seen` (и «Обновить» опять отдавало то же самое).
  const { suggestState, setSuggestState } = useSearchProfileSuggestState()
  const [showAll, setShowAll] = useState(false)
  // Порог сдвига перед стартом drag (OF-11 паттерн, OffersRail.tsx): без него обычный клик по
  // чипу иногда триггерил бы drag вместо клика.
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }))

  if (!data) return null

  const priorities = data.search_criteria?.niches ?? []
  const market = data.search_criteria?.market_segment ?? ""
  const dealbreakers = data.search_criteria?.dealbreakers ?? []

  const runSuggest = () => {
    // Выбранные + показанные: первые не предлагаем повторно, вторые дают новую порцию.
    // Именно `exclude_priorities` меняет вход запроса, а значит и ключ result-кэша.
    suggest.mutate(
      { exclude_priorities: buildExclude(priorities, suggestState.seen) },
      {
        onSuccess: (r) => {
          const { kind, state } = nextSuggestState(suggestState, r, priorities)
          setSuggestState(state)
          if (kind === "exhausted") {
            toast.info("Новых вариантов по резюме нет — следующее «Обновить» начнёт список заново")
          }
        },
      },
    )
  }

  // 0.8: подсказка по отрасли применяется только к ПУСТОЙ оси и только по клику —
  // раньше `market_segment` из ответа просто выбрасывался.
  const segmentHint = !market && suggestState.marketSegment ? suggestState.marketSegment : ""

  const applySegmentHint = () => {
    patchField.mutate({ search_criteria: { market_segment: segmentHint } })
    setSuggestState({ ...suggestState, marketSegment: "" })
  }

  const togglePriority = (label: string) => {
    if (!priorities.includes(label) && priorities.length >= MAX_PRIORITIES) {
      toast.info(`Выбрано ${MAX_PRIORITIES} из ${MAX_PRIORITIES} — снимите один, чтобы добавить`)
      return
    }
    const next = priorities.includes(label)
      ? priorities.filter((n) => n !== label)
      : [...priorities, label]
    patchField.mutate({ search_criteria: { niches: next } })
  }

  // Этап 4 §4.4 (plans/scoring_precision_2026_08_17.md): порядок ниш — не только очерёдность
  // клика, но и то, чем реально управляет владелец. Скоринг весит совпадение с приоритетом
  // №1 сильнее, чем с №6 (skill_overlap_fraction) — без перетаскивания порядок можно было
  // задать только «снять и добавить заново».
  const handleReorderPriorities = (event: DragEndEvent) => {
    const { active, over } = event
    if (!over || active.id === over.id) return
    const oldIndex = priorities.indexOf(String(active.id))
    const newIndex = priorities.indexOf(String(over.id))
    if (oldIndex === -1 || newIndex === -1) return
    patchField.mutate({
      search_criteria: { niches: arrayMove(priorities, oldIndex, newIndex) },
    })
  }

  const changeSegments = (next: string[]) => {
    // «Любые» несовместим с конкретными отраслями: выбор отрасли снимает «Любые»,
    // а выбор «Любые» очищает всё остальное.
    if (next.includes(ANY_SEGMENT)) {
      patchField.mutate({ search_criteria: { market_segment: "" } })
      return
    }
    patchField.mutate({ search_criteria: { market_segment: joinSegments(next) } })
  }

  // Отображение: пустой market_segment = выбрано «Любые».
  const selectedSegments = market ? parseSegments(market) : [ANY_SEGMENT]

  const candidatesFiltered = suggestState.candidates.filter((c) => !priorities.includes(c.label))
  const shown = showAll ? candidatesFiltered : candidatesFiltered.slice(0, MAX_PRIORITIES)

  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-medium text-slate-600">Отрасли</span>
          <HelpTip id="resume.market-segment" />
        </div>
        <MultiSelectPopover
          options={MARKET_SEGMENT_SUGGESTIONS.map((s) => ({ value: s, label: s }))}
          value={selectedSegments}
          onChange={changeSegments}
          placeholder="Любые"
        />
        {segmentHint && (
          <SuggestHint
            value={segmentHint}
            onApply={applySegmentHint}
            onDismiss={() => setSuggestState({ ...suggestState, marketSegment: "" })}
          />
        )}
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-medium text-slate-600">Ред флаги</span>
          <HelpTip id="resume.red-flags" />
        </div>
        <MultiSelectPopover
          options={RED_FLAG_OPTIONS}
          value={dealbreakers}
          onChange={(next) => {
            patchField.mutate({ search_criteria: { dealbreakers: next } })
          }}
          placeholder="Не выбрано"
        />
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            <span className="text-xs font-medium text-slate-600">Приоритеты</span>
            <HelpTip id="resume.priorities" />
          </div>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-6 gap-1 px-1.5 text-xs text-slate-500 hover:text-slate-700"
            disabled={suggest.isPending}
            onClick={runSuggest}
          >
            {suggest.isPending ? (
              <Loader2 className="size-3 animate-spin" strokeWidth={2} />
            ) : (
              <RefreshCw className="size-3" strokeWidth={2} />
            )}
            Обновить
          </Button>
        </div>

        <div className="flex flex-wrap gap-1.5 rounded-lg border bg-slate-50/50 p-2">
          {shown.length === 0 && priorities.length === 0 && (
            <span className="px-1 py-1 text-xs text-slate-400">
              Нажмите «Обновить» — подберу варианты по резюме
            </span>
          )}
          <DndContext sensors={sensors} onDragEnd={handleReorderPriorities}>
            <SortableContext items={priorities} strategy={rectSortingStrategy}>
              {priorities.map((p, idx) => (
                <SortablePriorityChip
                  key={p}
                  label={p}
                  rank={idx + 1}
                  onRemove={() => togglePriority(p)}
                />
              ))}
            </SortableContext>
          </DndContext>
          {shown.map((c) => (
            <PriorityChip
              key={c.label}
              label={c.label}
              reason={c.reason}
              onClick={() => togglePriority(c.label)}
            />
          ))}
        </div>

        {candidatesFiltered.length > MAX_PRIORITIES && (
          <button
            type="button"
            onClick={() => setShowAll((v) => !v)}
            className="text-xs text-slate-500 underline-offset-2 hover:text-slate-700 hover:underline"
          >
            {showAll ? "Свернуть варианты" : "Все варианты"}
          </button>
        )}
      </div>
    </div>
  )
}

/** Подсказка LLM по пустой оси профиля: применяется только по клику, чтобы не перетирать выбор. */
export function SuggestHint({
  value,
  onApply,
  onDismiss,
}: {
  value: string
  onApply: () => void
  onDismiss: () => void
}) {
  return (
    <div className="flex items-center gap-1.5 text-xs text-slate-500">
      <Sparkles className="size-3 shrink-0 text-slate-300" strokeWidth={2} />
      <span className="min-w-0 truncate">
        Похоже на <span className="text-slate-700">{value}</span>
      </span>
      <button
        type="button"
        onClick={onApply}
        className="shrink-0 text-sky-600 underline-offset-2 hover:underline"
      >
        применить
      </button>
      <button
        type="button"
        onClick={onDismiss}
        className="shrink-0 text-slate-400 hover:text-slate-600"
        aria-label="Скрыть подсказку"
      >
        <X className="size-3" strokeWidth={2} />
      </button>
    </div>
  )
}

/** Невыбранный вариант-подсказка — клик добавляет в приоритеты. */
function PriorityChip({
  label,
  reason,
  onClick,
}: {
  label: string
  reason: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={reason || undefined}
      className="inline-flex items-center gap-1 rounded-md bg-white px-2 py-1 text-left text-xs text-slate-700 shadow-xs transition-colors hover:bg-slate-100"
    >
      <Sparkles className="size-3 shrink-0 text-slate-300" strokeWidth={2} />
      {label}
    </button>
  )
}

/** Выбранный приоритет — перетаскиваемый (за ручку слева), клик по тексту снимает выбор.
 *
 * Этап 4 §4.4: место в списке — не декорация, `skill_overlap_fraction` весит совпадение с
 * приоритетом №1 сильнее, чем с последним, так что `rank` показан рядом с чипом.
 */
function SortablePriorityChip({
  label,
  rank,
  onRemove,
}: {
  label: string
  rank: number
  onRemove: () => void
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: label,
  })
  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={cn(
        "inline-flex items-center gap-1 rounded-md bg-sky-500 py-1 pr-2 pl-1 text-xs font-medium text-white",
        isDragging && "z-20 opacity-70",
      )}
    >
      <button
        type="button"
        {...attributes}
        {...listeners}
        className="cursor-grab touch-none text-sky-100 hover:text-white active:cursor-grabbing"
        aria-label={`Перетащить «${label}», чтобы изменить приоритет`}
      >
        <GripVertical className="size-3" strokeWidth={2} />
      </button>
      <button
        type="button"
        onClick={onRemove}
        title="Приоритет — снять выбор"
        className="tabular-nums"
      >
        {rank}. {label}
      </button>
    </div>
  )
}
