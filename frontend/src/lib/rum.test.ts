import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import {
  beginInteraction,
  cancelInteraction,
  flushRum,
  getRumBuffer,
  markDone,
  markFirstToken,
  markTtfb,
  resetRumForTests,
  stopRumForTests,
} from "./rum"

describe("rum.ts (L-04)", () => {
  beforeEach(() => {
    resetRumForTests()
    stopRumForTests()
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true }))
  })

  afterEach(() => {
    resetRumForTests()
    stopRumForTests()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it("пишет метки клик → ttfb / first_token / done", () => {
    vi.spyOn(performance, "now")
      .mockReturnValueOnce(1000) // begin
      .mockReturnValueOnce(1180) // ttfb
      .mockReturnValueOnce(1500) // first_token
      .mockReturnValueOnce(3200) // done

    beginInteraction("chat", "/api/chat/stream")
    markTtfb()
    markFirstToken()
    markDone()

    const kinds = getRumBuffer().map((e) => e.kind)
    expect(kinds).toEqual(["rum_ttfb", "rum_first_token", "rum_done"])
    expect(getRumBuffer()[0]).toMatchObject({
      level: "INFO",
      duration_ms: 180,
      endpoint: "/api/chat/stream",
      message: expect.stringContaining("первый байт"),
    })
    expect(getRumBuffer()[1]?.duration_ms).toBe(500)
    expect(getRumBuffer()[2]?.duration_ms).toBe(2200)
  })

  it("не дублирует одну и ту же метку", () => {
    beginInteraction("screening")
    markTtfb()
    markTtfb()
    expect(getRumBuffer()).toHaveLength(1)
  })

  it("cancelInteraction сбрасывает активное без done", () => {
    beginInteraction("chat")
    markTtfb()
    cancelInteraction()
    markDone()
    expect(getRumBuffer().map((e) => e.kind)).toEqual(["rum_ttfb"])
  })

  it("flushRum шлёт пачку на /api/logs/frontend", async () => {
    beginInteraction("chat")
    markTtfb()
    markDone()
    await flushRum()
    expect(fetch).toHaveBeenCalledWith(
      "/api/logs/frontend",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
      }),
    )
    const body = JSON.parse(
      (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][1].body as string,
    )
    expect(body.entries).toHaveLength(2)
    expect(body.entries[0].kind).toBe("rum_ttfb")
    expect(getRumBuffer()).toHaveLength(0)
  })
})
