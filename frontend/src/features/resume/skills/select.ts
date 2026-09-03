import type { SkillsPanel, SkillSuggestionRow } from "@/api/resume"

// Один и тот же отбор «видимых» и «действий» — использует SkillsPanel, чтобы шкала
// «Навыки» в балле резюме и блок спроса называли одни и те же навыки.

function byDemandDesc(a: SkillSuggestionRow, b: SkillSuggestionRow): number {
  return b.demand_count - a.demand_count
}

// Знаки состояния строки: ✓ не сигнал, это опора — рисуется нейтральным, без StatusChip;
// +/−/≈ — good/warn/info. Общий модуль (не SkillRow.tsx), чтобы формат строки был доступен
// и вне React-компонента (react-refresh требует чистых компонентов в файлах,
// экспортирующих компоненты).
export const SIGN: Record<SkillSuggestionRow["state"], string> = {
  have: "✓",
  add: "+",
  drop: "−",
  rename: "≈",
}

export function skillRowLabel(row: SkillSuggestionRow): string {
  return row.state === "rename" && row.renames_to ? `${row.skill} → ${row.renames_to}` : row.skill
}

/** Строки без скрытых и без «add» без пары на обмен при заполненных слотах (Решение 7). */
export function selectVisibleRows(panel: SkillsPanel | null | undefined): SkillSuggestionRow[] {
  const rows = panel?.rows ?? []
  if (!panel) return []
  const isFull = panel.slots_used >= panel.slots_limit
  const dropPool = rows.filter((r) => r.state === "drop" && r.user_state !== "accepted")
  const swappable = new Set<string>()
  let i = 0
  for (const row of rows) {
    if (row.state !== "add") continue
    if (dropPool[i]) swappable.add(row.skill)
    i += 1
  }
  return rows.filter((r) => {
    if (r.user_state === "hidden") return false
    if (isFull && r.state === "add" && !swappable.has(r.skill)) return false
    return true
  })
}

/** Видимые строки-действия (не «держу»), отсортированные по спросу — вкладка «Действия». */
export function selectActionRows(panel: SkillsPanel | null | undefined): SkillSuggestionRow[] {
  return selectVisibleRows(panel)
    .filter((r) => r.state !== "have")
    .sort(byDemandDesc)
}
