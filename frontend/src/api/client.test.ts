import { afterEach, describe, expect, it, vi } from "vitest"
import {
  ApiError,
  apiFetch,
  DEFAULT_TIMEOUT_MS,
  errorMessageFromBody,
  NETWORK_UNAVAILABLE_MSG,
  REQUEST_TIMEOUT_MSG,
} from "./client"

describe("apiFetch FR2-68", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it("при Failed to fetch отдаёт человеческое сообщение и status 0", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")))
    await expect(apiFetch("/api/health")).rejects.toMatchObject({
      name: "ApiError",
      status: 0,
      message: NETWORK_UNAVAILABLE_MSG,
    })
  })

  it("по таймауту AbortController отдаёт REQUEST_TIMEOUT_MSG", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url: string, init?: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            init?.signal?.addEventListener("abort", () => {
              reject(new DOMException("Aborted", "AbortError"))
            })
          }),
      ),
    )
    await expect(apiFetch("/api/slow", { timeoutMs: 20 })).rejects.toMatchObject({
      name: "ApiError",
      message: REQUEST_TIMEOUT_MSG,
    })
  })

  it("дефолтный таймаут — DEFAULT_TIMEOUT_MS", () => {
    expect(DEFAULT_TIMEOUT_MS).toBe(30_000)
  })

  it("A-15: достаёт человекочитаемое message из конверта detail", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: {
              code: "invalid_input",
              message: "нужен текст вакансии",
              details: {},
            },
          }),
          { status: 400, headers: { "Content-Type": "application/json" } },
        ),
      ),
    )
    await expect(apiFetch("/api/x")).rejects.toMatchObject({
      name: "ApiError",
      status: 400,
      message: "нужен текст вакансии",
      code: "invalid_input",
    })
  })

  it("A-15: errorMessageFromBody понимает строковый и объектный detail", () => {
    expect(errorMessageFromBody({ detail: "просто текст" }, "x")).toBe("просто текст")
    expect(
      errorMessageFromBody(
        { detail: { code: "llm_error", message: "нет ключа", details: {} } },
        "x",
      ),
    ).toBe("нет ключа")
    expect(errorMessageFromBody(undefined, "fallback")).toBe("fallback")
  })

  it("явная отмена через signal не маскируется в network-сообщение", async () => {
    const ctrl = new AbortController()
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url: string, init?: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            init?.signal?.addEventListener("abort", () => {
              reject(new DOMException("Aborted", "AbortError"))
            })
          }),
      ),
    )
    const pending = apiFetch("/api/x", { signal: ctrl.signal, timeoutMs: 0 })
    ctrl.abort()
    await expect(pending).rejects.toBeInstanceOf(DOMException)
    await expect(pending).rejects.not.toBeInstanceOf(ApiError)
  })
})
