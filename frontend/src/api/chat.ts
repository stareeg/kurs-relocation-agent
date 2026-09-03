import { streamSse, type SseEvent } from "@/api/sse"

export type { SseEvent }

export type ChatStreamBody = {
  message: string
  history?: { role: "user" | "assistant"; text: string }[]
  vacancy?: Record<string, unknown>
  tier?: string
  note_ids?: number[]
  resume_gap?: boolean
  hr_draft?: boolean
  /** Чат по ситуации на рынке (вкладка «Рынок», внизу под графиками) — карьерный стратег,
   *  персист в market_chat_messages. Заменяет бывший блок «Что сделать» (next-steps). */
  market?: boolean
  /** Чат вкладки «Офферы» — советник по условиям/торгу, персист в offers_chat_messages. */
  offers?: boolean
  reply_to_message_id?: number
  /** Картинки текущей реплики (Э2-5) — id из POST /api/attachments. */
  attachment_ids?: number[]
}

/** POST /api/chat/stream — единый SSE (A-14). */
export async function streamChat(
  body: ChatStreamBody,
  onEvent: (e: SseEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  await streamSse("/api/chat/stream", {
    body,
    signal,
    timeoutMs: 0, // отмена только через signal (долгий стрим токенов)
    rumInteraction: "chat",
    onEvent,
  })
}
