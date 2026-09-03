/** Сегодня — только время; иначе — только дата ДД.ММ. */
export function fmtChatWhen(iso?: string | null): string {
  if (!iso) return ""
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ""
  const now = new Date()
  const isToday =
    d.getDate() === now.getDate() &&
    d.getMonth() === now.getMonth() &&
    d.getFullYear() === now.getFullYear()
  const p = (n: number) => String(n).padStart(2, "0")
  if (isToday) return `${p(d.getHours())}:${p(d.getMinutes())}`
  return `${p(d.getDate())}.${p(d.getMonth() + 1)}`
}

/** Жёсткий лимит первой строки списка диалогов по вакансиям: имя HR / компания.
 * CSS `truncate` в узкой панели не удерживает дату последнего сообщения внутри рельса. */
export const CHAT_LIST_TITLE_MAX = 23

export function clipChatListTitle(value: string, max = CHAT_LIST_TITLE_MAX): string {
  if (value.length <= max) return value
  return `${value.slice(0, max)}…`
}
