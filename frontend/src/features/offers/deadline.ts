import type { OfferRecord } from "@/api/offers"
import { fieldValue } from "./rows"

/**
 * Дедлайн ответа по офферу: живой счётчик от текущего момента, а не сохранённое поле —
 * в базе лежит абсолютная дата, «сколько осталось» считается на клиенте.
 *
 * Вынесено из `components/offers/OfferCard.tsx` (Этап 1.5 плана
 * `plans/ui_slop_cleanup_2026_08_25.md`): просрочку теперь показывает не только карточка,
 * но и шапка сравнения, а чистую функцию проще накрыть тестом.
 */
export function deadlineCountdown(
  value: string | number | null,
): { text: string; overdue: boolean } | null {
  if (value == null || value === "") return null
  const d = new Date(String(value))
  if (Number.isNaN(d.getTime())) return null
  const days = Math.ceil((d.getTime() - Date.now()) / 86_400_000)
  if (days < 0) return { text: "дедлайн прошёл", overdue: true }
  if (days === 0) return { text: "сегодня", overdue: false }
  return { text: `осталось ${days} дн.`, overdue: false }
}

/**
 * Решение по офферу ещё не принято: только по такому имеет смысл считать дедлайн.
 *
 * И принятый, и отклонённый — уже закрытые истории: напоминать про срок ответа по ним незачем,
 * а предлагать «отметить отклонённым» принятый оффер прямо вредно.
 */
export function isOfferUndecided(offer: OfferRecord): boolean {
  return offer.status !== "accepted" && offer.status !== "declined"
}

/** Решение не принято, а срок ответа уже вышел. */
export function isOfferOverdue(offer: OfferRecord): boolean {
  if (!isOfferUndecided(offer)) return false
  return deadlineCountdown(fieldValue(offer, "deadline"))?.overdue === true
}

/**
 * Все нерешённые офферы просрочены — сравнение показывает историю, а не живые предложения.
 * Пустой список и набор из одних решённых таким состоянием не считаются: там нечего сравнивать
 * не потому, что сроки вышли, а потому, что выбор уже сделан.
 */
export function allOffersOverdue(offers: readonly OfferRecord[]): boolean {
  const undecided = offers.filter(isOfferUndecided)
  return undecided.length > 0 && undecided.every(isOfferOverdue)
}
