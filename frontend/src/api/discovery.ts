import type { components } from "@/api/schema"
import { api } from "@/api/client"

// FastAPI отдаёт Literal как enum query-параметра, не отдельной именованной схемой (в отличие
// от Pydantic-моделей) — components["schemas"] его не содержит, тот же приём, что у auto-apply.ts.
export type DiscoveryPlatform = "hh" | "getmatch" | "habr"
export type DiscoveryConfig = components["schemas"]["DiscoveryConfig"]
export type DiscoveryPlatformConfig = components["schemas"]["DiscoveryPlatformConfig"]
export type DiscoveryStatus = components["schemas"]["DiscoveryStatus"]
export type DiscoveryEvent = components["schemas"]["DiscoveryEvent"]
export type DiscoverySessionAction = components["schemas"]["DiscoverySessionRequest"]["action"]
export type DiscoveryPauseReason = components["schemas"]["DiscoverySessionRequest"]["reason"]

/** GET /api/opportunities/discovery/status — живой статус сессии одной площадки. */
export function fetchDiscoveryStatus(platform: DiscoveryPlatform) {
  const params = new URLSearchParams({ platform })
  return api.get<DiscoveryStatus>(`/api/opportunities/discovery/status?${params.toString()}`)
}

/** POST /api/opportunities/discovery/session — старт/пауза/возобновление/стоп. */
export function postDiscoverySession(
  platform: DiscoveryPlatform,
  action: DiscoverySessionAction,
  reason: DiscoveryPauseReason = "user",
) {
  const params = new URLSearchParams({ platform })
  return api.post<DiscoveryStatus>(`/api/opportunities/discovery/session?${params.toString()}`, {
    action,
    reason,
  })
}

/** POST /api/opportunities/discovery/remove-event — кнопка «Удалить» на сломанной
 * (parse_error) строке лога «Просмотра», убирает одну вакансию из списка. */
export function removeDiscoveryEvent(platform: DiscoveryPlatform, vacancyId: string) {
  const params = new URLSearchParams({ platform })
  return api.post<DiscoveryStatus>(
    `/api/opportunities/discovery/remove-event?${params.toString()}`,
    { vacancy_id: vacancyId },
  )
}
