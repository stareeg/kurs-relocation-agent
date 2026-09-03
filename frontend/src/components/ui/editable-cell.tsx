import { useRef, useState } from "react"
import { cn } from "@/lib/utils"
import { formatDate } from "@/lib/format"

/** Инлайн-ячейка: клик → правка, blur/Enter → коммит, Escape → отмена. Коммит только при изменении. */
export function EditableCell({
  value,
  type,
  highlight,
  onCommit,
}: {
  value: string | number | null
  type: "text" | "number" | "date"
  highlight?: boolean
  onCommit: (next: string | number | null) => void
}) {
  const [editing, setEditing] = useState(false)
  const initial = useRef("")

  function display() {
    if (value == null || value === "") return "—"
    if (type === "number") return Number(value).toLocaleString("ru-RU")
    if (type === "date") return formatDate(String(value)) || "—"
    return String(value)
  }

  function toDraft(): string {
    if (value == null) return ""
    if (type === "date") return String(value).slice(0, 10)
    return String(value)
  }

  function parse(draft: string): string | number | null {
    const t = draft.trim()
    if (type === "number")
      return t === "" ? null : Number.isFinite(Number(t)) ? Math.round(Number(t)) : null
    if (type === "date") return t === "" ? null : t
    return draft
  }

  function commit(draft: string) {
    setEditing(false)
    if (draft !== initial.current) onCommit(parse(draft))
  }

  if (!editing) {
    const empty = value == null || value === ""
    return (
      <button
        type="button"
        onClick={() => {
          initial.current = toDraft()
          setEditing(true)
        }}
        className={cn(
          "min-h-7 w-full rounded-md px-1.5 py-1 text-left text-sm transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          type === "number" && "tabular-nums",
          highlight && "bg-emerald-50 font-medium text-emerald-800 hover:bg-emerald-100",
          empty && !highlight && "text-muted-foreground",
        )}
      >
        {display()}
      </button>
    )
  }

  return (
    <input
      autoFocus
      type={type === "date" ? "date" : type === "number" ? "number" : "text"}
      defaultValue={toDraft()}
      onBlur={(e) => commit(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === "Enter") e.currentTarget.blur()
        if (e.key === "Escape") {
          e.currentTarget.value = initial.current
          e.currentTarget.blur()
        }
      }}
      className="h-7 w-full rounded-md border border-input bg-card px-1.5 text-sm tabular-nums focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    />
  )
}
