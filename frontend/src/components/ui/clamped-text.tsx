import { useState } from "react"
import { cn } from "@/lib/utils"

/**
 * Длинный LLM-абзац/резюмешный текст клипается до N строк с «Показать полностью»/«Свернуть».
 * `threshold` — грубая эвристика по длине строки (без замера DOM): порог подбирается под
 * контейнер конкретной карточки, не универсален.
 */
export function ClampedText({
  text,
  className,
  threshold = 160,
  lines = 2,
}: {
  text: string
  className?: string
  threshold?: number
  lines?: 1 | 2 | 3
}) {
  const [expanded, setExpanded] = useState(false)
  const isLong = text.length > threshold
  const clampClass = lines === 1 ? "line-clamp-1" : lines === 3 ? "line-clamp-3" : "line-clamp-2"

  return (
    <div>
      <p className={cn("whitespace-pre-line", className, isLong && !expanded && clampClass)}>
        {text}
      </p>
      {isLong ? (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="mt-0.5 text-xs font-medium text-slate-500 hover:text-slate-700"
        >
          {expanded ? "Свернуть" : "Показать полностью"}
        </button>
      ) : null}
    </div>
  )
}
