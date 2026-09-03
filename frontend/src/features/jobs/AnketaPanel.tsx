import { ClipboardList, Loader2 } from "lucide-react"
import { useState } from "react"
import type { Job } from "@/api/jobs"
import { Button } from "@/components/ui/button"
import { HelpTip } from "@/components/ui/help-tip"
import { Textarea } from "@/components/ui/textarea"
import { useConfirmAnketa, useRejectAnketa } from "@/features/settings/use-settings"
import { useUpdateJobApplyFields } from "./use-job-apply-fields"

// Вынесено из JobDetailDrawer.tsx (Расширение — иконка «Анкета» в очереди автооткликов, Фаза E):
// второй потребитель — попап на строке очереди (QueueVacancyRow), тот же компонент, что в
// полном дровере, без дублирования confirm/reject-логики.

// Фаза 3.3 (auto_apply_roadmap_2026_08_17.md): анкета работодателя hh.ru при отклике —
// раннер запарковал сгенерированные ответы, владелец правит и подтверждает ДО реальной
// отправки (анкета не участвует в L2/L3 автопилота независимо от режима площадки). Фаза 3.4:
// та же очередь (`jobs.anketa`) паркуется и БЕЗ анкеты — режим «Тест» (require_confirmation)
// на площадке ждёт подтверждения самого письма перед КАЖДЫМ реальным откликом. Один компонент
// на оба случая — различаются только тем, есть ли `questions` (анкета) или нет (только
// письмо, `job.cover_letter_text`, та же колонка, что редактируется во вкладке «Вакансия»).
export function AnketaPanel({ job }: { job: Job }) {
  const anketa = job.anketa
  const confirm = useConfirmAnketa()
  const reject = useRejectAnketa()
  const saveCover = useUpdateJobApplyFields()
  const hasQuestions = (anketa?.questions?.length ?? 0) > 0
  // DrawerBody монтируется с key={job.id} (см. коммент ниже) — ленивая инициализация из
  // job.anketa.answers/job.cover_letter_text достаточна, без эффекта: смена карточки уже
  // пересоздаёт компонент.
  const [answers, setAnswers] = useState<Record<string, string>>(() =>
    Object.fromEntries((anketa?.answers ?? []).map((a) => [a.question_id, a.value])),
  )
  const [letter, setLetter] = useState(job.cover_letter_text ?? "")

  if (job.id == null || !anketa) return null

  if (anketa.status === "approved") {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-sky-200 bg-sky-50/60 px-3 py-2.5">
        <ClipboardList className="size-4 shrink-0 text-sky-700" strokeWidth={2} />
        <p className="text-sm text-sky-900">
          {hasQuestions ? "Анкета подтверждена" : "Отклик подтверждён"} — ждёт отправки раннером
        </p>
      </div>
    )
  }
  if (anketa.status !== "pending") return null

  const jobId = job.id
  const pending = confirm.isPending || saveCover.isPending

  async function onConfirm() {
    if (hasQuestions) {
      const payload = (anketa!.questions ?? []).map((q) => ({
        question_id: q.id,
        value: answers[q.id] ?? "",
      }))
      confirm.mutate({ jobId, answers: payload })
      return
    }
    // Письмо могло быть отредактировано владельцем — сохраняем перед подтверждением, раннер
    // на резюме-визите (3.4) берёт `jobs.cover_letter_text` как есть, без новой генерации.
    if (letter !== (job.cover_letter_text ?? "")) {
      await saveCover.mutateAsync({ id: jobId, cover_letter_text: letter })
    }
    confirm.mutate({ jobId, answers: [] })
  }

  return (
    <div className="space-y-3 rounded-lg border border-sky-200 bg-sky-50/60 px-3 py-3">
      <div className="flex items-center gap-1.5">
        <ClipboardList className="size-3.5 shrink-0 text-sky-700" strokeWidth={2} />
        <p className="flex-1 text-xs font-semibold uppercase tracking-wider text-sky-700">
          {hasQuestions ? "Анкета работодателя — на подтверждении" : "Отклик ждёт подтверждения"}
        </p>
        <HelpTip id="jobs.anketa-pending" />
      </div>
      {hasQuestions ? (
        <div className="space-y-3">
          {(anketa.questions ?? []).map((q) => (
            <div key={q.id} className="space-y-1">
              <p className="text-sm font-medium text-slate-700">{q.text}</p>
              {q.type !== "text" && q.options && q.options.length > 0 && (
                <p className="text-xs text-slate-500">
                  Варианты: {q.options.map((o) => o.label).join(", ")}
                </p>
              )}
              <Textarea
                value={answers[q.id] ?? ""}
                onChange={(e) => setAnswers((prev) => ({ ...prev, [q.id]: e.target.value }))}
                className="min-h-16 bg-white"
              />
            </div>
          ))}
        </div>
      ) : (
        <div className="space-y-1">
          <p className="text-sm font-medium text-slate-700">
            Сопроводительное письмо — режим «Тест» шлёт по-настоящему, только когда вы нажмёте
            «Отправить»
          </p>
          <Textarea
            value={letter}
            onChange={(e) => setLetter(e.target.value)}
            className="min-h-24 bg-white"
          />
        </div>
      )}
      <div className="flex items-center gap-2">
        <Button size="sm" onClick={onConfirm} disabled={pending}>
          {pending && <Loader2 className="size-4 animate-spin" strokeWidth={2} />}
          Отправить
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={reject.isPending}
          onClick={() => reject.mutate(jobId)}
        >
          Пропустить
        </Button>
      </div>
    </div>
  )
}
