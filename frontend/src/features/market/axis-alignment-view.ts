/**
 * Чистая подготовка данных для «Насколько скор совпадает с вашими решениями» (Этап 7 §7.2-7.3,
 * plans/scoring_precision_2026_08_17.md). Карточка с «Рынка» снята (slop) — логика и API
 * остаются для будущего визуала; без БД и без React.
 */
import type { components } from "@/api/schema"

export type AxisAlignmentReport = components["schemas"]["AxisAlignmentReport"]
export type AxisAlignment = components["schemas"]["AxisAlignment"]

// Порядок и подписи — как в score_breakdown.py::DEFAULT_WEIGHTS / plans §1.6.
const AXIS_LABELS: Readonly<Record<string, string>> = {
  salary: "Зарплата",
  work_format: "Формат",
  grade_match: "Грейд",
  role_content: "Роль",
  management: "Управление",
  company: "Компания",
}

const AXIS_ORDER = ["role_content", "salary", "work_format", "grade_match", "management", "company"]

export function axisLabel(axis: string): string {
  return AXIS_LABELS[axis] ?? axis
}

/** Оси, отсортированные по |delta| убыв. — самая (не)разделяющая ось видна первой. */
export function sortedAxes(axes: readonly AxisAlignment[]): AxisAlignment[] {
  const order = new Map(AXIS_ORDER.map((a, i) => [a, i]))
  return [...axes].sort((a, b) => {
    const da = Math.abs(a.delta ?? 0)
    const db = Math.abs(b.delta ?? 0)
    if (da !== db) return db - da
    return (order.get(a.axis) ?? 99) - (order.get(b.axis) ?? 99)
  })
}
