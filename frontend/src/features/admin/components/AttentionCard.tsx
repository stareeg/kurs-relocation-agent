import { useState } from "react"
import { Button } from "@/components/ui/button"
import { StatusDot } from "@/components/ui/status-chip"
import { cn } from "@/lib/utils"
import type { AttentionItem } from "@/features/admin/attention"
import { KeyIssueForm } from "@/features/admin/components/KeyIssueForm"
import { useRejectAdminKey } from "@/features/admin/use-admin"

/**
 * Карточка дела: заголовок глаголом и действие на месте (Этап 2.2).
 * Полноценное «закрыть не уходя» для всех видов — Этап 10; здесь уже выдаём ключ из карточки.
 */
export function AttentionCard({
  item,
  onOpen,
}: {
  item: AttentionItem
  onOpen?: () => void
}) {
  const [issueOpen, setIssueOpen] = useState(false)
  const reject = useRejectAdminKey()
  const canIssue = item.action === "issue_key" && item.accountId != null

  return (
    <div className="rounded-lg border px-3 py-2">
      <div className="flex items-start justify-between gap-2">
        <button
          type="button"
          onClick={onOpen}
          disabled={!onOpen}
          className={cn(
            "min-w-0 flex-1 space-y-0.5 text-left",
            onOpen && "rounded-md hover:bg-slate-50",
          )}
        >
          <div className="flex items-baseline gap-1.5">
            {/* Дело без срочности (человек пропал) метится серой точкой: фиолетовый `info`
                кричал наравне с красным, а цвет в разделе означает «посмотри сюда» (§2.5). */}
            {item.tone === "info" ? (
              <span
                aria-hidden
                className="inline-block size-2 shrink-0 translate-y-[3px] rounded-full bg-slate-300"
              />
            ) : (
              <StatusDot tone={item.tone} className="translate-y-[3px]" />
            )}
            <span className="text-sm font-medium text-slate-800">{item.title}</span>
          </div>
          <p className="line-clamp-2 pl-3.5 text-xs text-slate-500">{item.note}</p>
        </button>
        {canIssue && (
          <Button
            size="sm"
            variant={issueOpen ? "outline" : "default"}
            onClick={() => setIssueOpen((v) => !v)}
          >
            {issueOpen ? "Скрыть" : "Выдать"}
          </Button>
        )}
      </div>
      {canIssue && issueOpen && item.accountId != null && (
        <div className="mt-2 border-t pt-2">
          <KeyIssueForm
            accountId={item.accountId}
            submitLabel="Выдать"
            extra={
              item.requestId != null ? (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={reject.isPending}
                  onClick={() => reject.mutate(item.requestId!)}
                >
                  Отклонить
                </Button>
              ) : undefined
            }
          />
        </div>
      )}
    </div>
  )
}
