import type { ReactNode } from "react"
import { cn } from "@/lib/utils"
import { resolveEmptyReason } from "./market-empty"
import type { MarketSectionId } from "./market-sections"

/**
 * Честное пустое состояние секции «Рынка» (F-06): одно предложение-причина, без прочерков
 * и без общих «нет данных». `note` с бэка побеждает запасную формулировку секции.
 */
export function MarketEmpty({
  sectionId,
  note,
  action,
  className,
}: {
  sectionId: MarketSectionId
  note?: string | null
  action?: ReactNode
  className?: string
}) {
  const reason = resolveEmptyReason(note, sectionId)
  return (
    <div
      className={cn(
        "flex flex-col items-start gap-3 py-2 text-sm leading-relaxed text-slate-500",
        className,
      )}
    >
      <p className="max-w-xl">{reason}</p>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  )
}
