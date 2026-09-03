import { Navigate } from "react-router-dom"
import { Loader2 } from "lucide-react"
import { useAuth } from "@/features/auth/auth-context"
import { useAuthStatusQuery } from "@/features/auth/use-auth-status"
import { homeTarget } from "@/features/auth/onboarding"

/**
 * Корень `/` (AUTH-1): онбординг не завершён → Параметры (токен из бота + ключ OpenRouter),
 * расширение не подтверждено → Расширение, иначе → Чаты.
 */
export function HomeRedirect() {
  const { status } = useAuth()
  const { data, isLoading } = useAuthStatusQuery()

  if (status === "checking" || (isLoading && !data)) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Loader2 className="size-5 animate-spin text-slate-400" strokeWidth={2} />
      </div>
    )
  }

  if (status === "anon") {
    return <Navigate to="/settings" replace />
  }

  return <Navigate to={homeTarget(data)} replace />
}
