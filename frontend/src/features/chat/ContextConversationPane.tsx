import { memo, useCallback, useEffect, useRef, useState } from "react"
import { toast } from "sonner"
import { Copy, Library, Loader2, Send, Trash2 } from "lucide-react"
import type { Note, NoteMessage } from "@/api/notes"
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuTrigger,
} from "@/components/ui/context-menu"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"
import {
  useAddNoteMessage,
  useDeleteNoteMessage,
  useNoteMessages,
  useUpdateNote,
  useUpdateNoteMessage,
} from "@/features/chat/use-notes"

// UX7: контекст выглядит как диалог по вакансии — лента реплик владельца (без ответа ассистента),
// клик по сообщению редактирует его на месте, правый клик даёт копировать/удалить. `notes.body`
// (используется в RAG-подмешивании и полнотекстовом поиске) — репозиторий сам держит его в
// синхроне с лентой сообщений, фронт про это не думает.

function fmtMsgTime(iso?: string | null): string {
  if (!iso) return ""
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ""
  const p = (n: number) => String(n).padStart(2, "0")
  return `${p(d.getDate())}.${p(d.getMonth() + 1)} ${p(d.getHours())}:${p(d.getMinutes())}`
}

function copyMessage(body: string) {
  navigator.clipboard.writeText(body).then(
    () => toast.success("Сообщение скопировано"),
    () => toast.error("Не удалось скопировать"),
  )
}

// JS-44: колбэки — стабильные ссылки на весь список (принимают id сообщения сами), а не
// замыкания на каждой итерации .map() — иначе memo ниже бесполезен: новый набор пропов на
// каждый рендер родителя (например, на каждую букву в поле ввода) всё равно перерисовывает
// каждый пузырь, несмотря на memo.
const ContextMessageBubble = memo(function ContextMessageBubble({
  message,
  editing,
  saving,
  onStartEdit,
  onSave,
  onCancelEdit,
  onCopy,
  onDelete,
}: {
  message: NoteMessage
  editing: boolean
  saving?: boolean
  onStartEdit: (id: number | null) => void
  onSave: (id: number | null, body: string) => void
  onCancelEdit: () => void
  onCopy: (body: string) => void
  onDelete: (id: number | null) => void
}) {
  const [draft, setDraft] = useState(message.body)
  const [wasEditing, setWasEditing] = useState(editing)
  if (editing !== wasEditing) {
    setWasEditing(editing)
    if (editing) setDraft(message.body)
  }

  function commit() {
    const v = draft.trim()
    if (!v || v === message.body) {
      onCancelEdit()
      return
    }
    onSave(message.id ?? null, v)
  }

  const row = (
    <div className="flex justify-end">
      <div
        className={cn(
          "rounded-2xl rounded-br-sm bg-sky-100 px-3 py-1.5",
          editing ? "w-full max-w-[68%]" : "max-w-[68%]",
        )}
      >
        {editing ? (
          <div className="space-y-1.5">
            <Textarea
              autoFocus
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault()
                  commit()
                }
                if (e.key === "Escape") onCancelEdit()
              }}
              disabled={saving}
              className="bg-white text-base"
              maxHeight={288}
            />
            <div className="flex justify-end gap-1">
              <Button size="sm" variant="ghost" onClick={onCancelEdit} disabled={saving}>
                Отмена
              </Button>
              <Button size="sm" onClick={commit} disabled={saving || !draft.trim()}>
                {saving ? (
                  <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />
                ) : (
                  "Сохранить"
                )}
              </Button>
            </div>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => onStartEdit(message.id ?? null)}
            title="Нажмите, чтобы редактировать"
            className="block w-full text-left"
          >
            <p className="whitespace-pre-wrap break-words text-base leading-snug text-slate-900">
              {message.body}
            </p>
            <span className="mt-0.5 block text-right text-xs font-semibold tabular-nums text-slate-400">
              {fmtMsgTime(message.created_at)}
            </span>
          </button>
        )}
      </div>
    </div>
  )

  if (editing) return row

  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>{row}</ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuItem onSelect={() => onCopy(message.body)}>
          <Copy />
          Копировать
        </ContextMenuItem>
        <ContextMenuItem variant="destructive" onSelect={() => onDelete(message.id ?? null)}>
          <Trash2 />
          Удалить
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  )
})

export function ContextConversationPane({ note }: { note: Note }) {
  const noteId = note.id ?? null
  const updateNote = useUpdateNote()
  const messagesQ = useNoteMessages(noteId)
  const addMessage = useAddNoteMessage()
  const updateMessage = useUpdateNoteMessage()
  const deleteMessage = useDeleteNoteMessage()

  const [title, setTitle] = useState(note.title.trim() || "Новый контекст")
  const [seenKey, setSeenKey] = useState(`${note.id}:${note.title}`)
  const noteKey = `${note.id}:${note.title}`
  if (noteKey !== seenKey) {
    setSeenKey(noteKey)
    setTitle(note.title.trim() || "Новый контекст")
  }

  const [editingId, setEditingId] = useState<number | null>(null)
  const [pendingDeleteId, setPendingDeleteId] = useState<number | null>(null)
  const [text, setText] = useState("")

  function saveTitle() {
    const v = title.trim() || "Новый контекст"
    if (noteId == null || v === (note.title.trim() || "Новый контекст")) return
    updateNote.mutate({ id: noteId, title: v })
  }

  function confirmDelete() {
    if (noteId == null || pendingDeleteId == null) return
    deleteMessage.mutate(
      { noteId, messageId: pendingDeleteId },
      { onSuccess: () => setPendingDeleteId(null) },
    )
  }

  function send() {
    const v = text.trim()
    if (!v || noteId == null || addMessage.isPending) return
    addMessage.mutate({ noteId, body: v }, { onSuccess: () => setText("") })
  }

  // JS-44: одна ссылка на весь список сообщений (не пересоздаётся при наборе текста в поле
  // ввода ниже) — см. комментарий у ContextMessageBubble.
  const onStartEdit = useCallback((id: number | null) => setEditingId(id), [])
  const onCancelEdit = useCallback(() => setEditingId(null), [])
  const onSaveMessage = useCallback(
    (id: number | null, body: string) => {
      if (noteId == null || id == null) return
      updateMessage.mutate({ noteId, messageId: id, body }, { onSuccess: () => setEditingId(null) })
    },
    [noteId, updateMessage],
  )
  const onDeleteMessage = useCallback((id: number | null) => setPendingDeleteId(id), [])

  const messages = messagesQ.data ?? []
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const prevLen = useRef(0)
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const grew = messages.length > prevLen.current
    prevLen.current = messages.length
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 140
    if (grew || nearBottom) el.scrollTo({ top: el.scrollHeight })
  }, [messages.length])

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-slate-50">
      <header className="flex shrink-0 items-center gap-2 border-b bg-background px-4 py-2.5">
        <Library className="size-4 shrink-0 text-slate-400" strokeWidth={2} />
        <Input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onBlur={saveTitle}
          onKeyDown={(e) => {
            if (e.key === "Enter") e.currentTarget.blur()
          }}
          className="h-8 max-w-md border-0 bg-transparent px-0 text-sm font-semibold shadow-none focus-visible:ring-0"
          placeholder="Название контекста"
        />
      </header>

      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto p-4">
        {messagesQ.isLoading ? (
          <p className="text-sm text-slate-400">Загрузка…</p>
        ) : messages.length === 0 ? (
          <p className="text-sm text-slate-400">Пока пусто — напишите первое сообщение ниже.</p>
        ) : (
          <div className="space-y-1.5">
            {messages.map((m) => (
              <ContextMessageBubble
                key={m.id}
                message={m}
                editing={editingId === m.id}
                saving={updateMessage.isPending && editingId === m.id}
                onStartEdit={onStartEdit}
                onCancelEdit={onCancelEdit}
                onSave={onSaveMessage}
                onCopy={copyMessage}
                onDelete={onDeleteMessage}
              />
            ))}
          </div>
        )}
      </div>

      <div className="shrink-0 space-y-2 border-t bg-white p-3">
        <div className="flex justify-end">
          <Button
            size="default"
            className="h-9 gap-1.5 px-3"
            disabled={!text.trim() || addMessage.isPending}
            onClick={send}
          >
            {addMessage.isPending ? (
              <Loader2 className="size-4 animate-spin" strokeWidth={2} />
            ) : (
              <Send className="size-4" strokeWidth={2} />
            )}
            Отправить
          </Button>
        </div>
        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault()
              send()
            }
          }}
          placeholder="Написать в контекст…"
          disabled={addMessage.isPending}
        />
      </div>

      <ConfirmDialog
        open={pendingDeleteId != null}
        onOpenChange={(open) => {
          if (!open) setPendingDeleteId(null)
        }}
        title="Удалить сообщение?"
        description="Действие необратимо."
        onConfirm={confirmDelete}
      />
    </div>
  )
}
