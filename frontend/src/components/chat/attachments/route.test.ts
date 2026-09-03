import { describe, expect, it } from "vitest"
import { defaultAttachmentRoute, isLowConfidenceRoute } from "./route"
import type { AttachmentAnalysis } from "@/api/attachments"

function analysis(overrides: Partial<AttachmentAnalysis> = {}): AttachmentAnalysis {
  return {
    kind: "document",
    title: "t",
    summary: "s",
    text: "text",
    confidence: 0.9,
    ...overrides,
  }
}

describe("defaultAttachmentRoute", () => {
  it("correspondence kind → correspondence", () => {
    expect(defaultAttachmentRoute(analysis({ kind: "correspondence" }))).toBe("correspondence")
  })

  it("любой другой kind → material", () => {
    expect(defaultAttachmentRoute(analysis({ kind: "diagram" }))).toBe("material")
  })

  it("нет анализа → material", () => {
    expect(defaultAttachmentRoute(null)).toBe("material")
    expect(defaultAttachmentRoute(undefined)).toBe("material")
  })
})

describe("isLowConfidenceRoute", () => {
  it("< 0.6 — не уверен", () => {
    expect(isLowConfidenceRoute(analysis({ confidence: 0.4 }))).toBe(true)
  })

  it(">= 0.6 — уверен", () => {
    expect(isLowConfidenceRoute(analysis({ confidence: 0.6 }))).toBe(false)
    expect(isLowConfidenceRoute(analysis({ confidence: 0.9 }))).toBe(false)
  })

  it("нет анализа — считаем уверенным (нечего раскрывать)", () => {
    expect(isLowConfidenceRoute(null)).toBe(false)
  })
})
