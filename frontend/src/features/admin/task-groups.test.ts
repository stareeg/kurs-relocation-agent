import { describe, expect, it } from "vitest"
import type { AdminTaskDetail } from "@/api/admin"
import { isMissingHandler, itemsForReason, taskReasonKey } from "./task-groups"

function task(over: Partial<AdminTaskDetail> = {}): AdminTaskDetail {
  return {
    id: 1,
    kind: "tg_cleanup",
    status: "failed",
    payload: {},
    attempts: 3,
    max_attempts: 3,
    last_error: "нет обработчика kind='tg_cleanup'",
    priority: 100,
    ...over,
  }
}

describe("isMissingHandler", () => {
  it("ломает перезапуск", () => {
    expect(isMissingHandler("нет обработчика kind='tg_cleanup'")).toBe(true)
    expect(isMissingHandler("timeout")).toBe(false)
  })
})

describe("itemsForReason", () => {
  it("режет список по виду и усечённой причине", () => {
    const items = [
      task({ id: 1 }),
      task({ id: 2, last_error: "timeout" }),
      task({ id: 3, kind: "tg_push" }),
    ]
    expect(
      itemsForReason(items, {
        kind: "tg_cleanup",
        reason: "нет обработчика kind='tg_cleanup'",
        status: "failed",
      }).map((row) => row.id),
    ).toEqual([1])
  })
})

describe("taskReasonKey", () => {
  it("не склеивает вид и причину", () => {
    expect(taskReasonKey("a", "b")).not.toBe(taskReasonKey("ab", ""))
    expect(taskReasonKey("a", "b", "failed")).not.toBe(taskReasonKey("a", "b", "done"))
  })
})
