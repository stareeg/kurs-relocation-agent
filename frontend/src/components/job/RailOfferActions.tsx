import { CircleCheck, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { usePatchOffer } from "@/features/offers/use-offers"
import { RailChatButton } from "./RailChatButton"

// Ряд кнопок под карточкой рельса Офферов: «Отклонён» — «Чат» — «Принят». Крайние заменяют
// переключалку Думаю/Принят/Отклонён внутри OfferCard (см. plan п.1d); статус по умолчанию
// остаётся «Думаю», пока не нажата одна из них. «Чат» посередине — тот же вход в переписку по
// вакансии, что в Скринингах/Техничках. Нет оффера под вакансией (черновик) — ряда нет вовсе.
export function RailOfferActions({ vacancyId }: { vacancyId: string }) {
  const patch = usePatchOffer()
  return (
    <>
      <Button
        size="sm"
        variant="outline"
        className="h-7 gap-1 border-rose-200 bg-rose-50 px-2 text-xs text-rose-700 hover:bg-rose-100"
        disabled={patch.isPending}
        onClick={() => patch.mutate({ vacancyId, patch: { status: "declined" } })}
      >
        <X className="size-3.5" strokeWidth={2} />
        Отклонён
      </Button>
      <RailChatButton vacancyId={vacancyId} />
      <Button
        size="sm"
        variant="outline"
        className="h-7 gap-1 border-emerald-200 bg-emerald-50 px-2 text-xs text-emerald-700 hover:bg-emerald-100"
        disabled={patch.isPending}
        onClick={() => patch.mutate({ vacancyId, patch: { status: "accepted" } })}
      >
        <CircleCheck className="size-3.5" strokeWidth={2} />
        Принят
      </Button>
    </>
  )
}
