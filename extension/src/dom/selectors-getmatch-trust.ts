/**
 * GM-12: парсер чеклиста доверия getmatch — GET /api/trust (JSON, тот же origin, cookies).
 *
 * getmatch отдаёт `{trusted, profile_filled, profile_checks: {phone,email,photo,skills,experience,
 * education}, linkedin_connected, github_connected, hh_connected, socials_required}`. Парсим в
 * структурный вид, пригодный для показа в расширении и персиста на бэке. Не трогает DOM —
 * чистый JSON.
 */

export type GmTrustProfileChecks = {
  phone: boolean
  email: boolean
  photo: boolean
  skills: boolean
  experience: boolean
  education: boolean
}

export type GmTrust = {
  trusted: boolean
  profile_filled: boolean
  profile_checks: GmTrustProfileChecks
  linkedin_connected: boolean
  github_connected: boolean
  hh_connected: boolean
  socials_required: boolean
}

const CHECK_KEYS = ['phone', 'email', 'photo', 'skills', 'experience', 'education'] as const

function toBool(v: unknown): boolean {
  return v === true || v === 1 || v === 'true' || v === '1'
}

export function parseGetmatchTrustFromJson(raw: Record<string, unknown> | unknown): GmTrust | null {
  try {
    if (!raw || typeof raw !== 'object') return null
    const arr = Array.isArray(raw) ? raw : null
    const data: unknown = arr ? arr[0] : raw
    if (!data || typeof data !== 'object') return null
    const root = data as Record<string, unknown>
    // getmatch может оборачивать в {trust: {...}} — берём вложенный, иначе сам корень.
    const trust: Record<string, unknown> =
      (root.trust as Record<string, unknown> | undefined) ?? root

    const checksSrc = (trust.profile_checks ?? {}) as Record<string, unknown>
    const profile_checks: GmTrustProfileChecks = {
      phone: false,
      email: false,
      photo: false,
      skills: false,
      experience: false,
      education: false,
    }
    for (const key of CHECK_KEYS) {
      profile_checks[key] = toBool(checksSrc[key])
    }

    return {
      trusted: toBool(trust.trusted),
      profile_filled: toBool(trust.profile_filled),
      profile_checks,
      linkedin_connected: toBool(trust.linkedin_connected),
      github_connected: toBool(trust.github_connected),
      hh_connected: toBool(trust.hh_connected),
      socials_required: toBool(trust.socials_required),
    }
  } catch {
    return null
  }
}
