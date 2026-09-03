import type { AdminUserRow } from "@/api/admin"

/** Подпись при наведении на имя в таблице людей — диагноз, не внутренний id. */
export function personHoverTitle(user: AdminUserRow): string {
  const bits: string[] = []
  if (!user.has_openrouter_key) bits.push("нет ключа")
  if (!user.has_resume) bits.push("нет резюме")
  if (!user.extension_confirmed) bits.push("нет расширения")
  if (user.telegram_chat_id == null) bits.push("нет чата с ботом")
  if (user.errors_24h > 0) bits.push(`${user.errors_24h} ошибок за сутки`)
  if (user.spend_alert) bits.push("порог расхода")
  const note = user.note?.trim()
  if (note) bits.push(note)
  if (bits.length === 0) bits.push(`id ${user.account_id}`)
  return bits.join(" · ")
}
