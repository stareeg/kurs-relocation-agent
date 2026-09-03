/**
 * Состояние раздела «Действия» ⇄ query URL. Фильтры очереди живут в адресе,
 * чтобы ссылка с Пульта («сбои tg_push») воспроизводила экран.
 *
 * По умолчанию — «Все» за последние 48 часов; список групп догружается порциями.
 */

export const TASK_STATUSES = ["pending", "running", "failed", "done", "cancelled"] as const
export type TaskStatus = (typeof TASK_STATUSES)[number]

export const TASK_FILTER_STATUSES = ["failed", "pending", "running", "all"] as const
export type TaskFilterStatus = (typeof TASK_FILTER_STATUSES)[number]

export const TASK_STATUS_CHIPS = [
  { value: "failed", label: "Сбои" },
  { value: "pending", label: "Ждут" },
  { value: "running", label: "В работе" },
  { value: "all", label: "Все" },
] as const

export const PURGE_DAYS = [30, 60, 90] as const
export type PurgeDays = (typeof PURGE_DAYS)[number]

export const PURGE_DAY_CHIPS = PURGE_DAYS.map((days) => ({
  value: String(days),
  label: `${days} дней`,
}))

/** Первая порция групп очереди; «Ещё» наращивает limit. */
export const TASK_PAGE_SIZE = 40

export type SystemFilters = {
  status: TaskFilterStatus
  kind: string
}

export const DEFAULT_SYSTEM_FILTERS: SystemFilters = { status: "all", kind: "" }

export function isTaskStatus(value: string): value is TaskStatus {
  return TASK_STATUSES.includes(value as TaskStatus)
}

export function isTaskFilterStatus(value: string): value is TaskFilterStatus {
  return TASK_FILTER_STATUSES.includes(value as TaskFilterStatus)
}

export function parseSystemFilters(params: URLSearchParams): SystemFilters {
  const raw = params.get("status")
  const kind = (params.get("kind") ?? "").trim()
  if (raw == null || raw === "") return { status: "all", kind }
  if (isTaskFilterStatus(raw)) return { status: raw, kind }
  return { status: "all", kind }
}

export function systemFiltersToParams(filters: SystemFilters): URLSearchParams {
  const params = new URLSearchParams()
  if (filters.status && filters.status !== DEFAULT_SYSTEM_FILTERS.status) {
    params.set("status", filters.status)
  }
  if (filters.kind?.trim()) params.set("kind", filters.kind.trim())
  return params
}

export function adminSystemPath(filters: Partial<SystemFilters> = {}): string {
  const params = systemFiltersToParams({ ...DEFAULT_SYSTEM_FILTERS, ...filters })
  const query = params.toString()
  return query ? `/admin/system?${query}` : "/admin/system"
}

/** Что уходит в `/api/admin/tasks?status=`: «все» — без фильтра. */
export function tasksQueryStatus(status: TaskFilterStatus): string {
  return status === "all" ? "" : status
}

export function taskStatusLabel(status: string | undefined): string {
  if (status === "pending") return "Ждут"
  if (status === "running") return "В работе"
  if (status === "failed") return "Сбой"
  if (status === "cancelled") return "Отменена"
  if (status === "done") return "Готово"
  return status || "—"
}

export function taskStatusTone(
  status: string | undefined,
): "strong" | "warn" | "bad" | "info" {
  if (status === "failed") return "bad"
  if (status === "running") return "warn"
  if (status === "done") return "strong"
  return "info"
}
