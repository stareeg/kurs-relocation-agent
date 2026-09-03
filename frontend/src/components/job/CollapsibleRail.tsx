import type { ReactNode } from "react"
import { PanelLeftClose, PanelLeftOpen } from "lucide-react"
import { cn } from "@/lib/utils"
import { usePersistedBoolean } from "@/lib/use-persisted-boolean"

// Ручное сворачивание рельса вакансий (Скрининги/Технички/Офферы) — правка 2026-08-19 п.2.
// Свёрнутое состояние держит только узкую полосу с кнопкой разворота; сама VacancyCardRail не
// монтируется свёрнутой (список всё равно не виден, а данные и так живут в react-query кэше
// `useJobs`, ремонтирование дёшево). Состояние — per-раздел (свой storageKey), переживает
// перезагрузку страницы.
export function CollapsibleRail({
  storageKey,
  children,
}: {
  storageKey: string
  children: ReactNode
}) {
  const [collapsed, setCollapsed] = usePersistedBoolean(storageKey)

  return (
    <aside
      className={cn(
        "flex min-h-0 shrink-0 flex-col border-r transition-[width] duration-150",
        collapsed ? "w-9" : "w-72",
      )}
    >
      <div
        className={cn(
          "flex shrink-0 items-center p-1.5",
          collapsed ? "justify-center" : "justify-end",
        )}
      >
        <button
          type="button"
          onClick={() => setCollapsed((v) => !v)}
          title={collapsed ? "Развернуть рельс вакансий" : "Свернуть рельс вакансий"}
          aria-label={collapsed ? "Развернуть рельс вакансий" : "Свернуть рельс вакансий"}
          className="flex size-6 shrink-0 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
        >
          {collapsed ? (
            <PanelLeftOpen className="size-4" strokeWidth={2} />
          ) : (
            <PanelLeftClose className="size-4" strokeWidth={2} />
          )}
        </button>
      </div>
      {!collapsed && (
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 pb-3 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {children}
        </div>
      )}
    </aside>
  )
}
