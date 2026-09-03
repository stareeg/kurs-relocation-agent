import { useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { deleteJob } from "@/api/jobs"
import { getJobsCache, removeJobFromCache, setJobsCache } from "./use-jobs"

// Удаление вакансии целиком (JS-1.2: кнопка «Удалить» в дровере — кривая/мусорная карточка).
// Необратимо (в отличие от «Пропустить»/«Отказ от HR») — вызывающая сторона (кнопка в дровере)
// подтверждает через ConfirmDialog перед вызовом mutate. Оптимистично убираем карточку из кэша
// ["jobs"], при ошибке — откат + тост; на финал — инвалидация (правда из PG). Зеркалит useSkipJob.
export function useDeleteJob() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id }: { id: number }) => deleteJob(id),
    onMutate: async ({ id }) => {
      await qc.cancelQueries({ queryKey: ["jobs"] })
      const prev = getJobsCache(qc)
      removeJobFromCache(qc, id)
      return { prev }
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) setJobsCache(qc, ctx.prev)
      toast.error("Не удалось удалить вакансию")
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["jobs"] })
    },
  })
}
