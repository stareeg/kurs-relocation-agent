import type { components } from "@/api/schema"
import { api, LLM_TIMEOUT_MS } from "@/api/client"

export type CoverLetterResponse = components["schemas"]["CoverLetterResponse"]
export type CoverLetterLang = "ru" | "en"

// POST /api/jobs/{id}/cover-letter — сгенерировать короткое сопроводительное (LLM) и записать
// в jobs.cover_letter_text (JS-6.1). Ручную правку письма сохраняет PATCH /api/jobs/{id}.
// `lang` — переключалка RU/EN (Э4.4 dual_employment_and_contracting_2026.md); не передан —
// бэкенд выводит язык из текста резюме сам и возвращает фактический выбор в `lang` ответа.
export function generateCoverLetter(jobId: number, lang?: CoverLetterLang) {
  return api.post<CoverLetterResponse>(
    `/api/jobs/${jobId}/cover-letter`,
    lang ? { lang } : undefined,
    { timeoutMs: LLM_TIMEOUT_MS },
  )
}
