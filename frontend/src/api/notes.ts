import type { components } from "@/api/schema"
import { api } from "@/api/client"

export type Note = components["schemas"]["Note"]
export type NoteMessage = components["schemas"]["NoteMessage"]

// GET /api/notes — список заметок; q — полнотекстовый поиск (пусто — все заметки).
export function fetchNotes(q = "") {
  const params = new URLSearchParams()
  if (q.trim()) params.set("q", q.trim())
  const qs = params.toString()
  return api.get<Note[]>(`/api/notes${qs ? `?${qs}` : ""}`)
}

// POST /api/notes — создать заметку.
export function createNote(body: {
  title: string
  body: string
  tags: string[]
  use_in_rag: boolean
}) {
  return api.post<Note>("/api/notes", body)
}

// PATCH /api/notes/{id} — правка заметки (undefined-поля не шлём — сервер их не тронет).
export function updateNote(
  id: number,
  body: { title?: string; body?: string; tags?: string[]; use_in_rag?: boolean },
) {
  return api.patch<Note>(`/api/notes/${id}`, body)
}

// DELETE /api/notes/{id} — удалить заметку.
export function deleteNote(id: number) {
  return api.del<void>(`/api/notes/${id}`)
}

// GET /api/notes/{id}/messages — лента сообщений контекста (UX7: контекст выглядит как чат).
export function fetchNoteMessages(noteId: number) {
  return api.get<NoteMessage[]>(`/api/notes/${noteId}/messages`)
}

// POST /api/notes/{id}/messages — добавить сообщение в контекст.
export function createNoteMessage(noteId: number, body: string) {
  return api.post<NoteMessage>(`/api/notes/${noteId}/messages`, { body })
}

// PATCH /api/notes/{id}/messages/{messageId} — правка сообщения (клик → редактирование).
export function updateNoteMessage(noteId: number, messageId: number, body: string) {
  return api.patch<NoteMessage>(`/api/notes/${noteId}/messages/${messageId}`, { body })
}

// DELETE /api/notes/{id}/messages/{messageId} — удалить сообщение контекста.
export function deleteNoteMessage(noteId: number, messageId: number) {
  return api.del<void>(`/api/notes/${noteId}/messages/${messageId}`)
}
