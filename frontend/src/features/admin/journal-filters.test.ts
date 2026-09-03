import { describe, expect, it } from "vitest"
import {
  DEFAULT_JOURNAL_FILTERS,
  adminJournalPath,
  auditActionLabel,
  isJournalWindow,
  journalFiltersToParams,
  journalRequestWindow,
  journalWindowBounds,
  logLevelTone,
  parseJournalFilters,
  parseJournalLevels,
} from "./journal-filters"

const parse = (search: string) => parseJournalFilters(new URLSearchParams(search))

describe("parseJournalFilters", () => {
  it("пустой адрес — значения по умолчанию: час, ERROR+WARNING, живой хвост", () => {
    expect(parse("")).toEqual(DEFAULT_JOURNAL_FILTERS)
  })

  it("читает параметры журнала", () => {
    const filters = parse("?window=24h&level=ERROR&telegram_user_id=9&live=0&cursor=1:x")
    expect(filters.window).toBe("24h")
    expect(filters.levels).toEqual(["ERROR"])
    expect(filters.telegramUserId).toBe("9")
    expect(filters.live).toBe(false)
    expect(filters.cursor).toBe("1:x")
  })

  it("незнакомые значения игнорируются: старая ссылка обязана открыть журнал", () => {
    const filters = parse("?view=audit&window=custom&level=FATAL")
    expect(filters.window).toBe("1h")
    expect(filters.levels).toEqual(["ERROR", "WARNING"])
    expect(filters.telegramUserId).toBe("")
    expect(filters.accountId).toBe("")
  })
})

describe("journalFiltersToParams", () => {
  it("не пишет значения по умолчанию", () => {
    expect(journalFiltersToParams(DEFAULT_JOURNAL_FILTERS).toString()).toBe("")
  })

  it("разбор и сборка обратимы для не-дефолтных", () => {
    const search = "window=15m&level=INFO&telegram_user_id=4&live=0"
    expect(journalFiltersToParams(parse(`?${search}`)).toString()).toBe(search)
  })
})

describe("adminJournalPath", () => {
  it("карточка ошибок ведёт в журнал с фильтром по telegram id", () => {
    expect(adminJournalPath({ telegramUserId: "9", window: "1h" })).toBe(
      "/admin/journal?telegram_user_id=9",
    )
    expect(adminJournalPath({ window: "24h", levels: ["ERROR"] })).toBe(
      "/admin/journal?window=24h&level=ERROR",
    )
  })
})

describe("journalWindowBounds", () => {
  it("пресеты — скользящее окно от now", () => {
    const now = Date.parse("2026-08-25T15:00:00.000Z")
    expect(isJournalWindow("15m")).toBe(true)
    expect(isJournalWindow("custom")).toBe(false)
    const hour = journalWindowBounds("1h", now)
    expect(hour.until).toBe("2026-08-25T15:00:00.000Z")
    expect(hour.since).toBe("2026-08-25T14:00:00.000Z")
    expect(journalRequestWindow({ ...DEFAULT_JOURNAL_FILTERS, window: "15m" }, now).since).toBe(
      "2026-08-25T14:45:00.000Z",
    )
  })
})

describe("logLevelTone", () => {
  it("цвет только у уровней, которые требуют взгляда", () => {
    expect(logLevelTone("ERROR")).toBe("bad")
    expect(logLevelTone("CRITICAL")).toBe("bad")
    expect(logLevelTone("WARNING")).toBe("warn")
    expect(logLevelTone("INFO")).toBe("info")
    expect(logLevelTone("DEBUG")).toBeNull()
  })
})

describe("auditActionLabel", () => {
  it("называет известные действия по-русски", () => {
    expect(auditActionLabel("log_bundle")).toBe("Скачал логи файлом")
    expect(auditActionLabel("mystery")).toBe("mystery")
  })
})

describe("parseJournalLevels", () => {
  it("пустая строка — дефолт, не «все уровни»", () => {
    expect(parseJournalLevels("")).toEqual(["ERROR", "WARNING"])
    expect(parseJournalLevels("ERROR,INFO")).toEqual(["ERROR", "INFO"])
  })
})
