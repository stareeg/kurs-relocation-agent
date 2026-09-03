import { describe, expect, it } from "vitest"
import {
  ADMIN_SECTIONS,
  ADMIN_SORT_COLUMNS,
  DEFAULT_ADMIN_FILTERS,
  DEFAULT_PEOPLE_COLS,
  adminFiltersActive,
  adminFiltersToParams,
  adminPeopleFilterCount,
  adminPeoplePath,
  adminPersonPath,
  adminRedirectPath,
  adminSectionPath,
  adminSortDirection,
  applyPeopleScope,
  isAdminSortKey,
  isProblemPerson,
  parseAdminAccountId,
  parseAdminFilters,
  parseAdminUserTab,
  parsePeopleCols,
  PEOPLE_ONBOARDING_CHIPS,
  PEOPLE_SIGNAL_CHIPS,
  PEOPLE_SORTABLE_COLUMNS,
  PEOPLE_STATUS_CHIPS,
  PEOPLE_FILTER_CHECKBOXES,
  peopleApiStatus,
  peopleScopeFromFilters,
  resetAdminPeopleFilters,
  resolveAdminSection,
  statusChipValue,
  statusFromChip,
  toggleAdminSort,
  toggleExclusive,
  togglePeopleCol,
  withPreservedTab,
} from "./admin-filters"

const parse = (search: string) => parseAdminFilters(new URLSearchParams(search))

describe("resolveAdminSection", () => {
  it("белый список — три экрана, Пульт без сегмента в адресе", () => {
    expect([...ADMIN_SECTIONS]).toEqual(["dashboard", "system", "journal"])
    expect(adminSectionPath("dashboard")).toBe("/admin")
    expect(adminSectionPath("journal")).toBe("/admin/journal")
    expect(adminSectionPath("system")).toBe("/admin/system")
    expect(adminPersonPath(12)).toBe("/admin/person/12")
  })

  it("знакомый раздел проходит как есть", () => {
    expect(resolveAdminSection("dashboard")).toBe("dashboard")
    expect(resolveAdminSection("journal")).toBe("journal")
    expect(resolveAdminSection("system")).toBe("system")
  })

  it("чужой раздел ведёт на пульт, а не в пустоту", () => {
    expect(resolveAdminSection("hacked")).toBe("dashboard")
    expect(resolveAdminSection("overview")).toBe("dashboard")
    expect(resolveAdminSection("people")).toBe("dashboard")
    expect(resolveAdminSection("keys")).toBe("dashboard")
    expect(resolveAdminSection("person")).toBe("dashboard")
    expect(resolveAdminSection(undefined)).toBe("dashboard")
  })
})

describe("adminRedirectPath", () => {
  it("канонические адреса не трогает", () => {
    expect(adminRedirectPath(undefined, undefined)).toBeNull()
    expect(adminRedirectPath("journal", undefined)).toBeNull()
    expect(adminRedirectPath("system", undefined)).toBeNull()
    expect(adminRedirectPath("person", "12")).toBeNull()
    expect(adminRedirectPath("person", "12", "tab=spend")).toBeNull()
  })

  it("старые адреса приводит к новым вместе с фильтрами", () => {
    expect(adminRedirectPath("overview", undefined)).toBe("/admin")
    expect(adminRedirectPath("people", undefined, "?status=disabled")).toBe("/admin?status=disabled")
    expect(adminRedirectPath("keys", undefined)).toBe("/admin")
    expect(adminRedirectPath("dashboard", undefined)).toBe("/admin")
    expect(adminRedirectPath("people", "12")).toBe("/admin/person/12")
    expect(adminRedirectPath("keys", "12", "?tab=spend")).toBe("/admin/person/12?tab=spend")
    expect(adminRedirectPath("journal", "4")).toBe("/admin/person/4")
  })

  it("мусорный id не открывает пустой дровер", () => {
    expect(adminRedirectPath("person", "abc")).toBe("/admin")
    expect(adminRedirectPath("person", "-1")).toBe("/admin")
    expect(adminRedirectPath("person", undefined)).toBe("/admin")
    expect(adminRedirectPath("people", "abc")).toBe("/admin")
    expect(parseAdminAccountId("abc")).toBeNull()
    expect(parseAdminAccountId("12")).toBe(12)
  })
})

describe("parseAdminFilters", () => {
  it("читает все параметры, включая сигнал", () => {
    expect(parse("?q=kate&status=disabled&onboarding=no_key&signal=stale&sort=-cost_month")).toEqual({
      q: "kate",
      status: "disabled",
      onboarding: "no_key",
      signal: "stale",
      sort: "-cost_month",
      scope: "",
      cols: DEFAULT_PEOPLE_COLS,
    })
  })

  it("пустой адрес — значения по умолчанию", () => {
    expect(parse("")).toEqual(DEFAULT_ADMIN_FILTERS)
  })

  it("незнакомое значение игнорируется: старая ссылка обязана открыть список", () => {
    const filters = parse("?status=deleted&onboarding=hacked&signal=all&sort=drop%20table")
    expect(filters.status).toBe("")
    expect(filters.onboarding).toBe("")
    expect(filters.signal).toBe("")
    expect(filters.sort).toBe("")
  })

  it("обрезает пробелы вокруг поиска", () => {
    expect(parse("?q=%20%20kate%20%20").q).toBe("kate")
  })
})

describe("adminFiltersToParams", () => {
  it("не пишет значения по умолчанию — ссылка не обрастает мусором", () => {
    expect(adminFiltersToParams(DEFAULT_ADMIN_FILTERS).toString()).toBe("")
  })

  it("разбор и сборка обратимы", () => {
    const search = "q=kate&status=active&onboarding=no_resume&signal=errors&sort=errors"
    expect(adminFiltersToParams(parse(`?${search}`)).toString()).toBe(search)
  })
})

describe("adminFiltersActive", () => {
  it("сортировка не считается фильтром: она ничего не прячет", () => {
    expect(adminFiltersActive({ ...DEFAULT_ADMIN_FILTERS, sort: "-errors" })).toBe(false)
    expect(adminFiltersActive({ ...DEFAULT_ADMIN_FILTERS, q: "kate" })).toBe(true)
    expect(adminFiltersActive({ ...DEFAULT_ADMIN_FILTERS, status: "disabled" })).toBe(true)
    expect(adminFiltersActive({ ...DEFAULT_ADMIN_FILTERS, onboarding: "no_key" })).toBe(true)
    expect(adminFiltersActive({ ...DEFAULT_ADMIN_FILTERS, signal: "stale" })).toBe(true)
    expect(adminFiltersActive({ ...DEFAULT_ADMIN_FILTERS, scope: "problem" })).toBe(true)
  })
})

describe("adminPeoplePath", () => {
  it("клик по ступени воронки открывает Пульт с фильтром в URL", () => {
    expect(adminPeoplePath({ status: "active", onboarding: "no_key" })).toBe(
      "/admin?status=active&onboarding=no_key",
    )
    expect(adminPeoplePath({ status: "active" })).toBe("/admin?status=active")
    expect(adminPeoplePath()).toBe("/admin")
  })
})

describe("isAdminSortKey", () => {
  it("принимает каждую колонку в обе стороны", () => {
    for (const column of ADMIN_SORT_COLUMNS) {
      expect(isAdminSortKey(column)).toBe(true)
      expect(isAdminSortKey(`-${column}`)).toBe(true)
    }
  })

  it("отвергает чужое", () => {
    expect(isAdminSortKey("password")).toBe(false)
    expect(isAdminSortKey("")).toBe(false)
  })
})

describe("toggleAdminSort", () => {
  it("числовая колонка начинает с убывания: интересное сверху", () => {
    expect(toggleAdminSort("", "cost_month")).toBe("-cost_month")
    expect(toggleAdminSort("-cost_month", "cost_month")).toBe("cost_month")
    expect(toggleAdminSort("cost_month", "cost_month")).toBe("")
  })

  it("текстовая колонка начинает с «А»", () => {
    expect(toggleAdminSort("", "username")).toBe("username")
    expect(toggleAdminSort("username", "username")).toBe("-username")
    expect(toggleAdminSort("-username", "username")).toBe("")
  })

  it("клик по другой колонке сбрасывает прежнюю", () => {
    expect(toggleAdminSort("-errors", "cost_month")).toBe("-cost_month")
  })
})

describe("adminSortDirection", () => {
  it("стрелка только у активной колонки", () => {
    expect(adminSortDirection("-errors", "errors")).toBe("desc")
    expect(adminSortDirection("errors", "errors")).toBe("asc")
    expect(adminSortDirection("-errors", "cost_month")).toBeNull()
    expect(adminSortDirection("", "errors")).toBeNull()
  })
})

describe("чипы людей", () => {
  it("сегмент статуса: все и проблемные не пишут status, отключённые пишут", () => {
    expect([...PEOPLE_STATUS_CHIPS].map((chip) => chip.value)).toEqual([
      "all",
      "problem",
      "disabled",
    ])
    expect(statusFromChip("all")).toBe("")
    expect(statusFromChip("problem")).toBe("")
    expect(statusFromChip("disabled")).toBe("disabled")
    expect(statusChipValue("")).toBe("all")
    expect(statusChipValue("disabled")).toBe("disabled")
    expect(statusChipValue("active")).toBe("active")
  })

  it("каждый чип онбординга пишется в URL и читается обратно", () => {
    for (const chip of PEOPLE_ONBOARDING_CHIPS) {
      const params = adminFiltersToParams({ ...DEFAULT_ADMIN_FILTERS, onboarding: chip.value })
      expect(params.get("onboarding")).toBe(chip.value)
      expect(parseAdminFilters(params).onboarding).toBe(chip.value)
    }
  })

  it("каждый чип сигнала пишется в URL и читается обратно", () => {
    for (const chip of PEOPLE_SIGNAL_CHIPS) {
      const params = adminFiltersToParams({ ...DEFAULT_ADMIN_FILTERS, signal: chip.value })
      expect(params.get("signal")).toBe(chip.value)
      expect(parseAdminFilters(params).signal).toBe(chip.value)
    }
  })

  it("в поповере нет «есть ошибки» — это сегмент «Проблемные»", () => {
    expect(PEOPLE_FILTER_CHECKBOXES.map((chip) => chip.value)).toEqual([
      "no_key",
      "no_resume",
      "no_extension",
      "stale",
      "spend",
    ])
  })
})

describe("сортировка колонок людей", () => {
  it("каждая числовая колонка переключается убывание → возрастание → сброс", () => {
    for (const column of PEOPLE_SORTABLE_COLUMNS) {
      expect(ADMIN_SORT_COLUMNS).toContain(column)
      const desc = toggleAdminSort("", column)
      expect(desc).toBe(`-${column}`)
      expect(isAdminSortKey(desc)).toBe(true)
      const asc = toggleAdminSort(desc, column)
      expect(asc).toBe(column)
      expect(toggleAdminSort(asc, column)).toBe("")
    }
  })
})

describe("вкладка карточки человека", () => {
  it("читает tab из адреса и игнорирует чужое значение", () => {
    expect(parseAdminUserTab(new URLSearchParams("tab=logs"))).toBe("logs")
    expect(parseAdminUserTab(new URLSearchParams("tab=hacked"))).toBe("profile")
    expect(parseAdminUserTab(new URLSearchParams(""))).toBe("profile")
  })

  it("смена фильтра не выкидывает вкладку карточки", () => {
    const current = new URLSearchParams("tab=logs&status=active")
    const next = withPreservedTab(adminFiltersToParams(parse("?q=kate")), current)
    expect(next.get("tab")).toBe("logs")
    expect(next.get("q")).toBe("kate")
    expect(next.get("status")).toBeNull()
  })

  it("вкладка по умолчанию в адрес не пишется", () => {
    const next = withPreservedTab(
      adminFiltersToParams(DEFAULT_ADMIN_FILTERS),
      new URLSearchParams("tab=profile"),
    )
    expect(next.get("tab")).toBeNull()
  })
})

describe("сегмент «Все · Проблемные · Отключённые»", () => {
  it("пишет в URL только отклонение от «Все»", () => {
    const problem = applyPeopleScope(DEFAULT_ADMIN_FILTERS, "problem")
    expect(peopleScopeFromFilters(problem)).toBe("problem")
    expect(adminFiltersToParams(problem).toString()).toBe("scope=problem")
    expect(parseAdminFilters(adminFiltersToParams(problem)).scope).toBe("problem")

    const disabled = applyPeopleScope(DEFAULT_ADMIN_FILTERS, "disabled")
    expect(peopleScopeFromFilters(disabled)).toBe("disabled")
    expect(adminFiltersToParams(disabled).get("status")).toBe("disabled")
    expect(adminFiltersToParams(disabled).has("scope")).toBe(false)

    const all = applyPeopleScope(disabled, "all")
    expect(peopleScopeFromFilters(all)).toBe("all")
    expect(adminFiltersToParams(all).toString()).toBe("")
  })

  it("проблемные и отключённые не живут в URL одновременно", () => {
    const mixed = applyPeopleScope(
      { ...DEFAULT_ADMIN_FILTERS, status: "disabled", scope: "problem" },
      "problem",
    )
    expect(mixed.status).toBe("")
    expect(mixed.scope).toBe("problem")
  })

  it("в API «Проблемные» уходят как активные — отключённые в соседнем сегменте", () => {
    expect(peopleApiStatus(DEFAULT_ADMIN_FILTERS)).toBe("")
    expect(peopleApiStatus({ ...DEFAULT_ADMIN_FILTERS, scope: "problem" })).toBe("active")
    expect(peopleApiStatus({ ...DEFAULT_ADMIN_FILTERS, status: "disabled" })).toBe("disabled")
    expect(peopleApiStatus({ ...DEFAULT_ADMIN_FILTERS, status: "active" })).toBe("active")
  })

  it("старая ссылка ?status=active по-прежнему читается", () => {
    const filters = parse("?status=active")
    expect(filters.status).toBe("active")
    expect(peopleScopeFromFilters(filters)).toBe("all")
    expect(peopleApiStatus(filters)).toBe("active")
  })
})

describe("счётчик и сброс фильтров", () => {
  it("считает нажатое в поповере, не поиск и не сортировку", () => {
    expect(adminPeopleFilterCount(DEFAULT_ADMIN_FILTERS)).toBe(0)
    expect(adminPeopleFilterCount({ ...DEFAULT_ADMIN_FILTERS, q: "kate", sort: "-errors" })).toBe(0)
    expect(
      adminPeopleFilterCount({
        ...DEFAULT_ADMIN_FILTERS,
        status: "disabled",
        onboarding: "no_key",
        signal: "stale",
      }),
    ).toBe(3)
    expect(adminPeopleFilterCount({ ...DEFAULT_ADMIN_FILTERS, scope: "problem" })).toBe(1)
  })

  it("сброс снимает ограничения списка и оставляет поиск, сортировку и колонки", () => {
    const current = {
      ...DEFAULT_ADMIN_FILTERS,
      q: "kate",
      status: "disabled" as const,
      onboarding: "no_key" as const,
      signal: "stale" as const,
      sort: "-errors",
      cols: togglePeopleCol(DEFAULT_PEOPLE_COLS, "jobs"),
    }
    const reset = resetAdminPeopleFilters(current)
    expect(reset.status).toBe("")
    expect(reset.scope).toBe("")
    expect(reset.onboarding).toBe("")
    expect(reset.signal).toBe("")
    expect(reset.q).toBe("kate")
    expect(reset.sort).toBe("-errors")
    expect(reset.cols).toEqual(current.cols)
    expect(adminPeopleFilterCount(reset)).toBe(0)
  })
})

describe("видимость колонок в URL", () => {
  it("дефолт колонок в адрес не пишется", () => {
    expect(DEFAULT_PEOPLE_COLS).toEqual([
      "person",
      "key",
      "resume",
      "extension",
      "seen",
      "jobs",
      "cost_today",
      "cost_month",
      "errors",
    ])
    expect(adminFiltersToParams(DEFAULT_ADMIN_FILTERS).has("cols")).toBe(false)
    expect(parsePeopleCols(null)).toEqual(DEFAULT_PEOPLE_COLS)
    expect(parsePeopleCols("")).toEqual(DEFAULT_PEOPLE_COLS)
  })

  it("снятая колонка уходит из URL, person снять нельзя", () => {
    const withoutKey = togglePeopleCol(DEFAULT_PEOPLE_COLS, "key")
    expect(withoutKey).not.toContain("key")
    expect(withoutKey[0]).toBe("person")
    expect(togglePeopleCol(withoutKey, "person")).toEqual(withoutKey)
    expect(parsePeopleCols("jobs,spark,hacked")).toEqual(["person", "jobs"])
  })

  it("старая ссылка tab=actions открывает профиль", () => {
    expect(parseAdminUserTab(new URLSearchParams("tab=actions"))).toBe("profile")
  })
})

describe("isProblemPerson", () => {
  const healthy = {
    status: "active",
    errors_24h: 0,
    spend_alert: false,
    has_openrouter_key: true,
    has_resume: true,
    extension_confirmed: true,
    last_seen_at: new Date("2026-08-25T12:00:00Z").toISOString(),
  }
  const now = Date.parse("2026-08-25T12:00:00Z")

  it("здоровый активный — не проблемный", () => {
    expect(isProblemPerson(healthy, now)).toBe(false)
  })

  it("ломается на любой одной дыре", () => {
    expect(isProblemPerson({ ...healthy, errors_24h: 1 }, now)).toBe(true)
    expect(isProblemPerson({ ...healthy, spend_alert: true }, now)).toBe(true)
    expect(isProblemPerson({ ...healthy, has_openrouter_key: false }, now)).toBe(true)
    expect(isProblemPerson({ ...healthy, has_resume: false }, now)).toBe(true)
    expect(isProblemPerson({ ...healthy, extension_confirmed: false }, now)).toBe(true)
    expect(isProblemPerson({ ...healthy, last_seen_at: null }, now)).toBe(true)
  })

  it("отключённый не попадает в «Проблемные» — у него свой сегмент", () => {
    expect(isProblemPerson({ ...healthy, status: "disabled", errors_24h: 4 }, now)).toBe(false)
  })
})

describe("toggleExclusive", () => {
  it("повторный клик снимает, соседний заменяет", () => {
    expect(toggleExclusive("", "no_key")).toBe("no_key")
    expect(toggleExclusive("no_key", "no_key")).toBe("")
    expect(toggleExclusive("no_key", "no_resume")).toBe("no_resume")
  })
})
