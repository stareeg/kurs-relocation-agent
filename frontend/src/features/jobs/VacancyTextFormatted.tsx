import { useEffect, useRef } from "react"

// Общий рендер текста вакансии с абзацами + **выделениями** (feature 2, LLM-форматирование,
// кэшируется бэкендом по хэшу текста — `useVacancyTextFormat`). Один компонент для Дровера
// (`JobDetailDrawer.tsx`) и закреплённого сообщения в Чатах (`VacancyPinnedText.tsx`) — оба
// показывают один и тот же форматированный текст и не должны разойтись в разметке.

/** `**жирным**` → `<strong>`. Split с захватывающей группой чередует [обычный, жирный, ...]. */
export function BoldRuns({ text }: { text: string }) {
  const parts = text.split(/\*\*([^*\n]+)\*\*/g)
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <strong key={i} className="font-semibold text-slate-900">
            {part}
          </strong>
        ) : (
          part
        ),
      )}
    </>
  )
}

/**
 * Текст вакансии, отформатированный LLM: абзацы + **выделения** вместо сплошного полотна.
 * `highlight` (Дровер: подсветка цитаты сигнала формата) — необязателен, закреплённое
 * сообщение в Чатах его не использует.
 */
export function VacancyTextFormatted({
  text,
  highlight = null,
  className,
}: {
  text: string
  highlight?: string | null
  className?: string
}) {
  const markRef = useRef<HTMLElement | null>(null)
  useEffect(() => {
    if (highlight && markRef.current) {
      markRef.current.scrollIntoView({ block: "center", behavior: "smooth" })
    }
  }, [highlight])

  const needle = highlight?.trim().toLowerCase() ?? ""
  const paragraphs = text.split(/\n{2,}/).filter((p) => p.trim())
  // Первый абзац, где нашлась цитата — остальные при том же тексте её не подсвечивают.
  const matchIndex = needle ? paragraphs.findIndex((p) => p.toLowerCase().includes(needle)) : -1

  return (
    <div className={className ?? "space-y-3 rounded-lg bg-slate-50 p-2.5 text-sm text-slate-700"}>
      {paragraphs.map((para, i) => {
        if (i !== matchIndex) {
          return (
            <p key={i} className="whitespace-pre-wrap">
              <BoldRuns text={para} />
            </p>
          )
        }
        const idx = para.toLowerCase().indexOf(needle)
        return (
          <p key={i} className="whitespace-pre-wrap">
            <BoldRuns text={para.slice(0, idx)} />
            <mark ref={markRef} className="rounded bg-amber-200/70 px-0.5 text-slate-900">
              <BoldRuns text={para.slice(idx, idx + needle.length)} />
            </mark>
            <BoldRuns text={para.slice(idx + needle.length)} />
          </p>
        )
      })}
    </div>
  )
}
