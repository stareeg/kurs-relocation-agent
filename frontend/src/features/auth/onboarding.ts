import type { AuthStatus } from "@/api/auth"

/**
 * Чистая логика онбординга (AUTH-1): по статусу с бэка решаем, какие разделы доступны
 * и куда вести пользователя. Разделы открываются, когда выполнены все три условия:
 * запрос авторизован, токен из бота выпущен, доступ к модели есть (свой ключ OpenRouter
 * или серверный провайдер курса — A-0).
 *
 * Инвариант «нет мёртвых путей» (закреплён тестами onboarding.test.ts): в любом состоянии
 * `/settings` доступен и `homeTarget` ведёт на доступный маршрут — застрять негде.
 */

/** Разделы открыты: вход жив и доступ к модели есть (ключ OpenRouter или сервер). */
export function isGateOpen(s: AuthStatus): boolean {
  return (
    s.authed &&
    s.auth_token_configured &&
    Boolean(s.openrouter_key_configured || s.server_llm_available)
  )
}

/** Маршрут доступен при закрытом гейте — только «Параметры». */
export function isRouteAllowedWhileGated(pathname: string): boolean {
  return pathname === "/settings" || pathname.startsWith("/settings/")
}

/**
 * Куда ведёт корень `/`:
 * гейт закрыт → Параметры; расширение не подтверждено → Расширение; иначе → Вакансии
 * (решение #16 — рабочий стол, а не пустой чат при первом входе).
 */
export function homeTarget(s: AuthStatus | undefined): string {
  if (!s || !isGateOpen(s)) return "/settings"
  if (!s.extension_confirmed) return "/extension"
  return "/jobs"
}

/** Форма входа по токену нужна, пока вход не жив вместе с выпущенным токеном. */
export function needsTokenLogin(s: AuthStatus): boolean {
  return !s.authed || !s.auth_token_configured
}
