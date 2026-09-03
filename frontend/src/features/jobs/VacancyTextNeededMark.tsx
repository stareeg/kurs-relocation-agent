import { AlertTriangle } from "lucide-react"
import { cn } from "@/lib/utils"
import { VACANCY_TEXT_NEEDED_HINT } from "./funnel"

/** Восклицание вместо скора: stub без текста JD — откройте страницу вакансии. */
export function VacancyTextNeededMark({
  className,
  size = "md",
}: {
  className?: string
  size?: "sm" | "md" | "lg"
}) {
  const iconClass = size === "lg" ? "size-5" : size === "sm" ? "size-3.5" : "size-4"
  return (
    <span
      className={cn("inline-flex shrink-0 text-amber-600", className)}
      title={VACANCY_TEXT_NEEDED_HINT}
      aria-label={VACANCY_TEXT_NEEDED_HINT}
    >
      <AlertTriangle className={iconClass} strokeWidth={2.25} />
    </span>
  )
}
