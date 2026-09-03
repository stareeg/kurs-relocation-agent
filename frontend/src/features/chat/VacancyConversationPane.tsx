import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"
import { formatMessagesForCopy, type ConvThread } from "@/api/conversations"
import type { Job, JobApplyFieldsUpdate } from "@/api/jobs"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { HelpTip } from "@/components/ui/help-tip"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { cn } from "@/lib/utils"
import { usePersistedBoolean } from "@/lib/use-persisted-boolean"
import { pluralMessages } from "@/components/chat/composer-widgets"
import { useVacancyConversation } from "@/features/jobs/use-vacancy-conversation"
import { useMessageSelection } from "@/features/jobs/use-message-selection"
import { useUpdateJobApplyFields } from "@/features/jobs/use-job-apply-fields"
import { usePendingSalaryRefresh } from "@/features/jobs/use-jobs"
import { useRecomputeSalary } from "@/features/jobs/use-recompute-salary"
import { SalaryRefreshButton } from "@/features/jobs/SalaryRefreshButton"
import { DialogComposer, DialogTimeline, type ReplyTarget } from "@/features/jobs/VacancyDialog"
import { VacancyPinnedText } from "@/features/jobs/VacancyPinnedText"
import {
  headerSalaryLabel,
  isSalaryStillPending,
  salaryHeaderHint,
  WORK_FORMAT_MANUAL_OPTIONS,
  workFormatLabel,
} from "@/features/jobs/funnel"
import { useCandidateSalaryMin } from "@/features/resume/use-resume"
import { useUpdateHrMeta, useUpdateVacancyIdentity } from "@/features/chat/use-conversations"
import { VacancyChatHeader } from "./VacancyChatHeader"

function Meta({
  label,
  value,
  tone,
  title,
}: {
  label: string
  value: string
  tone?: string
  title?: string
}) {
  return (
    <span
      className="inline-flex items-center gap-1.5 whitespace-nowrap text-sm leading-none"
      title={title}
    >
      <span className="text-slate-400">{label}</span>
      <span className={cn("font-semibold tabular-nums", tone ?? "text-slate-800")}>{value}</span>
    </span>
  )
}

// JS-8.3: LLM/площадка не определили формат — вместо немого прочерка даём выбрать из канона
// (WORK_FORMAT_MANUAL_OPTIONS) прямо в шапке. Триггер — компактный, под рост строки Meta/ScoreButton
// (h-5, без рамки/тени): полноразмерный SelectTrigger (h-8) раздул бы всю строку метрик по высоте.
function WorkFormatSelect({
  onSelect,
  disabled,
}: {
  onSelect: (value: string) => void
  disabled?: boolean
}) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-sm leading-none">
      <span className="text-slate-400">Формат</span>
      <Select onValueChange={onSelect} disabled={disabled}>
        <SelectTrigger
          className="h-5 gap-1 rounded-md border-0 bg-transparent px-1 py-0 text-sm font-semibold text-violet-700 shadow-none hover:bg-slate-100 [&_svg]:size-3.5"
          title="Формат не определён — выберите вручную"
        >
          <SelectValue placeholder="указать" />
        </SelectTrigger>
        <SelectContent>
          {WORK_FORMAT_MANUAL_OPTIONS.map((opt) => (
            <SelectItem key={opt.value} value={opt.value}>
              {opt.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </span>
  )
}

export function VacancyConversationPane({
  vacancyId,
  job,
  thread,
}: {
  vacancyId: string
  job: Job
  thread?: ConvThread
}) {
  const conv = useVacancyConversation(job)
  const activeThread = conv.thread ?? thread
  const updateHr = useUpdateHrMeta()
  const updateIdentity = useUpdateVacancyIdentity()
  const updateApplyFields = useUpdateJobApplyFields()
  // Персистится в localStorage (UX6): состояние переключателя не должно сбрасываться при
  // переходе между диалогами и разделами фронтенда.
  const [hideHr, setHideHr] = usePersistedBoolean("copilot.chat.hide-hr")
  const [hideAi, setHideAi] = usePersistedBoolean("copilot.chat.hide-ai")

  const selection = useMessageSelection()
  const [replyTo, setReplyTo] = useState<ReplyTarget | null>(null)
  const [pendingDeleteIds, setPendingDeleteIds] = useState<number[] | null>(null)

  const salaryMin = useCandidateSalaryMin()
  const salary = headerSalaryLabel(job, salaryMin)
  const salaryHint = salaryHeaderHint(job, salaryMin)
  const format = workFormatLabel(job.work_format)
  const salaryPending = isSalaryStillPending(job.score?.salary.estimate_pending, salary.text)
  const salaryLocked = job.score?.salary.source === "explicit"
  usePendingSalaryRefresh(salaryPending)
  const recomputeSalary = useRecomputeSalary()

  // value приходит из WORK_FORMAT_MANUAL_OPTIONS — тот же канон, что WorkFormatManual в схеме
  // (иначе не пройдёт валидацию бэка); Select даёт string, приводим типом в точке вызова.
  function pickWorkFormat(value: string) {
    if (job.id == null) return
    updateApplyFields.mutate({
      id: job.id,
      work_format: value as JobApplyFieldsUpdate["work_format"],
    })
  }

  const headerMetrics = (
    <div className="flex flex-nowrap items-center gap-x-4">
      <span className="inline-flex items-center gap-0.5">
        <Meta
          label="Зарплата"
          value={salary.text === "—" ? "—" : salary.text}
          tone={salary.meetsMin === true ? "text-emerald-700" : undefined}
          title={salaryHint ?? undefined}
        />
        <SalaryRefreshButton
          pending={salaryPending}
          locked={salaryLocked}
          onClick={() => recomputeSalary.mutate(vacancyId)}
        />
      </span>
      {format ? (
        <Meta label="Формат" value={format} />
      ) : job.id != null ? (
        <WorkFormatSelect onSelect={pickWorkFormat} disabled={updateApplyFields.isPending} />
      ) : (
        <Meta label="Формат" value="—" />
      )}
      <HelpTip id="chat.header-metrics" />
    </div>
  )

  function saveHrMeta(patch: { contactName?: string; hrLink?: string }) {
    if (activeThread?.id == null) return
    updateHr.mutate({
      threadId: activeThread.id,
      vacancyId,
      contactName: patch.contactName,
      hrLink: patch.hrLink,
    })
  }

  function copySelection(ids: number[]) {
    const idSet = new Set(ids)
    const selected = conv.messages.filter((m) => idSet.has(m.id))
    const text = formatMessagesForCopy(selected, activeThread?.contact_name)
    selection.clear()
    if (!text) return
    navigator.clipboard.writeText(text).then(
      () =>
        toast.success(selected.length === 1 ? "Сообщение скопировано" : "Сообщения скопированы"),
      () => toast.error("Не удалось скопировать"),
    )
  }

  function requestDeleteSelection(ids: number[]) {
    if (ids.length === 0) return
    setPendingDeleteIds(ids)
  }

  async function confirmDelete() {
    if (!pendingDeleteIds) return
    try {
      await conv.deleteMessages(pendingDeleteIds)
      selection.clear()
    } catch {
      /* тост в хуке */
    } finally {
      setPendingDeleteIds(null)
    }
  }

  const scrollRef = useRef<HTMLDivElement | null>(null)
  const prevLen = useRef(0)
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const total = conv.messages.length + conv.queue.length
    const grew = total > prevLen.current
    prevLen.current = total
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 140
    if (grew || nearBottom) el.scrollTo({ top: el.scrollHeight })
  }, [conv.messages, conv.queue])

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-slate-50">
      <header className="shrink-0 border-b bg-background px-4 py-2.5">
        <div className="min-w-0">
          <VacancyChatHeader
            job={job}
            thread={activeThread ?? undefined}
            hrLink={conv.hrLink}
            metrics={headerMetrics}
            onHrSave={
              activeThread?.id != null
                ? (p) =>
                    saveHrMeta({
                      contactName: p.contactName,
                      hrLink: p.hrLink,
                    })
                : undefined
            }
            hrSaveDisabled={updateHr.isPending}
            onIdentitySave={(patch) => updateIdentity.mutate({ vacancyId, ...patch })}
            identitySaveDisabled={updateIdentity.isPending}
            onApplyFunnelSuggestion={conv.applyFunnelSuggestion}
            onDismissFunnelSuggestion={conv.dismissFunnelSuggestion}
            funnelSuggestionPending={conv.funnelSuggestionPending}
          />
        </div>
      </header>

      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
        <div className="sticky top-0 z-10">
          <VacancyPinnedText
            job={job}
            onAttachText={(text) => conv.attachVacancyText(text)}
            attaching={conv.isAttachingText}
          />
        </div>
        <div className="p-4 pt-3">
          <DialogTimeline
            conv={conv}
            vacancyId={vacancyId}
            hrContactName={activeThread?.contact_name}
            hideHr={hideHr}
            hideAi={hideAi}
            selection={selection}
            onReply={setReplyTo}
            onCopySelection={copySelection}
            onDeleteSelection={requestDeleteSelection}
          />
        </div>
      </div>

      <DialogComposer
        conv={conv}
        canAsk
        hideHr={hideHr}
        onToggleHideHr={() => setHideHr((v) => !v)}
        hideAi={hideAi}
        onToggleHideAi={() => setHideAi((v) => !v)}
        replyTo={replyTo}
        onClearReply={() => setReplyTo(null)}
        selection={selection}
        onCopySelection={() => copySelection(Array.from(selection.selectedIds))}
        onRequestDeleteSelection={() => requestDeleteSelection(Array.from(selection.selectedIds))}
      />

      <ConfirmDialog
        open={pendingDeleteIds != null}
        onOpenChange={(open) => {
          if (!open) setPendingDeleteIds(null)
        }}
        title={
          pendingDeleteIds
            ? `Удалить ${pendingDeleteIds.length} ${pluralMessages(pendingDeleteIds.length)}?`
            : "Удалить сообщение?"
        }
        description="Действие необратимо."
        onConfirm={() => void confirmDelete()}
      />
    </div>
  )
}
