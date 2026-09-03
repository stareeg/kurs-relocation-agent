/**
 * Грубая проверка вида токена входа из Telegram-бота до отправки на бэкенд.
 * Два формата:
 * - обычный токен владельца: `secrets.token_urlsafe(24)` — ~32 символа [A-Za-z0-9_-];
 * - переносимый гостевой (AUTH-2): `cc.<base64url(аккаунт)>.<секрет>`.
 * Допускаем запас по длине, но отсекаем короткий мусор и явные не-токены.
 */
export function looksLikeBotAuthToken(raw: string): boolean {
  const token = raw.trim()
  if (/^cc\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{16,}$/.test(token)) return true
  return /^[A-Za-z0-9_-]{28,64}$/.test(token)
}
