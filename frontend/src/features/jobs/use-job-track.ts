import { useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { patchJobTrack, type JobTrackUpdate, type Job } from "@/api/jobs"
import { getJobsCache, patchJobsCache, setJobsCache } from "./use-jobs"

export type JobTrack = "primary" | "second_job"

const TRACK_LABELS = { primary: "Основная", second_job: "Дополнительная" } as const

/** Подпись рубрики у балла на карточке — чтобы 78 второго трека не читалось рядом с 74 основного. */
export const SCORE_RUBRIC_CAPTION: Record<JobTrack, string> = {
  primary: "",
  second_job: "вторая работа",
}

export function jobTrack(job: Pick<Job, "track">): JobTrack {
  return job.track === "second_job" ? "second_job" : "primary"
}

type Vars = { id: number } & JobTrackUpdate

/** Клик по чипу трека на карточке: оптимистично патчим кэш, затем инвалидация. */
export function useSetJobTrack() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, track }: Vars) => patchJobTrack(id, { track }),
    onMutate: async ({ id, track }) => {
      await qc.cancelQueries({ queryKey: ["jobs"] })
      const prev = getJobsCache(qc)
      patchJobsCache(qc, (j) =>
        j.id === id ? { ...j, track, track_override: true } : j,
      )
      return { prev }
    },
    onError: (_err, vars, ctx) => {
      if (ctx?.prev) setJobsCache(qc, ctx.prev)
      toast.error("Не удалось сменить трек")
      void vars
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["jobs"] })
    },
  })
}

export { TRACK_LABELS }
