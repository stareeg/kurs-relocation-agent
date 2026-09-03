import type { components } from "@/api/schema"
import { api, apiFetch } from "@/api/client"

export type AuthStatus = components["schemas"]["AuthStatusResponse"]
export type DeviceSession = components["schemas"]["DeviceSession"]

// Публичный статус входа/онбординга — работает и до логина (AUTH-1).
export function fetchAuthStatus() {
  return api.get<AuthStatus>("/auth/status")
}

// Логин: токен из Telegram-бота → httponly cookie copilot_auth (api/routers/meta/auth.py).
// skip401Handler: неверный токен в форме входа не должен глобально «разлогинивать» приложение.
export function loginWithToken(token: string) {
  return apiFetch<AuthStatus>("/auth/token", {
    method: "POST",
    body: JSON.stringify({ token }),
    skip401Handler: true,
  })
}

// Выход из аккаунта: токен отзывается на сервере — новый выдаёт только бот.
export function logout() {
  return api.post<unknown>("/auth/logout")
}

// Устройства (Part C): список активных сессий + отзыв по одной / всех разом.
export function fetchSessions() {
  return api.get<{ sessions: DeviceSession[] }>("/auth/sessions")
}

export function revokeSession(id: number) {
  return api.post<{ ok: boolean }>(`/auth/sessions/${id}/revoke`)
}

export function revokeAllSessions() {
  return api.post<{ revoked: number }>("/auth/sessions/revoke-all")
}
