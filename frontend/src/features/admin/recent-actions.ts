/**
 * Краткие подписи последних действий человека в чате поддержки.
 */
import type { AdminRecentAction } from "@/api/admin"
import { FEATURE_LABELS } from "@/features/admin/admin-spend"

const SECTION_LABELS: Record<string, string> = {
  "/": "Главная",
  "/chat": "Чаты",
  "/jobs": "Вакансии",
  "/screening": "Скрининги",
  "/tech": "Технички",
  "/offers": "Офферы",
  "/market": "Рынок",
  "/companies": "Компании",
  "/career": "Карьера",
  "/resume": "Резюме",
  "/settings": "Аккаунт",
  "/extension": "Автоотклики",
  "/admin": "Админ",
}

export function formatRecentAction(action: Pick<AdminRecentAction, "kind" | "label">): string {
  const raw = (action.label || "").trim()
  if (!raw) return "—"
  if (action.kind === "feature") {
    const feature = FEATURE_LABELS[raw] ?? raw
    return `Фича · ${feature}`
  }
  const path = raw.split(/[?#]/)[0] || raw
  const section = SECTION_LABELS[path] ?? SECTION_LABELS[path.replace(/\/$/, "")]
  if (section) return `Раздел · ${section}`
  if (raw.startsWith("Клик ")) return raw
  return `Раздел · ${raw}`
}
