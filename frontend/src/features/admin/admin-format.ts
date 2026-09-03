/**
 * Форматирование чисел и подписей админки — чистые функции без React.
 *
 * Вынесено из `AdminPage.tsx` (Этап 1.3), чтобы правила «как показывается число» проверялись
 * тестом, а не глазами по рендеру: подписи здесь несут смысл (см. Этап 0 — счётчик и список
 * считаются одним условием, и разница между «ноль» и «не знаю» обязана быть видна).
 */

/**
 * Правила форматов раздела (Этап 1, §2.6 плана). Даты здесь числовые — «12.08 17:11:06», а не
 * «12 авг., 17:11», как в остальном продукте: в плотной операторской таблице числовая дата
 * выравнивается по `tabular-nums` и занимает фиксированную ширину, а «авг.»/«сент.» скачут.
 * Часовой пояс не трогаем — как и везде, показываем локальное время браузера.
 */
function pad(value: number): string {
  return String(value).padStart(2, "0")
}

/** «12.08» — день-корзина. Совпадает с `formatDayShort` из библиотеки графиков. */
export function formatDay(iso: string | null | undefined): string {
  const at = iso ? new Date(iso) : null
  if (!at || Number.isNaN(at.getTime())) return "—"
  return `${pad(at.getDate())}.${pad(at.getMonth() + 1)}`
}

/** «16.08 23:16» — момент старше двух суток. */
export function formatMoment(iso: string | null | undefined): string {
  const at = iso ? new Date(iso) : null
  if (!at || Number.isNaN(at.getTime())) return "—"
  return `${formatDay(iso)} ${pad(at.getHours())}:${pad(at.getMinutes())}`
}

/** «12.08 17:11:06» — запись журнала: секунды нужны, чтобы связать соседние строки. */
export function formatLogTs(iso: string | null | undefined): string {
  const at = iso ? new Date(iso) : null
  if (!at || Number.isNaN(at.getTime())) return "—"
  return `${formatMoment(iso)}:${pad(at.getSeconds())}`
}

/**
 * Склонение существительного при числе — одно место на весь раздел.
 *
 * Правило было написано в разделе четыре раза (`attention.ts` дважды, `silenceLabel`,
 * `waitingNote`) и всё равно не применено там, где видно чаще всего: очередь писала
 * «23 сбоев», чип вида — «1 сбоев».
 */
export function plural(count: number, forms: readonly [string, string, string]): string {
  const abs = Math.abs(count)
  const tail = abs % 10
  const teen = abs % 100 >= 11 && abs % 100 <= 14
  if (!teen && tail === 1) return forms[0]
  if (!teen && tail >= 2 && tail <= 4) return forms[1]
  return forms[2]
}

/** «23 сбоя» — число со склонённым словом. */
export function pluralize(count: number, forms: readonly [string, string, string]): string {
  return `${count} ${plural(count, forms)}`
}

/** Крупное число в узкой ячейке: «9.5 М». Полное значение — в `title` у места вызова. */
export function compactNumber(value: number | null | undefined): string {
  const n = value ?? 0
  if (n < 1000) return String(n)
  if (n < 1_000_000) return `${(n / 1000).toFixed(n < 10_000 ? 1 : 0)} тыс.`
  return `${(n / 1_000_000).toFixed(n < 10_000_000 ? 1 : 0)} М`
}

export function usd(value: number | undefined | null): string {
  return `$${(value ?? 0).toFixed(2)}`
}

/**
 * «340 мс» / «1.2 с». Пустое — тире, не «0 мс»: нулевая latency врала бы как мгновенный ответ.
 *
 * Ровный ноль тоже тире: LLM-вызов не может занять 0 мс, значит замера не было. Источник нулей
 * (тайминги попаданий в кэш) починен в `core/platform/llm/call.py`, но старые строки в
 * `llm_usage` остаются — и они не должны рисоваться как измеренная латентность.
 */
export function msLabel(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value) || value === 0) return "—"
  if (value >= 1000) return `${(value / 1000).toFixed(1)} с`
  return `${Math.round(value)} мс`
}

/** Доля: «34%». Null — тире, чтобы «0%» не читалось как «кэш ничего не ловит». */
export function pctLabel(rate: number | null | undefined): string {
  if (rate == null || Number.isNaN(rate)) return "—"
  return `${Math.round(rate * 100)}%`
}

export function tokens(value: number | undefined | null): string {
  return (value ?? 0).toLocaleString("ru-RU")
}

export function atHandle(name: string | null | undefined): string {
  if (!name) return "без @"
  return name.startsWith("@") ? name : `@${name}`
}

/** «сейчас» / «12 мин» / «5 ч» / дата. Пустое значение — «не заходил», а не «только что». */
export function relativeSeen(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "не заходил"
  const at = new Date(iso).getTime()
  if (Number.isNaN(at)) return "не заходил"
  const minutes = Math.max(0, Math.round((now - at) / 60_000))
  if (minutes < 5) return "сейчас"
  if (minutes < 60) return `${minutes} мин`
  const hours = Math.round(minutes / 60)
  if (hours < 48) return `${hours} ч`
  return formatMoment(iso)
}

/** «молчит 21 день» / «не заходил ни разу» — None-дни это отсутствие, а не ноль. */
export function silenceLabel(days: number | null | undefined): string {
  if (days == null) return "не заходил ни разу"
  return `молчит ${pluralize(days, DAYS)}`
}

export const DAYS = ["день", "дня", "дней"] as const
export const FAILURES = ["сбой", "сбоя", "сбоев"] as const
export const TASKS_FELL = ["задача упала", "задачи упали", "задач упало"] as const
export const ERRORS = ["ошибка", "ошибки", "ошибок"] as const
export const CASES = ["дело", "дела", "дел"] as const
export const PEOPLE = ["человек", "человека", "человек"] as const

/** «показано 20 из 137» — либо ничего, если список и счётчик сошлись. */
export function shownOfLabel(shown: number, total: number): string {
  return total > shown ? `показано ${shown} из ${total}` : ""
}

/** «оператор» / «участник»: пара читается как две роли, а не как роль и сущность. */
export function roleLabel(role: string | undefined): string {
  return role === "owner" ? "оператор" : "участник"
}

export function statusLabel(status: string | undefined): string {
  return status === "active" ? "активен" : "отключён"
}

/** Размер jsonb резюме в снимке аккаунта — килобайты, не байты. */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null || bytes < 0) return "—"
  if (bytes < 1024) return `${bytes} Б`
  return `${(bytes / 1024).toFixed(1)} КБ`
}

/** Время последнего обновления витрины: «обновлено в 14:32». Ноль — витрину ещё не грузили. */
export function updatedAtLabel(updatedAt: number | undefined): string {
  if (!updatedAt) return ""
  const at = new Date(updatedAt)
  if (Number.isNaN(at.getTime())) return ""
  const hh = String(at.getHours()).padStart(2, "0")
  const mm = String(at.getMinutes()).padStart(2, "0")
  return `обновлено в ${hh}:${mm}`
}

/** Подпись точки спарклайна: индекс 0 — самый старый день, последний — сегодня. */
export function sparklineDayLabel(index: number, length = 14): string {
  const ago = length - 1 - index
  if (ago <= 0) return "сегодня"
  if (ago === 1) return "вчера"
  return `${ago} дн. назад`
}

/** Размер таблицы: килобайты и гигабайты, не только КБ как у jsonb резюме. */
export function formatSize(bytes: number | null | undefined): string {
  if (bytes == null || bytes < 0) return "—"
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} ГБ`
}

export type KeyRemainingProbe = {
  alive: boolean
  network_error: boolean
  error?: string
  limit_remaining?: number | null
  is_free_tier: boolean
}

/** Колонка «Остаток»: пока не обновляли — тире, а не «$0.00». */
export function remainingLabel(probe: KeyRemainingProbe | undefined): string {
  if (!probe) return "—"
  if (probe.network_error) return "нет ответа"
  if (!probe.alive) return "мёртв"
  if (probe.limit_remaining == null) return probe.is_free_tier ? "free-tier" : "без лимита"
  return usd(probe.limit_remaining)
}

export function remainingTone(
  probe: KeyRemainingProbe | undefined,
): "good" | "warn" | "bad" | "info" | undefined {
  if (!probe) return undefined
  if (probe.network_error) return "warn"
  if (!probe.alive) return "bad"
  if (probe.limit_remaining == null) return probe.is_free_tier ? "warn" : "info"
  if (probe.limit_remaining <= 0) return "bad"
  if (probe.limit_remaining < 1) return "warn"
  return "good"
}

/** Минимум, который нужен, чтобы понять, кто с кем делит ключ. */
export type KeyHolder = {
  account_id: number
  telegram_username?: string | null
  key_hint?: string | null
}

/**
 * Кто с кем делит один ключ OpenRouter: `account_id` → подпись «тот же ключ, что у @lil_hate».
 *
 * На живой установке совпадение есть, и сейчас его видно, только если сличать хвосты `…15fb`
 * глазами по всей таблице. Совпадение хвоста — не доказательство (четыре символа), но повод
 * посмотреть, поэтому подпись тихая, серая, без плашки.
 */
export function sharedKeyNotes(people: readonly KeyHolder[]): Record<number, string> {
  const byHint = new Map<string, { id: number; handle: string }[]>()
  for (const person of people) {
    const hint = (person.key_hint ?? "").trim()
    if (!hint) continue
    const holders = byHint.get(hint) ?? []
    holders.push({ id: person.account_id, handle: atHandle(person.telegram_username) })
    byHint.set(hint, holders)
  }

  const notes: Record<number, string> = {}
  for (const holders of byHint.values()) {
    if (holders.length < 2) continue
    for (const holder of holders) {
      const others = holders.filter((other) => other.id !== holder.id).map((other) => other.handle)
      notes[holder.id] = `тот же ключ, что у ${others.join(", ")}`
    }
  }
  return notes
}
