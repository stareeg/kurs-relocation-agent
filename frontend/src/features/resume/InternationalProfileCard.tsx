import { useQuery } from "@tanstack/react-query"
import type { DisclosurePolicy } from "@/api/settings"
import { fetchEmployerDescriptor, fetchInternationalReadiness } from "@/api/resume"
import { MARKET_SCOPE_DEFAULT } from "@/lib/resume-taxonomy"
import { ChipToggleGroup, type ChipOption } from "@/components/ui/chip-toggle-group"
import { useSearchTrack } from "@/features/career/search-track"
import { useDisclosurePolicy, useUpdateDisclosurePolicy } from "@/features/settings/use-settings"
import { PanelFieldLabel } from "./panel-field"
import { useResumeData } from "./use-resume"

// Зеркало DisclosurePolicy() в core/domains/profile/anonymize.py — фолбэк, пока /api/settings
// не подгрузился (мутация всегда шлёт полный объект, PATCH — не merge на бэке).
const DEFAULT_DISCLOSURE_POLICY: DisclosurePolicy = {
  hide_current_employer: true,
  hide_all_employers: false,
  hide_public_links: true,
  coarse_dates: false,
  coarse_city: false,
}

const READINESS_LABEL: Record<string, string> = {
  ready: "Готов",
  partial: "Частично",
  weak: "Слабо",
  unknown: "Не оценивали",
}

const CONTRACT_LABEL: Record<string, string> = {
  employment: "ТК",
  gph: "ГПХ",
  ip: "ИП",
  self_employed: "самозанятость",
}

const INTERNATIONAL_KEY = ["resume", "international"] as const
const EMPLOYER_DESCRIPTOR_KEY = ["resume", "employer-descriptor"] as const

// Э4.2 dual_employment_and_contracting_2026.md: единственный тумблер политики раскрытия в
// этом заходе (hide_all_employers/coarse_dates/coarse_city — без UI, дефолт False в модели).
const DISCLOSURE_OPTIONS: ChipOption[] = [
  { value: "on", label: "Скрывать" },
  { value: "off", label: "Показывать" },
]

function overlapLine(overlap: Record<string, number> | undefined): string {
  if (!overlap) return ""
  const bits = Object.entries(overlap)
    .filter(([, hours]) => hours > 0)
    .map(([region, hours]) => `${region} ${hours} ч`)
  return bits.length ? `Пересечение: ${bits.join(", ")}` : ""
}

/** Карточка вывода международного профиля — без полей ввода, под осями поиска. */
export function InternationalProfileCard() {
  const { data: resume } = useResumeData()
  const { data: track } = useSearchTrack()
  const { data: intl } = useQuery({
    queryKey: INTERNATIONAL_KEY,
    queryFn: fetchInternationalReadiness,
    staleTime: 60_000,
  })
  const disclosurePolicy = useDisclosurePolicy()
  const updateDisclosurePolicy = useUpdateDisclosurePolicy()
  const hideCurrentEmployer = disclosurePolicy?.hide_current_employer ?? true
  // Дескриптор — только пока тумблер включён (см. хук ниже): дёргать LLM ради превью, который
  // никто не увидит, незачем.
  const { data: descriptor } = useQuery({
    queryKey: EMPLOYER_DESCRIPTOR_KEY,
    queryFn: fetchEmployerDescriptor,
    enabled: hideCurrentEmployer,
    staleTime: 5 * 60_000,
  })

  const scope = resume?.search_criteria?.market_scope || MARKET_SCOPE_DEFAULT
  const show = scope !== MARKET_SCOPE_DEFAULT || Boolean(track?.second_job_enabled)
  if (!show || !intl) return null

  // evidence уже несёт источник («… — из раздела Языки»); индекс к синтетическим
  // строкам не совпадает (валюта/часы вклиниваются). Пустой снимок — запасные факты.
  const rows = [...(intl.evidence ?? [])]
  if (!rows.length) {
    const formLabels = (intl.contract_forms ?? [])
      .map((f) => CONTRACT_LABEL[f] ?? f)
      .filter(Boolean)
    const english = intl.english_level
      ? `Английский ${intl.english_level}`
      : intl.suggested_english_level
        ? `Английский ${intl.suggested_english_level} (предположение)`
        : "Английский не указан"
    const tz = intl.home_timezone
      ? `Часовой пояс ${intl.home_timezone}`
      : "Часовой пояс не определили"
    const forms = formLabels.length ? `Формы: ${formLabels.join(", ")}` : ""
    rows.push(english, tz, overlapLine(intl.overlap), forms)
  }

  return (
    <div className="space-y-2 rounded-xl border bg-white p-5">
      <div className="flex items-center justify-between gap-2">
        <PanelFieldLabel helpId="resume.international-profile">
          Международный профиль
        </PanelFieldLabel>
        <span className="text-xs font-medium text-slate-600">
          {READINESS_LABEL[intl.readiness] ?? intl.readiness}
        </span>
      </div>
      <ul className="space-y-1.5">
        {rows.filter(Boolean).map((row) => (
          <li key={row} className="text-xs text-slate-700">
            {row}
          </li>
        ))}
      </ul>

      {/* Э4.2: единственный тумблер политики раскрытия — скрывать текущее место в письмах на
          английском (cover_letter_intl). Дескриптор строится один раз при первом включении и
          кэшируется — здесь только показ превью, не генерация по каждому рендеру. */}
      <div className="flex items-center justify-between gap-2 border-t pt-2">
        <span className="text-xs text-slate-500">Скрывать текущее место в письмах</span>
        <ChipToggleGroup
          size="sm"
          options={DISCLOSURE_OPTIONS}
          value={[hideCurrentEmployer ? "on" : "off"]}
          onChange={([v]) => {
            const on = v === "on"
            if (on === hideCurrentEmployer) return
            updateDisclosurePolicy.mutate({
              ...(disclosurePolicy ?? DEFAULT_DISCLOSURE_POLICY),
              hide_current_employer: on,
            })
          }}
          multiple={false}
          allowEmpty={false}
        />
      </div>
      {hideCurrentEmployer && descriptor && (
        <p className="text-xs text-slate-500">Будет заменено на: «{descriptor.descriptor_ru}»</p>
      )}
    </div>
  )
}
