import { useState } from "react"
import { Library, Loader2, Send } from "lucide-react"
import type { Note } from "@/api/notes"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { useAddNoteMessage, useCreateNote } from "@/features/chat/use-notes"

// UX7: «Новый контекст» больше не создаёт пустую заметку по клику в сайдбаре — открывает пустой
// композер (как «Новая вакансия»), запись появляется только когда отправлено первое сообщение.
export function NewContextConversationPane({ onCreated }: { onCreated: (note: Note) => void }) {
  const [title, setTitle] = useState("")
  const [text, setText] = useState("")
  const createNote = useCreateNote()
  const addMessage = useAddNoteMessage()
  const busy = createNote.isPending || addMessage.isPending

  async function send() {
    const body = text.trim()
    if (!body || busy) return
    try {
      const note = await createNote.mutateAsync({
        title: title.trim(),
        body: "",
        tags: [],
        use_in_rag: true,
      })
      if (note.id != null) {
        await addMessage.mutateAsync({ noteId: note.id, body })
      }
      setText("")
      onCreated(note)
    } catch {
      /* тосты в хуках */
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-slate-50">
      <header className="flex shrink-0 items-center gap-2 border-b bg-background px-4 py-2.5">
        <Library className="size-4 shrink-0 text-slate-400" strokeWidth={2} />
        <Input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Название контекста"
          className="h-8 max-w-md border-0 bg-transparent px-0 text-sm font-semibold shadow-none focus-visible:ring-0"
          disabled={busy}
        />
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        <p className="text-sm text-slate-400">Напишите первое сообщение ниже.</p>
      </div>

      <div className="flex shrink-0 items-end gap-2 border-t bg-white p-3">
        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault()
              void send()
            }
          }}
          placeholder="Написать в контекст…"
          disabled={busy}
          autoFocus
        />
        <Button
          size="icon"
          variant="outline"
          disabled={!text.trim() || busy}
          onClick={() => void send()}
        >
          {busy ? (
            <Loader2 className="size-4 animate-spin" strokeWidth={2} />
          ) : (
            <Send className="size-4" strokeWidth={2} />
          )}
        </Button>
      </div>
    </div>
  )
}
