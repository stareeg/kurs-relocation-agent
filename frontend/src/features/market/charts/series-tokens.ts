/**
 * Категориальные слоты рядов (V-09, план market_redesign_v3 п. 4.2): три валидированных цвета
 * (`--series-1/2/3` в globals.css) — единственная палитра для сущностей на одном графике
 * (например, разные офферы на оси денег, разные метрики отклика резюме). `--status-*-dot` для
 * этого запрещён: провал по полосе светлоты и контраст 2.08–2.64 к белой поверхности (план п.
 * 4.2).
 *
 * Слот считается по месту сущности в полном перечне (`allKeys`), который передаёт вызывающий, а
 * не по её месту в уже отфильтрованном подмножестве — иначе фильтр «перекрашивает выживших»
 * (план п. 4.2/V-09): один и тот же ряд должен носить один и тот же цвет и до, и после фильтра.
 */
export const SERIES_SLOT_COUNT = 3

/** Слот 0..SERIES_SLOT_COUNT-1 для ключа сущности; ключ не из allKeys → первый слот. */
export function seriesSlot(key: string, allKeys: readonly string[]): number {
  const index = allKeys.indexOf(key)
  return index < 0 ? 0 : index % SERIES_SLOT_COUNT
}

/** Готовый класс Tailwind-заливки/обводки/текста для ключа сущности. */
export function seriesClass(
  layer: "bg" | "stroke" | "text" | "border",
  key: string,
  allKeys: readonly string[],
): string {
  return `${layer}-series-${seriesSlot(key, allKeys) + 1}`
}
