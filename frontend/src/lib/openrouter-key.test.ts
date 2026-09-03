import { describe, expect, it } from "vitest"
import { looksLikeOpenRouterKey, sanitizeOpenRouterKey } from "./openrouter-key"

describe("sanitizeOpenRouterKey", () => {
  it("срезает пробелы и переносы вокруг ключа", () => {
    expect(sanitizeOpenRouterKey("  sk-or-v1-abcdefghijklmnop\n")).toBe("sk-or-v1-abcdefghijklmnop")
  })

  it("пустую строку не превращает в мусор", () => {
    expect(sanitizeOpenRouterKey("")).toBe("")
    expect(sanitizeOpenRouterKey(" \n ")).toBe("")
  })
})

describe("looksLikeOpenRouterKey", () => {
  it("принимает ключ с хвостом перевода строки", () => {
    expect(looksLikeOpenRouterKey("sk-or-v1-abcdefghijklmnop\n")).toBe(true)
  })

  it("отсекает чужой префикс и короткий мусор", () => {
    expect(looksLikeOpenRouterKey("sk-live-abcdefghijklmnop")).toBe(false)
    expect(looksLikeOpenRouterKey("sk-or-short")).toBe(false)
  })
})
