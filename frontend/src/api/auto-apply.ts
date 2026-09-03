import type { components } from "@/api/schema"
import { api } from "@/api/client"

// FastAPI отдаёт Literal как enum query-параметра, не отдельной именованной схемой (в отличие
// от Pydantic-моделей) — components["schemas"] его не содержит, поэтому тип локальный. Значения
// должны совпадать с `AutoApplyPlatform` в core/domains/pipeline/auto_apply/config.py.
export type AutoApplyPlatform = "hh" | "getmatch" | "habr"
export type AutoApplyPlatformConfig = components["schemas"]["AutoApplyPlatformConfig"]
export type AutoApplyPreviewItem = components["schemas"]["AutoApplyPreviewItem"]
export type AutoApplyPreviewResponse = components["schemas"]["AutoApplyPreviewResponse"]
export type AutoApplySchedule = components["schemas"]["AutoApplySchedule"]
export type AutoApplyPauseResponse = components["schemas"]["AutoApplyPauseResponse"]
export type AutoApplyClearResponse = components["schemas"]["AutoApplyClearResponse"]
export type AutoApplyManualSendResponse = components["schemas"]["AutoApplyManualSendResponse"]
export type AutoApplyDailyCountResponse = components["schemas"]["AutoApplyDailyCountResponse"]
export type AnketaAnswer = components["schemas"]["AnketaAnswer"]
export type AnketaState = components["schemas"]["AnketaState"]
export type AnketaPendingItem = components["schemas"]["AnketaPendingItem"]
export type AnketaPendingResponse = components["schemas"]["AnketaPendingResponse"]
export type QueueOverride = components["schemas"]["AutoApplyMoveRequest"]["target"]

/** GET /api/pipeline/auto-apply/preview — живой пересчёт очереди одной площадки. */
export function fetchAutoApplyPreview(platform: AutoApplyPlatform) {
  const params = new URLSearchParams({ platform })
  return api.get<AutoApplyPreviewResponse>(`/api/pipeline/auto-apply/preview?${params.toString()}`)
}

// POST /api/pipeline/auto-apply/pause — kill switch (Фаза 7.4): мгновенно enabled=false на всех
// площадках разом, один сценарий с `/pause_autoapply` в Telegram-боте.
export function pauseAutoApply() {
  return api.post<AutoApplyPauseResponse>("/api/pipeline/auto-apply/pause")
}

// POST /api/pipeline/auto-apply/clear — пункт 1 редизайна «Расширения»: пропустить разом всё, что
// сейчас видно в очереди (auto + manual_review) по всем площадкам, без выключения самих площадок.
export function clearAutoApplyQueue() {
  return api.post<AutoApplyClearResponse>("/api/pipeline/auto-apply/clear")
}

// POST /api/pipeline/auto-apply/manual-send — ручная отправка всех автооткликов из очереди
// (auto bucket), не дожидаясь следующего тика раннера.
export function manualSendAutoApply() {
  return api.post<AutoApplyManualSendResponse>("/api/pipeline/auto-apply/manual-send")
}

// POST /api/pipeline/auto-apply/clear-manual-send — снять флаг ручной отправки (вызывается
// расширением после успешной обработки очереди).
export function clearManualSendAutoApply() {
  return api.post<void>("/api/pipeline/auto-apply/clear-manual-send")
}

/** GET /api/pipeline/auto-apply/daily-count — сколько уже отправлено сегодня против лимита
 * площадки (2.7) — прогресс-бар «Отклики» на карточке площадки (Этап 3 редизайна). */
export function fetchAutoApplyDailyCount(platform: AutoApplyPlatform) {
  const params = new URLSearchParams({ platform })
  return api.get<AutoApplyDailyCountResponse>(
    `/api/pipeline/auto-apply/daily-count?${params.toString()}`,
  )
}

// Фаза 3.3: очередь подтверждения анкеты работодателя (hh.ru).

/** GET /api/pipeline/auto-apply/anketa/pending — вакансии с анкетой в заданном статусе
 * (`pending` по умолчанию — очередь на подтверждение). */
export function fetchAnketaPending(platform: AutoApplyPlatform, status: string = "pending") {
  const params = new URLSearchParams({ platform, status })
  return api.get<AnketaPendingResponse>(
    `/api/pipeline/auto-apply/anketa/pending?${params.toString()}`,
  )
}

/** POST /api/pipeline/auto-apply/anketa/{job_id}/confirm — владелец подтверждает
 * (возможно отредактированные) ответы. Реальную отправку выполняет раннер на следующем тике. */
export function confirmAnketa(jobId: number, answers: AnketaAnswer[]) {
  return api.post<AnketaPendingItem>(`/api/pipeline/auto-apply/anketa/${jobId}/confirm`, {
    answers,
  })
}

/** POST /api/pipeline/auto-apply/anketa/{job_id}/reject — владелец отклоняет анкету. */
export function rejectAnketa(jobId: number) {
  return api.post<AnketaPendingItem>(`/api/pipeline/auto-apply/anketa/${jobId}/reject`)
}

/** POST /api/pipeline/auto-apply/{job_id}/move — квик-экшен «переместить» (Фаза E редизайна
 * «Расширения», пункт 4): ручной оверрайд бакета auto/manual_review, персистится отдельно от
 * живого пересчёта очереди. */
export function moveAutoApplyQueueItem(jobId: number, target: QueueOverride) {
  return api.post<AutoApplyPreviewItem>(`/api/pipeline/auto-apply/${jobId}/move`, { target })
}
