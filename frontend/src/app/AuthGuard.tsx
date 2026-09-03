import { Navigate, Outlet, useLocation } from "react-router-dom"
import { Loader2 } from "lucide-react"
import { useAuth } from "@/features/auth/auth-context"
import { useAuthStatusQuery } from "@/features/auth/use-auth-status"
import { isGateOpen, isRouteAllowedWhileGated } from "@/features/auth/onboarding"

// Гейт защищённых роутов (AUTH-1). Формы логина больше нет: anon и незавершённый онбординг
// ведут в «Параметры» — там вход по токену из бота и ключ OpenRouter. Пока оба не настроены,
// остальные разделы недоступны (в меню они серые, прямые URL редиректят сюда же).
export function AuthGuard() {
  const { status } = useAuth()
  const loc = useLocation()
  const { data, isLoading } = useAuthStatusQuery()

  if (status === "checking") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50">
        <Loader2 className="size-5 animate-spin text-muted-foreground" strokeWidth={2} />
      </div>
    )
  }

  const allowedHere = isRouteAllowedWhileGated(loc.pathname)

  if (status === "anon") {
    return allowedHere ? <Outlet /> : <Navigate to="/settings" replace />
  }

  // authed: дождаться статуса онбординга, чтобы не мигать контентом до редиректа.
  if (isLoading && !data) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50">
        <Loader2 className="size-5 animate-spin text-muted-foreground" strokeWidth={2} />
      </div>
    )
  }

  // data нет (бэк недоступен) — не блокируем: ошибки покажут сами страницы, 401 поймается позже.
  if (data && !isGateOpen(data) && !allowedHere) {
    return <Navigate to="/settings" replace />
  }

  return <Outlet />
}
