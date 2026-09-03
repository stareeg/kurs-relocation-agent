import { useState } from "react"
import { AlertTriangle, ChevronRight, CircleAlert, Copy, Info, Pause, Play, ScrollText } from "lucide-react"
import { toast } from "sonner"
import type { AdminAuditRow, AdminLogRow } from "@/api/admin"
import { Button } from "@/components/ui/button"
import { ChipToggleGroup } from "@/components/ui/chip-toggle-group"
import { EmptyState, ErrorState } from "@/components/ui/empty-state"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { atHandle, formatLogTs } from "@/features/admin/admin-format"
import { SectionCard } from "@/components/ui/section-card"
import { SegmentedControl } from "@/components/ui/segmented-control"
import {
  JOURNAL_LEVEL_CHIPS,
  JOURNAL_WINDOW_CHIPS,
  adminJournalPath,
  auditActionLabel,
  journalFiltersToParams,
  journalRequestWindow,
  logLevelTone,
  parseJournalFilters,
  type JournalFilters,
  type JournalLevel,
  type JournalWindow,
} from "@/features/admin/journal-filters"
import { mergeJournalEntries } from "@/features/admin/journal-merge"
import { useAdminAudit, useAdminLogs } from "@/features/admin/use-admin"

const TONE_ROW: Record<NonNullable<ReturnType<typeof logLevelTone>>, string> = {
  bad: "bg-status-bad-soft text-status-bad-fg",
  warn: "border-status-warn-dot text-status-warn-fg",
  info: "text-slate-600",
}

/**
 * Журнал логов и действий оператора в одном списке. Состояние — в URL.
 */
export function JournalSection({
  enabled,
  searchParams,
  onSearchParams,
}: {
  enabled: boolean
  searchParams: URLSearchParams
  onSearchParams: (next: URLSearchParams) => void
}) {
  const filters = parseJournalFilters(searchParams)
  const setFilters = (next: JournalFilters) => onSearchParams(journalFiltersToParams(next))
  const patch = (partial: Partial<JournalFilters>) => {
    const merged = { ...filters, ...partial }
    if (partial.cursor === undefined && partial.live === undefined) merged.cursor = ""
    setFilters(merged)
  }

  const telegramUserId = filters.telegramUserId ? Number(filters.telegramUserId) : undefined
  const accountId = filters.accountId ? Number(filters.accountId) : undefined
  const live = filters.live && !filters.cursor
  const parsedTelegram = Number.isFinite(telegramUserId) ? telegramUserId : undefined
  const parsedAccount = Number.isFinite(accountId) ? accountId : undefined
  const logsKey = {
    window: filters.window,
    level: filters.levels.join(","),
    telegram_user_id: parsedTelegram ?? null,
    account_id: parsedAccount ?? null,
    cursor: live ? "" : filters.cursor,
  }
  const auditKey = {
    window: logsKey.window,
    telegram_user_id: logsKey.telegram_user_id,
    account_id: logsKey.account_id,
    cursor: "",
  }

  const logs = useAdminLogs(enabled, logsKey, live, () => {
    const bounds = journalRequestWindow(filters)
    return {
      since: bounds.since,
      until: bounds.until,
      level: logsKey.level,
      telegram_user_id: parsedTelegram,
      account_id: parsedAccount,
      cursor: logsKey.cursor || undefined,
      limit: 100,
    }
  })
  const audit = useAdminAudit(enabled, auditKey, live, () => {
    const bounds = journalRequestWindow(filters)
    return {
      since: bounds.since,
      until: bounds.until,
      telegram_user_id: parsedTelegram,
      account_id: parsedAccount,
      limit: 100,
    }
  })
  const entries = mergeJournalEntries(logs.data?.items ?? [], audit.data?.items ?? [])
  const nextCursor = logs.data?.next_cursor ?? null
  const [expanded, setExpanded] = useState<string | null>(null)
  const loading = logs.isLoading || audit.isLoading
  const errored = logs.isError && audit.isError
  const empty = !loading && !errored && entries.length === 0

  return (
    <div className="flex flex-col gap-3 px-6 pb-6 pt-6">
      <div className="flex flex-wrap items-center gap-2">
        <Input
          value={filters.telegramUserId}
          onChange={(event) =>
            patch({ telegramUserId: event.target.value.replace(/\D/g, ""), cursor: "" })
          }
          placeholder="Telegram id человека"
          inputMode="numeric"
          className="h-11 w-56 rounded-xl text-sm"
        />
        <SegmentedControl
          ariaLabel="Окно"
          options={[...JOURNAL_WINDOW_CHIPS]}
          value={filters.window}
          onChange={(next) => patch({ window: next as JournalWindow, cursor: "" })}
        />
        <ChipToggleGroup
          multiple
          value={filters.levels}
          onChange={(next) =>
            patch({
              levels: (next.length ? next : ["ERROR", "WARNING"]) as JournalLevel[],
              cursor: "",
            })
          }
          options={[...JOURNAL_LEVEL_CHIPS]}
        />
        <Button
          size="sm"
          variant={live ? "default" : "outline"}
          onClick={() => patch({ live: !filters.live, cursor: "" })}
        >
          {live ? <Pause className="size-3.5" strokeWidth={2} /> : <Play className="size-3.5" strokeWidth={2} />}
          {live ? "Живой хвост" : "Хвост выключен"}
        </Button>
      </div>

      <SectionCard
        title="Записи"
        meta={
          <span className="text-xs tabular-nums text-slate-400">
            {logs.isFetching || audit.isFetching
              ? "обновляется…"
              : `показано ${entries.length}${nextCursor ? " · раньше" : ""}`}
          </span>
        }
        status={empty ? "empty" : errored ? "error" : loading ? "loading" : "content"}
        loading={<Skeleton className="h-48 w-full" />}
        empty={
          <EmptyState
            variant="empty"
            icon={ScrollText}
            title="В этом окне тихо"
            note="Попробуйте расширить окно или снять фильтр по уровню."
          />
        }
        error={
          <ErrorState
            compact
            icon={AlertTriangle}
            title="Журнал не загрузился"
            note="Не удалось прочитать записи. Сузьте окно или повторите."
            action={{
              label: "Повторить",
              onClick: () => {
                void logs.refetch()
                void audit.refetch()
              },
            }}
          />
        }
      >
        <div className="space-y-0.5">
          {entries.map((entry) =>
            entry.kind === "log" ? (
              <LogLine
                key={entry.id}
                row={entry.log}
                expanded={expanded === entry.id}
                onToggle={() => setExpanded((cur) => (cur === entry.id ? null : entry.id))}
                onTelegram={(id) => patch({ telegramUserId: String(id), cursor: "" })}
              />
            ) : (
              <AuditLine
                key={entry.id}
                row={entry.audit}
                expanded={expanded === entry.id}
                onToggle={() => setExpanded((cur) => (cur === entry.id ? null : entry.id))}
              />
            ),
          )}
        </div>
        {nextCursor && (
          <div className="flex items-center gap-2 pt-2 text-xs text-slate-400">
            <span>показано {entries.length}</span>
            <Button size="sm" variant="outline" onClick={() => patch({ cursor: nextCursor, live: false })}>
              Раньше
            </Button>
          </div>
        )}
      </SectionCard>
    </div>
  )
}

function LogLine({
  row,
  expanded,
  onToggle,
  onTelegram,
}: {
  row: AdminLogRow
  expanded: boolean
  onToggle: () => void
  onTelegram: (telegramUserId: number) => void
}) {
  const tone = logLevelTone(row.level)
  const telegramId = row.telegram_user_id
  const userLabel =
    row.telegram_username || row.account_id != null
      ? atHandle(row.telegram_username) || `id ${row.account_id}`
      : "—"
  return (
    <div
      className={cn(
        "rounded-md border-l-2 border-transparent px-2 py-1 font-mono text-xs",
        tone ? TONE_ROW[tone] : "text-slate-600",
      )}
    >
      <div className="flex w-full items-center gap-2">
        <button type="button" onClick={onToggle} className="flex min-w-0 flex-1 items-center gap-2 text-left">
          <ChevronRight
            className={cn("size-3.5 shrink-0 text-slate-400 transition-transform", expanded && "rotate-90")}
            strokeWidth={2}
          />
          <span className="w-28 shrink-0 truncate text-xs opacity-80" title={userLabel}>
            {userLabel}
          </span>
          <span className="shrink-0 tabular-nums text-xs opacity-80">{formatLogTs(row.ts)}</span>
          <LevelMark level={row.level} />
          <span className="min-w-0 flex-1 truncate">{row.msg || row.event || "—"}</span>
        </button>
        <Button
          size="sm"
          variant="ghost"
          className="h-7 shrink-0 gap-1 px-2 text-xs"
          onClick={() => copyJournalText(formatLogCopy(row))}
        >
          <Copy className="size-3.5" strokeWidth={2} />
          Копировать
        </Button>
      </div>
      {expanded && (
        <div className="mt-1 space-y-1 border-t border-current/10 pt-1 text-xs">
          <p>
            {row.logger || "—"} · {row.event || "без события"}
            {row.task_id ? ` · task ${row.task_id}` : ""}
            {telegramId != null && (
              <>
                {" · "}
                <a
                  href={adminJournalPath({ telegramUserId: String(telegramId) })}
                  className="underline-offset-2 hover:underline"
                  onClick={(event) => {
                    event.preventDefault()
                    onTelegram(telegramId)
                  }}
                >
                  tg {telegramId}
                </a>
              </>
            )}
          </p>
          {row.fields && Object.keys(row.fields).length > 0 && (
            <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all text-slate-700">
              {JSON.stringify(row.fields, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}

function AuditLine({
  row,
  expanded,
  onToggle,
}: {
  row: AdminAuditRow
  expanded: boolean
  onToggle: () => void
}) {
  const actor = atHandle(row.actor_username) || "оператор"
  return (
    <div className="rounded-md px-2 py-1 font-mono text-xs text-slate-700">
      <div className="flex w-full items-center gap-2">
        <button type="button" onClick={onToggle} className="flex min-w-0 flex-1 items-center gap-2 text-left">
          <ChevronRight
            className={cn("size-3.5 shrink-0 text-slate-400 transition-transform", expanded && "rotate-90")}
            strokeWidth={2}
          />
          <span className="w-28 shrink-0 truncate text-xs text-slate-500" title={actor}>
            {actor}
          </span>
          <span className="shrink-0 tabular-nums text-xs text-slate-400">{formatLogTs(row.at)}</span>
          <span className="w-36 shrink-0 font-medium">{auditActionLabel(row.action)}</span>
          <span className="min-w-0 flex-1 truncate">
            {row.target_id != null ? `→ ${atHandle(row.target_username)}` : ""}
          </span>
        </button>
        <Button
          size="sm"
          variant="ghost"
          className="h-7 shrink-0 gap-1 px-2 text-xs"
          onClick={() => copyJournalText(formatAuditCopy(row))}
        >
          <Copy className="size-3.5" strokeWidth={2} />
          Копировать
        </Button>
      </div>
      {expanded && (
        <div className="mt-1 space-y-1 border-t pt-1 text-xs text-slate-500">
          {row.details && Object.keys(row.details).length > 0 && (
            <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all">
              {JSON.stringify(row.details, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}

function LevelMark({ level }: { level: string }) {
  const tone = logLevelTone(level)
  const label = level || "—"
  if (tone === "bad") {
    return <CircleAlert className="size-4 shrink-0" strokeWidth={2} aria-label={label} />
  }
  if (tone === "warn") {
    return <AlertTriangle className="size-4 shrink-0" strokeWidth={2} aria-label={label} />
  }
  if (tone === "info") {
    return <Info className="size-4 shrink-0" strokeWidth={2} aria-label={label} />
  }
  return <span className="w-4 shrink-0 text-center text-[10px] opacity-60">{label.slice(0, 1)}</span>
}

function formatLogCopy(row: AdminLogRow): string {
  const user =
    row.telegram_username || row.account_id != null
      ? atHandle(row.telegram_username) || `account ${row.account_id}`
      : "—"
  const lines = [
    `[${row.level || "LOG"}] ${formatLogTs(row.ts)} ${user}`,
    row.msg || row.event || "—",
    `logger: ${row.logger || "—"}`,
    `event: ${row.event || "—"}`,
  ]
  if (row.task_id) lines.push(`task_id: ${row.task_id}`)
  if (row.telegram_user_id != null) lines.push(`telegram_user_id: ${row.telegram_user_id}`)
  if (row.account_id != null) lines.push(`account_id: ${row.account_id}`)
  if (row.fields && Object.keys(row.fields).length > 0) {
    lines.push("fields:")
    lines.push(JSON.stringify(row.fields, null, 2))
  }
  return lines.join("\n")
}

function formatAuditCopy(row: AdminAuditRow): string {
  const lines = [
    `[AUDIT] ${formatLogTs(row.at)} ${atHandle(row.actor_username) || "оператор"}`,
    auditActionLabel(row.action),
  ]
  if (row.target_id != null) {
    lines.push(`target: ${atHandle(row.target_username)} (id ${row.target_id})`)
  }
  if (row.details && Object.keys(row.details).length > 0) {
    lines.push("details:")
    lines.push(JSON.stringify(row.details, null, 2))
  }
  return lines.join("\n")
}

function copyJournalText(body: string) {
  if (!body) return
  void navigator.clipboard.writeText(body).then(
    () => toast.success("Скопировано"),
    () => toast.error("Не удалось скопировать"),
  )
}
