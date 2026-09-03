import { Search, X } from "lucide-react"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"

/**
 * Поиск по людям — идиома тулбара продукта (`JobsToolbar`): иконка внутри слева, крестик
 * справа, высота 11.
 *
 * Живёт в тулбаре списка, а не в строке вкладок: раньше поле появлялось и исчезало при
 * переключении раздела и раздвигало навигацию по высоте.
 */
export function AdminSearch({
  value,
  onChange,
  placeholder = "Поиск по @username, id или маске ключа",
  className,
  compact = false,
}: {
  value: string
  onChange: (next: string) => void
  placeholder?: string
  className?: string
  compact?: boolean
}) {
  return (
    <div className={cn("relative w-80 max-w-full", className)}>
      <Search
        className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400"
        strokeWidth={2}
      />
      <Input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className={cn(
          "w-full pl-10 pr-9 text-sm",
          compact ? "h-9 rounded-lg" : "h-11 rounded-xl",
        )}
      />
      {value && (
        <button
          type="button"
          onClick={() => onChange("")}
          aria-label="Очистить поиск"
          className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 transition-colors hover:text-slate-700"
        >
          <X className="size-4" strokeWidth={2} />
        </button>
      )}
    </div>
  )
}
