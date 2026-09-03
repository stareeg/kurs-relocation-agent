import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { skipJob, unskipJob } from "@/api/jobs"
import { fetchSkippedList } from "@/api/skipped"
import { getJobsCache, patchJobsCache, setJobsCache } from "./use-jobs"

// Пропуск/возврат вакансии перетаскиванием в колонку «Пропущено» и обратно (Этап 2). Флаг
// job.skipped ортогонален статусу воронки — оптимистично двигаем только его, при ошибке откат +
// тост, на финал — инвалидация кэша ["jobs"] (правда из PG). Зеркалит useUpdateJobStage.

function patchSkipped(qc: ReturnType<typeof useQueryClient>, id: number, skipped: boolean) {
  patchJobsCache(qc, (j) => (j.id === id ? { ...j, skipped } : j))
}

export function useSkipJob() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, reason }: { id: number; reason?: string }) => skipJob(id, reason),
    onMutate: async ({ id }) => {
      await qc.cancelQueries({ queryKey: ["jobs"] })
      const prev = getJobsCache(qc)
      patchSkipped(qc, id, true)
      return { prev }
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) setJobsCache(qc, ctx.prev)
      toast.error("Не удалось пропустить вакансию")
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["jobs"] })
      // job.skipped гейтит auto_apply.classify_for_auto_apply — очередь «Расширения» должна
      // отреагировать (строка «Убрать из очереди» пропадает), не только доска вакансий.
      void qc.invalidateQueries({ queryKey: ["auto-apply", "preview"] })
      // Вкладка «Пропуски» в «Расширении» живёт на этом списке — пропущенная строка обязана
      // появиться там сразу, а не просто исчезнуть из очереди.
      void qc.invalidateQueries({ queryKey: ["skipped"] })
    },
  })
}

export function useUnskipJob() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id }: { id: number }) => unskipJob(id),
    onMutate: async ({ id }) => {
      await qc.cancelQueries({ queryKey: ["jobs"] })
      const prev = getJobsCache(qc)
      patchSkipped(qc, id, false)
      return { prev }
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) setJobsCache(qc, ctx.prev)
      toast.error("Не удалось вернуть в воронку")
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["jobs"] })
      void qc.invalidateQueries({ queryKey: ["auto-apply", "preview"] })
      void qc.invalidateQueries({ queryKey: ["skipped"] })
    },
  })
}

/** Список пропущенных вакансий — вкладка «Пропуски» очереди «Расширения». Тот же поллинг,
 *  что у превью очереди рядом, чтобы обе вкладки обновлялись в одном такте. */
export function useSkippedList(enabled: boolean = true) {
  return useQuery({
    queryKey: ["skipped"],
    queryFn: () => fetchSkippedList(),
    enabled,
    staleTime: 30_000,
    refetchInterval: enabled ? 5_000 : false,
  })
}
