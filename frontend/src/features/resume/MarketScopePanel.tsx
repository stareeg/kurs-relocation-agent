import { ChipToggleGroup } from "@/components/ui/chip-toggle-group"
import { MARKET_SCOPE_DEFAULT, MARKET_SCOPE_OPTIONS } from "@/lib/resume-taxonomy"
import { PanelFieldRow } from "./panel-field"
import { usePatchResumeField, useResumeData } from "./use-resume"

/** «Рынок поиска» — под «Режимом поиска» в левой панели.
 *
 * Ось резюме (`search_criteria.market_scope`), не настройка приложения: её читает деривация
 * профиля (`CandidateProfile.market_scope`), она печатается в резюме-markdown для скоринга и
 * входит в блок ЦЕЛЬ на «Рынке». Пустое значение в сохранённом резюме = «Только РФ».
 */
export function MarketScopePanel() {
  const { data } = useResumeData()
  const patchField = usePatchResumeField()

  if (!data) return null

  const current = data.search_criteria?.market_scope || MARKET_SCOPE_DEFAULT

  return (
    <PanelFieldRow label="Рынок" helpId="resume.market-scope">
      <ChipToggleGroup
        options={MARKET_SCOPE_OPTIONS}
        value={[current]}
        onChange={([v]) => {
          if (v) patchField.mutate({ search_criteria: { market_scope: v } })
        }}
        multiple={false}
        allowEmpty={false}
      />
    </PanelFieldRow>
  )
}
