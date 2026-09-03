import { ChipToggleGroup, type ChipOption } from "@/components/ui/chip-toggle-group"
import { useSearchTrack, useSetSearchTrack } from "@/features/career/search-track"
import { PanelFieldRow } from "./panel-field"

const TRACK_OPTIONS: ChipOption[] = [
  { value: "primary", label: "Основная" },
  { value: "second_job", label: "Дополнительная" },
]

/** Тип работы — третья ось портрета, после режима и рынка. Дефолт: Основная. */
export function SearchTrackPanel() {
  const { data } = useSearchTrack()
  const setTrack = useSetSearchTrack()
  const current = data?.second_job_enabled ? "second_job" : "primary"

  return (
    <PanelFieldRow label="Тип работы" helpId="resume.search-track">
      <ChipToggleGroup
        options={TRACK_OPTIONS}
        value={[current]}
        onChange={(next) => {
          const on = next[0] === "second_job"
          if (on === (current === "second_job")) return
          setTrack.mutate(on)
        }}
        multiple={false}
        allowEmpty={false}
      />
    </PanelFieldRow>
  )
}
