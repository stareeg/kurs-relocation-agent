import type { components } from "@/api/schema"
import { api, ApiError, LLM_TIMEOUT_MS } from "@/api/client"
import { eventKind, streamSse } from "@/api/sse"

export type OfferRecord = components["schemas"]["OfferRecord"]
export type OfferUpdateRequest = components["schemas"]["OfferUpdateRequest"]
export type OfferCreateRequest = components["schemas"]["OfferCreateRequest"]
export type OfferCompareResponse = components["schemas"]["OfferCompareResponse"]
export type OfferComparison = components["schemas"]["OfferComparison"]
export type OfferParseApiRequest = components["schemas"]["OfferParseApiRequest"]
export type NegotiationBrief = components["schemas"]["NegotiationBrief"]
export type NegotiationArgument = components["schemas"]["NegotiationArgument"]
export type OfferNegotiateResponse = components["schemas"]["OfferNegotiateResponse"]

// Узкий вход для /decide: у сгенерённого *Request поля с pydantic-дефолтами помечены required
// (грабля openapi-typescript, как в UI-3). Клиент шлёт частичный body — дефолты добивает сервер.
export type OfferCompareInput = {
  vacancy_ids?: string[]
  max_age_days?: number
  save_to_disk?: boolean
}

// GET /api/offers — все офферы для матрицы сравнения (UI-6).
export function listOffers() {
  return api.get<OfferRecord[]>("/api/offers")
}

// POST /api/offers — создать колонку оффера под вакансию (если ещё нет).
export function createOffer(req: OfferCreateRequest) {
  return api.post<OfferRecord>("/api/offers", req)
}

// PATCH /api/offers/{id} — инлайн-правка ячейки матрицы.
export function patchOffer(vacancyId: string, patch: OfferUpdateRequest) {
  return api.patch<OfferRecord>(`/api/offers/${encodeURIComponent(vacancyId)}`, patch)
}

// DELETE /api/offers/{id} — убрать колонку.
export function deleteOffer(vacancyId: string) {
  return api.del<void>(`/api/offers/${encodeURIComponent(vacancyId)}`)
}

export type OfferCompareStreamEvent =
  | { type: "status"; stage?: string; label?: string }
  | {
      type: "rankings"
      rankings: OfferComparison["rankings"]
      favorable_fields: OfferComparison["favorable_fields"]
    }
  | {
      type: "verdict"
      sensitivity: OfferComparison["sensitivity"]
      recommendation: OfferComparison["recommendation"]
    }
  | { type: "part_error"; stage?: string; message?: string }
  | { type: "done"; response: OfferCompareResponse }
  | { type: "error"; detail?: string }

/** SSE-стрим сравнения (A-14/L-49): rankings/verdict по мере готовности + финальный результат. */
export async function compareOffersStream(
  onEvent: (event: OfferCompareStreamEvent) => void,
  req: OfferCompareInput = {},
  signal?: AbortSignal,
): Promise<OfferCompareResponse> {
  let finalResponse: OfferCompareResponse | null = null
  let streamError: string | null = null

  await streamSse("/api/offers/decide", {
    body: req,
    signal,
    timeoutMs: LLM_TIMEOUT_MS,
    rumInteraction: "offers-decide",
    onEvent: (e) => {
      const kind = eventKind(e)
      const data = e.data as OfferCompareStreamEvent & Record<string, unknown>
      if (kind === "error" || e.event === "error") {
        const detail =
          (typeof data.detail === "string" && data.detail) ||
          (typeof data.message === "string" && data.message) ||
          "Не удалось сравнить офферы"
        streamError = detail
        onEvent({ type: "error", detail })
        return
      }
      if (kind === "done" || e.event === "done") {
        const response = data.response as OfferCompareResponse | undefined
        if (response) {
          finalResponse = response
          onEvent({ type: "done", response })
        }
        return
      }
      onEvent(data as OfferCompareStreamEvent)
    },
  })

  if (streamError) throw new ApiError(502, streamError)
  if (!finalResponse) {
    throw new ApiError(502, "Стрим завершился без готового сравнения")
  }
  return finalResponse
}

// POST /api/offers/reorder — ручной порядок колонок матрицы (OF-11, drag-n-drop): индекс = приоритет.
export function reorderOffers(vacancyIds: string[]) {
  return api.post<OfferRecord[]>("/api/offers/reorder", { vacancy_ids: vacancyIds })
}

// POST /api/offers/parse — LLM-извлечение структуры оффера из текста письма HR
// (merge непустых полей по умолчанию; overwrite=true — перезапись).
export function parseOffer(req: OfferParseApiRequest) {
  return api.post<OfferRecord>("/api/offers/parse", req, { timeoutMs: LLM_TIMEOUT_MS })
}

// POST /api/offers/{id}/negotiate — RD-17: аргументы для торга (бенчмарк + другие офферы +
// leverage воронки). Персистится на офере — вызывать явно кнопкой «Торг», не на каждый рендер.
export function negotiateOffer(vacancyId: string) {
  return api.post<OfferNegotiateResponse>(
    `/api/offers/${encodeURIComponent(vacancyId)}/negotiate`,
    undefined,
    { timeoutMs: LLM_TIMEOUT_MS },
  )
}
