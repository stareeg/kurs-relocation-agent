import { describe, expect, it } from "vitest"
import type { AppSettings } from "@/api/settings"
import { hasOpenRouterKey, openRouterKeyView } from "./openrouter-key-state"

function settings(patch: Partial<AppSettings>): AppSettings {
  return {
    openrouter_key_configured: false,
    openrouter_key_origin: null,
    openrouter_key_request_status: null,
    ...patch,
  } as AppSettings
}

describe("openRouterKeyView", () => {
  it("ключа нет, но серверная модель настроена — доступ уже есть, ключ не нужен", () => {
    const view = openRouterKeyView(settings({ server_llm_available: true }))
    expect(view).toBe("server")
    expect(hasOpenRouterKey(view)).toBe(true)
  })

  it("свой ключ на стенде работает только с включённым тумблером", () => {
    expect(
      openRouterKeyView(
        settings({
          openrouter_key_configured: true,
          openrouter_key_origin: "self",
          server_llm_available: true,
          use_personal_openrouter_key: true,
          personal_openrouter_key_active: true,
        }),
      ),
    ).toBe("own")
  })

  it("ключ есть, но тумблер выключен — это модель курса", () => {
    expect(
      openRouterKeyView(
        settings({
          openrouter_key_configured: true,
          openrouter_key_origin: "self",
          server_llm_available: true,
          personal_openrouter_key_active: false,
        }),
      ),
    ).toBe("server")
  })

  it("без серверного провайдера свой ключ работает без тумблера", () => {
    expect(
      openRouterKeyView(
        settings({
          openrouter_key_configured: true,
          openrouter_key_origin: "self",
          server_llm_available: false,
        }),
      ),
    ).toBe("own")
  })

  it("ключа нет и заявок не было — просим ключ", () => {
    expect(openRouterKeyView(settings({}))).toBe("missing")
  })

  it("заявка в работе — кнопка запроса блокируется", () => {
    expect(openRouterKeyView(settings({ openrouter_key_request_status: "pending" }))).toBe(
      "requested",
    )
    expect(openRouterKeyView(settings({ openrouter_key_request_status: "approved" }))).toBe(
      "requested",
    )
  })

  it("по заявке отказали — состояние отдельное от «заявок не было»", () => {
    expect(openRouterKeyView(settings({ openrouter_key_request_status: "rejected" }))).toBe(
      "rejected",
    )
  })

  it("ключ выдан администратором — свой отдельный вид без кнопки сброса", () => {
    expect(
      openRouterKeyView(
        settings({ openrouter_key_configured: true, openrouter_key_origin: "admin" }),
      ),
    ).toBe("managed")
  })

  it("свой ключ", () => {
    expect(
      openRouterKeyView(
        settings({ openrouter_key_configured: true, openrouter_key_origin: "self" }),
      ),
    ).toBe("own")
  })

  it("ключ есть, происхождение неизвестно (старая БД) — считаем своим", () => {
    expect(openRouterKeyView(settings({ openrouter_key_configured: true }))).toBe("own")
  })

  it("закрытая заявка не отменяет уже выданный ключ", () => {
    const view = openRouterKeyView(
      settings({
        openrouter_key_configured: true,
        openrouter_key_origin: "admin",
        openrouter_key_request_status: "fulfilled",
      }),
    )
    expect(view).toBe("managed")
    expect(hasOpenRouterKey(view)).toBe(true)
  })
})

describe("hasOpenRouterKey", () => {
  it("гейт открыт только когда ключ реально есть", () => {
    expect(hasOpenRouterKey("own")).toBe(true)
    expect(hasOpenRouterKey("managed")).toBe(true)
    expect(hasOpenRouterKey("server")).toBe(true)
    expect(hasOpenRouterKey("requested")).toBe(false)
    expect(hasOpenRouterKey("rejected")).toBe(false)
    expect(hasOpenRouterKey("missing")).toBe(false)
  })
})
