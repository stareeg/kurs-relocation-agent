import type { ReactNode } from "react"

// Общий хелпер для plain-текстовых пузырей чата (вакансия/рынок): голые URL в тексте становятся
// кликабельными ссылками. Вынесен из VacancyDialog.tsx — используется и в MarketChat.tsx.
export function linkify(text: string): ReactNode[] {
  return text.split(/(https?:\/\/[^\s<]+)/g).map((part, i) =>
    /^https?:\/\//.test(part) ? (
      <a
        key={i}
        href={part}
        target="_blank"
        rel="noopener noreferrer"
        className="font-medium text-sky-700 underline decoration-sky-300 underline-offset-2 hover:text-sky-800"
      >
        {part}
      </a>
    ) : (
      <span key={i}>{part}</span>
    ),
  )
}
