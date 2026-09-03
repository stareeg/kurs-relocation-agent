import { useState } from "react"
import { CircleCheck, UserX } from "lucide-react"
import type { Job } from "@/api/jobs"
import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { useUpdateJobStage } from "@/features/jobs/use-job-stage"
import type { FunnelStage } from "@/features/jobs/funnel"
import { RailChatButton } from "./RailChatButton"

// Ряд кнопок под карточкой рельса (Скрининги/Технички): «Отказ» — «Чат» — следующий шаг. Обе
// крайние действуют на воронку целиком (не на конкретный этап цепочки, см. plan п.1d): отказ —
// через ConfirmDialog (как «Отказ от HR» в JobDetailDrawer.tsx), переход дальше — сразу.
// «Чат» посередине — вход в переписку по этой же вакансии, чтобы не искать её переключением
// разделов. `nextLabel` — подпись кнопки перехода (Скрининги: «Пройдено»; Технички: «Финал»/«Оффер»).
export function RailFunnelActions({
  job,
  nextStage,
  nextLabel = "Пройдено",
}: {
  job: Job
  nextStage: FunnelStage | null
  nextLabel?: string
}) {
  const stageM = useUpdateJobStage()
  const [confirmOpen, setConfirmOpen] = useState(false)
  if (job.id == null) return null
  const jobId = job.id
  return (
    <>
      <Button
        size="sm"
        variant="outline"
        className="h-7 gap-1 border-rose-200 bg-rose-50 px-2 text-xs text-rose-700 hover:bg-rose-100"
        onClick={() => setConfirmOpen(true)}
      >
        <UserX className="size-3.5" strokeWidth={2} />
        Отказ
      </Button>
      <RailChatButton vacancyId={job.vacancy_id} />
      {nextStage && (
        <Button
          size="sm"
          variant="outline"
          className="h-7 gap-1 border-emerald-200 bg-emerald-50 px-2 text-xs text-emerald-700 hover:bg-emerald-100"
          disabled={stageM.isPending}
          onClick={() => stageM.mutate({ id: jobId, stage: nextStage })}
        >
          <CircleCheck className="size-3.5" strokeWidth={2} />
          {nextLabel}
        </Button>
      )}
      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Перевести вакансию в «Отказ»?"
        description="Вакансия перейдёт в «Отказ». Вернуть обратно можно из раздела «Вакансии»."
        confirmLabel="Отказ"
        onConfirm={() => stageM.mutate({ id: jobId, stage: "Отказ" })}
      />
    </>
  )
}
