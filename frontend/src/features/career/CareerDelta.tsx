import { useState } from "react"
import { ChevronRight } from "lucide-react"
import { cn } from "@/lib/utils"
import { useCareerDelta } from "./use-career"

function pct(value: number | null | undefined): string | null {
  if (value == null) return null
  return `${Math.round(value * 100)}%`
}

/**
 * «Что изменилось» (Э9.5): детерминированное сравнение «было → стало» за 30 дней, ни одного
 * слова оценки — только числа. Свёрнуто по умолчанию. Блок целиком отсутствует, если истории
 * меньше двух точек (`useCareerDelta` вернёт `null`) — честная пустота, не нули.
 */
export function CareerDelta() {
  const { data: delta } = useCareerDelta()
  const [open, setOpen] = useState(false)

  if (!delta) return null

  const rows: string[] = []
  if (delta.resume_score_was != null && delta.resume_score_now != null) {
    rows.push(`Балл резюме: ${delta.resume_score_was} → ${delta.resume_score_now}`)
  }
  if (delta.active_applications_was != null && delta.active_applications_now != null) {
    rows.push(
      `Активные отклики: ${delta.active_applications_was} → ${delta.active_applications_now}`,
    )
  }
  const wasRate = pct(delta.response_rate_was)
  const nowRate = pct(delta.response_rate_now)
  if (wasRate != null && nowRate != null) {
    rows.push(`Конверсия отклик → скрининг: ${wasRate} → ${nowRate}`)
  }
  const newTotal = delta.new_facts_count + delta.new_milestones_count
  if (newTotal > 0) {
    rows.push(`Новых фактов и вех за ${delta.window_days} дней: ${newTotal}`)
  }

  if (!rows.length) return null

  return (
    <div className="rounded-xl border bg-white">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-1.5 p-3 text-left text-sm font-medium text-slate-800"
      >
        <ChevronRight
          className={cn("size-3.5 shrink-0 transition-transform", open && "rotate-90")}
          strokeWidth={2}
        />
        Что изменилось за {delta.window_days} дней
      </button>
      {open && (
        <ul className="space-y-1 px-3 pb-3 pl-9 text-sm text-slate-600">
          {rows.map((row) => (
            <li key={row}>{row}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
