// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest"
import { copyText } from "./clipboard"

describe("copyText", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    document.body.innerHTML = ""
  })

  it("uses navigator.clipboard.writeText when available", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(globalThis.navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    })
    await expect(copyText("token-abc")).resolves.toBe(true)
    expect(writeText).toHaveBeenCalledWith("token-abc")
  })

  it("falls back to execCommand when clipboard.writeText rejects", async () => {
    Object.defineProperty(globalThis.navigator, "clipboard", {
      value: { writeText: vi.fn().mockRejectedValue(new Error("NotAllowedError")) },
      configurable: true,
    })
    Object.defineProperty(document, "execCommand", {
      value: vi.fn().mockReturnValue(true),
      configurable: true,
    })
    await expect(copyText("token-xyz")).resolves.toBe(true)
    expect(document.execCommand).toHaveBeenCalledWith("copy")
  })

  it("empty string → false without touching clipboard", async () => {
    const writeText = vi.fn()
    Object.defineProperty(globalThis.navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    })
    await expect(copyText("")).resolves.toBe(false)
    expect(writeText).not.toHaveBeenCalled()
  })
})
