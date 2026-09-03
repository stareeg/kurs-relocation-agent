import { Link } from "react-router-dom"
import { Compass } from "lucide-react"
import { EmptyState, ErrorState } from "@/components/ui/empty-state"
import { Skeleton } from "@/components/ui/skeleton"
import { useCareerSnapshot } from "./use-career"

// Активные этапы воронки (стадии, где вакансия ещё «в работе») — тот же список, что
// `ACTIVE_STAGES` в core/domains/market/stage_aging.py.
const ACTIVE_STAGES_QUERY = "Скрининг,Техничка,Финал,Оффер"

const EMPLOYMENT_LABEL: Record<string, string> = {
  employed: "Работаю",
  searching_free: "Свободен для поиска",
}

/**
 * Полоса «Где я сейчас» (Э9.2) — снимок фактов без единого поля ввода. Верхняя строка крупно:
 * статус занятости + режим/рынок поиска + сколько дней в поиске. Нижняя строка — числа, каждое
 * кликабельно и ведёт в свой раздел с уже наложенным фильтром.
 */
export function CareerSnapshotStrip() {
  const { data: snap, isLoading, isError, refetch } = useCareerSnapshot()

  if (isLoading) return <Skeleton className="h-16 w-full rounded-lg" />
  if (isError) {
    return (
      <ErrorState
        compact
        icon={Compass}
        title="Снимок не загрузился"
        note="Не удалось получить сводку — данные на месте, их сейчас не видно."
        action={{ label: "Повторить", onClick: () => void refetch() }}
      />
    )
  }
  if (!snap) return null

  if (snap.days_active == null && !snap.active_applications && snap.resume_score == null) {
    return (
      <EmptyState
        icon={Compass}
        title="Ещё ничего не оценивали"
        note="Снимок появится, как только система оценит первую вакансию."
      />
    )
  }

  const headline = [
    EMPLOYMENT_LABEL[snap.employment],
    snap.search_mode_label,
    snap.tracks.length > 1 ? snap.tracks.join(" + ") : null,
    snap.market_scope_label,
    snap.days_active != null ? `${snap.days_active} дн.` : null,
  ]
    .filter(Boolean)
    .join(" · ")

  return (
    <div className="space-y-1 rounded-xl border bg-white p-4">
      {headline && <p className="text-sm font-medium text-slate-800">{headline}</p>}
      <p className="flex flex-wrap items-center gap-x-1.5 text-xs text-slate-500">
        <Link
          to={`/jobs?stage=${ACTIVE_STAGES_QUERY}`}
          className="font-medium text-slate-700 hover:underline"
        >
          {snap.active_applications}
        </Link>
        <span>активных откликов</span>
        {snap.stalled > 0 && (
          <>
            <span>·</span>
            <Link
              to={`/jobs?stage=${ACTIVE_STAGES_QUERY}`}
              className="font-medium text-status-warn-fg hover:underline"
            >
              {snap.stalled}
            </Link>
            <span>без движения</span>
          </>
        )}
        {snap.resume_score != null && (
          <>
            <span>·</span>
            <span>балл резюме</span>
            <Link to="/resume" className="font-medium text-slate-700 hover:underline">
              {snap.resume_score}
            </Link>
          </>
        )}
      </p>
    </div>
  )
}
