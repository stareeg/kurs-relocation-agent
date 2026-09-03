import type { ReactNode } from "react"

/**
 * Подзаголовок группы внутри карточки/дровера — единственный легальный капс в продукте.
 *
 * Жил в `features/jobs/ScoreDetails.tsx`, переехал в `components/ui` вместе с Этапом 0
 * редизайна админки: там каждый файл заводил свой вариант (`text-[11px] uppercase
 * text-slate-400`), и группы в дровере вакансии и в карточке человека выглядели по-разному.
 */
export function SectionTitle({ children }: { children: ReactNode }) {
  return (
    <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500">{children}</h3>
  )
}
