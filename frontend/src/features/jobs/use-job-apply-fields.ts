import { useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { updateJobApplyFields, type JobApplyFieldsUpdate } from "@/api/jobs"
import { getJobsCache, patchJobsCache, setJobsCache } from "./use-jobs"

type Vars = { id: number } & JobApplyFieldsUpdate

// Сохранение полей карточки вакансии (JS-1.2): заметка, дата отклика, текст письма.
// letter_required при необходимости пишет расширение (FR3-65), веб обычно шлёт только текст.
// Оптимистично патчим кэш ["jobs"], при ошибке откатываем + тост; на финал — инвалидация.
export function useUpdateJobApplyFields() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: Vars) => updateJobApplyFields(id, body),
    onMutate: async ({ id, ...patch }) => {
      await qc.cancelQueries({ queryKey: ["jobs"] })
      const prev = getJobsCache(qc)
      patchJobsCache(qc, (j) => (j.id === id ? { ...j, ...patch } : j))
      return { prev }
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) setJobsCache(qc, ctx.prev)
      toast.error("Не удалось сохранить")
    },
    onSuccess: () => toast.success("Сохранено"),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["jobs"] })
      // cover_letter_text денормализован в AutoApplyPreviewItem (иконка «Сопроводительное» в
      // очереди «Расширения», Фаза E) и в ["jobs","by-vacancy",...] (ховер-превью попап) — оба
      // редактируют то же поле через этот хук.
      void qc.invalidateQueries({ queryKey: ["auto-apply", "preview"] })
      void qc.invalidateQueries({ queryKey: ["jobs", "by-vacancy"] })
    },
  })
}
