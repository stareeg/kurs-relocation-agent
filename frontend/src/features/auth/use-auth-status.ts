import { useQuery } from "@tanstack/react-query"
import { fetchAuthStatus } from "@/api/auth"

export const AUTH_STATUS_KEY = ["auth", "status"] as const

/**
 * Публичный статус входа/онбординга (AUTH-1) — источник для гейта разделов и редиректов.
 * Инвалидируется после логина/логаута и сохранения ключа OpenRouter; `extension_confirmed`
 * бэкенд выставляет сам при первом запросе расширения (api/security.py) — фронт видит это
 * по staleTime/refetch (например, при возврате в вкладку после проверки на hh.ru), без
 * отдельной инвалидации отсюда.
 */
export function useAuthStatusQuery() {
  return useQuery({
    queryKey: AUTH_STATUS_KEY,
    queryFn: fetchAuthStatus,
    staleTime: 10_000,
    retry: 1,
  })
}
