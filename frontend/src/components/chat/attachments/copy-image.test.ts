// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { copyImageToClipboard, isPngMime, toPngBlob } from "./copy-image"

describe("isPngMime", () => {
  it("image/png — true", () => {
    expect(isPngMime("image/png")).toBe(true)
  })

  it("image/webp — false", () => {
    expect(isPngMime("image/webp")).toBe(false)
  })
})

describe("toPngBlob", () => {
  it("уже PNG — возвращает тот же blob без конверсии (canvas недоступен в jsdom)", async () => {
    const blob = new Blob(["x"], { type: "image/png" })
    await expect(toPngBlob(blob)).resolves.toBe(blob)
  })
})

describe("copyImageToClipboard", () => {
  let writeMock: ReturnType<typeof vi.fn>
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    writeMock = vi.fn().mockImplementation(async (items: { data: Record<string, unknown> }[]) => {
      // Как Safari: write резолвится только когда промисы внутри ClipboardItem готовы.
      for (const item of items) {
        for (const value of Object.values(item.data)) {
          await value
        }
      }
    })
    Object.defineProperty(globalThis.navigator, "clipboard", {
      value: { write: writeMock },
      configurable: true,
    })
    ;(globalThis as unknown as { ClipboardItem: unknown }).ClipboardItem = function (
      this: { data: Record<string, unknown> },
      data: Record<string, unknown>,
    ) {
      this.data = data
    }
    fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("PNG-байты по same-origin URL уходят прямо в буфер обмена, с credentials", async () => {
    const pngBlob = new Blob(["x"], { type: "image/png" })
    fetchMock.mockResolvedValue({ ok: true, blob: () => Promise.resolve(pngBlob) })

    await copyImageToClipboard("/api/attachments/1")

    expect(fetchMock).toHaveBeenCalledWith("/api/attachments/1", { credentials: "include" })
    expect(writeMock).toHaveBeenCalledTimes(1)
    const [items] = writeMock.mock.calls[0] as [{ data: Record<string, Promise<Blob> | Blob> }[]]
    const pngSlot = items[0].data["image/png"]
    // Safari-path: в ClipboardItem кладётся Promise, не готовый Blob.
    await expect(Promise.resolve(pngSlot)).resolves.toBe(pngBlob)
  })

  it("сеть отвечает не-2xx — падает с понятной ошибкой", async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 404 })

    await expect(copyImageToClipboard("/api/attachments/999")).rejects.toThrow("404")
    expect(writeMock).toHaveBeenCalledTimes(1)
  })
})
