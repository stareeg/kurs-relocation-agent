import type { DraggableAttributes, DraggableSyntheticListeners } from "@dnd-kit/core"
import { GripHorizontal, Trash2 } from "lucide-react"
import type { OfferRecord, OfferUpdateRequest } from "@/api/offers"
import { Button } from "@/components/ui/button"
import { HelpTip } from "@/components/ui/help-tip"
import { OfferRow, type OfferRowValue } from "@/components/offers/OfferRow"
import { computeAnnualIncome } from "@/features/offers/annual-income"
import { deadlineCountdown, isOfferUndecided } from "@/features/offers/deadline"
import {
  ROWS,
  FORMAT_OPTS,
  READONLY_ROW_KEYS,
  fieldValue,
  isOfferRowVisible,
  rowByKey,
} from "@/features/offers/rows"
import { BONUS_PCT_DEFAULT, offerBonusTypes } from "@/features/offers/bonus"
import { useDeleteOffer, usePatchOffer } from "@/features/offers/use-offers"
import type { HelpTextId } from "@/lib/help-texts"
import { cn } from "@/lib/utils"

/** Подсказки у неочевидных полей карточки (шаг 42). */
const OFFER_FIELD_HELP: Partial<Record<keyof OfferUpdateRequest, HelpTextId>> = {
  base_salary: "offers.base-salary",
  base_salary_tax_basis: "offers.tax-basis",
  bonus_types: "offers.bonus",
  deadline: "offers.deadline",
}

export function OfferCard({
  offer,
  priority = null,
  favorableFields,
  dragHandleAttrs,
  dragHandleListeners,
}: {
  offer: OfferRecord
  priority?: number | null
  // vacancy_id → список ключей полей (RowDef.key), в которых LLM-сравнение считает этот оффер
  // выгоднее остальных (OF-22) — сама подсветка считается снаружи (в рельсе), карточка её только
  // отображает.
  favorableFields?: Set<string>
  dragHandleAttrs?: DraggableAttributes
  dragHandleListeners?: DraggableSyntheticListeners
}) {
  const patch = usePatchOffer()
  const remove = useDeleteOffer()

  function edit(key: keyof OfferUpdateRequest, value: OfferRowValue) {
    if (READONLY_ROW_KEYS.has(key) || Array.isArray(value)) return
    patch.mutate({ vacancyId: offer.vacancy_id, patch: { [key]: value } as OfferUpdateRequest })
  }

  function editBonusTypes(next: string[]) {
    const patchBody: OfferUpdateRequest = { bonus_types: next as OfferUpdateRequest["bonus_types"] }
    if (next.includes("annual") && offer.annual_bonus_pct == null) {
      patchBody.annual_bonus_pct = BONUS_PCT_DEFAULT
    }
    if (next.includes("quarterly") && offer.quarterly_bonus_pct == null) {
      patchBody.quarterly_bonus_pct = BONUS_PCT_DEFAULT
    }
    patch.mutate({ vacancyId: offer.vacancy_id, patch: patchBody })
  }

  const countdown = deadlineCountdown(fieldValue(offer, "deadline"))
  const visibleRows = ROWS.filter((row) => isOfferRowVisible(row, offer))
  const annual = computeAnnualIncome(offer)

  return (
    <div className="flex w-72 shrink-0 flex-col overflow-hidden rounded-xl border bg-white shadow-sm">
      <button
        type="button"
        className="flex h-9 shrink-0 cursor-grab touch-none items-center justify-center border-b bg-slate-50/50 text-slate-300 hover:bg-slate-100 hover:text-slate-400 active:cursor-grabbing"
        aria-label="Перетащить, чтобы изменить приоритет"
        {...dragHandleAttrs}
        {...dragHandleListeners}
      >
        <GripHorizontal className="size-4" strokeWidth={2} />
      </button>

      <div className="space-y-2 border-b p-3">
        <div className="flex items-start justify-between gap-2">
          {annual ? (
            <p className="flex flex-wrap items-baseline gap-1.5 text-lg font-semibold tabular-nums text-slate-900">
              {annual.total.toLocaleString("ru-RU")} {annual.currency}/год
              {annual.hasSignon && (
                <span className="text-xs font-normal text-slate-400">с учётом welcome-бонуса</span>
              )}
            </p>
          ) : (
            <span />
          )}
          <Button
            size="icon-sm"
            variant="outline"
            className="shrink-0 border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100"
            aria-label="Удалить оффер"
            onClick={() => remove.mutate(offer.vacancy_id)}
          >
            <Trash2 className="size-4" strokeWidth={2} />
          </Button>
        </div>
        <div className="flex items-start gap-2">
          {priority != null && (
            // вне шкалы D-07: значок size-4, а не читаемый текст
            <span className="mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full bg-slate-900 text-[10px] font-semibold text-white tabular-nums">
              {priority}
            </span>
          )}
          <div className="min-w-0 flex-1 space-y-0.5">
            <p className="truncate text-sm font-semibold text-slate-900">
              {offer.company || "Без компании"}
            </p>
            <p className="truncate text-xs text-slate-500">{offer.position || "—"}</p>
          </div>
        </div>
        <div className="space-y-0.5">
          <div className="flex items-center gap-1">
            <p className="text-xs font-medium uppercase tracking-wider text-slate-500">
              Дедлайн ответа
            </p>
            <HelpTip id="offers.deadline" />
          </div>
          <OfferRow
            row={rowByKey("deadline")!}
            value={fieldValue(offer, "deadline")}
            onCommit={(next) => edit("deadline", next)}
          />
          {countdown && (
            <p
              className={cn(
                "text-xs",
                countdown.overdue ? "font-medium text-rose-600" : "text-slate-400",
              )}
            >
              {countdown.text}
            </p>
          )}
          {/* Этап 1.5 плана `plans/ui_slop_cleanup_2026_08_25.md`: просроченный дедлайн был
              красной строкой без единого действия, а оффер продолжал считаться живым — попадал
              и в сравнение, и в разбор агента наравне с актуальными. Теперь состояние объясняет
              последствие и даёт выход. «Продлить» отдельной кнопкой не делаем: поле даты стоит
              прямо над этой строкой, вторая точка входа в него была бы дублем. */}
          {countdown?.overdue && isOfferUndecided(offer) && (
            <div className="mt-1.5 space-y-1.5 rounded-md bg-rose-50 p-2">
              <p className="text-xs leading-snug text-rose-800">
                Пока оффер не отклонён, он участвует в сравнении и в разборе агента как
                действующий. Если срок сдвинули — поправьте дату выше.
              </p>
              <Button
                size="sm"
                variant="outline"
                className="h-7 w-full border-rose-200 bg-white text-xs text-rose-700 hover:bg-rose-100"
                disabled={patch.isPending}
                onClick={() =>
                  patch.mutate({ vacancyId: offer.vacancy_id, patch: { status: "declined" } })
                }
              >
                Отметить отклонённым
              </Button>
            </div>
          )}
        </div>
      </div>

      <div className="flex-1 space-y-2.5 p-3">
        {visibleRows.map((row) => {
          const v = row.type === "bonus_types" ? offerBonusTypes(offer) : fieldValue(offer, row.key)
          const helpId = OFFER_FIELD_HELP[row.key]
          return (
            <div key={row.key} className="space-y-0.5">
              <div className="flex items-center gap-1">
                <p className="text-xs font-medium uppercase tracking-wider text-slate-500">
                  {row.label}
                </p>
                {helpId && <HelpTip id={helpId} />}
              </div>
              <OfferRow
                row={row}
                value={v}
                onCommit={(next) => {
                  if (row.type === "bonus_types" && Array.isArray(next)) {
                    editBonusTypes(next)
                    return
                  }
                  if (Array.isArray(next)) return
                  edit(row.key, next)
                }}
                formatOptions={FORMAT_OPTS}
                readOnly={READONLY_ROW_KEYS.has(row.key)}
                highlight={favorableFields?.has(row.key)}
              />
            </div>
          )
        })}
      </div>
    </div>
  )
}
