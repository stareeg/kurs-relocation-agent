/**
 * Чат вкладки «Офферы»: GET/DELETE /api/offers/chat — персист на бэкенде.
 * Стрим переиспользует общий `streamChat({ offers: true })` из `@/api/chat`.
 */
import { api } from "@/api/client"
import type { AttachmentOut } from "@/api/attachments"

export type OffersChatMessage = {
  id: number
  role: "user" | "assistant"
  content: string
  reply_to_message_id?: number | null
  attachments?: AttachmentOut[]
  created_at?: string | null
}
export type OffersChatHistory = { items: OffersChatMessage[] }

export function fetchOffersChat() {
  return api.get<OffersChatHistory>("/api/offers/chat")
}

export function clearOffersChat() {
  return api.del<{ removed: number }>("/api/offers/chat")
}

export function deleteOffersChatMessage(messageId: number) {
  return api.del<{ deleted: boolean }>(`/api/offers/chat/messages/${messageId}`)
}
