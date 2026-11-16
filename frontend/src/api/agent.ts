/**
 * API агента (A-3): чат-сессии (серверный персист главного чата), запуски фоновой
 * задачей, SSE-поток событий запуска и подтверждение карточки. Типы локальные —
 * автоген `schema.d.ts` догонит после `npm run gen-api` в следующей сборке.
 */
import { api } from "@/api/client"
import { streamSse, type SseEvent } from "@/api/sse"

export type AgentRunStatus =
  | "queued"
  | "running"
  | "waiting_approval"
  | "done"
  | "failed"
  | "cancelled"

export type AgentChatSession = {
  id: number
  title: string
  created_at: string | null
  updated_at: string | null
}

export type AgentChatMessage = {
  id: number
  session_id: number
  role: "user" | "assistant"
  content: string
  created_at: string | null
}

export type AgentRun = {
  id: number
  goal: string
  status: AgentRunStatus
  session_id: number | null
  stop_reason: string | null
  answer: string | null
  error: string | null
  created_at: string | null
  updated_at: string | null
}

export type AgentEvent = {
  id: number
  type: string
  payload: Record<string, unknown>
  node: string | null
  duration_ms: number | null
  created_at: string | null
}

export type AgentActionCard = {
  action?: string
  params?: Record<string, unknown>
  step_id?: string
}

// ---------------------------------------------------------------- чат-сессии

export async function listAgentChats(): Promise<AgentChatSession[]> {
  const res = await api.get<{ items: AgentChatSession[] }>("/api/agent/chats")
  return res.items ?? []
}

export function createAgentChat(title?: string): Promise<AgentChatSession> {
  return api.post<AgentChatSession>("/api/agent/chats", title ? { title } : {})
}

export function renameAgentChat(id: number, title: string): Promise<AgentChatSession> {
  return api.patch<AgentChatSession>(`/api/agent/chats/${id}`, { title })
}

export function deleteAgentChat(id: number): Promise<unknown> {
  return api.del(`/api/agent/chats/${id}`)
}

export async function listAgentChatMessages(sessionId: number): Promise<AgentChatMessage[]> {
  const res = await api.get<{ items: AgentChatMessage[] }>(
    `/api/agent/chats/${sessionId}/messages`,
  )
  return res.items ?? []
}

export function appendAgentChatMessage(
  sessionId: number,
  role: "user" | "assistant",
  content: string,
): Promise<AgentChatMessage> {
  return api.post<AgentChatMessage>(`/api/agent/chats/${sessionId}/messages`, { role, content })
}

// ---------------------------------------------------------------- запуски

export function startAgentRun(goal: string, sessionId?: number | null): Promise<AgentRun> {
  return api.post<AgentRun>("/api/agent/runs", { goal, session_id: sessionId ?? null })
}

export function getAgentRun(runId: number): Promise<AgentRun> {
  return api.get<AgentRun>(`/api/agent/runs/${runId}`)
}

export async function listAgentRuns(sessionId: number | null): Promise<AgentRun[]> {
  const query = sessionId == null ? "" : `?session_id=${sessionId}`
  const res = await api.get<{ items: AgentRun[] }>(`/api/agent/runs${query}`)
  return res.items ?? []
}

export async function replayAgentRunEvents(runId: number): Promise<AgentEvent[]> {
  const res = await api.get<{ items: AgentEvent[] }>(`/api/agent/runs/${runId}/events/replay`)
  return res.items ?? []
}

/** Правка карточки перед «да» (U-1): текст для работодателя, 40–600 знаков, как у инструмента. */
export type AgentApprovalEdits = { cover_note?: string }

export const COVER_NOTE_MIN = 40
export const COVER_NOTE_MAX = 600

export function approveAgentRun(
  runId: number,
  approved: boolean,
  edits?: AgentApprovalEdits,
): Promise<AgentRun> {
  return api.post<AgentRun>(`/api/agent/runs/${runId}/approval`, {
    approved,
    ...(edits ? { edits } : {}),
  })
}

// ---------------------------------------------------------------- настройки агента

/** Режим подтверждения действий (OQ-8): спрашивать каждый раз или подтверждать автоматически. */
export type AgentConfirmMode = "ask" | "auto"

export type AgentSettings = { confirm_mode: AgentConfirmMode }

export function getAgentSettings(): Promise<AgentSettings> {
  return api.get<AgentSettings>("/api/agent/settings")
}

export function putAgentSettings(settings: AgentSettings): Promise<AgentSettings> {
  return api.put<AgentSettings>("/api/agent/settings", settings)
}

/**
 * SSE-поток событий запуска (GET /api/agent/runs/{id}/events): догон с
 * Last-Event-ID, затем живое следование; терминал (done/error) закрывает поток.
 */
export async function streamAgentRunEvents(
  runId: number,
  lastEventId: number | null,
  onEvent: (e: SseEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  await streamSse(`/api/agent/runs/${runId}/events`, {
    method: "GET",
    signal,
    timeoutMs: 0, // долгий поток: пауза на подтверждении не таймаутит
    lastEventId,
    onEvent,
  })
}
