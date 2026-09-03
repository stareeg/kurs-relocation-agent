import { Fragment, type KeyboardEvent, type ReactNode, useState } from "react"
import { ArrowDown, ArrowUp, ChevronRight, Users } from "lucide-react"
import { EmptyState, type EmptyStateAction } from "@/components/ui/empty-state"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { adminSortDirection, type AdminSortColumn } from "@/features/admin/admin-filters"

/**
 * Таблица админки: колонки описываются данными, разметку строки пишем один раз.
 *
 * Строка — настоящий `<tr tabIndex={0}>`: Enter/Space открывают карточку (В3).
 *
 * Раздел десктоп-онли (Этап 0, §2.9): карточной ветки под `md` больше нет — ниже 1024 px
 * раздел целиком показывает заглушку, а не пытается ужать таблицу в 182 px.
 *
 * Этап 4: разворот (`renderExpanded`) и видимость колонок (`visibleKeys`). Шеврон в первой
 * колонке — аффорданс, что строку можно раскрыть, не открывая карточку.
 *
 * Этап 5: `renderActions` — колонка «Открыть» + `⋯` в конце строки, клик по ней не выбирает.
 */
export type AdminColumn<T> = {
  key: string
  title: ReactNode
  align?: "left" | "right"
  sortable?: boolean
  /** Ключ `?sort=` на бэкенде; по умолчанию совпадает с `key`. */
  sortKey?: AdminSortColumn
  /** Ширина колонки резервируется заранее — строка не должна дёргаться при обновлении. */
  className?: string
  render: (row: T) => ReactNode
}

export function AdminTable<T>({
  rows,
  columns,
  rowKey,
  selectedKey,
  onSelect,
  loading,
  empty,
  minWidth,
  sort,
  onSort,
  rowClassName,
  visibleKeys,
  renderExpanded,
  renderActions,
}: {
  rows: readonly T[]
  columns: readonly AdminColumn<T>[]
  rowKey: (row: T) => string | number
  selectedKey?: string | number | null
  onSelect?: (row: T) => void
  loading?: boolean
  /** Что показать вместо таблицы, когда строк нет. */
  empty?: { title: string; note?: string; icon?: typeof Users; action?: EmptyStateAction }
  minWidth?: string
  sort?: string
  onSort?: (column: AdminSortColumn) => void
  /** Подсветка строки (мягкий лимит расхода) — selected перекрывает. */
  rowClassName?: (row: T) => string | undefined
  /** Какие колонки показать; нет ключа — все. Пустой набор не прячет таблицу целиком. */
  visibleKeys?: readonly string[]
  /** Вторая строка под разворотом. Пока нет — шеврона тоже нет. */
  renderExpanded?: (row: T) => ReactNode
  /**
   * Колонка действий в конце строки: не входит в `visibleKeys`, клик по ней не открывает
   * карточку. Этап 5: «Открыть» на виду, остальное — в `⋯`.
   */
  renderActions?: (row: T) => ReactNode
}) {
  const shownColumns = visibleColumns(columns, visibleKeys)
  const [expanded, setExpanded] = useState<ReadonlySet<string | number>>(() => new Set())

  function toggleExpanded(key: string | number) {
    setExpanded((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  if (loading) {
    return (
      <div className="space-y-2 p-4">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-9 w-full" />
        ))}
      </div>
    )
  }

  if (rows.length === 0) {
    return (
      <EmptyState
        variant="filtered"
        icon={empty?.icon ?? Users}
        title={empty?.title ?? "Ничего не нашлось"}
        note={empty?.note ?? "Измените фильтр или поиск."}
        action={empty?.action}
      />
    )
  }

  return (
    <table className={cn("w-full border-collapse text-sm", minWidth)}>
      <thead className="sticky top-0 z-10 bg-slate-50 text-left text-xs font-medium text-slate-500">
        <tr>
          {shownColumns.map((column) => (
            <th
              key={column.key}
              aria-sort={ariaSort(sort, column)}
              className={cn(
                "px-3 py-2 font-medium first:pl-4",
                !renderActions && "last:pr-4",
                column.align === "right" && "text-right",
                column.className,
              )}
            >
              <ColumnTitle column={column} sort={sort} onSort={onSort} />
            </th>
          ))}
          {renderActions ? (
            <th className="w-px px-3 py-2 pr-4">
              <span className="sr-only">Действия</span>
            </th>
          ) : null}
        </tr>
      </thead>
      <tbody className="divide-y divide-slate-100">
        {rows.map((row) => {
          const key = rowKey(row)
          const selected = selectedKey === key
          const open = expanded.has(key)
          return (
            <Fragment key={key}>
              <tr
                tabIndex={onSelect ? 0 : undefined}
                className={cn(
                  onSelect &&
                    "cursor-pointer hover:bg-slate-50 focus-visible:bg-slate-50 focus-visible:outline-none",
                  rowClassName?.(row),
                  selected && "bg-slate-100",
                )}
                onClick={onSelect ? () => onSelect(row) : undefined}
                onKeyDown={
                  onSelect ? (event) => handleRowKey(event, () => onSelect(row)) : undefined
                }
              >
                {shownColumns.map((column, index) => (
                  <td
                    key={column.key}
                    className={cn(
                      "px-3 py-1.5 first:pl-4",
                      !renderActions && "last:pr-4",
                      column.align === "right" && "text-right",
                      // Метка выбранной строки — полоса слева вместо заливки цветом статуса:
                      // «выбрано» не должно выглядеть как «хорошо» (Этап 0, §2.5). Прозрачная
                      // рамка у остальных строк держит ширину, чтобы текст не прыгал.
                      index === 0 &&
                        (selected
                          ? "border-l-2 border-slate-900"
                          : "border-l-2 border-transparent"),
                    )}
                  >
                    {index === 0 && renderExpanded ? (
                      <span className="flex items-center gap-1.5">
                        <ExpandToggle
                          open={open}
                          onToggle={() => toggleExpanded(key)}
                        />
                        <span className="min-w-0 flex-1">{column.render(row)}</span>
                      </span>
                    ) : (
                      column.render(row)
                    )}
                  </td>
                ))}
                {renderActions ? (
                  <td
                    className="w-px px-3 py-1.5 pr-4"
                    onClick={(event) => event.stopPropagation()}
                    onKeyDown={(event) => event.stopPropagation()}
                  >
                    {renderActions(row)}
                  </td>
                ) : null}
              </tr>
              {open && renderExpanded ? (
                <tr className={cn(selected && "bg-slate-100")}>
                  <td
                    colSpan={shownColumns.length + (renderActions ? 1 : 0)}
                    className={cn(
                      "px-3 py-2 first:pl-4 last:pr-4",
                      selected ? "border-l-2 border-slate-900" : "border-l-2 border-transparent",
                    )}
                  >
                    {renderExpanded(row)}
                  </td>
                </tr>
              ) : null}
            </Fragment>
          )
        })}
      </tbody>
    </table>
  )
}

function visibleColumns<T>(
  columns: readonly AdminColumn<T>[],
  visibleKeys: readonly string[] | undefined,
): readonly AdminColumn<T>[] {
  if (!visibleKeys) return columns
  const shown = columns.filter((column) => visibleKeys.includes(column.key))
  return shown.length > 0 ? shown : columns
}

function ExpandToggle({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      aria-expanded={open}
      aria-label={open ? "Скрыть подробности" : "Показать подробности"}
      onClick={(event) => {
        event.stopPropagation()
        onToggle()
      }}
      onKeyDown={(event) => event.stopPropagation()}
      className="inline-flex size-6 shrink-0 items-center justify-center rounded text-slate-400 hover:bg-slate-100 hover:text-slate-700"
    >
      <ChevronRight
        className={cn("size-4 transition-transform", open && "rotate-90")}
        strokeWidth={2}
      />
    </button>
  )
}

function handleRowKey(event: KeyboardEvent<HTMLElement>, open: () => void) {
  if (event.target !== event.currentTarget) return
  if (event.key !== "Enter" && event.key !== " ") return
  event.preventDefault()
  open()
}

function ariaSort(
  sort: string | undefined,
  column: { sortable?: boolean; sortKey?: AdminSortColumn; key: string },
): "ascending" | "descending" | "none" | undefined {
  if (!column.sortable) return undefined
  const key = (column.sortKey ?? column.key) as AdminSortColumn
  const direction = adminSortDirection(sort ?? "", key)
  if (direction === "asc") return "ascending"
  if (direction === "desc") return "descending"
  return "none"
}

function ColumnTitle<T>({
  column,
  sort,
  onSort,
}: {
  column: AdminColumn<T>
  sort?: string
  onSort?: (column: AdminSortColumn) => void
}) {
  if (!column.sortable || !onSort) return <>{column.title}</>
  const key = (column.sortKey ?? column.key) as AdminSortColumn
  const direction = adminSortDirection(sort ?? "", key)
  return (
    <button
      type="button"
      onClick={() => onSort(key)}
      className={cn(
        "inline-flex items-center gap-0.5",
        column.align === "right" && "flex-row-reverse",
        direction ? "text-slate-700" : "text-slate-500 hover:text-slate-800",
      )}
    >
      {column.title}
      {direction === "asc" ? (
        <ArrowUp className="size-3" strokeWidth={2} />
      ) : direction === "desc" ? (
        <ArrowDown className="size-3" strokeWidth={2} />
      ) : null}
    </button>
  )
}
