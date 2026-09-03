import type { ResumeData, ResumeDataPatch } from "@/api/resume"

/**
 * Зеркалит read-modify-write `PATCH /api/resume/data` (api/routers/profile/resume.py):
 * personal/position/search_criteria сливаются по переданным ключам, остальные поля патча —
 * полная замена значения/массива. Нужна для оптимистичного апдейта кэша ["resume","data"]
 * (K-02) — сервер всё равно перезапишет кэш точным ответом в onSuccess.
 */
export function applyResumePatch(current: ResumeData, patch: ResumeDataPatch): ResumeData {
  const next: ResumeData = { ...current }

  if (patch.personal) {
    next.personal = { ...current.personal, ...patch.personal }
  }
  if (patch.position) {
    next.position = { ...current.position, ...patch.position }
  }
  if (patch.search_criteria) {
    next.search_criteria = { ...current.search_criteria, ...patch.search_criteria }
  }
  if (patch.education_level != null) {
    next.education_level = patch.education_level
  }
  if (patch.education) {
    next.education = patch.education
  }
  if (patch.languages) {
    next.languages = patch.languages
  }
  if (patch.key_skills) {
    next.key_skills = patch.key_skills
  }

  return next
}

/** Снимок «Навыки и спрос» зависит от роли/скиллов/критериев, не от ФИО и города.
 * Инвалидировать его на каждый select в «Профиле» — лишний refetch таблицы внутри скролла. */
export function patchTouchesSkillCorpus(patch: ResumeDataPatch): boolean {
  return (
    patch.key_skills !== undefined ||
    patch.position !== undefined ||
    patch.search_criteria !== undefined
  )
}
