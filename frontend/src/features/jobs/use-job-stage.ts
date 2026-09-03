import { useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { generateCoverLetter } from "@/api/cover-letters"
import { updateJobStage, type Job } from "@/api/jobs"
import { dismissCoverLetterReminder, needsCoverLetterReminder } from "./cover-letter-reminder"
import { findJobInCache, getJobsCache, patchJobsCache, setJobsCache } from "./use-jobs"

type Vars = { id: number; stage: string }

// FR3-68: после перевода в «Отклик» — ненавязчивый тост, если площадка требует письмо, а текста нет.
function maybeRemindCoverLetter(job: Job | undefined, qc: ReturnType<typeof useQueryClient>) {
  if (!job?.id || !needsCoverLetterReminder(job)) return
  const jobId = job.id
  toast.message("Обычно нужно письмо", {
    description: "Площадка просит сопроводительное — сгенерировать черновик?",
    duration: 12_000,
    action: {
      label: "Сгенерировать",
      onClick: () => {
        dismissCoverLetterReminder(jobId)
        void generateCoverLetter(jobId)
          .then((res) => {
            patchJobsCache(qc, (j) =>
              j.id === res.id ? { ...j, cover_letter_text: res.cover_letter_text } : j,
            )
            toast.success("Письмо готово")
          })
          .catch((err: unknown) =>
            toast.error(err instanceof Error ? err.message : "Не удалось сгенерировать письмо"),
          )
      },
    },
    onDismiss: () => dismissCoverLetterReminder(jobId),
  })
}

// Смена стадии вакансии перетаскиванием карточки (JS-1.1). Оптимистично двигаем карточку в кэше
// ["jobs"], при ошибке откатываем и показываем тост, на финал — инвалидация (правда из PG).
export function useUpdateJobStage() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, stage }: Vars) => updateJobStage(id, stage),
    onMutate: async ({ id, stage }) => {
      // Гасим фоновый refetch (refetchInterval 30с), чтобы он не затёр оптимистичный апдейт.
      await qc.cancelQueries({ queryKey: ["jobs"] })
      const prev = getJobsCache(qc)
      patchJobsCache(qc, (j) => (j.id === id ? { ...j, status: stage } : j))
      return { prev }
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) setJobsCache(qc, ctx.prev)
      toast.error("Не удалось сменить статус")
    },
    onSuccess: (_data, vars) => {
      if (vars.stage !== "Отклик") return
      maybeRemindCoverLetter(
        findJobInCache(qc, (j) => j.id === vars.id),
        qc,
      )
    },
    onSettled: (_data, _err, vars) => {
      void qc.invalidateQueries({ queryKey: ["jobs"] })
      // Переход в «Техничка» авто-помечает скрининг — обновить кружки в дровере.
      const vacancyId = findJobInCache(qc, (j) => j.id === vars.id)?.vacancy_id
      if (vacancyId) {
        void qc.invalidateQueries({ queryKey: ["interview-stages", vacancyId] })
      } else {
        void qc.invalidateQueries({ queryKey: ["interview-stages"] })
      }
    },
  })
}
