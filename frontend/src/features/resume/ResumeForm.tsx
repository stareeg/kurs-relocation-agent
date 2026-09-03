import { memo, useCallback, useEffect, useRef, useState } from "react"
import { Loader2, Plus, Save, Sparkles, Trash2 } from "lucide-react"
import { toast } from "sonner"
import type { ResumeData } from "@/api/resume"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { DatePicker, type DateGranularity } from "@/components/ui/date-picker"
import { MultiSelectPopover } from "@/components/ui/multi-select-popover"
import { PhoneInput } from "@/components/ui/phone-input"
import { CityInput } from "@/components/ui/city-input"
import { formatCityUtcOffset, lookupCity, mergeDerivedCountries } from "@/lib/cities"
import {
  EXPERIENCE_INDUSTRY_OPTIONS,
  experienceIndustrySelectValue,
  normalizeDealbreakers,
  RESUME_CATEGORIES,
  RESUME_CATEGORIES_MAX,
  normalizeCategories,
} from "@/lib/resume-taxonomy"
import { rebaseDraft } from "@/lib/rebase-draft"
import { cn } from "@/lib/utils"
import { useBufferedValue } from "./use-buffered-field"
import {
  setOnAtsApplied,
  usePatchResumeField,
  useSaveResumeData,
  useStrengthenResumeAbout,
  useStrengthenResumeExperience,
} from "./use-resume"
import { useAtsFit } from "./ats-fit-context"
import { AtsFitBlockStatus, AtsFitProposalBanner, AtsFitSummaryBar } from "./AtsFitInline"
import { isResumeSectionComplete } from "./resume-filled"
import { leftPanelHints, leftPanelReadyForScore } from "./resume-score-criteria"
import { replaceBulletInDescription, type ScoreFixItem } from "./resume-score-fixes"
import { useRegisterScoreFixApply } from "./resume-score-apply-context"
import { useRegisterResumePdfSlot } from "./resume-pdf-slot"
import { useCitySuggestions } from "./use-cities"
import { NeedsFillMark, NeedsFillWrap, Section } from "./section"
import { ResumeScoreBlock } from "./ResumeScoreCard"
import { KeySkillsSection } from "./skills/KeySkillsSection"

function isBlank(v: string | null | undefined): boolean {
  return v == null || String(v).trim() === ""
}

// --- мелкие переиспользуемые поля -------------------------------------------------

function Field({
  label,
  className,
  needsFill,
  children,
}: {
  label: string
  className?: string
  needsFill?: boolean
  children: React.ReactNode
}) {
  return (
    <label className={cn("block space-y-1.5", className)}>
      <span className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-600">
        {label}
        {needsFill ? <NeedsFillMark /> : null}
      </span>
      <NeedsFillWrap active={needsFill}>{children}</NeedsFillWrap>
    </label>
  )
}

function TextField({
  label,
  value,
  onChange,
  placeholder,
  className,
  needsFill,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  className?: string
  needsFill?: boolean
}) {
  const buf = useBufferedValue(value, onChange)
  return (
    <Field label={label} className={className} needsFill={needsFill}>
      <Input
        value={buf.value}
        onChange={(e) => buf.onChange(e.target.value)}
        onFocus={buf.onFocus}
        onBlur={buf.onBlur}
        placeholder={placeholder}
      />
    </Field>
  )
}

function GrowTextarea({
  value,
  onChange,
  placeholder,
  className,
  maxHeight,
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
  className?: string
  maxHeight?: number
}) {
  const buf = useBufferedValue(value, onChange)
  return (
    <Textarea
      value={buf.value}
      onChange={(e) => buf.onChange(e.target.value)}
      onFocus={buf.onFocus}
      onBlur={buf.onBlur}
      placeholder={placeholder}
      className={className}
      maxHeight={maxHeight}
    />
  )
}

function BufferedPhoneInput({
  value,
  onChange,
  placeholder,
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
}) {
  const buf = useBufferedValue(value, onChange)
  return (
    <span onFocus={buf.onFocus} onBlur={buf.onBlur}>
      <PhoneInput value={buf.value} onChange={buf.onChange} placeholder={placeholder} />
    </span>
  )
}

function BufferedCityInput({
  value,
  onChange,
  onSelect,
  suggestions,
  placeholder,
}: {
  value: string
  onChange: (city: string) => void
  onSelect: (item: { city: string; country?: string }) => void
  suggestions: ReturnType<typeof useCitySuggestions>
  placeholder?: string
}) {
  // Только blur/выбор из списка: живой коммит через 300 мс перерисовывал всю форму,
  // закрывал саджест и ронял фокус — ввести город было нельзя.
  const buf = useBufferedValue(value, onChange, false)
  const utc = formatCityUtcOffset(buf.value, suggestions)
  return (
    <div className="flex min-w-0 items-center gap-2">
      <div className="min-w-0 flex-1">
        <span onFocus={buf.onFocus} onBlur={buf.onBlur}>
          <CityInput
            value={buf.value}
            onChange={buf.onChange}
            onSelect={(item) => {
              buf.sync(item.city)
              onSelect(item)
            }}
            suggestions={suggestions}
            placeholder={placeholder}
          />
        </span>
      </div>
      {utc ? (
        <span className="flex h-9 shrink-0 items-center text-xs tabular-nums text-slate-500">
          {utc}
        </span>
      ) : null}
    </div>
  )
}

// Закрытый список вместо свободного ввода (RD-2) — значение остаётся строкой в модели,
// select лишь ограничивает источник ввода тем же множеством, что и на hh.ru.
function SelectField({
  label,
  value,
  onChange,
  options,
  placeholder = "Выбрать",
  className,
  needsFill,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  options: string[] | { value: string; label: string }[]
  placeholder?: string
  className?: string
  needsFill?: boolean
}) {
  const items = options.map((o) => (typeof o === "string" ? { value: o, label: o } : o))
  return (
    <Field label={label} className={className} needsFill={needsFill}>
      <Select value={value || undefined} onValueChange={onChange}>
        <SelectTrigger className="w-full">
          <SelectValue placeholder={placeholder} />
        </SelectTrigger>
        <SelectContent>
          {items.map((item) => (
            <SelectItem key={item.value} value={item.value}>
              {item.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </Field>
  )
}

// Календарь вместо свободного ввода даты (RD-2/5/6) — значение в модели остаётся ISO-
// подстрокой (YYYY-MM-DD/YYYY-MM/YYYY), granularity задаёт точность виджета.
function DateField({
  label,
  value,
  onChange,
  granularity,
  className,
  needsFill,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  granularity?: DateGranularity
  className?: string
  needsFill?: boolean
}) {
  return (
    <Field label={label} className={className} needsFill={needsFill}>
      <DatePicker value={value} onChange={onChange} granularity={granularity} />
    </Field>
  )
}

const GENDER_OPTIONS = ["Мужчина", "Женщина", "Не указано"]
// RD-6 → «Релокация» — одно поле вместо пары «Переезд» + «Командировки» (модель Personal.relocation).
const RELOCATION_OPTIONS = ["Не готов", "Только командировки", "Готов полностью"]

// RD-6 — общий список и для «Уровня образования» (целиком), и для «Степени» конкретной записи
// (то же множество значений, не дублируем константу).
const EDUCATION_LEVELS = [
  "Среднее",
  "Среднее специальное",
  "Неоконченное высшее",
  "Высшее",
  "Бакалавр",
  "Магистр",
  "Кандидат наук",
  "Доктор наук",
]

// RD-7 — куцый curated список вместо полного ISO-639: используемые в резюме языки + «другой».
const LANGUAGES = [
  "Русский",
  "Английский",
  "Немецкий",
  "Испанский",
  "Французский",
  "Китайский",
  "Другой",
]

// RD-7 — CEFR + «Родной» отдельным значением вне шкалы (level остаётся строкой в модели).
const LANGUAGE_LEVELS = [
  "Родной",
  "A1 — начальный",
  "A2 — элементарный",
  "B1 — средний",
  "B2 — средне-продвинутый",
  "C1 — продвинутый",
  "C2 — в совершенстве",
]

// Тот же список валют, что OfferDraftCard.tsx CURRENCY_OPTS (RD-4) — вилка в SalaryPrefsPanel.

// Карточка повторяемого блока (опыт/образование/язык) с кнопкой удаления.
// `top` — кнопка над полями, чтобы не сжимать ширину select'ов (опыт работы).
function RepeatItem({
  onRemove,
  removePlacement = "overlay",
  children,
}: {
  onRemove: () => void
  removePlacement?: "overlay" | "top"
  children: React.ReactNode
}) {
  return (
    <div className="relative rounded-lg border bg-slate-50/40 p-4">
      {removePlacement === "top" ? (
        <div className="-mt-0.5 mb-3 flex justify-end">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onRemove}
            className="h-8 gap-1.5 border-rose-200 bg-white px-3 text-rose-700 shadow-xs hover:bg-rose-50 hover:text-rose-800"
          >
            <Trash2 className="size-3.5" strokeWidth={2} />
            Удалить
          </Button>
        </div>
      ) : (
        <button
          type="button"
          onClick={onRemove}
          className="absolute right-3 top-3 flex items-center gap-1 text-xs text-slate-400 transition-colors hover:text-rose-600"
        >
          <Trash2 className="size-3.5" strokeWidth={2} />
          Удалить
        </button>
      )}
      {children}
    </div>
  )
}

function AddButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex items-center gap-1.5 rounded-lg border border-dashed px-3 py-2 text-sm text-slate-500 transition-colors hover:border-slate-300 hover:text-slate-700"
    >
      <Plus className="size-4" strokeWidth={2} />
      {label}
    </button>
  )
}

// --- форма ------------------------------------------------------------------------

// openapi-typescript метит поля с дефолтами опциональными (`full_name?`). В форме работаем со
// строгими типами (снимаем опциональность через Required<NonNullable<…>>) — доступ без `?? ""`.
type Personal = Required<NonNullable<ResumeData["personal"]>>
type Contacts = Required<NonNullable<ResumeData["contacts"]>>
type Position = Required<NonNullable<ResumeData["position"]>>
type SearchCriteria = Required<NonNullable<ResumeData["search_criteria"]>>
type Exp = Required<NonNullable<NonNullable<ResumeData["experience"]>[number]>>
type Edu = Required<NonNullable<NonNullable<ResumeData["education"]>[number]>>
type Lang = Required<NonNullable<NonNullable<ResumeData["languages"]>[number]>>

// FR2-67: стабильный React-key для повторяемых блоков. Только UI — в API/JSON не уходит.
type ExpRow = Exp & { _uid: string }
type EduRow = Edu & { _uid: string }
type LangRow = Lang & { _uid: string }

type FormData = {
  personal: Personal
  contacts: Contacts
  position: Position
  search_criteria: SearchCriteria
  experience: ExpRow[]
  experience_total: string
  education_level: string
  education: EduRow[]
  courses: NonNullable<ResumeData["courses"]>
  key_skills: string[]
  languages: LangRow[]
  about: string
}

const EMPTY_EXP: Exp = {
  company: "",
  company_url: "",
  industry: "",
  position: "",
  start: "",
  end: "",
  current: false,
  area: "",
  description: "",
}
const EMPTY_EDU: Edu = {
  degree: "",
  year: "",
  institution: "",
  faculty: "",
  specialization: "",
}
const EMPTY_LANG: Lang = { name: "", level: "" }

/** Подсказки в пустых полях (шаблон resume_data.example.json теперь пустой). */
const PH = {
  fullName: "Как в паспорте",
  title: "Например, Lead LLM Engineer",
  city: "Москва",
  phone: "+7 900 000-00-00",
  email: "name@example.com",
  telegram: "@username",
  company: "Название компании",
  position: "Должность",
  description: "Что делал, стек, результат — коротко по строкам",
  institution: "ВУЗ или колледж",
  faculty: "Факультет",
  specialization: "Специализация",
} as const

function newRowUid(): string {
  return crypto.randomUUID()
}

function withUid<T extends object>(row: T): T & { _uid: string } {
  return { ...row, _uid: newRowUid() }
}

function stripUid<T extends { _uid: string }>(rows: T[]): Omit<T, "_uid">[] {
  return rows.map(({ _uid, ...rest }) => {
    void _uid
    return rest
  })
}

/** Снять клиентские `_uid` перед сравнением dirty / отправкой на бэк. */
function withoutRowUids(d: FormData): Omit<FormData, "experience" | "education" | "languages"> & {
  experience: Exp[]
  education: Edu[]
  languages: Lang[]
} {
  return {
    ...d,
    experience: stripUid(d.experience),
    education: stripUid(d.education),
    languages: stripUid(d.languages),
  }
}

/** Сравнение форм без клиентских `_uid` (их normalize() генерит заново на каждый вызов). */
function sameForm(a: FormData, b: FormData): boolean {
  return JSON.stringify(withoutRowUids(a)) === JSON.stringify(withoutRowUids(b))
}

/** Ключи-объекты FormData — сливаются по под-ключам (см. rebaseDraft). */
const NESTED_FORM_KEYS = ["personal", "contacts", "position", "search_criteria"] as const

/** Снять клиентские `_uid` перед сравнением: normalize() генерит их заново на каждый вызов. */
function withoutRowUidsValue(value: unknown): unknown {
  if (!Array.isArray(value)) return value
  return value.map((row) =>
    row && typeof row === "object" && "_uid" in row
      ? Object.fromEntries(Object.entries(row).filter(([k]) => k !== "_uid"))
      : row,
  )
}

function rebaseFormDraft(draft: FormData, prev: FormData, next: FormData): FormData {
  return rebaseDraft(draft, prev, next, {
    nestedKeys: NESTED_FORM_KEYS,
    normalize: withoutRowUidsValue,
  })
}

function expRowEqual(a: ExpRow | undefined, b: ExpRow): boolean {
  if (!a) return false
  return (
    a.company === b.company &&
    a.company_url === b.company_url &&
    a.industry === b.industry &&
    a.position === b.position &&
    a.start === b.start &&
    a.end === b.end &&
    a.current === b.current &&
    a.area === b.area &&
    a.description === b.description
  )
}

const ExperienceCard = memo(function ExperienceCard({
  exp,
  index,
  dirty,
  savePending,
  strengthenPending,
  localSuggestion,
  onPatch,
  onRemove,
  onSave,
  onStrengthen,
  onAcceptLocal,
  onSkipLocal,
  onAcceptAts,
  atsCriteriaReady,
  atsCriteriaHint,
}: {
  exp: ExpRow
  index: number
  dirty: boolean
  savePending: boolean
  strengthenPending: boolean
  localSuggestion: { original: string; proposed: string } | undefined
  onPatch: (i: number, p: Partial<Exp>) => void
  onRemove: (i: number) => void
  onSave: () => void
  onStrengthen: (i: number) => void
  onAcceptLocal: (i: number, desc: string) => void
  onSkipLocal: (i: number) => void
  onAcceptAts: (key: string, proposed: string) => void
  atsCriteriaReady: boolean
  atsCriteriaHint: string | undefined
}) {
  const atsFit = useAtsFit()
  const prop = atsFit.proposalFor(`exp:${index}`)
  const patchRow = (atsFit.result?.experience ?? []).find((e) => e.index === index)

  return (
    <RepeatItem onRemove={() => onRemove(index)} removePlacement="top">
      <div className="grid gap-3 sm:grid-cols-3">
        <TextField
          label="Компания"
          value={exp.company}
          onChange={(v) => onPatch(index, { company: v })}
          placeholder={PH.company}
          needsFill={isBlank(exp.company)}
        />
        <TextField
          label="Должность"
          value={exp.position}
          onChange={(v) => onPatch(index, { position: v })}
          placeholder={PH.position}
          needsFill={isBlank(exp.position)}
        />
        <TextField
          label="Город"
          value={exp.area}
          onChange={(v) => onPatch(index, { area: v })}
        />
        <DateField
          label="Начало"
          value={exp.start}
          onChange={(v) => onPatch(index, { start: v })}
          granularity="month"
          needsFill={isBlank(exp.start)}
        />
        <Field label="Окончание" needsFill={!exp.current && isBlank(exp.end)}>
          <div className="flex items-center gap-2">
            <DatePicker
              value={exp.end}
              onChange={(v) => onPatch(index, { end: v })}
              granularity="month"
              disabled={exp.current}
            />
            <label className="flex shrink-0 items-center gap-1.5 text-xs text-slate-600">
              <input
                type="checkbox"
                checked={exp.current}
                onChange={(e) =>
                  onPatch(index, {
                    current: e.target.checked,
                    end: e.target.checked ? "" : exp.end,
                  })
                }
              />
              по н.в.
            </label>
          </div>
        </Field>
        <SelectField
          label="Отрасль"
          value={experienceIndustrySelectValue(exp.industry) ?? ""}
          onChange={(v) => onPatch(index, { industry: v })}
          options={EXPERIENCE_INDUSTRY_OPTIONS}
          placeholder="Выбрать"
        />
      </div>
      <div className="mt-3 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <span className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-600">
            Описание (обязанности, достижения)
            {isBlank(exp.description) ? <NeedsFillMark /> : null}
          </span>
          <div className="flex items-center gap-2">
            {dirty && (
              <Button
                type="button"
                size="sm"
                disabled={savePending}
                onClick={onSave}
                className="h-7 shrink-0 gap-1.5 px-2.5 text-xs bg-slate-900 text-white hover:bg-slate-800"
                aria-label="Сохранить опыт"
              >
                <Save className="size-3" strokeWidth={2} />
                {savePending ? "Сохранение…" : "Сохранить"}
              </Button>
            )}
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={strengthenPending || !atsCriteriaReady}
              onClick={() => onStrengthen(index)}
              className="h-7 shrink-0 gap-1.5 px-2 text-xs border-sky-200 bg-sky-50 text-sky-800 hover:bg-sky-100 hover:text-sky-900 disabled:opacity-50"
              aria-label="Подогнать описание под ATS"
              title={
                atsCriteriaReady
                  ? "LLM перепишет описание под требования рынка и ключевые навыки"
                  : atsCriteriaHint
              }
            >
              {strengthenPending ? (
                <Loader2 className="size-3 animate-spin" strokeWidth={2} />
              ) : (
                <Sparkles className="size-3" strokeWidth={2} />
              )}
              Подогнать под ATS
            </Button>
          </div>
        </div>
        {!atsCriteriaReady && atsCriteriaHint ? (
          <p className="text-xs leading-snug text-slate-500">{atsCriteriaHint}</p>
        ) : null}
        <NeedsFillWrap active={isBlank(exp.description)}>
          <GrowTextarea
            value={exp.description}
            onChange={(v) => onPatch(index, { description: v })}
            placeholder={PH.description}
            className="leading-relaxed"
            maxHeight={480}
          />
        </NeedsFillWrap>
        {prop ? (
          <AtsFitProposalBanner
            proposal={prop}
            onAccept={() => onAcceptAts(prop.key, prop.proposed)}
            onSkip={() => atsFit.dismiss(prop.key)}
          />
        ) : localSuggestion ? (
          <AtsFitProposalBanner
            proposal={{
              key: `exp:${index}`,
              label: "Описание",
              original: localSuggestion.original,
              proposed: localSuggestion.proposed,
            }}
            onAccept={() => onAcceptLocal(index, localSuggestion.proposed)}
            onSkip={() => onSkipLocal(index)}
          />
        ) : (
          <AtsFitBlockStatus patch={patchRow} />
        )}
      </div>
    </RepeatItem>
  )
})

// Заполнить дефолты — бэкенд всегда отдаёт полные объекты (Pydantic), но типы этого не гарантируют.
function normalize(data: ResumeData): FormData {
  const p = data.personal
  const c = data.contacts
  const pos = data.position
  const sc = data.search_criteria
  return {
    personal: {
      full_name: p?.full_name ?? "",
      gender: p?.gender ?? "",
      birth_date: p?.birth_date ?? "",
      city: p?.city ?? "",
      work_countries: p?.work_countries ?? [],
      relocation: p?.relocation ?? "",
    },
    contacts: {
      phone: c?.phone ?? "",
      phone_preferred: c?.phone_preferred ?? true,
      email: c?.email ?? "",
      telegram: c?.telegram ?? "",
      site: c?.site ?? "",
      other: c?.other ?? [],
    },
    position: {
      title: pos?.title ?? "",
      salary_min: pos?.salary_min ?? null,
      salary_comfortable: pos?.salary_comfortable ?? null,
      salary_currency: pos?.salary_currency ?? "RUB",
      salary_basis: pos?.salary_basis ?? "",
      employment: pos?.employment ?? "",
      schedule: pos?.schedule ?? [],
      grade: pos?.grade ?? [],
      company_types: pos?.company_types ?? [],
      categories: normalizeCategories(pos?.categories),
    },
    search_criteria: {
      niches: sc?.niches ?? [],
      role_kind: sc?.role_kind ?? "",
      market_segment: sc?.market_segment ?? "",
      // Пусто = «Только РФ» (нормализация на бэке, `market_scope_label`); панель показывает
      // дефолт сама, здесь пустую строку не подменяем — иначе форма считалась бы «грязной».
      market_scope: sc?.market_scope ?? "",
      target_companies: sc?.target_companies ?? [],
      avoid_companies: sc?.avoid_companies ?? [],
      // Пустой список - норма; устаревшие строки мигрируем / отбрасываем (не валим форму).
      dealbreakers: normalizeDealbreakers(sc?.dealbreakers),
      notes: sc?.notes ?? "",
    },
    experience: (data.experience ?? []).map((e) => withUid({ ...EMPTY_EXP, ...e })),
    experience_total: data.experience_total ?? "",
    education_level: data.education_level ?? "",
    education: (data.education ?? []).map((e) => withUid({ ...EMPTY_EDU, ...e })),
    courses: data.courses ?? [],
    key_skills: data.key_skills ?? [],
    languages: (data.languages ?? []).map((l) => withUid({ ...EMPTY_LANG, ...l })),
    about: data.about ?? "",
  }
}

/** Контролы «Сохранить»/«Подогнать под ATS» — живут в левой панели (ResumeScoreCard), а не
 * в сейв-баре формы; форма отдаёт им состояние через этот мост. */
export type ResumeSaveUi = {
  dirty: boolean
  saving: boolean
  onSave: () => void
}

export const ResumeForm = memo(function ResumeForm({
  data,
  saveUi,
}: {
  data: ResumeData
  saveUi?: (ui: ResumeSaveUi | null) => void
}) {
  const [d, setD] = useState<FormData>(() => normalize(data))
  // База черновика — серверные данные, из которых он вырос. Всё, что пришло с бэкенда позже
  // (автосейв из панели слева, ATS, PDF), пересаживаем на черновик через rebaseDraft, иначе
  // форма считала себя грязной от чужой правки, а «Сохранить» PUT-ил устаревшие поля поверх.
  const [base, setBase] = useState<FormData>(d)
  const [seenData, setSeenData] = useState<ResumeData>(data)
  if (data !== seenData) {
    const next = normalize(data)
    setSeenData(data)
    setBase((prev) => (sameForm(prev, next) ? prev : next))
    setD((cur) => rebaseFormDraft(cur, base, next))
  }
  const save = useSaveResumeData()
  const persistResume = save.mutate
  const { mutate: patchMutate } = usePatchResumeField()
  const citySuggestions = useCitySuggestions(d.experience.map((e) => e.area))
  // normalize() каждый раз выдаёт новые `_uid` — сравниваем без них (FR2-67).
  const dirty = !sameForm(d, base)
  const hasManualEdits = dirty
  const draftRef = useRef(d)
  useEffect(() => {
    draftRef.current = d
  })

  // «Подогнать под ATS» для одного описания места работы. Ответ (правка) живёт в локальном
  // стейте формы, пока владелец не примет/не смахнёт её. onSuccess — только когда стрим
  // завершён без ошибки.
  const strengthenExp = useStrengthenResumeExperience()
  const strengthenAbout = useStrengthenResumeAbout()
  const [expSuggestions, setExpSuggestions] = useState<
    Record<number, { original: string; proposed: string }>
  >({})
  const [aboutSuggestion, setAboutSuggestion] = useState<{
    original: string
    proposed: string
  } | null>(null)
  const perExpSuggestions = expSuggestions
  const dismissExpSuggestion = useCallback((idx: number) => {
    setExpSuggestions((cur) => {
      const next = { ...cur }
      delete next[idx]
      return next
    })
  }, [])
  const strengthenExpMutate = strengthenExp.mutate
  const strengthenExpRun = useCallback(
    (idx: number) => {
      strengthenExpMutate(idx, {
        onSuccess: (patch) => {
          if (patch.status === "ok" && patch.proposed.trim()) {
            setExpSuggestions((cur) => ({
              ...cur,
              [idx]: { original: patch.original, proposed: patch.proposed },
            }))
          } else if (patch.status === "skipped" && patch.skip_reason) {
            toast.message(patch.skip_reason)
          } else if (patch.status === "error" && patch.error) {
            toast.error(patch.error)
          }
        },
      })
    },
    [strengthenExpMutate],
  )

  const strengthenAboutRun = () => {
    strengthenAbout.mutate(undefined, {
      onSuccess: (patch) => {
        if (patch.status === "ok" && patch.proposed.trim()) {
          setAboutSuggestion({ original: patch.original, proposed: patch.proposed })
        } else if (patch.status === "skipped" && patch.skip_reason) {
          toast.message(patch.skip_reason)
        } else if (patch.status === "error" && patch.error) {
          toast.error(patch.error)
        }
      },
    })
  }

  // Принять готовую правку описания: обновить черновик и сразу сохранить (как автосейв
  // на PATCH/навыках), чтобы принятое не потерялось и балл пересчитался.
  const acceptExpDescription = useCallback(
    (idx: number, desc: string) => {
      const cur = draftRef.current
      const nextExperience = cur.experience.map((e, k) =>
        k === idx ? { ...e, description: desc } : e,
      )
      persistResume(withoutRowUids({ ...cur, experience: nextExperience }))
      setD((c) => ({
        ...c,
        experience: c.experience.map((e, k) => (k === idx ? { ...e, description: desc } : e)),
      }))
      setExpSuggestions((s) => {
        const next = { ...s }
        delete next[idx]
        return next
      })
    },
    [persistResume],
  )

  const acceptAboutDescription = (desc: string) => {
    save.mutate(withoutRowUids({ ...d, about: desc }))
    setD((cur) => ({ ...cur, about: desc }))
    setAboutSuggestion(null)
  }

  // точечные апдейтеры (иммутабельные, без сторонних либ)
  const patch = useCallback((p: Partial<FormData>) => setD((cur) => ({ ...cur, ...p })), [])
  const patchPersonal = useCallback(
    (p: Partial<Personal>) => setD((cur) => ({ ...cur, personal: { ...cur.personal, ...p } })),
    [],
  )
  const patchContacts = useCallback(
    (p: Partial<Contacts>) => setD((cur) => ({ ...cur, contacts: { ...cur.contacts, ...p } })),
    [],
  )
  const patchPosition = useCallback(
    (p: Partial<Position>) => setD((cur) => ({ ...cur, position: { ...cur.position, ...p } })),
    [],
  )

  // ФИО / город / дата / профессия — свободный текст, в PATCH-схеме их нет (PUT по «Сохранить»).
  // Буфер в TextField не даёт каждому символу перерисовывать всю форму.
  const autoPersonalField = useCallback(
    (p: Partial<Personal>) => {
      patchPersonal(p)
    },
    [patchPersonal],
  )

  // Select / multi-select: сразу на бэкенд (как schedule/grade), без кнопки «Сохранить».
  const autoPersonal = useCallback(
    (p: Partial<Personal>) => {
      patchPersonal(p)
      patchMutate({ personal: p })
    },
    [patchPersonal, patchMutate],
  )
  const applyCity = useCallback(
    (city: string, picked?: { country?: string }) => {
      const geo = picked ?? lookupCity(city, citySuggestions)
      if (!geo?.country) {
        autoPersonalField({ city })
        return
      }
      const prevCountries = draftRef.current.personal.work_countries
      const work_countries = mergeDerivedCountries(prevCountries, geo.country)
      patchPersonal({ city, work_countries })
      // PATCH только если страна реально сменилась — иначе каждый blur известного
      // города инвалидировал бы балл и дёргал всю страницу резюме.
      const same =
        work_countries.length === prevCountries.length &&
        work_countries.every((c, i) => c === prevCountries[i])
      if (!same) patchMutate({ personal: { work_countries } })
    },
    [autoPersonalField, citySuggestions, patchPersonal, patchMutate],
  )
  // Грейд / формат / типы компаний / зарплата — левая панель скоринга; форме остались
  // профессия и специальности.
  const autoPositionTitle = useCallback(
    (title: string) => {
      patchPosition({ title })
    },
    [patchPosition],
  )
  const autoPositionCategories = useCallback(
    (categories: string[]) => {
      patchPosition({ categories })
      patchMutate({ position: { categories } })
    },
    [patchPosition, patchMutate],
  )
  const onSkillsChange = useCallback(
    (next: string[]) => {
      setD((cur) => ({ ...cur, key_skills: next }))
      patchMutate({ key_skills: next })
    },
    [patchMutate],
  )

  const applyScoreFix = useCallback(
    (fix: ScoreFixItem) => {
      const cur = draftRef.current
      switch (fix.apply_action) {
        case "replace_bullet": {
          if (fix.section === "about") {
            const proposed = replaceBulletInDescription(cur.about, fix.current, fix.suggested)
            setAboutSuggestion({ original: cur.about, proposed })
            return
          }
          const idx = fix.experience_index ?? 0
          const exp = cur.experience[idx]
          if (!exp) return
          const proposed = replaceBulletInDescription(exp.description, fix.current, fix.suggested)
          setExpSuggestions((s) => ({
            ...s,
            [idx]: { original: exp.description, proposed },
          }))
          return
        }
        case "patch_about":
          setAboutSuggestion({ original: cur.about, proposed: fix.suggested.trim() })
          return
        case "strengthen_block":
          if (fix.section === "about") strengthenAboutRun()
          else if (fix.experience_index != null) strengthenExpRun(fix.experience_index)
          return
        case "add_skill": {
          const skill = fix.suggested.replace(/^[-•]\s*/, "").trim()
          if (
            skill &&
            !cur.key_skills.some((s) => s.trim().toLowerCase() === skill.toLowerCase())
          ) {
            onSkillsChange([...cur.key_skills, skill])
          }
          return
        }
        default:
          return
      }
    },
    [onSkillsChange, strengthenExpRun],
  )
  useRegisterScoreFixApply(applyScoreFix)
  const autoEduDegree = (i: number, v: string) => {
    const next = d.education.map((e, idx) => (idx === i ? { ...e, degree: v } : e))
    setD((cur) => ({ ...cur, education: next }))
    patchMutate({
      education: stripUid(next),
    })
  }
  const autoLang = (i: number, p: Partial<Lang>) => {
    const next = d.languages.map((l, idx) => (idx === i ? { ...l, ...p } : l))
    setD((cur) => ({ ...cur, languages: next }))
    patchMutate({
      languages: stripUid(next),
    })
  }

  const patchExp = useCallback((i: number, p: Partial<Exp>) => {
    setD((cur) => ({
      ...cur,
      experience: cur.experience.map((e, idx) => (idx === i ? { ...e, ...p } : e)),
    }))
  }, [])
  const patchEdu = useCallback((i: number, p: Partial<Edu>) => {
    setD((cur) => ({
      ...cur,
      education: cur.education.map((e, idx) => (idx === i ? { ...e, ...p } : e)),
    }))
  }, [])
  const removeExp = useCallback(
    (i: number) => {
      setD((cur) => {
        const next = cur.experience.filter((_, idx) => idx !== i)
        persistResume(withoutRowUids({ ...cur, experience: next }))
        return { ...cur, experience: next }
      })
    },
    [persistResume],
  )

  const saveExpBlock = useCallback(() => {
    persistResume(withoutRowUids(draftRef.current))
  }, [persistResume])

  const saveAboutBlock = () => {
    save.mutate(withoutRowUids(d))
  }

  const toPayload = (): ResumeData => {
    const body = withoutRowUids(d)
    return {
      ...body,
      search_criteria: {
        ...body.search_criteria,
        dealbreakers: body.search_criteria.dealbreakers.map((s) => s.trim()).filter(Boolean),
      },
    }
  }

  const atsCriteriaReady = leftPanelReadyForScore(toPayload())
  const atsCriteriaHint = leftPanelHints(toPayload())[0]

  // Ответ сервера приезжает в кэш ["resume","data"] и подхватывается ребейзом черновика —
  // отдельный setD(normalize(saved)) только перегенерил бы `_uid` и ронял фокус в полях.
  // Через ref: onSave остаётся стабильным и не дёргает saveUi-эффект на каждый рендер.
  const saveRef = useRef<() => void>(() => {})
  useEffect(() => {
    saveRef.current = () => save.mutate(toPayload())
  })
  const onSave = useCallback(() => saveRef.current(), [])

  // Контролы «Сохранить»/«Подогнать под ATS» рендерятся в левой панели — отдаём им состояние.
  // Обновляем родителя только при реальной смене значений: новый объект каждый рендер
  // вызывал бы setState → ре-рендер → новый объект → бесконечный цикл (React #185).
  const saveUiRef = useRef<{ dirty: boolean; saving: boolean } | null>(null)
  useEffect(() => {
    const prev = saveUiRef.current
    if (prev && prev.dirty === dirty && prev.saving === save.isPending) return
    saveUiRef.current = { dirty, saving: save.isPending }
    saveUi?.({ dirty, saving: save.isPending, onSave })
  }, [dirty, save.isPending, onSave, saveUi])
  useEffect(() => () => saveUi?.(null), [saveUi])

  // Принятые ATS-правки патчат черновик; через этот хук контекст просит форму сохраниться,
  // чтобы правка не потерялась при unmount и балл пересчитался по новому тексту.
  useEffect(() => {
    setOnAtsApplied(() => () => save.mutate(toPayload()))
    return () => setOnAtsApplied(null)
    // toPayload/onSave всегда свежие по замыканию — намеренно без deps, перерегистрация дешёвая.
  })

  // FR2-34/35/36: инлайн-правки ats-fit — единственный вход в LLM-подгонку текста.
  const atsFit = useAtsFit()

  const markAccepted = atsFit.markAccepted
  const acceptAtsProposal = useCallback(
    (key: string, proposed: string) => {
      if (key === "about") {
        patch({ about: proposed })
      } else if (key.startsWith("exp:")) {
        const idx = Number(key.slice(4))
        if (Number.isFinite(idx)) patchExp(idx, { description: proposed })
      }
      markAccepted(key)
    },
    [patch, patchExp, markAccepted],
  )

  const acceptAllAts = () => {
    for (const p of [...atsFit.pending]) {
      acceptAtsProposal(p.key, p.proposed)
    }
  }

  const onPdfParsed = useCallback(
    (parsed: ResumeData) => {
      const cur = draftRef.current
      const next = normalize(parsed)
      // Базис зарплаты PDF не задаёт — не затираем уже выбранный.
      next.position.salary_basis = cur.position.salary_basis
      // Приоритеты из PDF только если в форме ещё пусто.
      if (cur.search_criteria.niches.length > 0) {
        next.search_criteria.niches = cur.search_criteria.niches
      }
      setD(next)
      const axes =
        Boolean(parsed.search_criteria?.role_kind?.trim()) ||
        Boolean(parsed.search_criteria?.market_segment?.trim())
      const hadPriorities = (parsed.search_criteria?.niches ?? []).length > 0
      if (axes && !hadPriorities) {
        toast.success(
          "Поля заполнены из PDF. Приоритеты можно подобрать кнопкой в «Профиль поиска» — данные сохранены.",
        )
      } else {
        toast.success("Поля заполнены из PDF и сохранены")
      }
      persistResume(withoutRowUids(next))
    },
    [persistResume],
  )
  useRegisterResumePdfSlot({
    onParsed: onPdfParsed,
    disabled: save.isPending,
    hasManualEdits,
  })

  return (
    <div className="p-6">
      <div className="mx-auto max-w-4xl space-y-4">
        <AtsFitSummaryBar
          pending={atsFit.pending}
          acceptedCount={atsFit.acceptedCount}
          totalOk={atsFit.totalOk}
          pendingCount={atsFit.pendingCount}
          isPending={atsFit.isPending}
          isError={atsFit.isError}
          hasResult={atsFit.result != null}
          hasActionable={atsFit.hasActionable}
          hasMarket={atsFit.result?.has_market ?? true}
          progress={atsFit.progress}
          onAcceptAll={acceptAllAts}
          onSkipAll={atsFit.skipAll}
          onClear={atsFit.clear}
        />
        <ResumeScoreBlock />
        {/* Профиль */}
        <Section
          id="personal"
          title="Профиль"
          helpId="resume.section-personal"
          dense
          needsFill={!isResumeSectionComplete("personal", d)}
        >
          {/* 1 строка — Профессия / Специальности поровну; 2 строка — ФИО / Дата рождения /
                Пол; 3 строка — Город (+ UTC справа) / Релокация. Страна больше не поле:
                выводится из города. Профессия и специальности отвечают на «кто кандидат». */}
          <div className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <TextField
              label="Профессия"
              value={d.position.title}
              onChange={autoPositionTitle}
              placeholder={PH.title}
              needsFill={isBlank(d.position.title)}
            />
            <Field
              label={`Специальности · до ${RESUME_CATEGORIES_MAX}`}
              needsFill={d.position.categories.length === 0}
            >
              <MultiSelectPopover
                options={RESUME_CATEGORIES}
                value={d.position.categories}
                onChange={autoPositionCategories}
                max={RESUME_CATEGORIES_MAX}
                columns={2}
                placeholder="Не выбрано"
              />
            </Field>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <TextField
              label="ФИО"
              value={d.personal.full_name}
              onChange={(v) => autoPersonalField({ full_name: v })}
              placeholder={PH.fullName}
              needsFill={isBlank(d.personal.full_name)}
            />
            <DateField
              label="Дата рождения"
              value={d.personal.birth_date}
              onChange={(v) => autoPersonalField({ birth_date: v })}
              granularity="day"
            />
            <SelectField
              label="Пол"
              value={d.personal.gender}
              onChange={(v) => autoPersonal({ gender: v })}
              options={GENDER_OPTIONS}
            />
            <div className="sm:col-span-2">
              <Field label="Город проживания" needsFill={isBlank(d.personal.city)}>
                <BufferedCityInput
                  value={d.personal.city}
                  onChange={(v) => applyCity(v)}
                  onSelect={(item) => applyCity(item.city, item)}
                  suggestions={citySuggestions}
                  placeholder={PH.city}
                />
              </Field>
            </div>
            <SelectField
              label="Релокация"
              value={d.personal.relocation}
              onChange={(v) => autoPersonal({ relocation: v })}
              options={RELOCATION_OPTIONS}
            />
          </div>
          </div>
        </Section>

        {/* Контакты */}
        <Section
          id="contacts"
          title="Контакты"
          helpId="resume.section-contacts"
          dense
          needsFill={!isResumeSectionComplete("contacts", d)}
        >
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Телефон" needsFill={isBlank(d.contacts.phone)}>
              <BufferedPhoneInput
                value={d.contacts.phone}
                onChange={(v) => patchContacts({ phone: v })}
                placeholder={PH.phone}
              />
            </Field>
            <TextField
              label="Email"
              value={d.contacts.email}
              onChange={(v) => patchContacts({ email: v })}
              placeholder={PH.email}
              needsFill={isBlank(d.contacts.email)}
            />
            <TextField
              label="Telegram"
              value={d.contacts.telegram}
              onChange={(v) => patchContacts({ telegram: v })}
              placeholder={PH.telegram}
            />
          </div>
        </Section>

        {/* Опыт работы. Даты периодов — свободные строки, система читает из них немного;
              значение несёт галочка «по н.в.»: она отвечает на вопрос «работает сейчас или уже
              свободен» (`is_currently_employed` в core/domains/profile/model.py) и уходит в
              резюме-markdown и в блок ЦЕЛЬ на «Рынке». Поэтому вывод показан прямо в шапке —
              рядом с галочкой, которая им управляет. */}
        <Section
          id="experience"
          title="Опыт работы"
          helpId="resume.section-experience"
          hint={
            d.experience.length > 0
              ? d.experience.some((e) => e.current)
                ? "сейчас работает"
                : "сейчас без работы"
              : undefined
          }
          needsFill={!isResumeSectionComplete("experience", d)}
          action={
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => patch({ experience: [...d.experience, withUid({ ...EMPTY_EXP })] })}
              className="h-7 shrink-0 gap-1.5 px-2 text-xs"
              aria-label="Добавить место работы"
            >
              <Plus className="size-3" strokeWidth={2} />
              Добавить
            </Button>
          }
        >
          <div className="space-y-3">
            {d.experience.map((exp, i) => (
              <ExperienceCard
                key={exp._uid}
                exp={exp}
                index={i}
                dirty={!expRowEqual(base.experience[i], exp)}
                savePending={save.isPending}
                strengthenPending={strengthenExp.isPending}
                localSuggestion={perExpSuggestions[i]}
                onPatch={patchExp}
                onRemove={removeExp}
                onSave={saveExpBlock}
                onStrengthen={strengthenExpRun}
                onAcceptLocal={acceptExpDescription}
                onSkipLocal={dismissExpSuggestion}
                onAcceptAts={acceptAtsProposal}
                atsCriteriaReady={atsCriteriaReady}
                atsCriteriaHint={atsCriteriaHint}
              />
            ))}
            <AddButton
              label="Добавить место работы"
              onClick={() => patch({ experience: [...d.experience, withUid({ ...EMPTY_EXP })] })}
            />
          </div>
        </Section>

        {/* Образование */}
        <Section
          id="education"
          title="Образование"
          helpId="resume.section-education"
          needsFill={!isResumeSectionComplete("education", d)}
        >
          <div className="space-y-3">
            {d.education.map((ed, i) => (
              <RepeatItem
                key={ed._uid}
                onRemove={() => patch({ education: d.education.filter((_, idx) => idx !== i) })}
              >
                <div className="grid gap-3 pr-20 sm:grid-cols-2">
                  <SelectField
                    label="Степень"
                    value={ed.degree}
                    onChange={(v) => autoEduDegree(i, v)}
                    options={EDUCATION_LEVELS}
                  />
                  <DateField
                    label="Год окончания"
                    value={ed.year}
                    onChange={(v) => patchEdu(i, { year: v })}
                    granularity="year"
                  />
                  <TextField
                    label="Учебное заведение"
                    value={ed.institution}
                    onChange={(v) => patchEdu(i, { institution: v })}
                    placeholder={PH.institution}
                    className="sm:col-span-2"
                    needsFill={isBlank(ed.institution)}
                  />
                  <TextField
                    label="Факультет"
                    value={ed.faculty}
                    onChange={(v) => patchEdu(i, { faculty: v })}
                    placeholder={PH.faculty}
                    className="sm:col-span-2"
                  />
                  <TextField
                    label="Специализация"
                    value={ed.specialization}
                    onChange={(v) => patchEdu(i, { specialization: v })}
                    placeholder={PH.specialization}
                    className="sm:col-span-2"
                  />
                </div>
              </RepeatItem>
            ))}
            <AddButton
              label="Добавить образование"
              onClick={() => patch({ education: [...d.education, withUid({ ...EMPTY_EDU })] })}
            />
          </div>
        </Section>

        {/* Навыки + спрос — один спойлер: свернуть навыки = скрыть спрос. */}
        <KeySkillsSection tags={d.key_skills} onChange={onSkillsChange} />

        {/* Языки */}
        <Section
          id="languages"
          title="Языки"
          helpId="resume.section-languages"
          dense
          needsFill={!isResumeSectionComplete("languages", d)}
        >
          <div className="space-y-1.5">
            {d.languages.map((lang, i) => (
              <div key={lang._uid} className="flex items-end gap-2">
                <SelectField
                  label="Язык"
                  value={lang.name}
                  onChange={(v) => autoLang(i, { name: v })}
                  options={LANGUAGES}
                  className="flex-1"
                  needsFill={isBlank(lang.name)}
                />
                <SelectField
                  label="Уровень"
                  value={lang.level}
                  onChange={(v) => autoLang(i, { level: v })}
                  options={LANGUAGE_LEVELS}
                  className="flex-1"
                  needsFill={isBlank(lang.level)}
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  className="text-slate-400 hover:text-rose-600"
                  onClick={() => patch({ languages: d.languages.filter((_, idx) => idx !== i) })}
                  title="Удалить"
                >
                  <Trash2 className="size-3.5" strokeWidth={2} />
                </Button>
              </div>
            ))}
            <AddButton
              label="Добавить язык"
              onClick={() => patch({ languages: [...d.languages, withUid({ ...EMPTY_LANG })] })}
            />
          </div>
        </Section>

        {/* Обо мне */}
        <Section
          id="about"
          title="Обо мне"
          helpId="resume.section-about"
          needsFill={!isResumeSectionComplete("about", d)}
          action={
            <div className="flex items-center gap-1.5">
              {d.about !== base.about && (
                <Button
                  type="button"
                  size="sm"
                  disabled={save.isPending}
                  onClick={saveAboutBlock}
                  className="h-7 shrink-0 gap-1.5 px-2.5 text-xs bg-slate-900 text-white hover:bg-slate-800"
                  aria-label="Сохранить блок Обо мне"
                >
                  <Save className="size-3" strokeWidth={2} />
                  {save.isPending ? "Сохранение…" : "Сохранить"}
                </Button>
              )}
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={strengthenAbout.isPending || !atsCriteriaReady}
                onClick={strengthenAboutRun}
                className="h-7 shrink-0 gap-1.5 px-2 text-xs border-sky-200 bg-sky-50 text-sky-800 hover:bg-sky-100 hover:text-sky-900 disabled:opacity-50"
                aria-label="Подогнать «Обо мне» под ATS"
                title={
                  atsCriteriaReady
                    ? "LLM перепишет блок «Обо мне» под целевую роль"
                    : atsCriteriaHint
                }
              >
                {strengthenAbout.isPending ? (
                  <Loader2 className="size-3 animate-spin" strokeWidth={2} />
                ) : (
                  <Sparkles className="size-3" strokeWidth={2} />
                )}
                Подогнать под ATS
              </Button>
            </div>
          }
        >
          {!atsCriteriaReady && atsCriteriaHint ? (
            <p className="mb-2 text-xs leading-snug text-slate-500">{atsCriteriaHint}</p>
          ) : null}
          <NeedsFillWrap active={isBlank(d.about)}>
            <GrowTextarea
              value={d.about}
              onChange={(v) => patch({ about: v })}
              className="leading-relaxed"
              maxHeight={480}
            />
          </NeedsFillWrap>
          {(() => {
            const prop = atsFit.proposalFor("about")
            if (prop) {
              return (
                <AtsFitProposalBanner
                  proposal={prop}
                  onAccept={() => acceptAtsProposal(prop.key, prop.proposed)}
                  onSkip={() => atsFit.dismiss(prop.key)}
                />
              )
            }
            if (aboutSuggestion) {
              return (
                <AtsFitProposalBanner
                  proposal={{
                    key: "about",
                    label: "Обо мне",
                    original: aboutSuggestion.original,
                    proposed: aboutSuggestion.proposed,
                  }}
                  onAccept={() => acceptAboutDescription(aboutSuggestion.proposed)}
                  onSkip={() => setAboutSuggestion(null)}
                />
              )
            }
            return <AtsFitBlockStatus patch={atsFit.result?.about} />
          })()}
        </Section>
      </div>
    </div>
  )
})
