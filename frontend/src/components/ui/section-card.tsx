import type { ReactNode } from "react"
import { HelpTip } from "@/components/ui/help-tip"
import type { HelpTextId } from "@/lib/help-texts"
import { cn } from "@/lib/utils"

export type SectionCardStatus = "loading" | "empty" | "error" | "content"

/**
 * Единая оболочка секции-карточки: заголовок + HelpTip + мета + действие справа,
 * слоты loading | empty | error | content. Рамку рисует только этот примитив.
 *
 * Жил в `features/market/MarketSection.tsx` (F-02), переехал в `components/ui` вместе с
 * Этапом 0 редизайна админки: у админки была своя копия (`AdminSection`) — та же разметка без
 * `helpId` и без `refreshing`. Две копии одного примитива — ровно та болезнь, из-за которой
 * раздел выглядел чужим, поэтому копия удалена, а оригинал стал общим.
 */
export function SectionCard({
  id,
  title,
  helpId,
  action,
  meta,
  status,
  refreshing,
  loading,
  empty,
  error,
  children,
  hidden,
  className,
}: {
  /** DOM-id для якорной прокрутки; нужен не всем секциям. */
  id?: string
  title: string
  helpId?: HelpTextId
  action?: ReactNode
  /** Мелочь у заголовка: время обновления, stale-бейдж и т.п. */
  meta?: ReactNode
  status: SectionCardStatus
  /**
   * Фоновая перезагрузка при уже показанных данных (V-10): держим прошлый кадр
   * приглушённым вместо скелета. Ставить только вместе со `status === "content"`
   * (например `keepPreviousData` + `isFetching` у смены периода) — иначе просто
   * рисуется `loading`.
   */
  refreshing?: boolean
  loading?: ReactNode
  empty?: ReactNode
  error?: ReactNode
  children?: ReactNode
  hidden?: boolean
  className?: string
}) {
  const body =
    status === "loading"
      ? loading
      : status === "empty"
        ? empty
        : status === "error"
          ? error
          : children
  const dimmed = status === "content" && refreshing

  return (
    <section
      id={id}
      aria-label={title}
      hidden={hidden}
      className={cn("min-w-0 rounded-xl border bg-white shadow-sm", className)}
    >
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <h2 className="truncate text-sm font-semibold text-slate-900">{title}</h2>
          {helpId ? <HelpTip id={helpId} /> : null}
          {meta}
        </div>
        {action ? <div className="min-w-0">{action}</div> : null}
      </div>
      {body != null ? (
        <div
          className={cn(
            "min-w-0 border-t px-4 py-4",
            dimmed && "pointer-events-none opacity-60 transition-opacity duration-200",
          )}
          aria-busy={dimmed || undefined}
        >
          {body}
        </div>
      ) : null}
    </section>
  )
}
