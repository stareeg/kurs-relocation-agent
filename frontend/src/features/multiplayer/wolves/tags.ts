/**
 * Категории опыта на русском. Служебные слаги движка (`ownership`, `scale`…) вслух за столом
 * не показываем — только эти ярлыки. Зеркало `core/domains/multiplayer/deck.CARD_TAG_LABELS`.
 *
 * `TAG_RU` — для прозы (строка требования в бюллетене), `TAG_SHORT` — для тесной карты опыта,
 * где длинная подпись не влезает.
 */
export const TAG_RU: Record<string, string> = {
  ownership: "вёл сам",
  scale: "рост нагрузки",
  incident: "инцидент",
  soft: "работа с людьми",
  stack: "стек",
  bluff: "блеф",
  batna: "запасной оффер",
  second_job: "две работы",
}

export const TAG_SHORT: Record<string, string> = {
  ownership: "вёл сам",
  scale: "масштаб",
  incident: "инцидент",
  soft: "люди",
  stack: "стек",
  bluff: "блеф",
  batna: "козырь",
  second_job: "две работы",
}

export function tagRu(tag: string): string {
  return TAG_RU[tag] ?? tag
}

export function tagShort(tag: string): string {
  return TAG_SHORT[tag] ?? tag
}
