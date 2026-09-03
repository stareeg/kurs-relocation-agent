import { describe, expect, it } from "vitest"
import { looksLikeBotAuthToken } from "./web-auth-token"

describe("looksLikeBotAuthToken", () => {
  it("accepts a plain urlsafe owner token (~32 chars)", () => {
    expect(looksLikeBotAuthToken("Ab3_x-9KpQ72LmNzR4tUv8WyE1cD5fGh")).toBe(true)
    expect(looksLikeBotAuthToken("  Ab3_x-9KpQ72LmNzR4tUv8WyE1cD5fGh  ")).toBe(true)
  })

  it("accepts a portable guest token cc.<payload>.<secret>", () => {
    expect(looksLikeBotAuthToken("cc.eyJ1Ijo0MiwibiI6ImZyaWVuZCJ9.R4tUv8WyE1cD5fGhAb3x")).toBe(true)
  })

  it("rejects short garbage and non-token text", () => {
    expect(looksLikeBotAuthToken("")).toBe(false)
    expect(looksLikeBotAuthToken("hello")).toBe(false)
    expect(looksLikeBotAuthToken("вставьте токен из бота")).toBe(false)
    expect(looksLikeBotAuthToken("cc.short.x")).toBe(false)
    expect(looksLikeBotAuthToken("has spaces inside the pasted line")).toBe(false)
  })
})
