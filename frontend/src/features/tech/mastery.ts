import type { MockMastery } from "@/api/debrief"
import type { StatusTone } from "@/components/ui/status-chip"

// Уровень владения темой - общий словарь для Прогресса и разбора собеса: один и тот же
// MockMastery ("confident"/"medium"/"weak") рендерится одинаково точками-индикаторами
// (дизайн-дисциплина CLAUDE.md - без бэкенд-лейблов ради трёх констант).
export const MASTERY_LABEL: Record<MockMastery, string> = {
  confident: "Уверенно",
  medium: "Средне",
  weak: "Слабо",
}

// Тон для StatusChip/StatusDot (D-04) — тот же словарь, что у recommendation/work-format чипов.
export const MASTERY_TONE: Record<MockMastery, StatusTone> = {
  confident: "strong",
  medium: "warn",
  weak: "bad",
}
