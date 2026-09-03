import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { api, ApiError, setUnauthorizedHandler } from "@/api/client"
import {
  loginWithToken,
  logout as logoutApi,
  revokeAllSessions,
  type AuthStatus as AuthStatusData,
} from "@/api/auth"
import { clearBuffer as clearErrorCaptureBuffer } from "@/lib/error-capture"
import { clearUiContext } from "@/lib/ui-context"
import { queryPersister } from "@/lib/query"
import { AUTH_STATUS_KEY } from "./use-auth-status"
import { AuthContext, type AuthContextValue, type AuthStatus } from "./auth-context"

// Источник правды об авторизации — перехват 401 в клиенте + проба GET /auth/status на старте
// (AUTH-1: публичная ручка, отвечает и до логина). anon = периметр закрыт, а cookie-токена нет:
// единственный путь дальше — вставить токен из бота в «Параметрах».
export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("checking")
  const qc = useQueryClient()

  // persist пишет в localStorage с дебаунсом — на логаут/протухшую сессию этого не ждём,
  // иначе следующий вход (в т.ч. другим пользователем на этой же машине) может на миг
  // гидратироваться чужими данными до первого фонового refetch. Буфер error-capture чистим
  // тем же жестом: незафлашенные ошибки прежнего аккаунта не должны долететь на
  // /api/logs/frontend уже под сессией следующего.
  const clearCache = useCallback(() => {
    qc.clear()
    void queryPersister.removeClient()
    clearErrorCaptureBuffer()
    clearUiContext()
  }, [qc])

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setStatus("anon")
      clearCache()
    })
    return () => setUnauthorizedHandler(null)
  }, [clearCache])

  useEffect(() => {
    let alive = true
    api
      .get<AuthStatusData>("/auth/status")
      .then((s) => {
        if (!alive) return
        qc.setQueryData(AUTH_STATUS_KEY, s)
        setStatus(s.authed ? "authed" : "anon")
      })
      .catch((e: unknown) => {
        if (!alive) return
        // 401 → нужен токен. Иные ошибки (бэк недоступен) не блокируют вход — поймаем 401 позже.
        setStatus(e instanceof ApiError && e.status === 401 ? "anon" : "authed")
      })
    return () => {
      alive = false
    }
  }, [qc])

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      async login(token: string) {
        const s = await loginWithToken(token)
        // Защита от переключения аккаунта без явного «Выйти» (UI сейчас это исключает,
        // но login() не должен полагаться на вызывающего): кэш прошлой сессии на этой машине
        // не должен на миг гидратироваться под новым аккаунтом.
        clearCache()
        qc.setQueryData(AUTH_STATUS_KEY, s)
        setStatus("authed")
      },
      async logout() {
        try {
          await logoutApi()
        } finally {
          setStatus("anon")
          clearCache()
        }
      },
      async logoutEverywhere() {
        try {
          await revokeAllSessions()
        } finally {
          setStatus("anon")
          clearCache()
        }
      },
    }),
    [status, clearCache, qc],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
