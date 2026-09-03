import type { components } from "@/api/schema"
import { api } from "@/api/client"

export type ScoreRevisionOut = components["schemas"]["ScoreRevisionOut"]
export type ScoreRevisionHistory = components["schemas"]["ScoreRevisionHistory"]

// GET /api/score-revision/{id} — история ревизий скоринга по вакансии (JS-8.1): исходный JD-скор +
// каждый пересчёт по HR-фактам, свежие первыми. Нет PG → пустой список (карточка не падает).
export function fetchScoreRevisions(vacancyId: string) {
  return api.get<ScoreRevisionHistory>(`/api/score-revision/${encodeURIComponent(vacancyId)}`)
}
