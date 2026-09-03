import type { components } from "@/api/schema"
import { api, type ApiCallOptions } from "@/api/client"

export type AppSettings = components["schemas"]["AppSettingsResponse"]
export type AppSettingsUpdate = components["schemas"]["AppSettingsUpdate"]
export type ScoringWeights = components["schemas"]["ScoringWeights"]
export type ScoringImportance = components["schemas"]["ScoringImportance"]
export type FixedScoringWeights = components["schemas"]["FixedScoringWeights"]
export type CompanyAdjustment = components["schemas"]["CompanyAdjustment"]
export type TelegramPrefs = components["schemas"]["TelegramPrefs"]
export type AutoApplyConfig = components["schemas"]["AutoApplyConfig"]
export type AutoApplyPlatformConfig = components["schemas"]["AutoApplyPlatformConfig"]
export type DisclosurePolicy = components["schemas"]["DisclosurePolicy"]

/** GET /api/settings — текущие параметры (секрет OpenRouter не отдаётся). */
export function fetchAppSettings(opts?: ApiCallOptions) {
  return api.get<AppSettings>("/api/settings", opts)
}

/** PATCH /api/settings — частичное обновление параметров. */
export function patchAppSettings(body: AppSettingsUpdate, opts?: ApiCallOptions) {
  return api.patch<AppSettings>("/api/settings", body, opts)
}

export type OpenRouterKeyRequestResult = components["schemas"]["OpenRouterKeyRequestResponse"]

/** POST /api/settings/openrouter-key/request — заявка администратору на ключ. */
export function requestOpenRouterKey() {
  return api.post<OpenRouterKeyRequestResult>("/api/settings/openrouter-key/request")
}
