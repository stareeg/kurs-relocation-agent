/** Окно логов файлом в карточке. Сервер принимает hours, дефолт — трое суток. */
export const LOG_WINDOW_HOURS = [
  { value: "24", label: "сутки" },
  { value: "72", label: "3 дня" },
  { value: "168", label: "7 дней" },
] as const

export const DEFAULT_LOG_HOURS = 72
