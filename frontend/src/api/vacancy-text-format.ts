import type { components } from "@/api/schema"
import { api } from "@/api/client"

export type VacancyTextFormatResponse = components["schemas"]["VacancyTextFormatResponse"]

// GET /api/vacancies/{vacancy_id}/text-format — текст вакансии с абзацами и **выделениями**
// (дешёвая extract-модель, результат кэшируется бэкендом по тексту — вызывается один раз).
export function fetchVacancyTextFormat(vacancyId: string) {
  return api.get<VacancyTextFormatResponse>(
    `/api/vacancies/${encodeURIComponent(vacancyId)}/text-format`,
  )
}
