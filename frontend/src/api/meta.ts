import type { components } from "@/api/schema"
import { api } from "@/api/client"

// 7.4 / D2 / D3: бэк — единственный источник истины для перечня ALL_JOB_SOURCES.
// Фронт не хардкодит HH_SOURCES, а строит из этого справочника (см. source.ts).
export type JobSourceItem = components["schemas"]["JobSourceItem"]
export type JobSourcesResponse = components["schemas"]["JobSourcesResponse"]
export type CitiesResponse = components["schemas"]["CitiesResponse"]
export type CitySuggestionOut = components["schemas"]["CitySuggestion"]

// GET /api/meta/sources — канон `ALL_JOB_SOURCES` + UI-группы (GM-6/GM-7).
// Статика на бэке, ответ быстрый; не кэшируем (справочник меняется редко).
export function fetchJobSources() {
  return api.get<JobSourcesResponse>("/api/meta/sources")
}

// GET /api/meta/cities — города из своих вакансий и опыта (Э0.2). Пустой список на
// холодном старте — норма, фронт подставляет курируемый справочник.
export function fetchCities() {
  return api.get<CitiesResponse>("/api/meta/cities")
}
