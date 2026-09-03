import type { components } from "@/api/schema"
import { api } from "@/api/client"

export type TelegramStatus = components["schemas"]["TelegramStatusResponse"]
export type TelegramPushRequest = components["schemas"]["TelegramPushRequest"]
export type TelegramPushResponse = components["schemas"]["TelegramPushResponse"]
export type TelegramPushKind = TelegramPushRequest["kind"]

/** GET /api/telegram/status — бот настроен? владелец привязан? */
export function fetchTelegramStatus() {
  return api.get<TelegramStatus>("/api/telegram/status")
}

/** POST /api/telegram/push — очередь «отправить себе» (TB-6.1/6.3). */
export function pushToTelegram(body: TelegramPushRequest) {
  return api.post<TelegramPushResponse>("/api/telegram/push", body)
}
