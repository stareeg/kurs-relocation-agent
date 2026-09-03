import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { fetchSessions, revokeSession } from "@/api/auth"

// Блок «Устройства» (Part C): список активных сессий входа + отзыв по одной. «Выйти на всех
// устройствах» идёт не отсюда, а через useAuth().logoutEverywhere() — та же зачистка
// клиентского состояния (кэш, error-capture), что и у обычного logout().

const KEY = ["auth", "sessions"] as const

export function useSessionsQuery() {
  return useQuery({
    queryKey: KEY,
    queryFn: fetchSessions,
    staleTime: 15_000,
    select: (data) => data.sessions,
  })
}

export function useRevokeSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => revokeSession(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: KEY }),
    onError: (err: Error) => toast.error(err.message || "Не удалось завершить сессию"),
  })
}
