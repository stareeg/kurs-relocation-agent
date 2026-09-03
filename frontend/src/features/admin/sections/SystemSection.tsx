import { useState } from "react"
import { AlertTriangle, ListTodo, MoreHorizontal } from "lucide-react"
import type { AdminTaskDetail, AdminTaskReasonCount } from "@/api/admin"
import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { EmptyState, ErrorState } from "@/components/ui/empty-state"
import { HelpTip } from "@/components/ui/help-tip"
import { Input } from "@/components/ui/input"
import { StatusChip } from "@/components/ui/status-chip"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { formatMoment } from "@/features/admin/admin-format"
import { taskKindLabel } from "@/features/admin/admin-spend"
import { DashboardMetrics } from "@/features/admin/components/DashboardMetrics"
import { SectionCard } from "@/components/ui/section-card"
import { SegmentedControl } from "@/components/ui/segmented-control"
import {
  PURGE_DAY_CHIPS,
  TASK_PAGE_SIZE,
  TASK_STATUS_CHIPS,
  parseSystemFilters,
  systemFiltersToParams,
  taskStatusLabel,
  taskStatusTone,
  tasksQueryStatus,
  type PurgeDays,
  type SystemFilters,
} from "@/features/admin/system-filters"
import { isMissingHandler, itemsForReason, taskReasonKey } from "@/features/admin/task-groups"
import {
  useAdminSummary,
  useAdminTasks,
  useCancelAdminTask,
  useCancelAdminTasksKind,
  usePurgeAdminLogs,
  useReclaimAdminTasks,
  useRepairAdminFriendships,
  useRetryAdminTask,
  useRetryAdminTasksKind,
  useSetAdminSpendAlert,
} from "@/features/admin/use-admin"

type ConfirmKind = "purge" | "retry-kind" | "cancel" | "cancel-kind" | "reclaim" | "spend" | null

function tasksFilterKey(filters: SystemFilters): string {
  return `${filters.status}\u0000${filters.kind}`
}

/**
 * Действия: метрики очереди за 48 ч и группы задач с русской подписью kind.
 */
export function SystemSection({
  enabled,
  searchParams,
  onSearchParams,
}: {
  enabled: boolean
  searchParams: URLSearchParams
  onSearchParams: (next: URLSearchParams) => void
}) {
  const filters = parseSystemFilters(searchParams)
  const patch = (partial: Partial<SystemFilters>) =>
    onSearchParams(systemFiltersToParams({ ...filters, ...partial }))

  const filterKey = tasksFilterKey(filters)
  const [limitsByFilter, setLimitsByFilter] = useState<Record<string, number>>({})
  const limit = limitsByFilter[filterKey] ?? TASK_PAGE_SIZE
  const setLimit = (update: number | ((cur: number) => number)) => {
    setLimitsByFilter((cur) => {
      const base = cur[filterKey] ?? TASK_PAGE_SIZE
      const next = typeof update === "function" ? update(base) : update
      return { ...cur, [filterKey]: next }
    })
  }

  const summary = useAdminSummary(enabled)
  const tasks = useAdminTasks(enabled, {
    status: tasksQueryStatus(filters.status),
    kind: filters.kind,
    limit,
  })

  const retryOne = useRetryAdminTask()
  const cancelOne = useCancelAdminTask()
  const retryKind = useRetryAdminTasksKind()
  const cancelKind = useCancelAdminTasksKind()
  const reclaim = useReclaimAdminTasks()
  const purge = usePurgeAdminLogs()
  const repair = useRepairAdminFriendships()
  const spendAlert = useSetAdminSpendAlert()

  const [confirm, setConfirm] = useState<ConfirmKind>(null)
  const [purgeDays, setPurgeDays] = useState<PurgeDays>(30)
  const [cancelId, setCancelId] = useState<number | null>(null)
  const [openPayload, setOpenPayload] = useState<number | null>(null)
  const [openGroup, setOpenGroup] = useState<string | null>(null)
  const savedAlert = summary.data?.spend_alert_usd ?? 0
  const [alertDraft, setAlertDraft] = useState<string | null>(null)
  const alertValue = alertDraft ?? String(savedAlert)

  const queue = tasks.data?.by_status
  const groups = tasks.data?.by_reason ?? []
  const items = tasks.data?.items ?? []
  const reasonsTotal = tasks.data?.reasons_total ?? groups.length
  const running = queue?.running ?? 0
  const [groupTarget, setGroupTarget] = useState<AdminTaskReasonCount | null>(null)

  const queueMetrics = queue
    ? [
        { key: "failed", value: String(queue.failed), unit: "", label: "Сбои" },
        { key: "pending", value: String(queue.pending), unit: "", label: "Ждут" },
        { key: "running", value: String(queue.running), unit: "", label: "В работе" },
        { key: "done", value: String(queue.done), unit: "", label: "Готово" },
      ]
    : []

  return (
    <div className="flex flex-col gap-4 px-6 pb-6 pt-6">
      <SectionCard
        title="Очередь за 48 часов"
        status={tasks.isError ? "error" : queueMetrics.length === 0 ? "loading" : "content"}
        refreshing={tasks.isFetching && queueMetrics.length > 0}
        loading={<Skeleton className="h-20 w-full" />}
        error={
          <ErrorState
            compact
            icon={AlertTriangle}
            title="Метрики не загрузились"
            note="Не удалось прочитать глубину очереди."
            action={{ label: "Повторить", onClick: () => void tasks.refetch() }}
          />
        }
      >
        <DashboardMetrics items={queueMetrics} />
      </SectionCard>

      <SectionCard
        title="Очередь задач"
        action={
          <div className="flex flex-wrap items-center gap-2">
            <SegmentedControl
              ariaLabel="Статус задач"
              options={[...TASK_STATUS_CHIPS]}
              value={filters.status}
              onChange={(next) => patch({ status: next as SystemFilters["status"] })}
            />
            <Button size="sm" variant="outline" onClick={() => setConfirm("reclaim")}>
              Вернуть зависшие в очередь
            </Button>
            <HelpTip id="admin.task-reclaim" showIcon />
            <MaintenanceMenu
              onPurge={() => setConfirm("purge")}
              onSpend={() => setConfirm("spend")}
              onRepair={() => repair.mutate()}
              repairBusy={repair.isPending}
            />
            <HelpTip id="admin.repair-friendships" showIcon />
          </div>
        }
        status={tasks.isError ? "error" : tasks.isLoading ? "loading" : "content"}
        loading={<Skeleton className="h-40 w-full" />}
        error={
          <ErrorState
            compact
            icon={AlertTriangle}
            title="Очередь не загрузилась"
            note="Не удалось прочитать фоновые задачи."
            action={{ label: "Повторить", onClick: () => void tasks.refetch() }}
          />
        }
      >
        <div className="flex flex-col gap-3">
          {groups.length === 0 && items.length === 0 ? (
            <EmptyState
              variant="empty"
              icon={ListTodo}
              title="Очередь пуста"
              note="Нет задач с выбранным фильтром за последние 48 часов."
            />
          ) : groups.length > 0 ? (
            <>
              <ul className="divide-y rounded-lg border">
                {groups.map((group) => {
                  const key = taskReasonKey(group.kind, group.reason, group.status)
                  const expanded = openGroup === key
                  const missing = isMissingHandler(group.reason)
                  const members = itemsForReason(items, group)
                  const status = group.status || filters.status
                  return (
                    <li key={key} className="px-3 py-2.5">
                      <div className="flex flex-wrap items-center gap-3">
                        <button
                          type="button"
                          onClick={() => setOpenGroup((cur) => (cur === key ? null : key))}
                          className="flex min-w-0 flex-1 items-center gap-3 text-left"
                        >
                          <span className="w-[4.5rem] shrink-0 text-sm font-semibold tabular-nums text-slate-800">
                            {formatMoment(group.last_finished_at)}
                          </span>
                          <StatusChip tone={taskStatusTone(status)} className="shrink-0">
                            {taskStatusLabel(status)}
                          </StatusChip>
                          <span className="min-w-0 truncate text-sm font-medium text-slate-800">
                            {taskKindLabel(group.kind)}
                          </span>
                          <span className="shrink-0 text-base font-semibold tabular-nums text-slate-900">
                            {group.count}
                          </span>
                        </button>
                        {status === "failed" || filters.status === "failed" ? (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => {
                              setGroupTarget(group)
                              setConfirm(missing ? "cancel-kind" : "retry-kind")
                            }}
                          >
                            {missing
                              ? `Отменить ${group.count}`
                              : `Перезапустить ${group.count}`}
                          </Button>
                        ) : null}
                      </div>
                      {missing ? (
                        <p className="mt-1 pl-[calc(4.5rem+0.75rem)] text-xs text-slate-400">
                          Перезапуск не поможет — обработчика нет в этом процессе.
                        </p>
                      ) : group.reason ? (
                        <p className="mt-1 line-clamp-2 pl-[calc(4.5rem+0.75rem)] text-xs text-slate-500">
                          {group.reason}
                        </p>
                      ) : null}
                      {expanded && (
                        <ul className="mt-2 space-y-1 border-t pt-2">
                          {(members.length > 0 ? members : []).map((task) => (
                            <TaskRow
                              key={task.id}
                              task={task}
                              expanded={openPayload === task.id}
                              onToggle={() =>
                                setOpenPayload((id) => (id === task.id ? null : task.id))
                              }
                              onRetry={() => retryOne.mutate(task.id)}
                              onCancel={() => {
                                setCancelId(task.id)
                                setConfirm("cancel")
                              }}
                              busy={retryOne.isPending || cancelOne.isPending}
                            />
                          ))}
                        </ul>
                      )}
                    </li>
                  )
                })}
              </ul>
              {reasonsTotal > groups.length ? (
                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={tasks.isFetching}
                    onClick={() => setLimit((cur) => cur + TASK_PAGE_SIZE)}
                  >
                    Ещё
                  </Button>
                  <span className="text-xs tabular-nums text-slate-400">
                    показано {groups.length} из {reasonsTotal}
                  </span>
                </div>
              ) : null}
            </>
          ) : (
            <ul className="divide-y rounded-lg border">
              {items.map((task) => (
                <TaskRow
                  key={task.id}
                  task={task}
                  expanded={openPayload === task.id}
                  onToggle={() => setOpenPayload((id) => (id === task.id ? null : task.id))}
                  onRetry={() => retryOne.mutate(task.id)}
                  onCancel={() => {
                    setCancelId(task.id)
                    setConfirm("cancel")
                  }}
                  busy={retryOne.isPending || cancelOne.isPending}
                />
              ))}
            </ul>
          )}
        </div>
      </SectionCard>

      <ConfirmDialog
        open={confirm === "purge"}
        onOpenChange={(open) => !open && setConfirm(null)}
        title={`Удалить логи старше ${purgeDays} дней?`}
        description="Строки журнала младше окна останутся. Это нельзя отменить."
        confirmLabel="Удалить"
        onConfirm={() => {
          purge.mutate(purgeDays)
          setConfirm(null)
        }}
      >
        <div className="flex items-center gap-2">
          <HelpTip id="admin.purge-logs" showIcon />
          <SegmentedControl
            size="sm"
            ariaLabel="Окно уборки"
            options={PURGE_DAY_CHIPS}
            value={String(purgeDays)}
            onChange={(next) => setPurgeDays(Number(next) as PurgeDays)}
          />
        </div>
      </ConfirmDialog>
      <ConfirmDialog
        open={confirm === "spend"}
        onOpenChange={(open) => !open && setConfirm(null)}
        title="Порог расхода за месяц"
        description="При превышении человек подсветится. Ноль — сигнал выключен."
        confirmLabel="Сохранить"
        onConfirm={() => {
          const nextUsd = Number(alertValue.replace(",", "."))
          if (Number.isNaN(nextUsd) || nextUsd < 0) return
          spendAlert.mutate(nextUsd, { onSuccess: () => setAlertDraft(null) })
          setConfirm(null)
        }}
      >
        <div className="flex items-center gap-2">
          <HelpTip id="admin.spend-alert" showIcon />
          <Input
            type="number"
            min={0}
            max={10000}
            step={0.5}
            value={alertValue}
            onChange={(event) => setAlertDraft(event.target.value)}
            className="h-9 w-24 text-sm tabular-nums"
            aria-label="Порог расхода за календарный месяц"
          />
        </div>
      </ConfirmDialog>
      <ConfirmDialog
        open={confirm === "retry-kind"}
        onOpenChange={(open) => !open && setConfirm(null)}
        title={`Перезапустить ${groupTarget?.count ?? 0} сбоев ${groupTarget ? taskKindLabel(groupTarget.kind) : ""}?`}
        description="В очередь вернутся упавшие задачи этой причины."
        confirmLabel="Перезапустить"
        onConfirm={() => {
          if (groupTarget) retryKind.mutate({ kind: groupTarget.kind, reason: groupTarget.reason })
          setConfirm(null)
          setGroupTarget(null)
        }}
      />
      <ConfirmDialog
        open={confirm === "cancel-kind"}
        onOpenChange={(open) => !open && setConfirm(null)}
        title={`Отменить ${groupTarget?.count ?? 0} сбоев ${groupTarget ? taskKindLabel(groupTarget.kind) : ""}?`}
        description="Перезапуск не поможет: обработчика нет. Задачи снимут со сбоев."
        confirmLabel="Отменить"
        onConfirm={() => {
          if (groupTarget) cancelKind.mutate({ kind: groupTarget.kind, reason: groupTarget.reason })
          setConfirm(null)
          setGroupTarget(null)
        }}
      />
      <ConfirmDialog
        open={confirm === "cancel"}
        onOpenChange={(open) => !open && setConfirm(null)}
        title="Отменить задачу?"
        description="Зависшая или ожидающая задача не выполнится. Готовые не трогаем."
        confirmLabel="Отменить"
        onConfirm={() => {
          if (cancelId != null) cancelOne.mutate(cancelId)
          setConfirm(null)
          setCancelId(null)
        }}
      />
      <ConfirmDialog
        open={confirm === "reclaim"}
        onOpenChange={(open) => !open && setConfirm(null)}
        title="Вернуть зависшие в очередь?"
        description={`${running} задач сейчас в статусе «в работе». Их снимут и поставят в pending — иначе они висят до рестарта воркера.`}
        confirmLabel="Вернуть"
        onConfirm={() => {
          reclaim.mutate()
          setConfirm(null)
        }}
      />
    </div>
  )
}

function MaintenanceMenu({
  onPurge,
  onSpend,
  onRepair,
  repairBusy,
}: {
  onPurge: () => void
  onSpend: () => void
  onRepair: () => void
  repairBusy: boolean
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size="icon-sm" variant="ghost" aria-label="Обслуживание">
          <MoreHorizontal className="size-4" strokeWidth={2} />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuItem onSelect={onPurge}>Уборка журнала</DropdownMenuItem>
        <DropdownMenuItem onSelect={onSpend}>Порог расхода</DropdownMenuItem>
        <DropdownMenuItem disabled={repairBusy} onSelect={onRepair}>
          Проверить чаты с ботом
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function TaskRow({
  task,
  expanded,
  onToggle,
  onRetry,
  onCancel,
  busy,
}: {
  task: AdminTaskDetail
  expanded: boolean
  onToggle: () => void
  onRetry: () => void
  onCancel: () => void
  busy: boolean
}) {
  const canRetry = task.status === "failed" || task.status === "cancelled"
  const canCancel = task.status === "pending" || task.status === "running"
  const payload = task.payload ?? {}
  const hasPayload = Object.keys(payload).length > 0
  const when = task.finished_at || task.updated_at || task.created_at

  return (
    <li className="px-1 py-1.5">
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" onClick={onToggle} className="flex min-w-0 flex-1 items-center gap-3 text-left">
          <span className="w-[4.5rem] shrink-0 text-sm font-semibold tabular-nums text-slate-800">
            {formatMoment(when)}
          </span>
          <StatusChip tone={taskStatusTone(task.status)} className="shrink-0">
            {taskStatusLabel(task.status)}
          </StatusChip>
          <span className="min-w-0 truncate text-sm font-medium text-slate-800">
            {taskKindLabel(task.kind)}
          </span>
          <span className="text-xs tabular-nums text-slate-400">
            {task.attempts}/{task.max_attempts}
          </span>
        </button>
        <div className="flex shrink-0 gap-1">
          {canRetry && (
            <Button size="sm" variant="outline" disabled={busy} onClick={onRetry}>
              Перезапустить
            </Button>
          )}
          {canCancel && (
            <Button size="sm" variant="outline" disabled={busy} onClick={onCancel}>
              Отменить
            </Button>
          )}
        </div>
      </div>
      {task.last_error ? (
        <p className="mt-1 line-clamp-2 pl-[calc(4.5rem+0.75rem)] text-xs text-slate-500">
          {task.last_error}
        </p>
      ) : null}
      {expanded && (
        <pre
          className={cn(
            "mt-2 max-h-48 overflow-auto rounded-md bg-slate-50 p-2 font-mono text-xs text-slate-600",
          )}
        >
          {hasPayload ? JSON.stringify(payload, null, 2) : "без данных"}
        </pre>
      )}
    </li>
  )
}
