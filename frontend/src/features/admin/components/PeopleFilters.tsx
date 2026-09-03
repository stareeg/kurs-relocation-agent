import { SegmentedControl } from "@/components/ui/segmented-control"
import {
  PEOPLE_STATUS_CHIPS,
  applyPeopleScope,
  peopleScopeFromFilters,
  type AdminFilters,
  type AdminPeopleScope,
} from "@/features/admin/admin-filters"

/**
 * Пилюли «Все / Проблемные / Отключённые» справа от поиска.
 */
export function PeopleFilters({
  filters,
  onChange,
}: {
  filters: AdminFilters
  onChange: (next: AdminFilters) => void
}) {
  return (
    <SegmentedControl
      size="sm"
      ariaLabel="Кого показать"
      options={[...PEOPLE_STATUS_CHIPS]}
      value={peopleScopeFromFilters(filters)}
      onChange={(next) => onChange(applyPeopleScope(filters, next as AdminPeopleScope))}
    />
  )
}
