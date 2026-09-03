import { useEffect, useRef } from "react"
import { Check, ChevronDown } from "lucide-react"
import { HelpTip } from "@/components/ui/help-tip"
import type { HelpTextId } from "@/lib/help-texts"
import { usePersistedBoolean } from "@/lib/use-persisted-boolean"
import { cn } from "@/lib/utils"
import { useResumeCollapse } from "./resume-collapse-context"

// Общая обёртка секций формы резюме (`ResumeForm.tsx`) и вынесенных из неё блоков
// (`skills/KeySkillsSection.tsx`, U-09/P-08) — один источник вместо копии разметки.

/** Ненавязчивый маркер «стоит дозаполнить» у пустых важных полей (в т.ч. после PDF-парса). */
export function NeedsFillMark() {
  return (
    <HelpTip id="resume.field-needs-fill" side="top">
      <span
        // вне шкалы D-07: значок size-3.5, а не читаемый текст
        className="inline-flex size-3.5 shrink-0 items-center justify-center rounded-full bg-amber-100 text-[10px] font-semibold leading-none text-amber-700 ring-1 ring-amber-200/80"
        aria-label="Стоит заполнить"
      >
        !
      </span>
    </HelpTip>
  )
}

/** Компактная зелёная галочка «блок заполнен» — без эмодзи и без «AI-slop» бейджа. */
export function SectionCompleteMark() {
  return (
    <span
      className="inline-flex size-3.5 shrink-0 items-center justify-center rounded-full bg-emerald-500/12 text-emerald-600 ring-1 ring-emerald-500/20"
      aria-label="Заполнено"
      title="Все поля блока заполнены"
    >
      <Check className="size-2.5" strokeWidth={3} />
    </span>
  )
}

/** Обёртка контрола с янтарным кольцом, когда поле стоит дозаполнить. */
export function NeedsFillWrap({
  active,
  className,
  children,
}: {
  active?: boolean
  className?: string
  children: React.ReactNode
}) {
  // Всегда один и тот же DOM-узел: смена fragment↔div при active размонтирует инпут
  // и сбрасывает фокус (город/ФИО — ввод в пустое поле после паузы).
  return (
    <div className={cn(active && "rounded-md ring-1 ring-amber-300/55", className)}>
      {children}
    </div>
  )
}

// `dense` — компактный вариант (RD-3): секции с короткими однострочными полями (Личные
// данные/Контакты/Языки) не нуждаются в том же воздухе, что textarea-секции («Обо мне» и т.п.).
export function Section({
  id,
  title,
  hint,
  helpId,
  action,
  dense,
  needsFill,
  className,
  defaultOpen = true,
  children,
}: {
  /** Ключ для localStorage свёрнутости (`copilot.resume.section.<id>.open`). */
  id: string
  title: string
  hint?: React.ReactNode
  helpId?: HelpTextId
  action?: React.ReactNode
  dense?: boolean
  /** `true` — блок неполный (янтарный «!»); `false` — зелёная галочка. */
  needsFill?: boolean
  className?: string
  defaultOpen?: boolean
  children: React.ReactNode
}) {
  const [open, setOpen] = usePersistedBoolean(`copilot.resume.section.${id}.open`, defaultOpen)
  // Форс-сворачивание/разворачивание из кнопки «Свернуть все»/«Развернуть все». Вызываем в
  // эффекте по инкременту сигнала, не в рендере — иначе setOpen во время рендера → бесконечный
  // цикл. Сам сигнал персистится через общий setOpen (та же localStorage-ключ).
  const collapse = useResumeCollapse()
  const appliedSignal = useRef(0)
  useEffect(() => {
    if (collapse.signal === appliedSignal.current) return
    appliedSignal.current = collapse.signal
    setOpen(collapse.collapse)
  }, [collapse.signal, collapse.collapse, setOpen])

  return (
    <div
      className={cn(
        "overflow-hidden rounded-xl border bg-white shadow-xs transition-[border-color,box-shadow] duration-200",
        needsFill && "border-amber-200/80",
        needsFill === false && "border-emerald-100/90",
        needsFill == null && "border-slate-200/90",
        className,
      )}
    >
      <div
        className={cn(
          "flex items-center gap-1",
          open && "border-b border-slate-100",
        )}
      >
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-controls={`resume-section-${id}`}
          className={cn(
            "group flex min-w-0 flex-1 items-center gap-2.5 px-3 text-left",
            dense ? "py-2" : "py-2.5",
            "hover:bg-slate-50/90",
            "outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset",
          )}
        >
          <span
            className={cn(
              "flex size-6 shrink-0 items-center justify-center rounded-md bg-slate-100 text-slate-500",
              "transition-colors group-hover:bg-slate-200/80 group-hover:text-slate-700",
            )}
          >
            <ChevronDown
              className={cn(
                "size-3.5 transition-transform duration-200 ease-out",
                !open && "-rotate-90",
              )}
              strokeWidth={2.25}
              aria-hidden
            />
          </span>
          <span className="flex min-w-0 items-center gap-1.5">
            {needsFill === false ? <SectionCompleteMark /> : null}
            {needsFill === true ? (
              <span
                className="inline-flex size-3.5 shrink-0 items-center justify-center rounded-full bg-amber-100 text-[10px] font-semibold leading-none text-amber-700 ring-1 ring-amber-200/80"
                aria-label="Стоит заполнить"
              >
                !
              </span>
            ) : null}
            <h3 className="text-sm font-semibold text-slate-800">{title}</h3>
            {hint != null && (
              <span className="inline-flex items-center gap-1 text-xs text-slate-400">{hint}</span>
            )}
          </span>
        </button>
        {helpId ? (
          <div className="shrink-0 pr-1">
            <HelpTip id={helpId} />
          </div>
        ) : null}
        {action ? <div className="shrink-0 pr-2">{action}</div> : null}
      </div>
      {open ? (
        <section
          id={`resume-section-${id}`}
          className={cn(dense ? "p-4" : "p-6", "resume-section-body")}
        >
          {children}
        </section>
      ) : null}
    </div>
  )
}
