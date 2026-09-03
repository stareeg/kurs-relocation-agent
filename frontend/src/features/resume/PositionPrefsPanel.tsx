import { ChipToggleGroup } from "@/components/ui/chip-toggle-group"
import {
  CANDIDATE_COMPANY_TYPES,
  RESUME_GRADES,
  ROLE_KIND_OPTIONS,
  SCHEDULE_OPTIONS,
  roleKindLabel,
} from "@/lib/resume-taxonomy"
import { PanelFieldLabel, PanelFieldRow } from "./panel-field"
import { SuggestHint } from "./SearchProfilePanel"
import { usePatchResumeField, useResumeData, useSearchProfileSuggestState } from "./use-resume"

/** Формат — сразу под «Тип работы» в портрете. */
export function SchedulePrefsField() {
  const { data } = useResumeData()
  const patchField = usePatchResumeField()
  if (!data) return null
  const schedule = data.position?.schedule ?? []

  return (
    <PanelFieldRow label="Формат" helpId="resume.schedule" needsFill={schedule.length === 0}>
      <ChipToggleGroup
        options={SCHEDULE_OPTIONS}
        value={schedule}
        onChange={(next) => patchField.mutate({ position: { schedule: next } })}
      />
    </PanelFieldRow>
  )
}

/** Роль (исполнитель / управленец / обе) — канон в резюме прежний, на чипе короткие подписи. */
export function RolePrefsField() {
  const { data } = useResumeData()
  const patchField = usePatchResumeField()
  const { suggestState, setSuggestState } = useSearchProfileSuggestState()
  if (!data) return null

  const roleKind = data.search_criteria?.role_kind ?? ""
  const roleKindHint = !roleKind && suggestState.roleKind ? suggestState.roleKind : ""

  return (
    <div className="space-y-1.5">
      <PanelFieldRow label="Роль" helpId="resume.role-kind">
        <ChipToggleGroup
          options={ROLE_KIND_OPTIONS}
          value={roleKind ? [roleKind] : []}
          onChange={(next) => {
            patchField.mutate({ search_criteria: { role_kind: next[0] ?? "" } })
          }}
          multiple={false}
          allowEmpty
        />
      </PanelFieldRow>
      {roleKindHint ? (
        <SuggestHint
          value={roleKindLabel(roleKindHint)}
          onApply={() => {
            patchField.mutate({ search_criteria: { role_kind: roleKindHint } })
            setSuggestState({ ...suggestState, roleKind: "" })
          }}
          onDismiss={() => setSuggestState({ ...suggestState, roleKind: "" })}
        />
      ) : null}
    </div>
  )
}

export function GradePrefsField() {
  const { data } = useResumeData()
  const patchField = usePatchResumeField()
  if (!data) return null
  const grades = data.position?.grade ?? []

  return (
    <PanelFieldRow label="Грейд" helpId="resume.grade" needsFill={grades.length === 0}>
      <ChipToggleGroup
        options={RESUME_GRADES}
        value={grades}
        onChange={(next) => patchField.mutate({ position: { grade: next } })}
      />
    </PanelFieldRow>
  )
}

export function CompanyTypesField() {
  const { data } = useResumeData()
  const patchField = usePatchResumeField()
  if (!data) return null
  const companyTypes = data.position?.company_types ?? []

  return (
    <div className="space-y-1.5">
      <PanelFieldLabel helpId="resume.company-types">Типы компаний</PanelFieldLabel>
      <ChipToggleGroup
        options={CANDIDATE_COMPANY_TYPES}
        value={companyTypes}
        onChange={(next) => patchField.mutate({ position: { company_types: next } })}
      />
    </div>
  )
}
