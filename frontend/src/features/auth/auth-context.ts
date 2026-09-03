import { createContext, useContext } from "react"

export type AuthStatus = "checking" | "authed" | "anon"

export interface AuthContextValue {
  status: AuthStatus
  /** Вход по токену из Telegram-бота (AUTH-1). Бросает ApiError при неверном токене. */
  login: (token: string) => Promise<void>
  /** Выход «с этого устройства» — отзывает только текущую сессию (блок «Устройства»). */
  logout: () => Promise<void>
  /** «Выйти на всех устройствах» — отзывает все сессии аккаунта, включая текущую. */
  logoutEverywhere: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error("useAuth вызван вне AuthProvider")
  return ctx
}
