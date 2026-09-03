import type { AdminUserDetail, AdminUserRow } from "@/api/admin"
import { SectionTitle } from "@/components/ui/section-title"
import { FUNNEL_STAGES, resolveStage, type FunnelStage } from "@/features/jobs/funnel"
import {
  compactNumber,
  formatBytes,
  formatMoment,
  tokens,
  usd,
} from "@/features/admin/admin-format"
import { PersonOps } from "@/features/admin/user/PersonOps"
import { DiagnosisBlock } from "@/features/admin/user/DiagnosisBlock"
import { useAdminUserDiagnosis } from "@/features/admin/use-admin"

/**
 * Карточка человека: ключ и сессии сверху, деньги таблицей, затем работа.
 */
export function ProfileTab({
  user,
  detail,
}: {
  user: AdminUserRow
  detail: AdminUserDetail | undefined
}) {
  const snap = detail?.snapshot
  const resumeAt = snap?.resume_updated_at
  const title = [snap?.search_title, snap?.search_grades, snap?.search_formats]
    .filter(Boolean)
    .join(" · ")
  const funnelRows = funnelByStage(detail?.funnel?.counts)
  const diagnosis = useAdminUserDiagnosis(user.account_id)

  const workRows: { label: string; value: string }[] = [
    {
      label: "Резюме",
      value: resumeAt
        ? `${formatMoment(resumeAt)} · ${formatBytes(snap?.resume_bytes)}`
        : user.has_resume
          ? "есть"
          : "нет",
    },
    {
      label: "Поиск",
      value: title || "не выведен — резюме пустое",
    },
    {
      label: "Расширение",
      value: snap?.extension_version || "не видно в логах",
    },
    {
      label: "Последний скоринг",
      value: snap?.last_scored_at ? formatMoment(snap.last_scored_at) : "не оценивал",
    },
    {
      label: "Зарплата от",
      value:
        snap?.salary_min_override != null
          ? snap.salary_min_override.toLocaleString("ru-RU")
          : "нет",
    },
    // Автоотклик/автопоиск — во вкладке «Автоматизация» (со статусом по площадкам и кнопками).
  ]

  return (
    <div className="space-y-4">
      <PersonOps user={user} detail={detail} />

      <div className="space-y-2">
        <SectionTitle>Деньги</SectionTitle>
        <div className="overflow-x-auto rounded-lg bg-slate-50 p-2.5">
          <table className="w-full text-sm">
            <thead className="text-left text-xs font-medium text-slate-500">
              <tr>
                <th className="py-1 pr-3">Период</th>
                <th className="py-1 pr-3 text-right">$</th>
                <th className="py-1 pr-3 text-right">Вход</th>
                <th className="py-1 text-right">Выход</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-t border-slate-200/80">
                <td className="py-1.5 pr-3 text-slate-500">Сегодня</td>
                <td className="py-1.5 pr-3 text-right tabular-nums text-slate-800">
                  {usd(detail?.today_cost_usd ?? user.today_cost_usd)}
                </td>
                <td className="py-1.5 pr-3 text-right tabular-nums text-slate-400">—</td>
                <td className="py-1.5 text-right tabular-nums text-slate-400">—</td>
              </tr>
              <tr className="border-t border-slate-200/80">
                <td className="py-1.5 pr-3 text-slate-500">30 дней</td>
                <td className="py-1.5 pr-3 text-right tabular-nums text-slate-800">
                  {usd(detail?.month_cost_usd ?? user.month_cost_usd)}
                </td>
                <td
                  className="py-1.5 pr-3 text-right tabular-nums text-slate-800"
                  title={tokens(detail?.month_tokens_in ?? user.month_tokens_in)}
                >
                  {compactNumber(detail?.month_tokens_in ?? user.month_tokens_in)}
                </td>
                <td
                  className="py-1.5 text-right tabular-nums text-slate-800"
                  title={tokens(detail?.month_tokens_out ?? user.month_tokens_out)}
                >
                  {compactNumber(detail?.month_tokens_out ?? user.month_tokens_out)}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <DiagnosisBlock
        items={diagnosis.data?.items}
        loading={diagnosis.isLoading}
        telegramUserId={user.telegram_user_id}
      />

      <div className="space-y-2">
        <SectionTitle>Работа</SectionTitle>
        <div className="overflow-x-auto rounded-lg bg-slate-50 p-2.5">
          <table className="w-full text-sm">
            <thead className="text-left text-xs font-medium text-slate-500">
              <tr>
                <th className="py-1 pr-3">Поле</th>
                <th className="py-1 text-right">Значение</th>
              </tr>
            </thead>
            <tbody>
              {workRows.map((row) => (
                <tr key={row.label} className="border-t border-slate-200/80">
                  <td className="py-1.5 pr-3 text-slate-500">{row.label}</td>
                  <td className="py-1.5 text-right break-words text-slate-800">{row.value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {funnelRows.length > 0 && (
        <div className="space-y-2">
          <SectionTitle>Воронка</SectionTitle>
          <div className="overflow-x-auto rounded-lg bg-slate-50 p-2.5">
            <table className="w-full text-sm">
              <thead className="text-left text-xs font-medium text-slate-500">
                <tr>
                  <th className="py-1 pr-3">Этап</th>
                  <th className="py-1 text-right">Кол-во</th>
                </tr>
              </thead>
              <tbody>
                {funnelRows.map(([stage, count]) => (
                  <tr key={stage} className="border-t border-slate-200/80">
                    <td className="py-1.5 pr-3 text-slate-500">{stage}</td>
                    <td className="py-1.5 text-right tabular-nums text-slate-800">{count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

/**
 * Воронка человека — по канону продукта (`features/jobs/funnel`), а не по порядку ключей в
 * словаре. Бэкенд отдаёт сырые `jobs.status`, среди них живут легаси-варианты: «Просмотрено»
 * стоял рядом с «Просмотр» и читался как два разных этапа. `resolveStage` сводит их к одному,
 * счётчики складываются, порядок — путь кандидата.
 */
function funnelByStage(
  counts: Record<string, number> | undefined,
): [FunnelStage, number][] {
  if (!counts) return []
  const totals = new Map<FunnelStage, number>()
  for (const [status, count] of Object.entries(counts)) {
    const stage = resolveStage(status)
    totals.set(stage, (totals.get(stage) ?? 0) + count)
  }
  return FUNNEL_STAGES.filter((stage) => totals.has(stage)).map((stage) => [
    stage,
    totals.get(stage)!,
  ])
}
