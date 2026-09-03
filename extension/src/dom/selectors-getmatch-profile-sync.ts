/**
 * GM-13: парсер профиля getmatch — GET /api/profiles (JSON, тот же origin, cookies).
 *
 * Парсит summary/skills/experience/education/зарплатные ожидания/локации в структурный вид,
 * пригодный для сравнения с Copilot-резюме на бэке. Не трогает DOM — чистый JSON.
 */

export type GmProfile = {
  full_name: string
  /** Локации (город + страна). */
  locations: string[]
  /** Свободный текст «Обо мне» из профиля getmatch. */
  summary: string
  /** Навыки (ключевые слова, как ввёл кандидат). */
  skills: string[]
  /** Специализации (роли/грейды, выбранные на getmatch). */
  specializations: GmSpecialization[]
  /** Опыт работы (getmatch-версия). */
  experience: GmExperience[]
  /** Образование (getmatch-версия). */
  education: GmEducation[]
  /** Зарплатные ожидания (вилка + валюта). */
  salary_expectation: GmSalaryExpectation | null
  /** Текущая позиция. */
  current_position: string
}

export type GmSpecialization = {
  name: string
  /** Грейд (junior/middle/senior/lead) или пусто. */
  grade: string
  /** Минимальная зарплата в вилке этой специализации (или null). */
  salary_min: number | null
  /** желаемая зарплата (комфортная) или null. */
  salary_desired: number | null
}

export type GmExperience = {
  company: string
  position: string
  start: string
  end: string
  current: boolean
  description: string
}

export type GmEducation = {
  institution: string
  degree: string
  field: string
  year: string
}

export type GmSalaryExpectation = {
  /** Валюта (RUB/USD/EUR). */
  currency: string
  /** Годовая/месячная? Парсим из поля профиля. */
  period: string
  /** Минимальная ожидаемая. */
  from: number | null
  /** Комфортная/желаемая. */
  to: number | null
}

/**
 * FETCH: GET /api/profiles → raw JSON-ответ getmatch. Не используем в контенте экстеншена —
 * только сам парсер и fetch-вызывающий (getmatch-profile-sync.ts).
 */
export function parseGetmatchProfileFromJson(
  raw: Record<string, unknown> | unknown,
): GmProfile | null {
  try {
    const arr = Array.isArray(raw) ? raw : null
    const data: unknown = arr ? arr[0] : raw
    if (!data || typeof data !== 'object') return null

    const root = data as Record<string, unknown>
    const profile: Record<string, unknown> =
      (root.profile as Record<string, unknown> | undefined) ?? root

    // Специализации: массив {name, grade, salary_min, salary_desired (желаемая)}
    const specializations: GmSpecialization[] = (
      (profile.specializations || profile.specialization || []) as Array<Record<string, unknown>>
    ).map((s: Record<string, unknown>) => ({
      name: String(s?.name ?? s?.title ?? ''),
      grade: String(s?.grade ?? s?.level ?? s?.seniority ?? ''),
      salary_min:
        typeof s?.salary_min === 'number' ? s.salary_min : null,
      salary_desired:
        typeof s?.salary_desired === 'number'
          ? s.salary_desired
          : typeof s?.salary_max === 'number'
            ? s.salary_max
            : null,
    }))

    // Локации
    const locations: string[] = (Array.isArray(profile.locations) ? profile.locations : [])
      .map((l: unknown) => {
        if (typeof l === 'string') return l
        if (typeof l === 'object' && l !== null) {
          const o = l as Record<string, unknown>
          return String(o?.name ?? o?.city ?? o?.title ?? l)
        }
        return ''
      })
      .filter(Boolean)

    // Опыт
    const experience: GmExperience[] = (
      (profile.experience || profile.work_experience || []) as Array<Record<string, unknown>>
    ).map((exp: Record<string, unknown>) => ({
      company: String(exp?.company ?? exp?.company_name ?? ''),
      position: String(exp?.position ?? exp?.title ?? exp?.role ?? ''),
      start: String(exp?.start ?? exp?.start_date ?? exp?.started_at ?? ''),
      end: String(exp?.end ?? exp?.end_date ?? exp?.finished_at ?? ''),
      current: Boolean(exp?.current ?? exp?.present ?? false),
      description: String(exp?.description ?? exp?.duties ?? ''),
    }))

    // Образование
    const education: GmEducation[] = (
      (profile.education || []) as Array<Record<string, unknown>>
    ).map((ed: Record<string, unknown>) => ({
      institution: String(ed?.institution ?? ed?.name ?? ed?.university ?? ''),
      degree: String(ed?.degree ?? ed?.level ?? ''),
      field: String(ed?.field ?? ed?.specialization ?? ed?.faculty ?? ''),
      year: String(ed?.year ?? ed?.graduation_year ?? ed?.graduation ?? ''),
    }))

    // Зарплатные ожидания
    let salary_expectation: GmSalaryExpectation | null = null
    const sal = (profile.salary_expectation ??
      profile.expected_salary ??
      profile.salary ??
      {}) as Record<string, unknown>
    if (sal) {
      const from =
        typeof sal?.from === 'number'
          ? sal.from
          : typeof sal?.min === 'number'
            ? sal.min
            : null
      const to =
        typeof sal?.to === 'number'
          ? sal.to
          : typeof sal?.max === 'number'
            ? sal.max
            : typeof sal?.desired === 'number'
              ? sal.desired
              : null
      salary_expectation = {
        currency: String(sal?.currency ?? 'RUB'),
        period: String(sal?.period ?? 'month'),
        from,
        to,
      }
    }

    return {
      full_name: String(
        profile.full_name ??
          profile.name ??
          profile.display_name ??
          '',
      ),
      locations,
      summary: String(
        profile.summary ??
          profile.about ??
          profile.about_me ??
          profile.bio ??
          '',
      ),
      skills: (Array.isArray(profile.skills) ? profile.skills.map(String) : []).filter(
        (s: string) => s.length > 0,
      ),
      specializations,
      experience,
      education,
      salary_expectation,
      current_position: String(
        profile.current_position ??
          profile.position ??
          profile.title ??
          '',
      ),
    }
  } catch {
    return null
  }
}