import type { MarketSectionId } from "./market-sections"

/**
 * Fallback-причины пустоты по секциям (F-06). Бэкендовый `note` / `empty_reason` важнее —
 * эти строки только если бэк молчит. Без жаргона («скор», «гейт», «заскорено»).
 */
export const SECTION_EMPTY_FALLBACKS: Readonly<Record<MarketSectionId, string>> = {
  "gde-stoyu":
    "Оцените несколько вакансий через расширение на hh.ru или getmatch.ru — здесь появятся зарплаты рынка.",
  "otklik-rynka":
    "Зайдите на hh.ru в личный кабинет резюме — расширение снимет показы и просмотры, здесь появится статистика площадок.",
  "chto-rezhet-potok":
    "Пропустите несколько вакансий с причиной — здесь появится, что вы отклоняете чаще всего.",
  voronka: "Пока нет откликов — появятся, когда отклики попадут в воронку.",
  formats: "Заскорьте вакансии — здесь появятся условия рынка (форматы, грейды, роли).",
  "shans-offera":
    "Заскорьте вакансии и откликнитесь на несколько — здесь появится шанс офферов во времени.",
  "stavki-valyuta":
    "Оцените несколько валютных вакансий второго трека — здесь появятся ставки в своей валюте, без перевода в рубли.",
}

/** Причина пустоты: note бэка, иначе запасная формулировка секции. Без общих «нет данных». */
export function resolveEmptyReason(
  backendNote: string | null | undefined,
  sectionId: MarketSectionId,
): string {
  const note = backendNote?.trim()
  if (note) return note
  return SECTION_EMPTY_FALLBACKS[sectionId]
}

/**
 * Gated-виджеты (калибровка, источники, ниши…): мало данных → секции нет, не пустая рамка.
 * `enoughData === false` прячет даже при `available=true` (плашка note — внутри виджета, если он
 * сам решил остаться на экране, как воронка W-03).
 */
export function shouldHideEmptyBlock(opts: {
  available?: boolean | null
  enoughData?: boolean | null
}): boolean {
  if (opts.available === false) return true
  if (opts.enoughData === false) return true
  return false
}
