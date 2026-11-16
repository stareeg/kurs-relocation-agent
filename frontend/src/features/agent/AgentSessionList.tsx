import { useState } from "react"
import { Pencil, Plus, Trash2 } from "lucide-react"
import { toast } from "sonner"
import { cn } from "@/lib/utils"
import type { AgentSessions } from "./use-agent-sessions"

// Диалоги агента в основном меню под пунктом «Агент» (U-5) и в шторке на узком экране.
// Заголовок сервер ставит по первой реплике; карандаш или двойной клик переименовывают
// (PATCH), корзина удаляет с подтверждением в строке (реплики удаляются, запуски остаются
// в журнале). Стиль строк — как у пунктов меню (`navItemClass` в AppShell).

const ROW = "group flex h-8 items-center gap-1.5 rounded-lg px-2 text-sm"
const ROW_IDLE = "font-normal text-slate-600 hover:bg-slate-100"
const ROW_ACTIVE = "bg-slate-200/60 font-medium text-slate-900"

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

export function AgentSessionList({
  sessions,
  activeId,
  newActive = false,
  limit,
  onSelect,
  onCreate,
  onDelete,
  className,
}: {
  sessions: AgentSessions
  /** Подсвеченный диалог; null — ни один (например, открыт другой раздел). */
  activeId: number | null
  /** Подсветить «Новый диалог»: экран агента открыт без выбранного диалога. */
  newActive?: boolean
  /** Сколько диалогов показать до «Ещё N». */
  limit?: number
  onSelect: (id: number) => void
  onCreate: () => void
  onDelete: (id: number) => void
  className?: string
}) {
  const [confirmId, setConfirmId] = useState<number | null>(null)
  const [editId, setEditId] = useState<number | null>(null)
  const [showAll, setShowAll] = useState(false)

  function finishRename(id: number, current: string, title: string | null) {
    setEditId(null)
    if (title == null || !title.trim() || title.trim() === current) return
    void sessions.rename(id, title).then((ok) => {
      if (!ok) toast.error("Не удалось переименовать диалог")
    })
  }

  const all = sessions.sessions
  const cut = limit != null && !showAll && all.length > limit
  const visible = cut ? all.slice(0, limit) : all
  // Выбранный диалог за пределами «первых N» всё равно виден.
  const pinned = cut ? all.find((s) => s.id === activeId && !visible.includes(s)) : undefined
  const rows = pinned ? [...visible, pinned] : visible

  return (
    <div className={cn("space-y-0.5", className)}>
      <button
        type="button"
        className={cn(ROW, "w-full text-left", newActive ? ROW_ACTIVE : ROW_IDLE)}
        onClick={onCreate}
      >
        <Plus className="size-3.5 shrink-0" strokeWidth={2} />
        <span className="min-w-0 flex-1 truncate">Новый диалог</span>
      </button>
      {all.length === 0 ? (
        <p className="px-2 py-1 text-xs text-muted-foreground">
          {sessions.loading ? "Загрузка…" : "Диалогов пока нет"}
        </p>
      ) : (
        rows.map((s) => (
          <div key={s.id} className={cn(ROW, s.id === activeId ? ROW_ACTIVE : ROW_IDLE)}>
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
                  aria-current={s.id === activeId ? "page" : undefined}
                  onClick={() => onSelect(s.id)}
                  onDoubleClick={() => setEditId(s.id)}
                >
                  {s.title}
                </button>
                <span className="hidden shrink-0 items-center gap-1.5 group-focus-within:flex group-hover:flex">
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
      {limit != null && all.length > limit ? (
        <button
          type="button"
          className="flex h-7 w-full items-center rounded-lg px-2 text-left text-xs text-muted-foreground hover:bg-slate-100 hover:text-foreground"
          onClick={() => setShowAll((v) => !v)}
        >
          {showAll ? "Свернуть" : `Ещё ${all.length - limit}`}
        </button>
      ) : null}
    </div>
  )
}
