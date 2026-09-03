import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { fetchSearchMode, patchSearchMode, type SearchModeOut } from "@/api/career"

export const SEARCH_MODE_KEY = ["career", "search-mode"] as const

/** Текущий режим поиска (ST-01). */
export function useSearchMode() {
  return useQuery({
    queryKey: SEARCH_MODE_KEY,
    queryFn: fetchSearchMode,
    staleTime: 60_000,
  })
}

/** Переключение режима: оптимистичный апдейт пилюли, откат при ошибке. */
export function useSetSearchMode() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (mode: SearchModeOut["mode"]) =>
      patchSearchMode({ mode, actor: "owner", reason: "" }),
    onMutate: async (mode) => {
      await qc.cancelQueries({ queryKey: SEARCH_MODE_KEY })
      const prev = qc.getQueryData<SearchModeOut>(SEARCH_MODE_KEY)
      if (prev) qc.setQueryData<SearchModeOut>(SEARCH_MODE_KEY, { ...prev, mode })
      return { prev }
    },
    onSuccess: (saved) => qc.setQueryData<SearchModeOut>(SEARCH_MODE_KEY, saved),
    onError: (err: Error, _mode, ctx) => {
      if (ctx?.prev) qc.setQueryData<SearchModeOut>(SEARCH_MODE_KEY, ctx.prev)
      toast.error(err.message || "Не удалось переключить режим")
    },
  })
}
