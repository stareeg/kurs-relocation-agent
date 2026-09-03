import type { AdminTaskDetail, AdminTaskReasonCount } from "@/api/admin"

export function isMissingHandler(reason: string): boolean {
  return reason.includes("нет обработчика")
}

export function taskReasonKey(kind: string, reason: string, status = ""): string {
  return `${kind}\u0000${status}\u0000${reason}`
}

export function itemsForReason(
  items: readonly AdminTaskDetail[],
  group: Pick<AdminTaskReasonCount, "kind" | "reason" | "status">,
): AdminTaskDetail[] {
  return items.filter(
    (task) =>
      task.kind === group.kind &&
      (group.status ? task.status === group.status : true) &&
      (task.last_error ?? "").slice(0, 120) === group.reason,
  )
}
