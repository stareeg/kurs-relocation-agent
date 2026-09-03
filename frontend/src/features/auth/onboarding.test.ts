import { describe, expect, it } from "vitest"
import type { AuthStatus } from "@/api/auth"
import { homeTarget, isGateOpen, isRouteAllowedWhileGated, needsTokenLogin } from "./onboarding"

function status(overrides: Partial<AuthStatus> = {}): AuthStatus {
  return {
    authed: false,
    auth_token_configured: false,
    openrouter_key_configured: false,
    extension_confirmed: false,
    bot_configured: false,
    bot_username: null,
    account_username: null,
    is_admin: false,
    ...overrides,
  }
}

const BOOLS = [false, true] as const

describe("онбординг AUTH-1: нет мёртвых путей", () => {
  // Полный перебор состояний бэка: из любого состояния есть доступный маршрут,
  // и homeTarget всегда ведёт на него (нельзя застрять ни в одной комбинации).
  it("для всех 32 комбинаций homeTarget ведёт на достижимый маршрут", () => {
    for (const authed of BOOLS)
      for (const token of BOOLS)
        for (const key of BOOLS)
          for (const ext of BOOLS)
            for (const bot of BOOLS) {
              const s = status({
                authed,
                auth_token_configured: token,
                openrouter_key_configured: key,
                extension_confirmed: ext,
                bot_configured: bot,
              })
              const target = homeTarget(s)
              expect(["/settings", "/extension", "/jobs"]).toContain(target)
              if (!isGateOpen(s)) {
                // Гейт закрыт → ведём в Параметры, и Параметры точно доступны.
                expect(target).toBe("/settings")
                expect(isRouteAllowedWhileGated(target)).toBe(true)
              }
            }
  })

  it("гейт открыт только при полном онбординге: вход + токен + ключ", () => {
    expect(isGateOpen(status())).toBe(false)
    expect(isGateOpen(status({ authed: true }))).toBe(false)
    expect(isGateOpen(status({ authed: true, auth_token_configured: true }))).toBe(false)
    expect(isGateOpen(status({ authed: true, openrouter_key_configured: true }))).toBe(false)
    expect(
      isGateOpen(
        status({ authed: true, auth_token_configured: true, openrouter_key_configured: true }),
      ),
    ).toBe(true)
    // Токен выпущен, но запрос не авторизован (протухшая cookie) — гейт закрыт.
    expect(
      isGateOpen(status({ auth_token_configured: true, openrouter_key_configured: true })),
    ).toBe(false)
  })

  it("порядок онбординга: Параметры → Расширение → Вакансии", () => {
    // Статус ещё не загружен → безопасный дефолт.
    expect(homeTarget(undefined)).toBe("/settings")
    // Всё настроено, расширение не подтверждено → шаг «Расширение».
    expect(
      homeTarget(
        status({ authed: true, auth_token_configured: true, openrouter_key_configured: true }),
      ),
    ).toBe("/extension")
    // Подтверждено → обычная работа, домашний экран — Вакансии (решение #16).
    expect(
      homeTarget(
        status({
          authed: true,
          auth_token_configured: true,
          openrouter_key_configured: true,
          extension_confirmed: true,
        }),
      ),
    ).toBe("/jobs")
  })

  it("кнопка «Расширение установлено» не блокирует: гейт не зависит от extension_confirmed", () => {
    const withoutConfirm = status({
      authed: true,
      auth_token_configured: true,
      openrouter_key_configured: true,
      extension_confirmed: false,
    })
    expect(isGateOpen(withoutConfirm)).toBe(true)
  })

  it("при закрытом гейте доступны только Параметры", () => {
    expect(isRouteAllowedWhileGated("/settings")).toBe(true)
    expect(isRouteAllowedWhileGated("/settings/extra")).toBe(true)
    for (const path of [
      "/",
      "/chat",
      "/jobs",
      "/resume",
      "/extension",
      "/admin",
      "/market",
      "/offers",
    ]) {
      expect(isRouteAllowedWhileGated(path)).toBe(false)
    }
  })

  it("форма входа нужна, пока нет живого входа с выпущенным токеном", () => {
    expect(needsTokenLogin(status())).toBe(true)
    expect(needsTokenLogin(status({ authed: true }))).toBe(true) // bootstrap: токена ещё нет
    expect(needsTokenLogin(status({ auth_token_configured: true }))).toBe(true) // anon
    expect(needsTokenLogin(status({ authed: true, auth_token_configured: true }))).toBe(false)
  })
})
