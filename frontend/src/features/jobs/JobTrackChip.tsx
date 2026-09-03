import { StatusChip } from "@/components/ui/status-chip"
import { useSearchTrack } from "@/features/career/search-track"
import type { Job } from "@/api/jobs"
import { getHelpText } from "@/lib/help-texts"
import { TRACK_LABELS, useSetJobTrack } from "./use-job-track"

/** Чип трека рядом с форматом. Клик переключает вручную и гасит всплытие до карточки. */
export function JobTrackChip({ job }: { job: Job }) {
  const { data: tracks } = useSearchTrack()
  const setTrack = useSetJobTrack()
  const current = job.track === "second_job" ? "second_job" : "primary"
  const show = Boolean(tracks?.second_job_enabled) || current === "second_job"
  if (!show || job.id == null) return null
  const next = current === "primary" ? "second_job" : "primary"
  return (
    <button
      type="button"
      onPointerDown={(e) => e.stopPropagation()}
      onClick={(e) => {
        e.stopPropagation()
        if (setTrack.isPending) return
        setTrack.mutate({ id: job.id!, track: next })
      }}
      className="rounded-md"
      title={getHelpText("jobs.card-track")}
      aria-label={`Трек: ${TRACK_LABELS[current]}. Нажмите, чтобы переключить`}
    >
      <StatusChip tone={current === "second_job" ? "info" : "good"} className="px-1.5 text-xs">
        {TRACK_LABELS[current]}
      </StatusChip>
    </button>
  )
}
