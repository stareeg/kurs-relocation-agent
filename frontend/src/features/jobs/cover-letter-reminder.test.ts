import { describe, expect, it, beforeEach } from "vitest"
import {
  _resetCoverLetterReminderDismissalsForTests,
  dismissCoverLetterReminder,
  needsCoverLetterReminder,
} from "./cover-letter-reminder"

describe("needsCoverLetterReminder (FR3-65/68)", () => {
  beforeEach(() => _resetCoverLetterReminderDismissalsForTests())

  it("true только когда площадка требует и текста нет", () => {
    expect(
      needsCoverLetterReminder({ id: 1, letter_required: true, cover_letter_text: null }),
    ).toBe(true)
    expect(
      needsCoverLetterReminder({ id: 1, letter_required: true, cover_letter_text: "  " }),
    ).toBe(true)
  })

  it("false если письмо не требуется или текст уже есть", () => {
    expect(
      needsCoverLetterReminder({ id: 1, letter_required: false, cover_letter_text: null }),
    ).toBe(false)
    expect(
      needsCoverLetterReminder({ id: 1, letter_required: null, cover_letter_text: null }),
    ).toBe(false)
    expect(
      needsCoverLetterReminder({
        id: 1,
        letter_required: true,
        cover_letter_text: "Готовый черновик",
      }),
    ).toBe(false)
  })

  it("не показывает повторно после dismiss в сессии", () => {
    const job = { id: 42, letter_required: true as const, cover_letter_text: null }
    expect(needsCoverLetterReminder(job)).toBe(true)
    dismissCoverLetterReminder(42)
    expect(needsCoverLetterReminder(job)).toBe(false)
  })
})
