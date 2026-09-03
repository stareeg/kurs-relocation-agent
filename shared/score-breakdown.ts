// Разбор балла «Почему N» — общая логика строк панели расширения и дровера (U-06 / V-04).

import {
  DEFAULT_SCORE_BREAKDOWN_MAX,
  SCORE_BREAKDOWN_DISPLAY_ORDER,
  SCORE_BREAKDOWN_LABEL,
  SECOND_JOB_BREAKDOWN_DISPLAY_ORDER,
  SECOND_JOB_SCORE_BREAKDOWN_MAX,
  fractionTone,
  isScoreBreakdownComplete,
  isSecondJobScoreBreakdown,
  scoreBreakdownTone,
  type CriterionTone,
  type ScoreBreakdownInput,
  type ScoreBreakdownKey,
} from "./criteria"

export type ScoreBreakdownWeights = Partial<Record<ScoreBreakdownKey, number>>

export type ScoreBreakdownSource = ScoreBreakdownInput & {
  overall_score: number
  score_breakdown?: Partial<Record<ScoreBreakdownKey, number>>
  salary: ScoreBreakdownInput["salary"] & { note?: string }
  remote_abroad_compat: ScoreBreakdownInput["remote_abroad_compat"] & { reasoning?: string }
  grade_match: ScoreBreakdownInput["grade_match"] & { reasoning?: string }
  role_content_match?: { score?: number | null; reasoning?: string }
  burnout_risk: ScoreBreakdownInput["burnout_risk"] & { reasoning?: string }
  company_fit?: { level?: string | null; reasoning?: string } | null
}

function scoreBreakdownReasoning(key: ScoreBreakdownKey, s: ScoreBreakdownSource): string {
  switch (key) {
    case "salary":
      return s.salary?.note || ""
    case "work_format":
      return s.remote_abroad_compat?.reasoning || ""
    case "grade_match":
      return s.grade_match?.reasoning || ""
    case "role_content":
      return s.role_content_match?.reasoning || ""
    case "management":
      return s.burnout_risk?.reasoning || ""
    case "company":
      return s.company_fit?.reasoning ?? ""
    case "flexibility":
    case "compat":
    case "rate":
      return ""
  }
}

export type ScoreBreakdownRow = {
  key: ScoreBreakdownKey
  label: string
  value: number
  max: number
  tone: CriterionTone
  reasoning: string
}

/** Шесть строк в фиксированном порядке отображения (2×3 сетка, не по убыванию вклада — иначе
 *  разбор перемешивается от вакансии к вакансии); null для легаси-формы score_breakdown. */
export function scoreBreakdownRows(
  s: ScoreBreakdownSource,
  weights?: ScoreBreakdownWeights | null,
): ScoreBreakdownRow[] | null {
  const breakdown = s.score_breakdown
  if (!isScoreBreakdownComplete(breakdown)) return null
  const secondJob = isSecondJobScoreBreakdown(breakdown)
  const order = secondJob ? SECOND_JOB_BREAKDOWN_DISPLAY_ORDER : SCORE_BREAKDOWN_DISPLAY_ORDER
  const max = secondJob ? SECOND_JOB_SCORE_BREAKDOWN_MAX : (weights ?? DEFAULT_SCORE_BREAKDOWN_MAX)
  return order.map((key) => {
    const rawVal = breakdown[key] ?? 0
    const m =
      max[key] ??
      (secondJob ? SECOND_JOB_SCORE_BREAKDOWN_MAX[key] : DEFAULT_SCORE_BREAKDOWN_MAX[key]) ??
      15
    const val = Math.max(0, rawVal)
    return {
      key,
      label: SCORE_BREAKDOWN_LABEL[key],
      value: val,
      max: m,
      tone: secondJob && (key === "flexibility" || key === "compat" || key === "rate")
        ? fractionTone(val, m)
        : scoreBreakdownTone(key, s),
      reasoning: scoreBreakdownReasoning(key, s),
    }
  })
}

/** Остаток «сумма разбора − итоговый балл» — мягкие калибровки (`score.adjustments`).
 *  С Этапа 1 гейт в остаток не входит: дилбрейкер стал флагом и балл не режет. */
export function scoreCalibrationDelta(
  overallScore: number,
  rows: Pick<ScoreBreakdownRow, "value">[],
): number {
  const sum = rows.reduce((acc, r) => acc + r.value, 0)
  return overallScore - sum
}

export type ParsedScoreGate = { label: string; key: ScoreBreakdownKey }

/** Разбор `gate_triggered` («Балл срезан: формат-гейт») в ярлык + вовлечённый критерий — общая
 * логика панели расширения и дровера: иконку-барьер рисуем прямо в строке фактора-виновника, не
 * отдельным текстовым лейблом. Маппинг на критерий — по суффиксу «-гейт» (`detect_gates` в
 * `rules.py`): формат→work_format, грейд→grade_match; company-правила отдают reason как есть →
 * company. Префикс «Балл срезан: » — исторический проводной маркер: с Этапа 1 гейт балл не
 * режет, но форма строки в сохранённом jsonb осталась прежней. */
export function parseScoreGate(gate: string | null | undefined): ParsedScoreGate {
  const raw = gate ? String(gate) : ""
  const label = raw.replace(/^балл срезан:\s*/i, "").trim() || raw
  const low = label.toLowerCase()
  let key: ScoreBreakdownKey
  if (low.includes("формат")) key = "work_format"
  else if (low.includes("грейд")) key = "grade_match"
  else if (low.includes("професси")) key = "role_content"
  else if (low.includes("зарплат")) key = "salary"
  else if (low.includes("ставк")) key = "rate"
  else if (low.includes("домен") || low.includes("стек") || low.includes("роль")) key = "role_content"
  else if (low.includes("управлен") || low.includes("выгоран")) key = "management"
  else if (
    low.includes("право на работу") ||
    low.includes("присутств") ||
    low.includes("пересечен")
  )
    key = "compat"
  else if (low.includes("эксклюзив") || low.includes("гибк")) key = "flexibility"
  else key = "company"
  return { label, key }
}
