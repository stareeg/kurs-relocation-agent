import { CompaniesBoardSection } from "@/features/market/companies/CompaniesBoard"
import { SectionCard } from "@/components/ui/section-card"
import { SkeletonCard, SkeletonRow } from "@/components/ui/skeleton"
import { StatusChip } from "@/components/ui/status-chip"

/**
 * Заглушка будущей секции: заголовок + скелетон + бейдж «Скоро»,
 * чтобы в разделе уже было видно, что фича появится.
 */
function ComingSoonSection({ title }: { title: string }) {
  return (
    <SectionCard
      title={title}
      status="content"
      meta={<StatusChip tone="info">Скоро</StatusChip>}
    >
      <div className="space-y-3" aria-hidden>
        <SkeletonRow lines={2} />
        <SkeletonCard className="h-20" />
      </div>
    </SectionCard>
  )
}

/**
 * Страница «Компании» (отдельный раздел, 2026-08-08): целевые / избегаемые / кандидаты.
 * Вынесена из «Рынка» — задел под будущие фичи работы с компаниями (карточки, аналитика,
 * история контактов). Первый блок — доска банов и пиков (K-01); ниже — плейсхолдеры
 * «Контакты HR» и «Вакансии из Telegram».
 */
export function CompaniesPage() {
  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-x-hidden">
      <div
        id="screen-start-companies"
        className="min-w-0 flex-1 overflow-y-auto overflow-x-hidden overscroll-contain"
      >
        <div className="flex flex-col gap-6 px-6 pb-6 pt-6">
          <CompaniesBoardSection className="col-span-2" />
          <ComingSoonSection title="Контакты HR" />
          <ComingSoonSection title="Вакансии из Telegram" />
        </div>
      </div>
    </div>
  )
}
