import type { Job } from "@/api/jobs"

/** Сессия: сброс напоминания по job.id, чтобы не спамить при повторном дропе в «Отклик». */
const dismissedJobIds = new Set<number>()

/** FR3-65/68: площадка требует письмо, текста ещё нет, напоминание не снимали в этой сессии. */
export function needsCoverLetterReminder(
  job: Pick<Job, "id" | "letter_required" | "cover_letter_text">,
): boolean {
  if (job.letter_required !== true) return false
  if ((job.cover_letter_text ?? "").trim().length > 0) return false
  if (job.id != null && dismissedJobIds.has(job.id)) return false
  return true
}

export function dismissCoverLetterReminder(jobId: number): void {
  dismissedJobIds.add(jobId)
}

/** Только для тестов. */
export function _resetCoverLetterReminderDismissalsForTests(): void {
  dismissedJobIds.clear()
}
