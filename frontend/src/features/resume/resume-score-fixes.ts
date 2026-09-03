/** Structured пункты аудита writing / role_fit — зеркало `ScoreFixItem` на бэке. */

export type ScoreFixApplyAction =
  | "replace_bullet"
  | "strengthen_block"
  | "add_skill"
  | "patch_about"

export type ScoreFixSection = "experience" | "about" | "skills" | "title"

export type ScoreFixItem = {
  axis: "writing" | "role_fit"
  points_lost: number
  label: string
  current: string
  suggested: string
  why: string
  section: ScoreFixSection
  experience_index?: number | null
  apply_action: ScoreFixApplyAction
}

export type ScoreFixInput = Pick<
  import("@/api/resume").ResumeScoreBreakdown,
  "score_fixes" | "weak_bullets" | "role_fit_notes" | "writing" | "role_fit"
>

export function writingFixesFromScore(score: ScoreFixInput): ScoreFixItem[] {
  const fixes = (score.score_fixes ?? []).filter((f) => f.axis === "writing")
  if (fixes.length) return fixes as ScoreFixItem[]
  return []
}

export function roleFitFixesFromScore(score: ScoreFixInput): ScoreFixItem[] {
  const fixes = (score.score_fixes ?? []).filter((f) => f.axis === "role_fit")
  if (fixes.length) return fixes as ScoreFixItem[]
  return []
}

export function subscalePointsLost(fix: ScoreFixItem, weight: number): number {
  return Math.max(1, Math.round((fix.points_lost * weight) / 100))
}

export function replaceBulletInDescription(
  description: string,
  current: string,
  suggested: string,
): string {
  const needle = current.trim()
  if (!needle) return description
  const lines = description.split("\n")
  const idx = lines.findIndex((line) => {
    const t = line.trim()
    return t.includes(needle) || needle.includes(t.replace(/^[-•]\s*/, ""))
  })
  const bullet = suggested.trim().startsWith("-") ? suggested.trim() : `- ${suggested.trim()}`
  if (idx >= 0) {
    const next = [...lines]
    next[idx] = bullet
    return next.join("\n")
  }
  const trimmed = description.trim()
  return trimmed ? `${trimmed}\n${bullet}` : bullet
}
