import { useMemo } from "react"
import { buildAttentionItems } from "@/features/admin/attention"
import { ADMIN_BADGE_POLL_MS, useAdminAttention } from "@/features/admin/use-admin"
import { cn } from "@/lib/utils"

/**
 * Бейдж дел на пункте «Админ» в сайдбаре.
 *
 * Зачем: раздел открывают реактивно — когда друг написал «не работает». Без сигнала снаружи
 * оператор узнаёт о деле, только если сам догадается зайти. Сигнал живёт там, где человек и
 * так смотрит (рядом уже висят счётчики вакансий и чатов), а не уходит новой рассылкой в
 * Telegram — это запрещено правилом CLAUDE.md.
 *
 * Число считается **той же** функцией, что рисует список дел на Обзоре. План предлагал
 * отдавать счётчик отдельным `count(*)` на бэкенде, но тогда правило «что считается делом»
 * жило бы в двух местах на двух языках — ровно так в прошлый раз KPI разошлись со списками
 * под ними. Запрос тот же самый (`["admin", "attention"]`), поэтому при открытом разделе
 * лишнего похода на сервер нет.
 *
 * Хук здесь, а не в оболочке: иначе опрос ре-рендерил бы весь Outlet (тот же приём, что у
 * `ResumeScoreBadge`).
 */
export function AdminAttentionBadge({ enabled }: { enabled: boolean }) {
  const attention = useAdminAttention(enabled, ADMIN_BADGE_POLL_MS)
  const items = useMemo(() => buildAttentionItems(attention.data), [attention.data])

  if (items.length === 0) return null
  const blocking = items.some((item) => item.tone === "bad")

  return (
    <span
      title={`Дел, ждущих решения: ${items.length}`}
      className={cn(
        "inline-flex h-5 min-w-5 shrink-0 items-center justify-center rounded-md px-1.5 text-xs font-medium tabular-nums",
        blocking
          ? "bg-status-bad-soft text-status-bad-fg ring-1 ring-inset ring-status-bad-line"
          : "bg-slate-200/70 text-slate-600",
      )}
    >
      {items.length}
    </span>
  )
}
