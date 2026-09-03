import { useEffect, useRef, useState } from "react"
import { Loader2, Send, X } from "lucide-react"
import { toast } from "sonner"
import { ApiError } from "@/api/client"
import {
  importConversationDump,
  openConversation,
  suggestVacancyAttach,
  type VacancyAttachSuggestion,
} from "@/api/conversations"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { useCreateOutreachVacancy } from "@/features/chat/use-conversations"

export type OutreachDraftFields = {
  company: string
  position: string
  vacancyUrl: string
  contactName: string
  hrLink: string
}

// eslint-disable-next-line react-refresh/only-export-components -- фабрика черновика для родителя
export function defaultOutreachDraft(): OutreachDraftFields {
  return {
    company: "",
    position: "",
    vacancyUrl: "",
    contactName: "",
    hrLink: "",
  }
}

const SUGGEST_DEBOUNCE_MS = 500
const FIELD_CLS = "h-10 bg-white"

// FR2-87 / FR3-72: дамп/компания/ссылка совпали с вакансией в воронке — предложить привязку
// вместо новой карточки. Ровно 1 кандидат — одна фраза, ≥2 — список.
function AttachSuggestionBanner({
  candidates,
  onApply,
  onDismiss,
  disabled,
}: {
  candidates: VacancyAttachSuggestion[]
  onApply: (vacancyId: string) => void
  onDismiss: () => void
  disabled?: boolean
}) {
  if (candidates.length === 0) return null
  const linkCls =
    "font-medium underline decoration-sky-400 underline-offset-2 hover:text-sky-950 disabled:opacity-50"
  return (
    <div className="flex items-start gap-2 rounded-lg border border-sky-200 bg-sky-50/80 px-3 py-2 text-sm text-sky-800">
      <span className="min-w-0 flex-1">
        {candidates.length === 1 ? (
          <>
            Такая вакансия уже есть в воронке — привязать переписку к{" "}
            <button
              type="button"
              disabled={disabled}
              onClick={() => onApply(candidates[0].vacancy_id)}
              className={linkCls}
            >
              {candidates[0].label}
            </button>
            ?
          </>
        ) : (
          <>
            Похоже на уже открытые вакансии:{" "}
            {candidates.map((c, i) => (
              <span key={c.vacancy_id}>
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => onApply(c.vacancy_id)}
                  className={linkCls}
                >
                  {c.label}
                </button>
                {i < candidates.length - 1 ? ", " : ""}
              </span>
            ))}
          </>
        )}
      </span>
      <button
        type="button"
        disabled={disabled}
        onClick={onDismiss}
        aria-label="Скрыть предложение"
        className="shrink-0 rounded p-0.5 text-sky-600/70 transition-colors hover:bg-sky-100 hover:text-sky-900 disabled:opacity-50"
      >
        <X className="size-3.5" strokeWidth={2} />
      </button>
    </div>
  )
}

export function NewVacancyConversationPane({
  draft,
  onDraftChange,
  onCreated,
}: {
  draft: OutreachDraftFields
  onDraftChange: (draft: OutreachDraftFields) => void
  onCreated: (vacancyId: string) => void
}) {
  const create = useCreateOutreachVacancy()
  const [text, setText] = useState("")
  const [vacancyText, setVacancyText] = useState("")
  const [attachCandidates, setAttachCandidates] = useState<VacancyAttachSuggestion[]>([])
  const [attachDismissed, setAttachDismissed] = useState(false)
  const [attachPending, setAttachPending] = useState(false)
  const suggestSeq = useRef(0)
  const busy = create.isPending || attachPending

  function patch(p: Partial<OutreachDraftFields>) {
    if (p.company !== undefined || p.vacancyUrl !== undefined) {
      setAttachDismissed(false)
    }
    onDraftChange({ ...draft, ...p })
  }

  // FR2-87 / FR3-72: по дампу/компании/ссылке предложить привязку (1 = фраза, ≥2 = список).
  useEffect(() => {
    const combined = [text, vacancyText]
      .map((s) => s.trim())
      .filter(Boolean)
      .join("\n")
    const company = draft.company.trim()
    const vacancyUrl = draft.vacancyUrl.trim()
    if (!combined && !company && !vacancyUrl) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- сброс подсказки при опустевших полях черновика
      setAttachCandidates([])
      return
    }
    if (attachDismissed) return

    const seq = ++suggestSeq.current
    const timer = window.setTimeout(() => {
      void suggestVacancyAttach({
        text: combined,
        company,
        vacancy_url: vacancyUrl,
      })
        .then((res) => {
          if (seq !== suggestSeq.current) return
          setAttachCandidates(res.candidates ?? [])
        })
        .catch(() => {
          if (seq !== suggestSeq.current) return
          setAttachCandidates([])
        })
    }, SUGGEST_DEBOUNCE_MS)
    return () => window.clearTimeout(timer)
  }, [text, vacancyText, draft.company, draft.vacancyUrl, attachDismissed])

  function canCreate(extraText?: string) {
    const t = (extraText ?? text).trim()
    return Boolean(
      draft.company.trim() ||
      draft.vacancyUrl.trim() ||
      draft.contactName.trim() ||
      draft.hrLink.trim() ||
      vacancyText.trim() ||
      t,
    )
  }

  async function submitHr() {
    const t = text.trim()
    if (!canCreate(t) || busy) return
    create.mutate(
      {
        company: draft.company.trim(),
        position: draft.position.trim(),
        contact_name: draft.contactName.trim(),
        hr_link: draft.hrLink.trim(),
        vacancy_url: draft.vacancyUrl.trim(),
        initial_text: t,
        vacancy_text: vacancyText.trim(),
      },
      {
        onSuccess: (res) => {
          setText("")
          setVacancyText("")
          setAttachCandidates([])
          onCreated(res.vacancy_id)
        },
      },
    )
  }

  async function applyAttachSuggestion(vacancyId: string) {
    const chosen = attachCandidates.find((c) => c.vacancy_id === vacancyId)
    if (!chosen || attachPending) return
    const dump = text.trim()
    setAttachPending(true)
    try {
      if (dump) {
        const res = await importConversationDump(chosen.vacancy_id, dump)
        if (res.added > 0) {
          toast.success(`Привязано, сообщений: ${res.added}`)
        } else {
          toast.success("Открыт существующий разговор")
        }
      } else {
        // Без дампа привязать нечего — но диалог всё равно должен стать настоящим (в БД,
        // видимым в списке слева), а не просто локальной навигацией без следа.
        await openConversation(chosen.vacancy_id)
        toast.success("Открыт существующий разговор")
      }
      // Подставим поля черновика на случай повторного захода — и уйдём в найденную вакансию.
      if (chosen.company || chosen.title) {
        patch({
          company: chosen.company || draft.company,
          position: chosen.title || draft.position,
        })
      }
      setText("")
      setVacancyText("")
      setAttachCandidates([])
      onCreated(chosen.vacancy_id)
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Не удалось привязать переписку")
    } finally {
      setAttachPending(false)
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-slate-50">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-lg flex-col gap-3 p-4">
          <Input
            value={draft.company}
            onChange={(e) => patch({ company: e.target.value })}
            placeholder="Компания"
            className={FIELD_CLS}
            disabled={busy}
          />
          <Input
            value={draft.position}
            onChange={(e) => patch({ position: e.target.value })}
            placeholder="Должность"
            className={FIELD_CLS}
            disabled={busy}
          />
          <Input
            value={draft.vacancyUrl}
            onChange={(e) => patch({ vacancyUrl: e.target.value })}
            placeholder="Ссылка на вакансию"
            className={FIELD_CLS}
            disabled={busy}
          />
          <Input
            value={draft.contactName}
            onChange={(e) => patch({ contactName: e.target.value })}
            placeholder="Имя HR"
            className={FIELD_CLS}
            disabled={busy}
          />
          <Input
            value={draft.hrLink}
            onChange={(e) => patch({ hrLink: e.target.value })}
            placeholder="Telegram HR — @username или t.me/…"
            className={FIELD_CLS}
            disabled={busy}
          />
          <Textarea
            value={vacancyText}
            onChange={(e) => {
              setAttachDismissed(false)
              setVacancyText(e.target.value)
            }}
            placeholder="Текст вакансии целиком — обязанности, требования, условия (если ссылка не с hh.ru/getmatch.ru)"
            className="bg-white"
            maxHeight={288}
            disabled={busy}
          />
          <Textarea
            value={text}
            onChange={(e) => {
              setAttachDismissed(false)
              setText(e.target.value)
            }}
            placeholder="Переписка с HR — вставьте первое сообщение или дамп из Telegram целиком"
            className="bg-white"
            disabled={busy}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault()
                void submitHr()
              }
            }}
          />
          <AttachSuggestionBanner
            candidates={attachCandidates}
            onApply={(id) => void applyAttachSuggestion(id)}
            onDismiss={() => {
              setAttachDismissed(true)
              setAttachCandidates([])
            }}
            disabled={attachPending}
          />
          <Button
            size="lg"
            className="gap-2"
            disabled={!canCreate() || busy}
            onClick={() => void submitHr()}
          >
            {busy ? (
              <Loader2 className="size-4 animate-spin" strokeWidth={2} />
            ) : (
              <Send className="size-4" strokeWidth={2} />
            )}
            Добавить вакансию
          </Button>
        </div>
      </div>
    </div>
  )
}
