import { describe, expect, it } from "vitest"
import {
  adminSystemPath,
  DEFAULT_SYSTEM_FILTERS,
  isTaskStatus,
  parseSystemFilters,
  systemFiltersToParams,
  taskStatusLabel,
  taskStatusTone,
  tasksQueryStatus,
} from "./system-filters"

const parse = (search: string) => parseSystemFilters(new URLSearchParams(search))

describe("parseSystemFilters", () => {
  it("без статуса — все", () => {
    expect(parse("")).toEqual(DEFAULT_SYSTEM_FILTERS)
    expect(parse("?kind=tg_push")).toEqual({ status: "all", kind: "tg_push" })
  })

  it("читает статус и вид", () => {
    expect(parse("?status=pending&kind=tg_push")).toEqual({ status: "pending", kind: "tg_push" })
    expect(parse("?status=failed")).toEqual({ status: "failed", kind: "" })
  })

  it("незнакомый статус — как будто фильтра нет", () => {
    expect(parse("?status=hacked&kind=%20")).toEqual(DEFAULT_SYSTEM_FILTERS)
  })
})

describe("systemFiltersToParams", () => {
  it("не пишет значения по умолчанию", () => {
    expect(systemFiltersToParams(DEFAULT_SYSTEM_FILTERS).toString()).toBe("")
  })

  it("разбор и сборка обратимы", () => {
    const search = "status=running&kind=salary_estimate"
    expect(systemFiltersToParams(parse(`?${search}`)).toString()).toBe(search)
  })
})

describe("adminSystemPath", () => {
  it("собирает ссылку с Обзора", () => {
    expect(adminSystemPath({ status: "failed", kind: "tg_push" })).toBe(
      "/admin/system?status=failed&kind=tg_push",
    )
    expect(adminSystemPath()).toBe("/admin/system")
  })
})

describe("tasksQueryStatus", () => {
  it("все — пустой фильтр API", () => {
    expect(tasksQueryStatus("all")).toBe("")
    expect(tasksQueryStatus("failed")).toBe("failed")
  })
})

describe("taskStatusLabel", () => {
  it("называет статусы по-русски", () => {
    expect(taskStatusLabel("failed")).toBe("Сбой")
    expect(taskStatusTone("failed")).toBe("bad")
    expect(taskStatusTone("done")).toBe("strong")
  })
})

describe("isTaskStatus", () => {
  it("белый список", () => {
    expect(isTaskStatus("pending")).toBe(true)
    expect(isTaskStatus("queued")).toBe(false)
  })
})
