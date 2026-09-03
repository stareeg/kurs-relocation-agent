import { SectionTitle } from "@/components/ui/section-title"
import { formatVacancyEventAt } from "@/lib/format"
import { useVacancyEvents } from "./use-vacancy-events"

export function VacancyEvents({ vacancyId }: { vacancyId: string | null }) {
  const { data, isLoading, isError } = useVacancyEvents(vacancyId)
  const items = data?.items ?? []

  return (
    <div className="space-y-2">
      <SectionTitle>События</SectionTitle>
      {isLoading ? (
        <p className="text-sm text-slate-400">Загружаю…</p>
      ) : isError ? (
        <p className="text-sm text-slate-400">Не удалось загрузить события.</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-slate-400">Событий пока нет.</p>
      ) : (
        <ul className="space-y-1.5">
          {items.map((ev) => (
            <li key={ev.id} className="flex items-baseline gap-3 text-sm">
              <span className="w-[5.75rem] shrink-0 tabular-nums text-slate-400">
                {formatVacancyEventAt(ev.at)}
              </span>
              <span className="min-w-0 text-slate-800">{ev.label}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
