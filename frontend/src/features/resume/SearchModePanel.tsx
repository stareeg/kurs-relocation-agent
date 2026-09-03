import type { SearchMode } from "@/api/career"
import { ChipToggleGroup, type ChipOption } from "@/components/ui/chip-toggle-group"
import { useSearchMode, useSetSearchMode } from "@/features/career/search-mode"
import { PanelFieldRow } from "./panel-field"

const SEARCH_MODE_OPTIONS: ChipOption[] = [
  { value: "active", label: "Активно ищу", activeClass: "border-sky-200 bg-sky-100 text-sky-800" },
  {
    value: "passive",
    label: "Рассматриваю",
    activeClass: "border-violet-200 bg-violet-100 text-violet-800",
  },
]

export function SearchModePanel() {
  const { data } = useSearchMode()
  const setMode = useSetSearchMode()
  const current = data?.mode ?? "active"

  return (
    <PanelFieldRow label="Режим поиска" helpId="resume.search-mode">
      <ChipToggleGroup
        options={SEARCH_MODE_OPTIONS}
        value={[current]}
        onChange={([v]) => {
          if (v) setMode.mutate(v as SearchMode)
        }}
        multiple={false}
        allowEmpty={false}
      />
    </PanelFieldRow>
  )
}
