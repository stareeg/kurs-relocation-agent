import { Loader2 } from "lucide-react"
import { useRef, useState, type ReactNode } from "react"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { useCandidateSalaryMin } from "@/features/resume/use-resume"
import {
  REMOTE_FEASIBILITY,
  effectiveWorkFormat,
  formatSalaryCardText,
  remoteFeasibilityOf,
  resolveJobSalary,
  salaryProvenanceLabel,
  workFormatChip,
} from "./funnel"
import { jobSourceGroup, resolveJobListingUrl } from "./source"
import { SourceIcon } from "./SourceIcon"
import { TabDecision } from "./ScoreDetails"
import { useJobPreview } from "./use-job-preview"

const OPEN_DELAY_MS = 200
// Правка 2026-08-19 пункт 6: попап рендерится в портале Radix — вне DOM-поддерева триггера,
// поэтому курсор, идущий от строки к превью через зазор (`sideOffset`), физически покидает
// триггер ДО того, как долетит до контента, и старое мгновенное закрытие по mouseleave гасило
// превью раньше, чем на него можно было навести курсор. Задержка даёт время долететь; наведение
// на сам контент (обработчики ниже) отменяет закрытие полностью, пока курсор там.
const CLOSE_DELAY_MS = 250

// Мини-дровер по наведению (Фаза A/C редизайна «Расширения», пункт 1): та же композиция, что
// первый экран вкладки «Решение» дровера (TabDecision — карточки фактов, «Почему N», бриф,
// плюсы/красные флаги/минусы), без управляющих кнопок. Открывается по ховеру строки очереди
// («Просмотр» / «Отклики») — `vacancyId` без резолвящегося job (напр. discovery parse_error)
// просто не рендерит popover, оборачивает children как есть.
export function VacancyHoverPreview({
  vacancyId,
  children,
}: {
  vacancyId: string | null | undefined
  children: ReactNode
}) {
  const [open, setOpen] = useState(false)
  const openTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const closeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const salaryMin = useCandidateSalaryMin()
  const { data: job, isLoading } = useJobPreview(vacancyId, open)

  if (!vacancyId) return <>{children}</>

  function clearOpenTimer() {
    if (openTimerRef.current) {
      clearTimeout(openTimerRef.current)
      openTimerRef.current = null
    }
  }

  function clearCloseTimer() {
    if (closeTimerRef.current) {
      clearTimeout(closeTimerRef.current)
      closeTimerRef.current = null
    }
  }

  function handleEnter() {
    clearCloseTimer()
    clearOpenTimer()
    openTimerRef.current = setTimeout(() => setOpen(true), OPEN_DELAY_MS)
  }

  function handleLeave() {
    clearOpenTimer()
    clearCloseTimer()
    closeTimerRef.current = setTimeout(() => setOpen(false), CLOSE_DELAY_MS)
  }

  // Наведение на сам попап (в портале, вне триггера) держит его открытым, пока курсор там.
  function handleContentEnter() {
    clearCloseTimer()
  }

  const s = job?.score ?? null
  const remote = job ? remoteFeasibilityOf(job) : undefined
  const remoteChip = remote?.verdict ? REMOTE_FEASIBILITY[remote.verdict] : undefined
  const formatChip = job ? workFormatChip(effectiveWorkFormat(job), s?.currency_remote) : null
  const salary = job ? resolveJobSalary(job, salaryMin) : null
  const salaryValue = salary ? formatSalaryCardText(salary) : ""
  const salaryProvenance = job ? salaryProvenanceLabel(job) : null
  // Правка 2026-08-20: заголовок шапки превью — ссылка на реальную вакансию на площадке, не
  // просто текст. Клик по названию (как и в строке очереди — QueueVacancyRow) открывает саму
  // вакансию на hh.ru/getmatch.ru/habr в новой вкладке, без похода во внутренний дровер.
  const listingUrl = job ? resolveJobListingUrl(job) : null

  return (
    <Popover open={open} onOpenChange={setOpen}>
      {/* Один общий hover-регион на триггер + портал контента: React-события всплывают по дереву
          компонентов (не DOM), портал Radix остаётся внутри этого div на уровне обработчиков. */}
      <div onMouseEnter={handleEnter} onMouseLeave={handleLeave}>
        <PopoverTrigger asChild>
          <div>{children}</div>
        </PopoverTrigger>
        <PopoverContent
          align="start"
          side="right"
          sideOffset={12}
          collisionPadding={16}
          // Правка: фиксированные 70vh резали попап скроллом даже там, где под ним реально
          // оставался свободный экран (строка ближе к верху длинной очереди) — Radix уже считает
          // фактически доступную высоту до края вьюпорта (avoidCollisions по умолчанию включён),
          // используем её вместо произвольной доли экрана; scroll остаётся страховкой на случай,
          // когда контента больше, чем есть места вообще.
          // Правка 2026-08-20: ширина попапа увеличена с 384px (`w-96`) до 500px (~+30%) — контенту
          // (плюсы/красные флаги/минусы) меньше нужно переноситься по строкам, попап меньше
          // растягивается по высоте.
          className="w-[500px] max-h-[var(--radix-popover-content-available-height)] space-y-3 overflow-y-auto"
          onOpenAutoFocus={(e) => e.preventDefault()}
          onMouseEnter={handleContentEnter}
          onMouseLeave={handleLeave}
        >
          {isLoading || !job ? (
            <div className="flex items-center justify-center py-6">
              <Loader2 className="size-4 animate-spin text-slate-400" strokeWidth={2} />
            </div>
          ) : (
            <>
              <div className="flex items-start gap-2">
                <SourceIcon group={jobSourceGroup(job)} className="mt-0.5 shrink-0" />
                <div className="min-w-0">
                  {listingUrl ? (
                    <a
                      href={listingUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="text-sm font-semibold leading-snug text-slate-900 hover:underline"
                    >
                      {job.title ?? "Без названия"}
                    </a>
                  ) : (
                    <p className="text-sm font-semibold leading-snug text-slate-900">
                      {job.title ?? "Без названия"}
                    </p>
                  )}
                  {job.company && <p className="text-xs text-slate-500">{job.company}</p>}
                </div>
              </div>
              <TabDecision
                s={s}
                vacancyId={job.vacancy_id}
                salaryValue={salaryValue}
                salary={salary!}
                formatChip={formatChip}
                salaryProvenance={salaryProvenance}
                remote={remote}
                remoteChip={remoteChip}
                hideScale
              />
            </>
          )}
        </PopoverContent>
      </div>
    </Popover>
  )
}
