import { useEffect, useRef, useState } from "react"
import { AlertTriangle, ChevronDown, Loader2, Pin } from "lucide-react"
import type { Job } from "@/api/jobs"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"
import { needsVacancyText } from "./funnel"
import { useVacancyTextFormat } from "./use-vacancy-text-format"
import { VacancyTextFormatted } from "./VacancyTextFormatted"

// Закреплённое сообщение «Текст вакансии» (как в Telegram, план п.2): заменяет старый режим
// композера «Вакансия» — краткая строка вверху ленты, клик разворачивает просмотр/правку.
// Клик прямо по тексту сразу открывает его на редактирование (без отдельной кнопки «Изменить»),
// правка автосохраняется тем же мутатором `conv.attachVacancyText`, что и раньше — бэк не менялся.
// Форматирование (абзацы + **выделения**) — тот же LLM-кэш `useVacancyTextFormat`, что и вкладка
// «Вакансия» дровера (`JobDetailDrawer.tsx`), поэтому текст здесь и там не расходится.

const AUTOSAVE_DEBOUNCE_MS = 1500

function oneLine(text: string, max = 90): string {
  const flat = text.replace(/\s+/g, " ").trim()
  return flat.length > max ? `${flat.slice(0, max).trimEnd()}…` : flat
}

export function VacancyPinnedText({
  job,
  onAttachText,
  attaching,
}: {
  job: Pick<Job, "vacancy_text" | "overall_score" | "vacancy_id">
  onAttachText: (text: string) => Promise<unknown>
  attaching?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState("")
  const [dirty, setDirty] = useState(false)
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const savedTextRef = useRef("")

  const missing = needsVacancyText(job)
  const text = (job.vacancy_text ?? "").trim()
  const hasText = Boolean(text)
  const { data: textFormat } = useVacancyTextFormat(job.vacancy_id ?? null, hasText && !editing)
  const formattedText = textFormat?.formatted?.trim()

  useEffect(
    () => () => {
      if (saveTimer.current) clearTimeout(saveTimer.current)
    },
    [],
  )

  function toggleOpen() {
    setOpen((v) => {
      const next = !v
      if (next && (missing || !text)) startEdit()
      return next
    })
  }

  function startEdit() {
    savedTextRef.current = text
    setDraft(text)
    setDirty(false)
    setEditing(true)
  }

  function stopEdit() {
    if (saveTimer.current) {
      clearTimeout(saveTimer.current)
      saveTimer.current = null
    }
    setEditing(false)
    setDirty(false)
    if (missing || !savedTextRef.current) setOpen(false)
  }

  function commit(value: string) {
    const v = value.trim()
    if (!v || v === savedTextRef.current || attaching) return
    savedTextRef.current = v
    onAttachText(v).catch(() => {
      /* тост в хуке */
    })
  }

  function scheduleSave(value: string) {
    setDirty(true)
    if (saveTimer.current) clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(() => {
      saveTimer.current = null
      setDirty(false)
      commit(value)
    }, AUTOSAVE_DEBOUNCE_MS)
  }

  function flushSave() {
    if (saveTimer.current) {
      clearTimeout(saveTimer.current)
      saveTimer.current = null
    }
    setDirty(false)
    commit(draft)
  }

  return (
    <div className={cn("border-b", missing ? "bg-amber-50/60" : "bg-white")} data-missing={missing}>
      <button
        type="button"
        onClick={toggleOpen}
        aria-expanded={open}
        className={cn(
          "flex w-full items-center gap-2 px-4 py-2 text-left text-sm transition-colors hover:bg-black/[0.02]",
        )}
      >
        {missing ? (
          <AlertTriangle className="size-4 shrink-0 text-amber-600" strokeWidth={2} />
        ) : (
          <Pin className="size-4 shrink-0 text-slate-400" strokeWidth={2} />
        )}
        <span className="min-w-0 flex-1 truncate">
          <span className={cn("font-medium", missing ? "text-amber-800" : "text-slate-700")}>
            Текст вакансии
          </span>
          {!missing && text ? <span className="text-slate-500"> · {oneLine(text)}</span> : null}
          {missing ? (
            <span className="text-amber-700"> · не добавлен, нажмите, чтобы добавить</span>
          ) : null}
        </span>
        {attaching || dirty ? (
          <Loader2 className="size-3.5 shrink-0 animate-spin text-slate-400" strokeWidth={2} />
        ) : null}
        <ChevronDown
          className={cn(
            "size-3.5 shrink-0 text-slate-400 transition-transform",
            open && "rotate-180",
          )}
          strokeWidth={2}
        />
      </button>

      {open ? (
        <div className="space-y-1.5 px-4 pb-3">
          {editing ? (
            <>
              <Textarea
                value={draft}
                onChange={(e) => {
                  setDraft(e.target.value)
                  scheduleSave(e.target.value)
                }}
                onBlur={flushSave}
                onKeyDown={(e) => {
                  if (e.key === "Escape") {
                    e.currentTarget.blur()
                    stopEdit()
                  }
                }}
                placeholder="Вставьте текст вакансии целиком — обязанности, требования, условия. Заменит бриф и пересчитает скор…"
                className="w-full bg-white text-sm"
                maxHeight={288}
                autoFocus
              />
              <p className="text-right text-xs text-slate-400">
                {dirty ? "сохраняю…" : "сохранено — просто начните печатать, чтобы изменить"}
              </p>
            </>
          ) : (
            <button
              type="button"
              onClick={startEdit}
              title="Нажмите, чтобы редактировать"
              className="block w-full text-left"
            >
              {formattedText ? (
                <VacancyTextFormatted
                  text={formattedText}
                  className="max-h-56 space-y-2 overflow-y-auto rounded-lg border bg-white p-3 text-sm text-slate-700 transition-colors hover:bg-slate-50"
                />
              ) : (
                <div className="max-h-56 overflow-y-auto rounded-lg border bg-white p-3 text-sm whitespace-pre-wrap text-slate-700 transition-colors hover:bg-slate-50">
                  {text}
                </div>
              )}
            </button>
          )}
        </div>
      ) : null}
    </div>
  )
}
