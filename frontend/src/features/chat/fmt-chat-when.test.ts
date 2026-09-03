import { describe, expect, it } from "vitest"
import { CHAT_LIST_TITLE_MAX, clipChatListTitle, fmtChatWhen } from "./fmt-chat-when"

describe("clipChatListTitle", () => {
  it("не трогает строку до лимита", () => {
    expect(clipChatListTitle("Анастасия")).toBe("Анастасия")
    expect(clipChatListTitle("а".repeat(CHAT_LIST_TITLE_MAX))).toBe("а".repeat(23))
  })

  it("обрезает имя HR / название вакансии до 23 символов", () => {
    const long = "Александра Константинопольская"
    expect(long.length).toBeGreaterThan(23)
    expect(clipChatListTitle(long)).toBe(`${long.slice(0, 23)}…`)
    expect(clipChatListTitle(long).replace(/…$/, "").length).toBe(23)
  })
})

describe("fmtChatWhen", () => {
  it("для прошедшего дня отдаёт ДД.ММ", () => {
    expect(fmtChatWhen("2026-08-20T10:15:00")).toBe("20.08")
  })
})
