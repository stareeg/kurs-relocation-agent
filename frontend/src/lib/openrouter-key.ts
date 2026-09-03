/** Убрать пробелы и переносы: парольный менеджер часто кладёт хвост \n. */
export function sanitizeOpenRouterKey(raw: string): string {
  return raw.replace(/\s+/g, "")
}

/** Грубая проверка вида ключа OpenRouter до отправки на бэкенд. */
export function looksLikeOpenRouterKey(raw: string): boolean {
  const key = sanitizeOpenRouterKey(raw)
  if (!/^sk-or-/i.test(key)) return false
  // Реальные ключи длиннее; короткий мусор не автосейвим.
  return key.length >= 24
}
