import { useState } from "react"
import { Pencil, Plus, Trash2 } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import type { AgentSessions } from "./use-agent-sessions"

// Список серверных диалогов агента (A-3). Заголовок сервер ставит по первой реплике,
// карандаш переименовывает (PATCH), корзина удаляет с подтверждением в строке (реплики
// удаляются, запуски остаются в журнале). На узком экране тот же список живёт в шторке.

function fmtDate(iso: string | null): string {
  if (!iso) return ""
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ""
  const p = (n: number) => String(n).padStart(2, "0")
  const now = new Date()
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()
  return sameDay ? `${p(d.getHours())}:${p(d.getMinutes())}` : `${p(d.getDate())}.${p(d.getMonth() + 1)}`
}

function RenameInput({
  initial,
  onDone,
}: {
  initial: string
  onDone: (title: string | null) => void
}) {
  const [value, setValue] = useState(initial)
  return (
    <input
      autoFocus
      value={value}
      maxLength={120}
      aria-label="Название диалога"
      className="min-w-0 flex-1 rounded border border-border bg-card px-1.5 py-0.5 text-sm text-foreground outline-none focus:border-slate-400"
      onChange={(e) => setValue(e.target.value)}
      onFocus={(e) => e.target.select()}
      onBlur={() => onDone(value)}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault()
          onDone(value)
        }
        if (e.key === "Escape") {
          e.preventDefault()
          onDone(null)
        }
      }}
    />
  )
}

export function AgentChatSessions({
  sessions,
  activeId,
  onSelect,
  onCreate,
  onDelete,
  className,
}: {
  sessions: AgentSessions
  activeId: number | null
  onSelect: (id: number) => void
  onCreate: () => void
  onDelete: (id: number) => void
  className?: string
}) {
  const [confirmId, setConfirmId] = useState<number | null>(null)
  const [editId, setEditId] = useState<number | null>(null)

  function finishRename(id: number, current: string, title: string | null) {
    setEditId(null)
    if (title == null || !title.trim() || title.trim() === current) return
    void sessions.rename(id, title).then((ok) => {
      if (!ok) toast.error("Не удалось переименовать диалог")
    })
  }

  return (
    <aside
      className={cn(
        "w-64 shrink-0 flex-col border-r border-border bg-card",
        className ?? "hidden md:flex",
      )}
    >
      <div className="p-3">
        <Button variant="outline" size="sm" className="w-full justify-start gap-2" onClick={onCreate}>
          <Plus className="size-4" strokeWidth={2} />
          Новый диалог
        </Button>
      </div>
      <div className="px-4 pb-1 text-xs font-medium uppercase tracking-wider text-muted-foreground">
        Диалоги
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {sessions.sessions.length === 0 ? (
          <p className="px-2 py-1 text-sm text-muted-foreground">
            {sessions.loading ? "Загрузка…" : "Пока пусто"}
          </p>
        ) : (
          sessions.sessions.map((s) => (
            <div
              key={s.id}
              className={cn(
                "group flex items-center gap-2 rounded-lg px-2 py-2 text-sm",
                s.id === activeId
                  ? "bg-slate-100 font-medium text-foreground"
                  : "text-muted-foreground hover:bg-slate-50 hover:text-foreground",
              )}
            >
              {confirmId === s.id ? (
                <div className="flex min-w-0 flex-1 items-center justify-between gap-2">
                  <span className="truncate text-foreground">Удалить?</span>
                  <span className="flex shrink-0 items-center gap-2">
                    <button
                      type="button"
                      className="text-xs font-medium text-status-bad-fg"
                      onClick={() => {
                        setConfirmId(null)
                        onDelete(s.id)
                      }}
                    >
                      Да
                    </button>
                    <button
                      type="button"
                      className="text-xs text-muted-foreground"
                      onClick={() => setConfirmId(null)}
                    >
                      Нет
                    </button>
                  </span>
                </div>
              ) : editId === s.id ? (
                <RenameInput initial={s.title} onDone={(title) => finishRename(s.id, s.title, title)} />
              ) : (
                <>
                  <button
                    type="button"
                    className="min-w-0 flex-1 truncate text-left"
                    title={s.title}
                    onClick={() => onSelect(s.id)}
                    onDoubleClick={() => setEditId(s.id)}
                  >
                    {s.title}
                  </button>
                  <span className="shrink-0 text-xs font-normal text-muted-foreground tabular-nums group-hover:hidden">
                    {fmtDate(s.updated_at ?? s.created_at)}
                  </span>
                  <span className="hidden shrink-0 items-center gap-1.5 group-hover:flex">
                    <button
                      type="button"
                      aria-label="Переименовать диалог"
                      className="text-muted-foreground hover:text-foreground"
                      onClick={() => setEditId(s.id)}
                    >
                      <Pencil className="size-3.5" strokeWidth={2} />
                    </button>
                    <button
                      type="button"
                      aria-label="Удалить диалог"
                      className="text-muted-foreground hover:text-status-bad-fg"
                      onClick={() => setConfirmId(s.id)}
                    >
                      <Trash2 className="size-3.5" strokeWidth={2} />
                    </button>
                  </span>
                </>
              )}
            </div>
          ))
        )}
      </div>
    </aside>
  )
}
