import { useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { type CoverLetterLang, generateCoverLetter } from "@/api/cover-letters"
import { patchJobsCache } from "./use-jobs"

// Генерация сопроводительного (JS-6.1): LLM-ручка пишет текст в jobs.cover_letter_text. На успехе
// вкладываем свежий текст в кэш ["jobs"], чтобы карточка/дровер показали его без рефетча. Локальное
// поле редактора дровер сидит из onSuccess результата напрямую (карточка не ремонтится по id).
// `lang` (Э4.4) — явный выбор переключалки RU/EN; без него бэкенд выводит язык из резюме сам.
export function useGenerateCoverLetter() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ jobId, lang }: { jobId: number; lang?: CoverLetterLang }) =>
      generateCoverLetter(jobId, lang),
    onSuccess: (res) => {
      // FR3-65: обновляем только текст; letter_required — сигнал площадки, не факт генерации.
      patchJobsCache(qc, (j) =>
        j.id === res.id
          ? { ...j, cover_letter_text: res.cover_letter_text, cover_letter_lang: res.lang }
          : j,
      )
      // Тот же денормализованный текст показывают иконка «Сопроводительное» в очереди
      // «Расширения» (Фаза E) и ховер-превью — им ["jobs"] не видно, нужна инвалидация отдельно.
      void qc.invalidateQueries({ queryKey: ["auto-apply", "preview"] })
      void qc.invalidateQueries({ queryKey: ["jobs", "by-vacancy"] })
      toast.success("Письмо готово")
    },
    onError: (err) =>
      toast.error(err instanceof Error ? err.message : "Не удалось сгенерировать письмо"),
  })
}
