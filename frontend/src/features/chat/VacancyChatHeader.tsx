import { type ReactNode, useState } from "react"
import { CalendarClock, Check, Pencil, X } from "lucide-react"
import type { ConvThread } from "@/api/conversations"
import { vacancyHeading } from "@/api/conversations"
import type { Job } from "@/api/jobs"
import { StageChainPills } from "@/components/job/StageChain"
import { Input } from "@/components/ui/input"
import { StatusChip } from "@/components/ui/status-chip"
import { formatEventLabel } from "@/lib/format"
import { jobSourceGroup, resolveJobListingUrl } from "@/features/jobs/source"
import { SourceIcon } from "@/features/jobs/SourceIcon"
import { HrContactRow } from "./HrContactRow"

// FR: карандаш у названия вакансии — компания/должность правятся вручную (executive-recruiter
// кейс: экзек-рекрутер выходит на связь ДО того, как определилась конкретная роль — заголовок
// заведён вслепую при первом контакте, поправить его можно только тут, руками). Enter сохраняет
// оба поля разом и пересчитывает скор бэком, если уже есть текст вакансии.
function InlineIdentityEdit({
  company,
  title,
  onSave,
  onCancel,
  disabled,
}: {
  company: string
  title: string
  onSave: (patch: { company: string; title: string }) => void
  onCancel: () => void
  disabled?: boolean
}) {
  const [companyDraft, setCompanyDraft] = useState(company)
  const [titleDraft, setTitleDraft] = useState(title)
  const commit = () => onSave({ company: companyDraft.trim(), title: titleDraft.trim() })

  return (
    <span className="inline-flex min-w-0 flex-1 items-start gap-1">
      <span className="flex min-w-0 flex-1 flex-col gap-1">
        <Input
          value={companyDraft}
          onChange={(e) => setCompanyDraft(e.target.value)}
          placeholder="Компания"
          className="h-7 max-w-[220px] text-xs"
          disabled={disabled}
          autoFocus
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault()
              commit()
            }
            if (e.key === "Escape") onCancel()
          }}
        />
        <Input
          value={titleDraft}
          onChange={(e) => setTitleDraft(e.target.value)}
          placeholder="Должность"
          className="h-7 max-w-[220px] text-xs"
          disabled={disabled}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault()
              commit()
            }
            if (e.key === "Escape") onCancel()
          }}
        />
      </span>
      <button
        type="button"
        disabled={disabled}
        onClick={commit}
        className="mt-0.5 rounded p-1 text-emerald-600 hover:bg-emerald-50"
        title="Сохранить"
      >
        <Check className="size-3.5" strokeWidth={2} />
      </button>
      <button
        type="button"
        disabled={disabled}
        onClick={onCancel}
        className="mt-0.5 rounded p-1 text-slate-400 hover:bg-slate-100"
        title="Отмена"
      >
        <X className="size-3.5" strokeWidth={2} />
      </button>
    </span>
  )
}

// RD-15: «Созвон: чт 09.07 15:00» — ближайший назначенный этап, извлечён фоном из HR-переписки.
function NextStageBadge({ thread }: { thread?: ConvThread }) {
  const label = formatEventLabel(thread?.next_stage_at)
  if (!label) return null
  return (
    <StatusChip tone="info" className="whitespace-nowrap">
      <CalendarClock className="size-3.5 shrink-0" strokeWidth={2} />
      Созвон: {label}
    </StatusChip>
  )
}

// FR2-86: LLM предложила сдвиг воронки из диалога — один клик применяет, крестик снимает.
function FunnelSuggestionChip({
  status,
  onApply,
  onDismiss,
  disabled,
}: {
  status: string
  onApply?: () => void
  onDismiss?: () => void
  disabled?: boolean
}) {
  return (
    <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-md border border-amber-200 bg-amber-50/80 py-0.5 pl-2.5 pr-1 text-xs font-medium text-amber-800">
      <button
        type="button"
        disabled={disabled || !onApply}
        onClick={onApply}
        className="transition-colors hover:text-amber-950 disabled:opacity-50"
      >
        Перевести в «{status}»?
      </button>
      {onDismiss ? (
        <button
          type="button"
          disabled={disabled}
          onClick={onDismiss}
          aria-label="Скрыть предложение"
          className="rounded p-0.5 text-amber-600/70 transition-colors hover:bg-amber-100 hover:text-amber-900 disabled:opacity-50"
        >
          <X className="size-3.5" strokeWidth={2} />
        </button>
      ) : null}
    </span>
  )
}

export function VacancyChatHeader({
  job,
  thread,
  hrLink,
  metrics,
  onHrSave,
  hrSaveDisabled,
  onIdentitySave,
  identitySaveDisabled,
  onApplyFunnelSuggestion,
  onDismissFunnelSuggestion,
  funnelSuggestionPending,
}: {
  job: Job
  thread?: ConvThread
  hrLink?: string | null
  metrics?: ReactNode
  onHrSave?: (patch: { contactName?: string; hrLink?: string }) => void
  hrSaveDisabled?: boolean
  onIdentitySave?: (patch: { company: string; title: string }) => void
  identitySaveDisabled?: boolean
  onApplyFunnelSuggestion?: () => void
  onDismissFunnelSuggestion?: () => void
  funnelSuggestionPending?: boolean
}) {
  const sourceGroup = jobSourceGroup(job)
  const listingUrl = resolveJobListingUrl(job)
  const heading = vacancyHeading(job, thread)
  const suggestedStatus = thread?.suggested_funnel_status?.trim() || null
  const [editIdentity, setEditIdentity] = useState(false)

  const titleBlock = editIdentity ? (
    <InlineIdentityEdit
      company={job.company ?? ""}
      title={job.title ?? ""}
      disabled={identitySaveDisabled}
      onCancel={() => setEditIdentity(false)}
      onSave={(patch) => {
        onIdentitySave?.(patch)
        setEditIdentity(false)
      }}
    />
  ) : (
    <span className="inline-flex min-w-0 max-w-full items-start gap-1">
      {listingUrl ? (
        <a
          href={listingUrl.startsWith("http") ? listingUrl : `https://${listingUrl}`}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex min-w-0 items-start gap-2 rounded-lg py-0.5 transition-colors hover:bg-slate-50"
        >
          <SourceIcon group={sourceGroup} size={16} className="mt-0.5 shrink-0" />
          <span className="min-w-0 truncate text-sm font-semibold text-sky-600 hover:text-sky-700 hover:underline">
            {heading}
          </span>
        </a>
      ) : (
        <span className="inline-flex min-w-0 items-start gap-2">
          <SourceIcon group={sourceGroup} size={16} className="mt-0.5 shrink-0" />
          <span className="min-w-0 truncate text-sm font-semibold text-slate-900">{heading}</span>
        </span>
      )}
      {onIdentitySave && (
        <button
          type="button"
          title="Изменить компанию/должность"
          disabled={identitySaveDisabled}
          onClick={() => setEditIdentity(true)}
          className="mt-0.5 shrink-0 rounded p-0.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 disabled:opacity-40"
        >
          <Pencil className="size-3" strokeWidth={2} />
        </button>
      )}
    </span>
  )

  return (
    <div className="space-y-1.5">
      {/* Заголовок + HR-контакты сверху; Зарплата/Формат и подписанные этапы воронки — одной
          строкой ниже (не переносятся, при нехватке ширины скроллятся по горизонтали). Строка
          заведомо чуть выше своего контента (py-1, не просто pt), иначе паддинг «в притык» под
          самый высокий чип даёт горизонтальный overflow-x-auto побочный вертикальный скролл —
          браузер трактует overflow-x:auto с overflow-y:visible как overflow-y:auto. */}
      <div className="flex items-start justify-between gap-x-3">
        <div className="min-w-0 flex-1">{titleBlock}</div>
        <div className="shrink-0">
          <HrContactRow
            contactName={thread?.contact_name}
            hrLink={hrLink}
            onSave={onHrSave}
            disabled={hrSaveDisabled}
          />
        </div>
      </div>
      {metrics || suggestedStatus ? (
        <div className="flex flex-nowrap items-center gap-x-4 overflow-x-auto py-1">
          {metrics}
          <NextStageBadge thread={thread} />
          {suggestedStatus ? (
            <FunnelSuggestionChip
              status={suggestedStatus}
              onApply={onApplyFunnelSuggestion}
              onDismiss={onDismissFunnelSuggestion}
              disabled={funnelSuggestionPending}
            />
          ) : null}
          <StageChainPills vacancyId={job.vacancy_id} nowrap />
        </div>
      ) : null}
    </div>
  )
}
