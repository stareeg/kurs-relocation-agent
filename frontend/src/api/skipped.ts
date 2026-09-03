import type { components } from "@/api/schema"
import { api } from "@/api/client"

export type SkippedVacancy = components["schemas"]["SkippedVacancy"]

// GET /skipped — вакансии, по которым принято решение «не подавать» (`skipped_vacancies`).
// Питает вкладку «Пропуски» в очереди «Расширения»: нажатый «Пропуск» должен уезжать туда
// сразу, а не просто исчезать из очереди.
export function fetchSkippedList(limit = 100) {
  return api.get<SkippedVacancy[]>(`/skipped?limit=${limit}`)
}
