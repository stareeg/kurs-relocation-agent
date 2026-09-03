import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import {
  createNote,
  createNoteMessage,
  deleteNote,
  deleteNoteMessage,
  fetchNoteMessages,
  fetchNotes,
  updateNote,
  updateNoteMessage,
  type Note,
  type NoteMessage,
} from "@/api/notes"

// Ключуем по поисковой строке — сервер делает полнотекстовый поиск (websearch-tsquery),
// пустая строка — весь список. Компонент дебаунсит ввод перед сменой q.
export function useNotes(q: string) {
  return useQuery({
    queryKey: ["notes", q],
    queryFn: () => fetchNotes(q),
    staleTime: 10_000,
  })
}

function invalidateNotes(qc: ReturnType<typeof useQueryClient>) {
  void qc.invalidateQueries({ queryKey: ["notes"] })
}

export function useCreateNote() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { title: string; body: string; tags: string[]; use_in_rag: boolean }) =>
      createNote(body),
    onSuccess: () => {
      invalidateNotes(qc)
      toast.success("Контекст добавлен")
    },
    onError: () => toast.error("Не удалось добавить контекст"),
  })
}

export function useUpdateNote() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      ...body
    }: {
      id: number
      title?: string
      body?: string
      tags?: string[]
      use_in_rag?: boolean
    }) => updateNote(id, body),
    onSuccess: (_note, vars) => {
      invalidateNotes(qc)
      // Тумблер «доступен в чатах» не должен каждый раз дёргать тост «сохранено» — тихая правка.
      if (!("use_in_rag" in vars && Object.keys(vars).length === 2)) {
        toast.success("Сохранено")
      }
    },
    onError: () => toast.error("Не удалось сохранить"),
  })
}

export function useDeleteNote() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => deleteNote(id),
    onSuccess: () => {
      invalidateNotes(qc)
      toast.success("Контекст удалён")
    },
    onError: () => toast.error("Не удалось удалить"),
  })
}

// UX7: контекст выглядит как чат — лента сообщений отдельно от списка контекстов слева.
export function useNoteMessages(noteId: number | null) {
  return useQuery({
    queryKey: ["note-messages", noteId],
    queryFn: () => fetchNoteMessages(noteId as number),
    enabled: noteId != null,
  })
}

function invalidateNoteMessages(qc: ReturnType<typeof useQueryClient>, noteId: number) {
  void qc.invalidateQueries({ queryKey: ["note-messages", noteId] })
  // Сообщение меняет notes.body (конкатенация) — список контекстов пересортируется по updated_at.
  invalidateNotes(qc)
}

export function useAddNoteMessage() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ noteId, body }: { noteId: number; body: string }) =>
      createNoteMessage(noteId, body),
    onSuccess: (_msg, vars) => invalidateNoteMessages(qc, vars.noteId),
    onError: () => toast.error("Не удалось отправить сообщение"),
  })
}

export function useUpdateNoteMessage() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      noteId,
      messageId,
      body,
    }: {
      noteId: number
      messageId: number
      body: string
    }) => updateNoteMessage(noteId, messageId, body),
    onSuccess: (_msg, vars) => invalidateNoteMessages(qc, vars.noteId),
    onError: () => toast.error("Не удалось сохранить сообщение"),
  })
}

export function useDeleteNoteMessage() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ noteId, messageId }: { noteId: number; messageId: number }) =>
      deleteNoteMessage(noteId, messageId),
    onSuccess: (_void, vars) => invalidateNoteMessages(qc, vars.noteId),
    onError: () => toast.error("Не удалось удалить сообщение"),
  })
}

export type { Note, NoteMessage }
