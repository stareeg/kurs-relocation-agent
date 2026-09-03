/**
 * Чат по ситуации на рынке (F-04): GET/DELETE /api/market/chat — персист на бэкенде.
 * Стрим переиспользует общий `streamChat({ market: true })` из `@/api/chat`.
 */
import type { components } from "@/api/schema"
import { api } from "@/api/client"

export type MarketChatMessage = components["schemas"]["MarketChatMessageOut"]
export type MarketChatHistory = components["schemas"]["MarketChatHistory"]

// GET /api/market/chat — история чата по ситуации на рынке (хронологически; пусто при нет PG).
export function fetchMarketChat() {
  return api.get<MarketChatHistory>("/api/market/chat")
}

// DELETE /api/market/chat — очистить чат по ситуации на рынке. Возвращает число удалённых строк.
export function clearMarketChat() {
  return api.del<{ removed: number }>("/api/market/chat")
}

// DELETE /api/market/chat/messages/{id} — удалить одну реплику (выделение → Удалить, зеркало
// deleteConversationMessage чата по вакансии).
export function deleteMarketChatMessage(messageId: number) {
  return api.del<{ deleted: boolean }>(`/api/market/chat/messages/${messageId}`)
}
