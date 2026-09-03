import type { ResumeData } from "@/api/resume"

function isBlank(v: string | null | undefined): boolean {
  return v == null || String(v).trim() === ""
}

/** Зеркало `_is_filled` в `core/domains/profile/profile.py` — базовый профиль для скоринга. */
export function isResumeFilled(data: ResumeData): boolean {
  const hasRole = Boolean(data.position.title?.trim()) || (data.experience?.length ?? 0) > 0
  const hasTarget =
    (data.position.grade?.length ?? 0) > 0 ||
    Boolean(data.position.salary_min || data.position.salary_comfortable)
  return hasRole && hasTarget
}

/** Полнота блоков формы «Резюме» — зелёная галочка / янтарная подсказка в шапке секции. */
export type ResumeSectionKey =
  | "personal"
  | "contacts"
  | "search"
  | "experience"
  | "education"
  | "skills"
  | "languages"
  | "about"

export function isResumeSectionComplete(
  key: ResumeSectionKey,
  data: {
    personal: { full_name: string; city: string }
    contacts: { phone: string; email: string }
    position: {
      title: string
      categories: string[]
    }
    search_criteria: {
      market_segment: string
      niches: string[]
      dealbreakers: string[]
    }
    experience: Array<{
      company: string
      position: string
      start: string
      end: string
      current: boolean
      description: string
    }>
    education: Array<{ institution: string }>
    key_skills: string[]
    languages: Array<{ name: string; level: string }>
    about: string
  },
): boolean {
  switch (key) {
    // Блок «Профиль»: профессия и специальности переехали сюда из удалённой «Должности»,
    // поэтому входят в его полноту. Грейд и формат работы больше не здесь — они в левой
    // панели, и их «стоит заполнить» показывает она сама.
    case "personal":
      return (
        !isBlank(data.position.title) &&
        data.position.categories.length > 0 &&
        !isBlank(data.personal.full_name) &&
        !isBlank(data.personal.city)
      )
    case "contacts":
      return !isBlank(data.contacts.phone) && !isBlank(data.contacts.email)
    case "search":
      return data.search_criteria.niches.length > 0
    case "experience":
      return (
        data.experience.length > 0 &&
        data.experience.every(
          (e) =>
            !isBlank(e.company) &&
            !isBlank(e.position) &&
            !isBlank(e.start) &&
            (e.current || !isBlank(e.end)) &&
            !isBlank(e.description),
        )
      )
    case "education":
      return data.education.length > 0 && data.education.every((e) => !isBlank(e.institution))
    case "skills":
      return data.key_skills.length > 0
    case "languages":
      return (
        data.languages.length > 0 &&
        data.languages.every((l) => !isBlank(l.name) && !isBlank(l.level))
      )
    case "about":
      return !isBlank(data.about)
  }
}
