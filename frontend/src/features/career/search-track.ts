import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { fetchSearchTrack, patchSearchTrack, type SearchTrackOut } from "@/api/career"

export const SEARCH_TRACK_KEY = ["career", "search-track"] as const

/** Текущий набор треков поиска (Э1.1). */
export function useSearchTrack() {
  return useQuery({
    queryKey: SEARCH_TRACK_KEY,
    queryFn: fetchSearchTrack,
    staleTime: 60_000,
  })
}

/** Включение/выключение второй работы: оптимистичный апдейт чипа, откат при ошибке. */
export function useSetSearchTrack() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (secondJobEnabled: boolean) =>
      patchSearchTrack({ second_job_enabled: secondJobEnabled, actor: "owner", reason: "" }),
    onMutate: async (secondJobEnabled) => {
      await qc.cancelQueries({ queryKey: SEARCH_TRACK_KEY })
      const prev = qc.getQueryData<SearchTrackOut>(SEARCH_TRACK_KEY)
      if (prev) {
        qc.setQueryData<SearchTrackOut>(SEARCH_TRACK_KEY, {
          ...prev,
          second_job_enabled: secondJobEnabled,
        })
      }
      return { prev }
    },
    onSuccess: (saved) => {
      qc.setQueryData<SearchTrackOut>(SEARCH_TRACK_KEY, saved)
      void qc.invalidateQueries({ queryKey: ["resume", "international"] })
    },
    onError: (err: Error, _enabled, ctx) => {
      if (ctx?.prev) qc.setQueryData<SearchTrackOut>(SEARCH_TRACK_KEY, ctx.prev)
      toast.error(err.message || "Не удалось переключить трек")
    },
  })
}
