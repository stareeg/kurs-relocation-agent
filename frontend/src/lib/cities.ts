/**
 * Курируемый справочник городов для автокомплита «Город проживания» (Э0.2).
 * Холодный старт, пока GET /api/meta/cities не вернул свои данные. Канон географии —
 * `core/kernel/timezones.py`; страна здесь совпадает с label в countries.ts.
 */

export const UNKNOWN_CITY_HINT =
  "Страну и часовой пояс не определили — выберите ближайший город из списка"

export type CitySuggestion = {
  city: string
  country?: string
  timezone?: string
  utcOffset?: string
  overlapEmea?: number | null
  source?: string
  aliases?: string[]
}

export const CURATED_CITIES: CitySuggestion[] = [
  { city: "Москва", country: "Россия", timezone: "Europe/Moscow", utcOffset: "UTC+3", aliases: ["Moscow"] },
  {
    city: "Санкт-Петербург",
    country: "Россия",
    timezone: "Europe/Moscow",
    utcOffset: "UTC+3",
    aliases: ["СПб", "Питер", "Saint Petersburg", "St. Petersburg"],
  },
  { city: "Новосибирск", country: "Россия", timezone: "Asia/Novosibirsk", utcOffset: "UTC+7" },
  { city: "Екатеринбург", country: "Россия", timezone: "Asia/Yekaterinburg", utcOffset: "UTC+5" },
  { city: "Казань", country: "Россия", timezone: "Europe/Moscow", utcOffset: "UTC+3" },
  { city: "Нижний Новгород", country: "Россия", timezone: "Europe/Moscow", utcOffset: "UTC+3" },
  { city: "Челябинск", country: "Россия", timezone: "Asia/Yekaterinburg", utcOffset: "UTC+5" },
  { city: "Самара", country: "Россия", timezone: "Europe/Samara", utcOffset: "UTC+4" },
  { city: "Ростов-на-Дону", country: "Россия", timezone: "Europe/Moscow", utcOffset: "UTC+3" },
  { city: "Уфа", country: "Россия", timezone: "Asia/Yekaterinburg", utcOffset: "UTC+5" },
  { city: "Красноярск", country: "Россия", timezone: "Asia/Krasnoyarsk", utcOffset: "UTC+7" },
  { city: "Воронеж", country: "Россия", timezone: "Europe/Moscow", utcOffset: "UTC+3" },
  { city: "Пермь", country: "Россия", timezone: "Asia/Yekaterinburg", utcOffset: "UTC+5" },
  { city: "Краснодар", country: "Россия", timezone: "Europe/Moscow", utcOffset: "UTC+3" },
  { city: "Владивосток", country: "Россия", timezone: "Asia/Vladivostok", utcOffset: "UTC+10" },
  { city: "Калининград", country: "Россия", timezone: "Europe/Kaliningrad", utcOffset: "UTC+2" },
  { city: "Сочи", country: "Россия", timezone: "Europe/Moscow", utcOffset: "UTC+3" },
  { city: "Тюмень", country: "Россия", timezone: "Asia/Yekaterinburg", utcOffset: "UTC+5" },
  { city: "Иркутск", country: "Россия", timezone: "Asia/Irkutsk", utcOffset: "UTC+8" },
  { city: "Томск", country: "Россия", timezone: "Asia/Tomsk", utcOffset: "UTC+7" },
  { city: "Минск", country: "Беларусь", timezone: "Europe/Minsk", utcOffset: "UTC+3" },
  { city: "Алматы", country: "Казахстан", timezone: "Asia/Almaty", utcOffset: "UTC+5" },
  { city: "Астана", country: "Казахстан", timezone: "Asia/Almaty", utcOffset: "UTC+5", aliases: ["Нур-Султан"] },
  { city: "Тбилиси", country: "Грузия", timezone: "Asia/Tbilisi", utcOffset: "UTC+4", aliases: ["Tbilisi"] },
  { city: "Ереван", country: "Армения", timezone: "Asia/Yerevan", utcOffset: "UTC+4" },
  { city: "Баку", country: "Азербайджан", timezone: "Asia/Baku", utcOffset: "UTC+4" },
  { city: "Ташкент", country: "Узбекистан", timezone: "Asia/Tashkent", utcOffset: "UTC+5" },
  { city: "Бишкек", country: "Киргизия", timezone: "Asia/Bishkek", utcOffset: "UTC+6" },
  { city: "Кишинёв", country: "Молдова", timezone: "Europe/Chisinau", utcOffset: "UTC+2", aliases: ["Кишинев"] },
  { city: "Киев", country: "Украина", timezone: "Europe/Kyiv", utcOffset: "UTC+2" },
  { city: "Лиссабон", country: "Португалия", timezone: "Europe/Lisbon", utcOffset: "UTC+0" },
  { city: "Барселона", country: "Испания", timezone: "Europe/Madrid", utcOffset: "UTC+1" },
  { city: "Берлин", country: "Германия", timezone: "Europe/Berlin", utcOffset: "UTC+1" },
  { city: "Амстердам", country: "Нидерланды", timezone: "Europe/Amsterdam", utcOffset: "UTC+1" },
  { city: "Варшава", country: "Польша", timezone: "Europe/Warsaw", utcOffset: "UTC+1" },
  { city: "Прага", country: "Чехия", timezone: "Europe/Prague", utcOffset: "UTC+1" },
  { city: "Белград", country: "Сербия", timezone: "Europe/Belgrade", utcOffset: "UTC+1" },
  { city: "Стамбул", country: "Турция", timezone: "Europe/Istanbul", utcOffset: "UTC+3" },
  { city: "Дубай", country: "ОАЭ", timezone: "Asia/Dubai", utcOffset: "UTC+4" },
  { city: "Лимассол", country: "Кипр", timezone: "Asia/Nicosia", utcOffset: "UTC+2" },
  { city: "Бангкок", country: "Таиланд", timezone: "Asia/Bangkok", utcOffset: "UTC+7" },
  { city: "Хошимин", country: "Вьетнам", timezone: "Asia/Ho_Chi_Minh", utcOffset: "UTC+7" },
  { city: "Сингапур", country: "Сингапур", timezone: "Asia/Singapore", utcOffset: "UTC+8" },
  { city: "Тель-Авив", country: "Израиль", timezone: "Asia/Jerusalem", utcOffset: "UTC+2" },
  { city: "Лондон", country: "Великобритания", timezone: "Europe/London", utcOffset: "UTC+0" },
  { city: "Нью-Йорк", country: "США", timezone: "America/New_York", utcOffset: "UTC-5" },
  { city: "Буэнос-Айрес", country: "Аргентина", timezone: "America/Argentina/Buenos_Aires", utcOffset: "UTC-3" },
]

export function normalizeCity(city: string): string {
  return city.trim().toLocaleLowerCase("ru").replaceAll("ё", "е").replace(/\s+/g, " ")
}

function keysOf(item: CitySuggestion): string[] {
  return [item.city, ...(item.aliases ?? [])].map(normalizeCity).filter(Boolean)
}

export function lookupCity(city: string, extra: CitySuggestion[] = []): CitySuggestion | undefined {
  const key = normalizeCity(city)
  if (!key) return undefined
  for (const item of extra) {
    if (keysOf(item).includes(key)) return item
  }
  return CURATED_CITIES.find((item) => keysOf(item).includes(key))
}

/** API-города и опыт первыми, курируемый список — фолбэк. Дубликаты схлопываются. */
export function mergeCitySuggestions(
  fromApi: CitySuggestion[],
  fromExperience: string[] = [],
): CitySuggestion[] {
  const out: CitySuggestion[] = []
  const seen = new Set<string>()
  const add = (item: CitySuggestion) => {
    const key = normalizeCity(item.city)
    if (!key || seen.has(key)) return
    seen.add(key)
    out.push(item)
  }
  for (const item of fromApi) add(item)
  for (const area of fromExperience) {
    const trimmed = area.trim()
    if (!trimmed) continue
    add(lookupCity(trimmed, fromApi) ?? { city: trimmed, source: "resume" })
  }
  for (const item of CURATED_CITIES) add(item)
  return out
}

export function mergeDerivedCountries(existing: string[], country?: string): string[] {
  if (!country) return existing
  return [country, ...existing.filter((c) => c !== country)]
}

export function formatCitySuggestion(item: CitySuggestion): string {
  if (item.country && item.utcOffset) {
    return `${item.city} · ${item.country} · ${item.utcOffset}`
  }
  if (item.country) return `${item.city} · ${item.country}`
  return item.city
}

export function formatCityUtcOffset(city: string, extra: CitySuggestion[] = []): string {
  if (!city.trim()) return ""
  return lookupCity(city, extra)?.utcOffset ?? ""
}

export function formatCityDerivedLine(city: string, extra: CitySuggestion[] = []): string {
  if (!city.trim()) return ""
  const geo = lookupCity(city, extra)
  if (!geo?.utcOffset) return UNKNOWN_CITY_HINT
  return geo.utcOffset
}
