import type { AuthStatus } from "@/api/auth"

// U-0 (PLAN 3.2): видимость разделов приходит в статусе входа (`features`). Режим курса
// прячет всё, что не относится к сценарию агента; код разделов остаётся. Скрытый раздел
// пропадает из меню, его адрес отдаёт «не найдено». «Автоотклики» (`extension_nav`) прячутся
// только из меню: страница работает, через неё уходит отклик после «да».

export type UiSection =
  | "agent"
  | "jobs"
  | "resume"
  | "screening"
  | "tech"
  | "offers"
  | "extension_nav"
  | "market"
  | "companies"
  | "career"
  | "multiplayer"
  | "today"

/** Раздел меню по адресу пункта. */
export const NAV_SECTION: Record<string, UiSection> = {
  "/chat": "agent",
  "/jobs": "jobs",
  "/resume": "resume",
  "/screening": "screening",
  "/tech": "tech",
  "/offers": "offers",
  "/extension": "extension_nav",
  "/market": "market",
  "/companies": "companies",
  "/career": "career",
  "/multiplayer": "multiplayer",
}

/** Нет флага или статус ещё не пришёл — раздел виден (не мигаем пустым меню). */
export function isSectionVisible(status: AuthStatus | undefined, section: UiSection): boolean {
  return status?.features?.[section] !== false
}
