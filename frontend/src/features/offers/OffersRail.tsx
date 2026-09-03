import { DndContext, PointerSensor, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core"
import {
  SortableContext,
  arrayMove,
  horizontalListSortingStrategy,
  useSortable,
} from "@dnd-kit/sortable"
import { CSS } from "@dnd-kit/utilities"
import type { Job } from "@/api/jobs"
import type { OfferRecord } from "@/api/offers"
import { OfferCard } from "@/components/offers/OfferCard"
import { OfferDraftCard } from "@/components/offers/OfferDraftCard"
import { HelpTip } from "@/components/ui/help-tip"
import { cn, useListAppearMotion } from "@/lib/utils"
import { allOffersOverdue } from "./deadline"
import { useReorderOffers } from "./use-offers"

// Обёртка карточки под drag-n-drop приоритета (OF-11): useSortable живёт на этом <div>, а не
// на самой OfferCard — ручка перетаскивания (верхняя полоса) внутри карточки лишь получает
// attributes/listeners пропами, как раньше делал SortableOfferColumn для <th>.
function SortableOfferCard({
  offer,
  priority,
  className,
}: {
  offer: OfferRecord
  priority: number | null
  className?: string
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: offer.vacancy_id,
  })
  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={cn(isDragging && "z-20 opacity-70", className)}
    >
      <OfferCard
        offer={offer}
        priority={priority}
        dragHandleAttrs={attributes}
        dragHandleListeners={listeners}
      />
    </div>
  )
}

export function OffersRail({
  offers,
  draftJob,
}: {
  offers: OfferRecord[]
  draftJob: Job | null
}) {
  const reorder = useReorderOffers()
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }))
  // Состав без порядка: DnD приоритета не перезапускает появление; смена набора — fade.
  const listSig = [...offers.map((o) => o.vacancy_id), draftJob?.vacancy_id ?? ""]
    .filter(Boolean)
    .sort()
    .join("\0")
  const appear = useListAppearMotion(listSig)

  // OF-11: перетащили карточку — индекс в новом порядке становится приоритетом (1-based, OF-2.4
  // сортирует load_all_offers по нему). offers уже отсортированы по priority с сервера.
  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event
    if (!over || active.id === over.id) return
    const oldIndex = offers.findIndex((o) => o.vacancy_id === active.id)
    const newIndex = offers.findIndex((o) => o.vacancy_id === over.id)
    if (oldIndex === -1 || newIndex === -1) return
    reorder.mutate(arrayMove(offers, oldIndex, newIndex).map((o) => o.vacancy_id))
  }

  const draftOffset = draftJob ? 1 : 0

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-1.5">
        <h2 className="text-sm font-semibold text-slate-900">Приоритеты офферов</h2>
        <HelpTip id="offers.priority-dnd" />
      </div>

      {/* Этап 1.5 плана `plans/ui_slop_cleanup_2026_08_25.md`: типичная картина через месяц после
          ввода — все дедлайны прошли, а экран по-прежнему выглядит рабочим сравнением. Строка
          сверху называет вещи своими именами, чтобы решение не принималось по мёртвым цифрам. */}
      {allOffersOverdue(offers) && (
        <p className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-800">
          Все дедлайны прошли: сравнение показывает историю, а не актуальные предложения.
        </p>
      )}

      <div className="flex gap-3 overflow-x-auto pb-2">
        {draftJob && (
          <div key={`draft-${appear.appearKey}`} className={appear.itemClass(0)}>
            <OfferDraftCard job={draftJob} />
          </div>
        )}
        <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
          <SortableContext
            items={offers.map((o) => o.vacancy_id)}
            strategy={horizontalListSortingStrategy}
          >
            {offers.map((o, idx) => (
              <SortableOfferCard
                key={`${o.vacancy_id}-${appear.appearKey}`}
                offer={o}
                priority={o.priority != null ? idx + 1 : null}
                className={appear.itemClass(idx + draftOffset)}
              />
            ))}
          </SortableContext>
        </DndContext>
      </div>
    </div>
  )
}
