import type { LucideIcon } from "lucide-react"
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

/** Кнопка пустого состояния: переход по вкладке, внешняя ссылка или локальный обработчик. */
export type EmptyStateAction = {
  label: string
  to?: string
  href?: string
  onClick?: () => void
}

/**
 * empty — раздела/подборки ещё нет («здесь появится…»); filtered — данные есть, но фильтры их
 * скрыли («ничего не найдено»); failed — загрузка не удалась. `filtered` визуально не отличается
 * от `empty` (оба нейтральны), `failed` красится в статусный тон `bad` (D-04) — ошибка должна
 * читаться иначе, чем «здесь пока пусто».
 */
export type EmptyStateVariant = "empty" | "filtered" | "failed"

const ICON_WRAP_CLASS: Record<EmptyStateVariant, string> = {
  empty: "bg-muted text-muted-foreground",
  filtered: "bg-muted text-muted-foreground",
  failed: "bg-status-bad-soft text-status-bad-fg",
}

/**
 * Единый шаблон пустого состояния (D-09, было `Placeholder` шага 36 universal profile):
 * одна строка «что здесь будет», одна «что для этого сделать», кнопка-действие. Почти всегда
 * есть реальное действие (перейти, повторить, сбросить фильтр) — оставляй `action` без него
 * только для чисто описательных подсказок, где действие уже под рукой на этом же экране
 * (см. `ProgressPanel`: «выбери формат собеса слева»).
 */
export function EmptyState({
  variant = "empty",
  icon: Icon,
  title,
  note,
  action,
}: {
  variant?: EmptyStateVariant
  icon: LucideIcon
  title: string
  note: string
  action?: EmptyStateAction
}) {
  return (
    <div className="flex flex-1 items-center justify-center p-6">
      <div className="flex max-w-sm flex-col items-center gap-3 text-center">
        <div
          className={cn(
            "flex size-12 items-center justify-center rounded-xl",
            ICON_WRAP_CLASS[variant],
          )}
        >
          <Icon className="size-5" strokeWidth={2} />
        </div>
        <div className="space-y-1">
          <p className="text-sm font-medium text-foreground">{title}</p>
          <p className="text-sm text-muted-foreground">{note}</p>
        </div>
        {action ? <EmptyStateActionButton action={action} /> : null}
      </div>
    </div>
  )
}

/**
 * Ошибка загрузки раздела/блока (D-10) — тот же силуэт, что `variant="failed"` (D-09), но
 * `action` обязателен: у ошибки почти всегда есть осмысленное «повторить», в отличие от пустых
 * состояний, где действие иногда объективно некуда повесить.
 * `compact` — для виджета внутри уже загруженного раздела (рельса вакансий, панель на странице
 * настроек), а не полноэкранного провала: узкая полоса тем же тоном `bad`, а не центрированный
 * экран во весь блок.
 */
export function ErrorState({
  compact = false,
  icon: Icon,
  title,
  note,
  action,
}: {
  compact?: boolean
  icon: LucideIcon
  title: string
  note: string
  action: EmptyStateAction
}) {
  if (compact) {
    return (
      <div className="flex w-full items-center gap-3 rounded-lg border border-status-bad-line bg-status-bad-soft px-3 py-2 text-status-bad-fg">
        <Icon className="size-4 shrink-0" strokeWidth={2} />
        <p className="min-w-0 flex-1 text-sm">{note}</p>
        <EmptyStateActionButton action={action} className="shrink-0" />
      </div>
    )
  }
  return <EmptyState variant="failed" icon={Icon} title={title} note={note} action={action} />
}

function EmptyStateActionButton({
  action,
  className = "mt-1",
}: {
  action: EmptyStateAction
  className?: string
}) {
  if (action.to) {
    return (
      <Button asChild size="sm" className={className}>
        <Link to={action.to}>{action.label}</Link>
      </Button>
    )
  }
  if (action.href) {
    return (
      <Button asChild size="sm" variant="outline" className={className}>
        <a href={action.href} target="_blank" rel="noreferrer">
          {action.label}
        </a>
      </Button>
    )
  }
  return (
    <Button size="sm" className={className} onClick={action.onClick}>
      {action.label}
    </Button>
  )
}
