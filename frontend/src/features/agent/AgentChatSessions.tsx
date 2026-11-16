import { useState } from "react"
import { MessageSquarePlus, Trash2 } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import type { AgentSessions } from "./use-agent-sessions"

// Список серверных диалогов агента (A-3): слева, как в COWORK. Создание — кнопкой;
// удаление — корзиной (сессия с репликами удаляется, запуски остаются в журнале).
// Переименование придёт с U-1 (контракт PATCH уже есть).

export function AgentChatSessions({
  sessions,
  activeId,
  onSelect,
  onCreate,
  onDelete,
}: {
  sessions: AgentSessions
  activeId: number | null
  onSelect: (id: number) => void
  onCreate: () => void
  onDelete: (id: number) => void
}) {
  const [confirmId, setConfirmId] = useState<number | null>(null)

  return (
    <aside className="flex w-56 shrink-0 flex-col border-r bg-white">
      <div className="flex items-center justify-between px-3 py-2.5">
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">
          Диалоги
        </span>
        <Button
          size="icon"
          variant="ghost"
          className="size-7"
          aria-label="Новый диалог"
          onClick={onCreate}
        >
          <MessageSquarePlus className="size-4" strokeWidth={2} />
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-1.5 pb-2">
        {sessions.sessions.length === 0 ? (
          <p className="px-2 py-1 text-xs text-slate-400">
            {sessions.loading ? "Загрузка…" : "Пока нет диалогов"}
          </p>
        ) : (
          sessions.sessions.map((s) => (
            <div
              key={s.id}
              className={cn(
                "group flex items-center gap-1 rounded-lg px-2 py-1.5 text-sm",
                s.id === activeId ? "bg-violet-100 text-slate-900" : "text-slate-600 hover:bg-slate-100",
              )}
            >
              <button
                type="button"
                className="min-w-0 flex-1 truncate text-left"
                title={s.title}
                onClick={() => onSelect(s.id)}
              >
                {s.title}
              </button>
              {confirmId === s.id ? (
                <div className="flex shrink-0 items-center gap-1">
                  <button
                    type="button"
                    className="text-[11px] font-semibold text-rose-600"
                    onClick={() => {
                      setConfirmId(null)
                      onDelete(s.id)
                    }}
                  >
                    Удалить
                  </button>
                  <button
                    type="button"
                    className="text-[11px] text-slate-400"
                    onClick={() => setConfirmId(null)}
                  >
                    Нет
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  aria-label="Удалить диалог"
                  className="shrink-0 text-slate-300 opacity-0 transition-opacity group-hover:opacity-100 hover:text-rose-500"
                  onClick={() => {
                    if (s.id === activeId) {
                      setConfirmId(s.id)
                    } else {
                      onDelete(s.id)
                      void toast.success("Диалог удалён")
                    }
                  }}
                >
                  <Trash2 className="size-3.5" strokeWidth={2} />
                </button>
              )}
            </div>
          ))
        )}
      </div>
    </aside>
  )
}
