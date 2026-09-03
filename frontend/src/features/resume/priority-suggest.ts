/** Чистая логика ротации вариантов «Приоритеты» → «Обновить».
 *
 * Вынесено из `SearchProfilePanel`, потому что здесь сидел баг: панель отправляла в
 * `exclude_priorities` только ВЫБРАННЫЕ приоритеты. Пока пользователь ничего не выбрал, вход
 * запроса между нажатиями не менялся, `call.run` отдавал ответ из result-кэша (ключ =
 * `feature:prompt_version:hash(system,user,…)`, TTL 7 дней), и кнопка выглядела мёртвой:
 * на проде 2026-08-16 три нажатия подряд дали три `LLM cache hit` за 9/4/3 мс.
 *
 * Лечение — накапливать показанные ярлыки: они меняют вход (значит и ключ кэша) и заодно
 * говорят модели не повторяться.
 */

export type PriorityCandidate = { label: string; reason: string }

/** Состояние слайта подсказок. Живёт в query-кэше, а не в `useState` панели: панель
 * размонтируется при переключении вкладок «Резюме», и подсказки иначе теряются вместе с историей
 * показанного — то есть после возврата «Обновить» опять присылало бы то же самое.
 *
 * `roleKind` / `marketSegment` — предложения LLM по осям профиля. Панель применяет их только к
 * ПУСТЫМ осям и только по явному действию: перетирать выбор пользователя подсказка не должна.
 */
export type SuggestState = {
  candidates: PriorityCandidate[]
  seen: string[]
  roleKind: string
  marketSegment: string
}

export const EMPTY_SUGGEST_STATE: SuggestState = {
  candidates: [],
  seen: [],
  roleKind: "",
  marketSegment: "",
}

/** Сколько показанных ярлыков помним — против бесконечного роста блока exclude в промпте. */
export const MAX_SEEN = 40

/** Сколько приоритетов пользователь может держать выбранными. */
export const MAX_PRIORITIES = 6

/** Что уходит в `exclude_priorities`: выбранное + всё уже показанное, без дублей. */
export function buildExclude(
  priorities: readonly string[],
  seen: readonly string[],
  max = MAX_SEEN,
): string[] {
  return Array.from(new Set([...priorities, ...seen])).slice(-max)
}

/** Отобрать из ответа только реально новые варианты (пустой результат = круг пройден). */
export function pickFresh(
  candidates: readonly PriorityCandidate[],
  priorities: readonly string[],
  seen: readonly string[],
  limit = MAX_PRIORITIES * 2,
): PriorityCandidate[] {
  const taken = new Set([...priorities, ...seen])
  const out: PriorityCandidate[] = []
  for (const candidate of candidates) {
    const label = candidate.label.trim()
    if (!label || taken.has(label)) continue
    taken.add(label)
    out.push({ label, reason: candidate.reason })
    if (out.length >= limit) break
  }
  return out
}

/** Обновлённый список показанного после порции новых вариантов. */
export function rememberSeen(
  seen: readonly string[],
  fresh: readonly PriorityCandidate[],
  max = MAX_SEEN,
): string[] {
  return [...seen, ...fresh.map((c) => c.label)].slice(-max)
}

/** Ответ бэка в том виде, в каком он важен для состояния (поля схемы опциональны). */
export type SuggestResponse = {
  priorities?: readonly PriorityCandidate[]
  role_kind?: string
  market_segment?: string
}

export type SuggestOutcome = {
  /** `exhausted` — новых вариантов нет: круг показанного сбрасываем и говорим об этом вслух. */
  kind: "fresh" | "exhausted"
  state: SuggestState
}

/** Свести ответ бэка с текущим состоянием. Чистая функция — вся развилка «Обновить» тестируема.
 *
 * Оси профиля (`role_kind` / `market_segment`) запоминаются всегда: они не зависят от ротации
 * приоритетов, и даже на исчерпанном круге подсказка по отрасли остаётся валидной.
 */
export function nextSuggestState(
  prev: SuggestState,
  response: SuggestResponse,
  priorities: readonly string[],
): SuggestOutcome {
  const axes = {
    roleKind: (response.role_kind ?? "").trim() || prev.roleKind,
    marketSegment: (response.market_segment ?? "").trim() || prev.marketSegment,
  }
  const fresh = pickFresh(response.priorities ?? [], priorities, prev.seen)

  if (fresh.length === 0) {
    return { kind: "exhausted", state: { ...prev, ...axes, seen: [] } }
  }
  return {
    kind: "fresh",
    state: { ...axes, candidates: fresh, seen: rememberSeen(prev.seen, fresh) },
  }
}
