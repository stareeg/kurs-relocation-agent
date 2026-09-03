import { MessageSquare } from "lucide-react"
import { useNavigate } from "react-router-dom"
import type { Job } from "@/api/jobs"
import { StatusChip } from "@/components/ui/status-chip"
import { useCountUp } from "@/lib/use-count-up"
import { cn } from "@/lib/utils"
import { getHelpText } from "@/lib/help-texts"
import {
  ARCHIVED_BADGE,
  AUTO_APPLY_BADGE,
  cardDay,
  chatButtonLabel,
  effectiveWorkFormat,
  formatSalaryCardText,
  isAutoApplied,
  needsVacancyText,
  resolveJobSalary,
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

// Карточка вакансии в колонке воронки: слева заголовок/компания/зарплата/формат, справа скор/дата,
// кнопка чата — на всю ширину снизу. Клик по самой карточке открывает дровер (JS-1.2).
// onOpen нет в DragOverlay; navigate нет в DragOverlay → кнопку чата прячем там же.
// className — токены появления списка (motion-rise / motion-fade / motion-pop).
export function JobCard({
  job,
  onOpen,
  className,
}: {
  job: Job
  onOpen?: (job: Job) => void
  className?: string
}) {
  const navigate = useNavigate()
  const salaryMin = useCandidateSalaryMin()
  const { data: searchTracks } = useSearchTrack()
  const fmt = workFormatChip(effectiveWorkFormat(job))
  const salary = resolveJobSalary(job, salaryMin)
  const day = cardDay(job) // дата отклика/публикации, либо дата последнего изменения, если дальше
  // Оффер в руках (OF-6/OF-7) — светло-зелёный акцент, не перебивает scoreTone/зарплату внутри.
  const hasOffer = job.offer_status === "thinking" || job.offer_status === "accepted"
  // has_hr_dialog — уже в списке jobs (EXISTS hr_threads+messages); тот же смысл, что «Продолжить» в дровере.
  const chatLabel = chatButtonLabel(job)
  const isArchivedChat = chatLabel === "Архивный чат"
  // X-07 (карточка): та же быстрая ссылка на текущий этап, что в шапке дровера — рядом с «Чат».
  const sectionJump = sectionJumpFor(job)
  const scoreTarget =
    job.overall_score != null && Number.isFinite(job.overall_score) ? job.overall_score : null
  const { display: scoreDisplay, flash: scoreFlash } = useCountUp(scoreTarget)
  const missingText = needsVacancyText(job)
  const autoApplied = isAutoApplied(job)
  const rubricCaption =
    (searchTracks?.second_job_enabled || jobTrack(job) === "second_job") &&
    SCORE_RUBRIC_CAPTION[jobTrack(job)]
      ? SCORE_RUBRIC_CAPTION[jobTrack(job)]
      : ""
  return (
    <div
      role={onOpen ? "button" : undefined}
      tabIndex={onOpen ? 0 : undefined}
      onClick={onOpen ? () => onOpen(job) : undefined}
      onKeyDown={
        onOpen
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault()
                onOpen(job)
              }
            }
          : undefined
      }
      className={cn(
        "block space-y-2 rounded-xl border bg-white p-3.5 shadow-sm transition-all duration-200",
        hasOffer && "border-emerald-200 bg-emerald-50/50",
        onOpen && "cursor-pointer hover:border-slate-300 hover:shadow",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-2.5">
        <div className="min-w-0">
          <p className="line-clamp-1 truncate text-sm font-medium leading-snug text-slate-900">
            <span className="mr-1.5 inline-flex align-middle">
              <SourceIcon group={jobSourceGroup(job)} />
            </span>
            {job.title ?? "Без названия"}
          </p>
          {job.company && (
            <p className="mt-0.5 truncate text-xs font-semibold text-slate-900">{job.company}</p>
          )}
          {/* Плотные метаданные карточки без HelpTip: тултипы на скор/бейджи
              перекрывали соседние кнопки. Пояснения — в «Что делать?». */}
          <span
            className={cn(
              "mt-1 block min-w-0 truncate text-sm",
              salary.text === "—" || salary.text === "оценка…"
                ? "text-slate-400"
                : salary.isEstimate
                  ? "text-slate-400"
                  : salary.meetsMin === true
                    ? "font-medium text-emerald-700"
                    : "text-slate-600",
            )}
          >
            {formatSalaryCardText(salary)}
          </span>
          {(fmt ||
            job.is_archived ||
            autoApplied ||
            searchTracks?.second_job_enabled ||
            job.track === "second_job") && (
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              {job.is_archived && (
                <StatusChip tone={ARCHIVED_BADGE.tone} className="px-1.5 text-xs">
                  {ARCHIVED_BADGE.label}
                </StatusChip>
              )}
              {autoApplied && (
                <StatusChip
                  tone={AUTO_APPLY_BADGE.tone}
                  className="px-1.5 text-xs"
                  title={getHelpText("jobs.card-auto-applied")}
                >
                  {AUTO_APPLY_BADGE.label}
                </StatusChip>
              )}
              {fmt && (
                <StatusChip tone={fmt.tone} className="px-1.5 text-xs">
                  {fmt.label}
                </StatusChip>
              )}
              <JobTrackChip job={job} />
            </div>
          )}
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          {missingText ? (
            <VacancyTextNeededMark size="lg" />
          ) : (
            <span className="flex flex-col items-end">
              <span
                className={cn(
                  "text-2xl font-semibold leading-none tabular-nums transition-colors duration-200",
                  scoreFlash === "up" && "text-emerald-600",
                  scoreFlash === "down" && "text-rose-600",
                  !scoreFlash && scoreTone(job.overall_score),
                )}
              >
                {scoreDisplay ?? "—"}
              </span>
              {rubricCaption ? (
                <span className="mt-0.5 text-[10px] font-medium leading-none text-slate-400">
                  {rubricCaption}
                </span>
              ) : null}
            </span>
          )}
          {day.text && (
            <span
              className="text-xs font-medium tabular-nums text-slate-500"
              aria-label={day.label}
            >
              {day.text}
            </span>
          )}
          {job.total_responses != null && (
            <span className="text-xs font-medium tabular-nums text-slate-400">
              {responsesLabel(job.total_responses)}
            </span>
          )}
        </div>
      </div>

      {onOpen && (
        <div className="flex items-center gap-1.5">
          {sectionJump && (
            <button
              type="button"
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => {
                e.stopPropagation()
                navigate(`${sectionJump.path}?vacancy=${encodeURIComponent(job.vacancy_id)}`)
              }}
              className="flex flex-1 items-center justify-center rounded-lg bg-primary px-2 py-1 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90"
              aria-label={`Открыть вакансию в разделе «${sectionJump.label.replace(" →", "")}»`}
            >
              {sectionJump.label}
            </button>
          )}
          <button
            type="button"
            // Не открыть дровер и не начать drag: гасим всплытие до обёртки-перетаскивателя.
            onPointerDown={(e) => e.stopPropagation()}
            onClick={(e) => {
              e.stopPropagation()
              navigate(`/chat?vacancy=${encodeURIComponent(job.vacancy_id)}`)
            }}
            className={cn(
              "flex items-center justify-center gap-1 rounded-lg border px-2 py-1 text-xs font-medium transition-colors",
              isArchivedChat
                ? "border-slate-200 bg-slate-50 text-slate-500 hover:bg-slate-100 hover:text-slate-700"
                : "border-sky-200 bg-sky-50 text-sky-700 hover:bg-sky-100 hover:text-sky-800",
              sectionJump ? "shrink-0" : "flex-1",
            )}
            aria-label={chatLabel}
          >
            <MessageSquare className="size-3.5" strokeWidth={2} />
            {/* Отказ/Пропущено не показывают sectionJump — кнопка чата на всю ширину, места
                хватает на честный полный лейбл вместо короткого «Чат» (X-07). */}
            {isArchivedChat ? chatLabel : "Чат"}
          </button>
        </div>
      )}
    </div>
  )
}
