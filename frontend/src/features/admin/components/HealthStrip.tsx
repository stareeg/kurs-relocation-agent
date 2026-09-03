import { StatusDot } from "@/components/ui/status-chip"
import type { HealthItem } from "@/features/admin/admin-health"
import { cn } from "@/lib/utils"

/**
 * Полоса здоровья установки. Красная точка кликает в Систему — там очередь, версии, уборка.
 *
 * Здоровый факт рисуется без точки вовсе (Этап 0, §2.5): цвет в разделе означает «посмотри
 * сюда», и шесть зелёных точек рядом с одной красной ровно это значение и убивали. Пары
 * «подпись — значение» разделены вертикальной чертой — идиома метрики из «Рынка».
 */
export function HealthStrip({
  items,
  onOpenSystem,
}: {
  items: readonly HealthItem[]
  onOpenSystem?: () => void
}) {
  if (items.length === 0) return null
  return (
    <ul className="flex flex-wrap items-center gap-x-5 gap-y-2">
      {items.map((item) => {
        const clickable = Boolean(onOpenSystem) && item.tone === "bad"
        const content = (
          <>
            {item.tone !== "ok" ? <StatusDot tone={item.tone} /> : null}
            <span className="text-xs text-slate-500">{item.label}</span>
            <span
              className={cn(
                "truncate text-sm tabular-nums",
                item.tone === "bad"
                  ? "font-medium text-status-bad-fg"
                  : item.tone === "warn"
                    ? "font-medium text-status-warn-fg"
                    : "text-slate-800",
              )}
            >
              {item.value}
            </span>
          </>
        )
        return (
          <li
            key={item.key}
            className="flex min-w-0 items-center gap-1.5 border-l border-slate-200 pl-3 first:border-l-0 first:pl-0"
            title={item.hint}
          >
            {clickable ? (
              <button
                type="button"
                onClick={onOpenSystem}
                className="flex min-w-0 items-center gap-1.5 rounded-md hover:bg-slate-50"
              >
                {content}
              </button>
            ) : (
              content
            )}
          </li>
        )
      })}
    </ul>
  )
}
