// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest"
import { downloadLogsBundle } from "./logs"

describe("downloadLogsBundle", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  function stubDownloadClick(): string[] {
    const clicks: string[] = []
    vi.stubGlobal(
      "URL",
      Object.assign(URL, {
        createObjectURL: () => "blob:mock",
        revokeObjectURL: vi.fn(),
      }),
    )
    const realCreate = document.createElement.bind(document)
    vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      const el = realCreate(tag)
      if (tag === "a") {
        el.click = () => {
          clicks.push(el.download)
        }
      }
      return el
    })
    return clicks
  }

  it("вешает <a download> в document и кликает по zip с бэкенда", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(async (url: string) => {
        if (String(url).includes("/api/logs/frontend")) {
          return new Response(null, { status: 204 })
        }
        return new Response(new Blob(["PK"]), {
          status: 200,
          headers: {
            "Content-Type": "application/zip",
            "Content-Disposition": 'attachment; filename="support_bundle-test.zip"',
          },
        })
      }),
    )
    const clicks = stubDownloadClick()
    const result = await downloadLogsBundle()
    expect(result).toBe("full")
    expect(clicks).toEqual(["support_bundle-test.zip"])
  })

  it("при 500 бандла скачивает клиентский JSON, а не глотает клик", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Internal Server Error" }), {
          status: 500,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    )
    const clicks = stubDownloadClick()
    const result = await downloadLogsBundle()
    expect(result).toBe("fallback")
    expect(clicks).toHaveLength(1)
    expect(clicks[0]).toMatch(/^copilot-incident-frontend-only-/)
  })
})
