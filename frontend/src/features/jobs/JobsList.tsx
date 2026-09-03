import { MessageSquare } from "lucide-react"
import { useNavigate } from "react-router-dom"
import type { Job } from "@/api/jobs"
import { HelpTip } from "@/components/ui/help-tip"
import { StatusChip } from "@/components/ui/status-chip"
import { OnboardingHint } from "@/components/ui/tooltip"
import { getHelpText } from "@/lib/help-texts"
import { ONBOARDING_HINT_IDS, useOnboardingHints } from "@/lib/use-onboarding-hints"
import { cn, useListAppearMotion } from "@/lib/utils"
import {
  ARCHIVED_BADGE,
  chatButtonLabel,
  effectiveWorkFormat,
  fmtChanged,
  formatSalaryCardText,
  needsVacancyText,
  resolveJobSalary,
  resolveStage,
  responsesLabel,
  scoreTone,
  sectionJumpFor,
  workFormatChip,
} from "./funnel"
import { jobSourceGroup } from "./source"
import { SourceIcon } from "./SourceIcon"
import { VacancyTextNeededMark } from "./VacancyTextNeededMark"
import { JobTrackChip } from "./JobTrackChip"
import { jobTrack, SCORE_RUBRIC_CAPTION } from "./use-job-track"
import { useCandidateSalaryMin } from "@/features/resume/use-resume"
import { useSearchTrack } from "@/features/career/search-track"

function Th({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <th
      className={cn(
        "sticky top-0 z-20 border-b border-slate-200 bg-slate-50 px-3 py-2.5 text-left text-xs font-semibold text-slate-800",
        className,
      )}
    >
      {children}
    </th>
  )
}

// Списочный вид рабочего стола (JS-1.3): таблица с сортировкой/фильтрами из тулбара. Клик по строке
// открывает тот же дровер, что и карточки доски.
export function JobsList({ jobs, onOpen }: { jobs: Job[]; onOpen: (job: Job) => void }) {
  const navigate = useNavigate()
  const salaryMin = useCandidateSalaryMin()
  const { data: searchTracks } = useSearchTrack()
  const { shouldShow, dismissHint } = useOnboardingHints()
  const showFirstCardHint = jobs.length > 0 && shouldShow(ONBOARDING_HINT_IDS.jobsFirstCard)
  // Сортированный набор id: смена фильтров → fade; DnD/порядок не трогаем (список сам по дате).
  const listSig = [...jobs.map((j) => String(j.id ?? j.vacancy_id))].sort().join("\0")
  const appear = useListAppearMotion(listSig)
  return (
    <div className="relative min-h-0 flex-1 overflow-auto px-6 pb-6 pt-3">
      <table className="w-full border-separate border-spacing-0 text-sm">
        <thead className="sticky top-0 z-20 shadow-[0_1px_0_0_#e2e8f0]">
          <tr>
            <Th className="w-8 px-2" aria-label="Источник">
              <span className="sr-only">Источник</span>
            </Th>
            <Th>Вакансия</Th>
            <Th className="max-w-[10rem]">Компания</Th>
            <Th>Статус</Th>
            <Th className="text-right">
              <span className="inline-flex items-center justify-end gap-1">
                Скор
                <HelpTip id="jobs.card-score" />
              </span>
            </Th>
            <Th>
              <span className="inline-flex items-center gap-1">
                Зарплата
                <HelpTip id="jobs.card-salary" />
              </span>
            </Th>
            <Th>
              <span className="inline-flex items-center gap-1">
                Формат
                <HelpTip id="jobs.card-format" />
              </span>
            </Th>
            <Th className="text-right">
              <span className="inline-flex items-center justify-end gap-1">
                Изменено
                <HelpTip id="jobs.card-date" />
              </span>
            </Th>
            <Th className="w-44 px-2" aria-label="Чат">
              <span className="sr-only">Чат</span>
            </Th>
          </tr>
        </thead>
        <tbody>
          {jobs.map((job, index) => {
            const currencyRemote = (job.score as { currency_remote?: boolean } | undefined)
              ?.currency_remote
            const formatChip = workFormatChip(effectiveWorkFormat(job), currencyRemote)
            const salary = resolveJobSalary(job, salaryMin) // оценка тоже видна — как на карточке (Этап 3)
            // Оффер в руках (OF-7) — тот же светло-зелёный акцент, что на карточке доски.
            const hasOffer = job.offer_status === "thinking" || job.offer_status === "accepted"
            const chatLabel = chatButtonLabel(job)
            const isArchivedChat = chatLabel === "Архивный чат"
            const sectionJump = sectionJumpFor(job)
            const missingText = needsVacancyText(job)
            const title = (
              <div className="min-w-0">
                <div className="flex items-center gap-1.5">
                  <span className="line-clamp-1 font-medium text-slate-900">
                    {job.title ?? "Без названия"}
                  </span>
                  {job.is_archived && (
                    <StatusChip tone={ARCHIVED_BADGE.tone} className="shrink-0 px-1.5 text-xs">
                      {ARCHIVED_BADGE.label}
                    </StatusChip>
                  )}
                </div>
                {job.total_responses != null && (
                  <span className="text-xs tabular-nums text-slate-400">
                    {responsesLabel(job.total_responses)}
                  </span>
                )}
              </div>
            )
            return (
              <tr
                key={`${job.id ?? job.vacancy_id}-${appear.appearKey}`}
                role="button"
                tabIndex={0}
                onClick={() => onOpen(job)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault()
                    onOpen(job)
                  }
                }}
                className={cn(
                  "cursor-pointer transition-colors hover:bg-slate-50 focus-visible:bg-slate-50 focus-visible:outline-none",
                  hasOffer && "bg-emerald-50/40",
                  appear.itemClass(index),
                )}
              >
                <td className="w-8 border-b border-slate-100 px-2 py-2.5">
                  <SourceIcon group={jobSourceGroup(job)} size={20} />
                </td>
                <td className="max-w-[16rem] border-b border-slate-100 px-3 py-2.5">
                  {index === 0 && showFirstCardHint ? (
                    <OnboardingHint
                      open
                      onDismiss={() => dismissHint(ONBOARDING_HINT_IDS.jobsFirstCard)}
                      side="bottom"
                      align="start"
                      content="Откройте строку — там разбор вакансии, брифинг и письмо."
                    >
                      {title}
                    </OnboardingHint>
                  ) : (
                    title
                  )}
                </td>
                <td className="max-w-[10rem] border-b border-slate-100 px-3 py-2.5 text-slate-600">
                  <span className="line-clamp-1">{job.company ?? "—"}</span>
                </td>
                <td className="border-b border-slate-100 px-3 py-2.5 text-slate-600">
                  {resolveStage(job.status)}
                </td>
                <td
                  className={cn(
                    "border-b border-slate-100 px-3 py-2.5 text-right text-base font-semibold tabular-nums",
                    !missingText && scoreTone(job.overall_score),
                  )}
                >
                  {missingText ? (
                    <span className="inline-flex justify-end">
                      <VacancyTextNeededMark />
                    </span>
                  ) : (
                    <>
                      {job.overall_score ?? "—"}
                      {(searchTracks?.second_job_enabled || jobTrack(job) === "second_job") &&
                      SCORE_RUBRIC_CAPTION[jobTrack(job)]
                        ? ` · ${SCORE_RUBRIC_CAPTION[jobTrack(job)]}`
                        : ""}
                    </>
                  )}
                </td>
                <td className="max-w-[9rem] border-b border-slate-100 px-3 py-2.5">
                  <span
                    className={cn(
                      "line-clamp-1",
                      salary.text === "—" || salary.text === "оценка…" || salary.isEstimate
                        ? "text-slate-400"
                        : salary.meetsMin === true
                          ? "font-medium text-emerald-700"
                          : "text-slate-600",
                    )}
                  >
                    {formatSalaryCardText(salary)}
                  </span>
                </td>
                <td className="border-b border-slate-100 px-3 py-2.5">
                  <div className="flex flex-wrap items-center gap-1.5">
                    {formatChip ? (
                      <StatusChip tone={formatChip.tone} className="px-1.5">
                        {formatChip.label}
                      </StatusChip>
                    ) : (
                      <span className="text-slate-400">—</span>
                    )}
                    <JobTrackChip job={job} />
                  </div>
                </td>
                <td className="border-b border-slate-100 px-3 py-2.5 text-right tabular-nums text-slate-500">
                  {fmtChanged(job)}
                </td>
                <td className="w-44 border-b border-slate-100 px-2 py-2.5 text-right">
                  <div className="flex items-center justify-end gap-1.5">
                    {sectionJump && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation()
                          navigate(
                            `${sectionJump.path}?vacancy=${encodeURIComponent(job.vacancy_id)}`,
                          )
                        }}
                        className="inline-flex shrink-0 items-center rounded-lg bg-primary px-2 py-1 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90"
                        aria-label={`Открыть вакансию в разделе «${sectionJump.label.replace(" →", "")}»`}
                      >
                        {sectionJump.label}
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation()
                        navigate(`/chat?vacancy=${encodeURIComponent(job.vacancy_id)}`)
                      }}
                      className={cn(
                        "inline-flex shrink-0 items-center gap-1 rounded-lg border px-2 py-1 text-xs font-medium transition-colors",
                        isArchivedChat
                          ? "border-slate-200 bg-slate-50 text-slate-500 hover:bg-slate-100 hover:text-slate-700"
                          : "border-sky-200 bg-sky-50 text-sky-700 hover:bg-sky-100 hover:text-sky-800",
                      )}
                      aria-label={chatLabel}
                      title={getHelpText("jobs.drawer-to-chat")}
                    >
                      <MessageSquare className="size-3.5" strokeWidth={2} />
                      Чат
                    </button>
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
