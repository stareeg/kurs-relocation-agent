import { cn } from "@/lib/utils"

// Подсказки следующего сообщения (JS-20): 2-3 коротких варианта продолжения диалога под последним
// ответом ассистента — клик отправляет текст как обычное сообщение владельца. Убирает рутинный
// набор «уточни подробнее» / «дай пример попроще».
export function FollowUpChips({
  items,
  onPick,
  disabled,
}: {
  items: string[]
  onPick: (text: string) => void
  disabled?: boolean
}) {
  if (!items.length) return null
  return (
    <div className="flex flex-wrap gap-1.5 pt-1">
      {items.map((t, i) => (
        <button
          key={i}
          type="button"
          disabled={disabled}
          onClick={() => onPick(t)}
          className={cn(
            "rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-600",
            "transition-colors hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900",
            "disabled:opacity-50",
          )}
        >
          {t}
        </button>
      ))}
    </div>
  )
}
