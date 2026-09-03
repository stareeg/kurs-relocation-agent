import type { AdminDiagnosisItem } from "@/api/admin"
import { Button } from "@/components/ui/button"
import { SectionTitle } from "@/components/ui/section-title"
import { Skeleton } from "@/components/ui/skeleton"
import { adminJournalPath } from "@/features/admin/journal-filters"

function scrollToAnchor(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" })
}

/**
 * Вердикт «что не так» — первое в Профиле. Здоровый человек — одна строка.
 */
export function DiagnosisBlock({
  items,
  loading,
  telegramUserId,
}: {
  items: readonly AdminDiagnosisItem[] | undefined
  loading: boolean
  telegramUserId: number
}) {
  if (loading && !items) {
    return (
      <div className="space-y-2">
        <SectionTitle>Что не так</SectionTitle>
        <Skeleton className="h-8 w-full" />
      </div>
    )
  }
  const problems = (items ?? []).filter((item) => !item.ok)
  return (
    <div className="space-y-2">
      <SectionTitle>Что не так</SectionTitle>
      {problems.length === 0 ? (
        <p className="text-sm text-slate-600">Всё на месте</p>
      ) : (
        <ul className="space-y-1.5 rounded-lg bg-slate-50 p-2.5">
          {problems.map((item) => (
            <li key={item.id} className="flex items-start justify-between gap-2 px-1 py-0.5">
              <div className="min-w-0">
                <p className="text-sm text-slate-800">{item.title}</p>
                {item.detail ? <p className="text-xs text-slate-500">{item.detail}</p> : null}
              </div>
              <DiagnosisAction item={item} telegramUserId={telegramUserId} />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function DiagnosisAction({
  item,
  telegramUserId,
}: {
  item: AdminDiagnosisItem
  telegramUserId: number
}) {
  if (!item.action_kind || !item.action_label) return null
  if (item.action_kind === "journal") {
    return (
      <Button size="sm" variant="outline" asChild>
        <a href={adminJournalPath({ telegramUserId: String(telegramUserId), window: "24h" })}>
          {item.action_label}
        </a>
      </Button>
    )
  }
  const target = item.action_kind === "issue_key" ? "admin-person-key" : "admin-person-contact"
  return (
    <Button size="sm" variant="outline" onClick={() => scrollToAnchor(target)}>
      {item.action_label}
    </Button>
  )
}
