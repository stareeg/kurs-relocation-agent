import { Loader2, RefreshCw } from "lucide-react"

// Кнопка «Обновить» рядом с зарплатой — ручной пересчёт вилки в обход полного /score, на случай
// если она не посчиталась или посчиталась неверно. Общая для шапки чата вакансии (Чаты) и
// дровера (Вакансии) — обе поверхности уже используют usePendingSalaryRefresh для того же job.
export function SalaryRefreshButton({
  pending,
  locked,
  onClick,
}: {
  pending: boolean
  locked: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={pending || locked}
      title={locked ? "Зарплата зафиксирована вручную" : "Пересчитать зарплату"}
      className="inline-flex items-center justify-center rounded-md p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 disabled:cursor-not-allowed disabled:opacity-40"
    >
      {pending ? (
        <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />
      ) : (
        <RefreshCw className="size-3.5" strokeWidth={2} />
      )}
    </button>
  )
}
