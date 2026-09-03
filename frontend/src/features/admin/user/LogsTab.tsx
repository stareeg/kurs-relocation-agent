import { Download } from "lucide-react"
import { Link } from "react-router-dom"
import type { AdminUserDetail } from "@/api/admin"
import { Button } from "@/components/ui/button"
import { ChipToggleGroup } from "@/components/ui/chip-toggle-group"
import { formatDateTime } from "@/lib/format"
import { useDownloadAdminLogs } from "@/features/admin/use-admin"
import { adminJournalPath } from "@/features/admin/journal-filters"
import { DEFAULT_LOG_HOURS, LOG_WINDOW_HOURS } from "@/features/admin/user/log-window"

/**
 * Свежие ошибки и бандл. Полный журнал — раздел «Журнал» с фильтром по человеку.
 */
export function LogsTab({
  accountId,
  detail,
  hours,
  onHoursChange,
}: {
  accountId: number
  detail: AdminUserDetail | undefined
  hours: number
  onHoursChange: (hours: number) => void
}) {
  const logs = useDownloadAdminLogs()
  const errors = detail?.recent_errors ?? []
  const journalHref = adminJournalPath({ accountId: String(accountId), window: "24h" })

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <ChipToggleGroup
          multiple={false}
          allowEmpty={false}
          value={[String(hours)]}
          onChange={(next) => onHoursChange(Number(next[0] || DEFAULT_LOG_HOURS))}
          options={[...LOG_WINDOW_HOURS]}
        />
        <Button
          size="sm"
          variant="outline"
          disabled={logs.isPending}
          onClick={() => logs.mutate({ accountId, hours })}
        >
          <Download className="size-3.5" strokeWidth={2} />
          Скачать файл
        </Button>
        <Button size="sm" variant="ghost" asChild>
          <Link to={journalHref}>Журнал</Link>
        </Button>
      </div>
      {errors.length === 0 ? (
        <p className="text-sm text-slate-400">Ошибок за неделю нет.</p>
      ) : (
        <div className="space-y-1.5">
          {errors.map((error, index) => (
            <p key={`${error.ts}-${index}`} className="line-clamp-3 text-xs text-slate-600">
              {formatDateTime(error.ts)} · {error.msg || error.event}
            </p>
          ))}
        </div>
      )}
    </div>
  )
}
