import { useCallback, useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import {
  CircleX,
  Copy,
  Eye,
  EyeOff,
  Loader2,
  Mail,
  RotateCcw,
  Sparkles,
  Trash2,
  UserX,
} from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { toast } from "sonner"
import type { Job } from "@/api/jobs"
import { fetchInternationalReadiness } from "@/api/resume"
import { overlapCaption, EXCLUSIVITY_LABEL } from "./work-terms-view"
import { ageDays } from "@/lib/format"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { ChipToggleGroup, type ChipOption } from "@/components/ui/chip-toggle-group"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { HelpTip } from "@/components/ui/help-tip"
import { getHelpText } from "@/lib/help-texts"
import { SkipReasonDialog } from "./SkipReasonDialog"
import { useSkipReasonsPoll } from "./use-skip-reasons-poll"
import { TelegramPushButton } from "@/features/settings/TelegramPushButton"
import { StatusChip } from "@/components/ui/status-chip"
import { Textarea } from "@/components/ui/textarea"
import { SectionTitle } from "@/components/ui/section-title"
import { TabDecision } from "./ScoreDetails"
import { AnketaPanel } from "./AnketaPanel"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  ARCHIVED_BADGE,
  chatButtonLabel,
  COMPANY_TYPE_LABEL,
  competitionLabel,
  competitionInsightLabel,
  competitionInsightOf,
  REMOTE_FEASIBILITY,
  effectiveWorkFormat,
  formatSalaryCardText,
  fmtPublishedDate,
  type FunnelStage,
  levelLabel,
  remoteFeasibilityOf,
  resolveJobSalary,
  resolveStage,
  responsesLabel,
  salaryProvenanceLabel,
  scoreTone,
  sectionJumpFor,
  needsVacancyText,
  isSalaryStillPending,
  VACANCY_TEXT_NEEDED_HINT,
  workFormatChip,
} from "./funnel"
import { StageChainFull, StageChainPills } from "@/components/job/StageChain"
import { useUpdateJobApplyFields } from "./use-job-apply-fields"
import { useDeleteJob } from "./use-delete-job"
import { usePendingSalaryRefresh } from "./use-jobs"
import { useRecomputeSalary } from "./use-recompute-salary"
import { SalaryRefreshButton } from "./SalaryRefreshButton"
import { useUpdateJobStage } from "./use-job-stage"
import { useSkipJob, useUnskipJob } from "./use-skip"
import type { CoverLetterLang } from "@/api/cover-letters"
import { useGenerateCoverLetter } from "./use-cover-letter"
import { useVacancyConversation } from "./use-vacancy-conversation"
import { useVacancyTextFormat } from "./use-vacancy-text-format"
import { VacancyTextFormatted } from "./VacancyTextFormatted"
import {
  jobSourceGroup,
  resolveJobListingUrl,
  resolveSourceGroup,
  listingLinkLabel,
  SOURCE_GROUP_LABEL,
  type SourceGroup,
} from "./source"
import { SourceIcon } from "./SourceIcon"
import { VacancyTextNeededMark } from "./VacancyTextNeededMark"
import { VacancyEvents } from "./VacancyEvents"
import { useCandidateSalaryMin } from "@/features/resume/use-resume"
import { usePersistedNumber } from "@/lib/use-persisted-number"

// Текст вакансии с подсветкой активной цитаты (feature 2.2): клик по сигналу удалёнки находит
// цитату в тексте, подсвечивает её и скроллит к ней. Цитата ищется регистронезависимо первым
// вхождением; модель цитирует дословно, но при перефразе совпадения нет - тогда просто текст.
// Без собственного скролла (V-02): единственный скроллящийся контейнер — тело активной вкладки,
// внутри которого этот блок рендерится: вложенный overflow-y-auto здесь дал бы два скролла разом.
function VacancyText({ text, highlight }: { text: string; highlight: string | null }) {
  const markRef = useRef<HTMLElement | null>(null)
  useEffect(() => {
    if (highlight && markRef.current) {
      markRef.current.scrollIntoView({ block: "center", behavior: "smooth" })
    }
  }, [highlight])

  const needle = highlight?.trim() ?? ""
  const idx = needle ? text.toLowerCase().indexOf(needle.toLowerCase()) : -1
  return (
    <p className="whitespace-pre-wrap rounded-lg bg-slate-50 p-2.5 text-sm text-slate-700">
      {idx >= 0 ? (
        <>
          {text.slice(0, idx)}
          <mark ref={markRef} className="rounded bg-amber-200/70 px-0.5 text-slate-900">
            {text.slice(idx, idx + needle.length)}
          </mark>
          {text.slice(idx + needle.length)}
        </>
      ) : (
        text
      )}
    </p>
  )
}

// V-02: три вкладки дровера. «decision» — открывается по умолчанию (сюда смотрят чаще всего —
// решить, откликаться ли); «vacancy» и «work» — по клику.
type DrawerTab = "decision" | "vacancy" | "work"

// V-11: вкладка живёт в sessionStorage вкладки браузера, а не в URL — ссылкой делятся вакансией
// (`/jobs/:vacancyId`), не выбранной вкладкой (F-10). Ключ хранит vacancyId вместе с вкладкой:
// открытие другой вакансии должно сбрасывать на «Решение», а не наследовать вкладку чужой
// карточки, поэтому читаем сохранённое значение только когда vacancyId совпадает.
const DRAWER_TAB_STORAGE_KEY = "jobs-drawer-tab"

function readStoredDrawerTab(vacancyId: string): DrawerTab {
  try {
    const raw = sessionStorage.getItem(DRAWER_TAB_STORAGE_KEY)
    if (!raw) return "decision"
    const sep = raw.indexOf(":")
    if (sep < 0 || raw.slice(0, sep) !== vacancyId) return "decision"
    const tab = raw.slice(sep + 1)
    return tab === "vacancy" || tab === "work" ? tab : "decision"
  } catch {
    return "decision"
  }
}

function writeStoredDrawerTab(vacancyId: string, tab: DrawerTab) {
  try {
    sessionStorage.setItem(DRAWER_TAB_STORAGE_KEY, `${vacancyId}:${tab}`)
  } catch {
    /* приватный режим/квота — деградируем без персиста */
  }
}

// Шапка — единственный нескроллящийся блок над вкладками (V-01/V-02): два фиксированных ряда
// (заголовок-ссылка + мета/цепочка этапов), высота не зависит от данных вакансии и от вкладки.
function DrawerHeader({
  job,
  listingUrl,
  sourceGroup,
  companyType,
  stage,
  hrViewedDaysAgo,
}: {
  job: Job
  listingUrl: string | null
  sourceGroup: SourceGroup
  companyType: { label: string; rawTitle?: string } | undefined
  stage: FunnelStage
  hrViewedDaysAgo: number | null
}) {
  return (
    <SheetHeader className="border-b p-4">
      {/* Скор — слева от иконки площадки и названия (заголовок-ссылка, UX5-18: клик открывает
          hh/getmatch, как в шапке Чатов). Ссылка — вложенный <a>, а не asChild: Slot просто
          конкатенирует классы без tailwind-merge, и цвет ссылки проигрывал бы text-slate-900 из
          SheetTitle. Статус воронки пилюлей убран — те же данные видны цепочкой этапов ниже. */}
      <SheetTitle className="flex min-w-0 items-center gap-2">
        {needsVacancyText(job) ? (
          <span title={getHelpText("jobs.card-needs-text")}>
            <VacancyTextNeededMark size="lg" />
          </span>
        ) : (
          <span
            className={cn(
              "shrink-0 text-lg font-semibold tabular-nums",
              scoreTone(job.overall_score),
            )}
          >
            {job.overall_score ?? "—"}
          </span>
        )}
        {listingUrl ? (
          <a
            href={listingUrl}
            target="_blank"
            rel="noreferrer"
            className="flex min-w-0 flex-1 items-center gap-2 text-sky-600 hover:text-sky-700 hover:underline"
          >
            <SourceIcon group={sourceGroup} size={20} className="shrink-0" />
            <span className="min-w-0 truncate">{job.title ?? "Без названия"}</span>
          </a>
        ) : (
          <>
            <SourceIcon group={sourceGroup} size={20} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">{job.title ?? "Без названия"}</span>
          </>
        )}
        {job.is_archived && (
          <StatusChip
            tone={ARCHIVED_BADGE.tone}
            className="shrink-0"
            title={getHelpText("jobs.card-archived")}
          >
            {ARCHIVED_BADGE.label}
          </StatusChip>
        )}
      </SheetTitle>
      {/* V-01: мета компании — отдельная строка; цепочка этапов — следующей (не втискивается
          вправо и не дублирует визуальный ряд с городом/типом). */}
      <SheetDescription className="flex min-w-0 flex-wrap items-center gap-x-1.5">
        <span>{job.company ?? "Компания не указана"}</span>
        {job.work_city && (
          <>
            <span className="text-slate-300">•</span>
            <span>{job.work_city}</span>
          </>
        )}
        {companyType && (
          <>
            <span className="text-slate-300">•</span>
            <span title={companyType.rawTitle}>{companyType.label}</span>
          </>
        )}
        {job.total_responses != null && (
          <>
            <span className="text-slate-300">•</span>
            <span title={getHelpText("jobs.card-responses")}>
              {responsesLabel(job.total_responses)}
            </span>
          </>
        )}
        {/* Просмотр резюме HR (JS-9.1) — актуален только пока вакансия на «Отклике»; переехал
            из ряда кнопок футера (V-10) в мета-строку шапки, где живут остальные факты о вакансии. */}
        {stage === "Отклик" && (
          <>
            <span className="text-slate-300">•</span>
            <span
              className={cn(
                "flex items-center gap-1",
                job.hr_viewed_at ? "text-sky-600" : "text-slate-400",
              )}
            >
              {job.hr_viewed_at ? (
                <Eye className="size-3.5 shrink-0" strokeWidth={2} />
              ) : (
                <EyeOff className="size-3.5 shrink-0" strokeWidth={2} />
              )}
              {job.hr_viewed_at
                ? `Просмотрено HR${hrViewedDaysAgo != null ? ` · ${hrViewedDaysAgo} дн назад` : ""}`
                : "Ещё не просмотрено HR"}
            </span>
          </>
        )}
      </SheetDescription>
      <StageChainPills vacancyId={job.vacancy_id} />
    </SheetHeader>
  )
}

// Вкладка «Решение» (по умолчанию): всё нужное, чтобы решить, откликаться ли — бриф, зарплата/
// Метаданные площадки (V-07, часть F-12): источник + ссылка, дата публикации, график, уровень
// конкуренции по откликам, «снята с публикации». Строка над текстом — те же факты, что раньше
// теснили заголовок бейджами.
//
// Этап 6 §6.2: `job.competition` (backend, учитывает возраст публикации + letter_required) —
// приоритетный источник бейджа; старая эвристика `competitionLabel` (только сырой count,
// shared/criteria) — фолбэк для записей, посчитанных до этого поля (job.competition = null).
function VacancyMeta({ job }: { job: Job }) {
  const insight = competitionInsightOf(job)
  const insightLabel = insight ? competitionInsightLabel(insight) : null
  const competition =
    insightLabel ?? (job.total_responses != null ? competitionLabel(job.total_responses) : null)
  const published = fmtPublishedDate(job.published_at)
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-slate-500">
      {published && <span>Опубликовано {published}</span>}
      {job.work_schedule && <span>{job.work_schedule}</span>}
      {competition && (
        <StatusChip
          tone={competition.tone}
          className="normal-case tracking-normal"
          title={insightLabel ? insight?.reasoning : undefined}
        >
          {competition.text}
        </StatusChip>
      )}
      {job.is_archived && (
        <StatusChip tone={ARCHIVED_BADGE.tone}>{ARCHIVED_BADGE.label}</StatusChip>
      )}
      {/* E-04: letter_required — сигнал площадки «нужно сопроводительное», раньше был виден только
          в панели расширения (постоянный бейдж) и в вебе всплывал разово тостом при отклике
          (FR3-65/69). Здесь — тот же факт, что и в панели: виден всегда, а не только один раз. */}
      {job.letter_required && (
        <StatusChip tone="info" className="gap-1 normal-case tracking-normal">
          <Mail className="size-3 shrink-0" strokeWidth={2} />
          Письмо обязательно
        </StatusChip>
      )}
    </div>
  )
}

const _ENGAGE_LABEL: Record<string, string> = {
  employment: "Найм",
  contractor: "Контракт",
  b2b: "B2B",
  freelance: "Фриланс",
  internship: "Стажировка",
  unknown: "не указано",
}
const _SCOPE_LABEL: Record<string, string> = {
  full_time: "полный день",
  part_time: "part-time",
  project: "проект",
  unknown: "",
}
const _GEO_LABEL: Record<string, string> = {
  worldwide: "весь мир",
  region: "регион",
  country_list: "список стран",
  single_city: "один город",
  unknown: "не указано",
}
const _ASYNC_LABEL: Record<string, string> = {
  async_first: "async-first",
  hybrid_sync: "смешанный синхрон",
  sync_heavy: "много синхрона",
  unknown: "не указано",
}
const _TIME_TRACK_LABEL: Record<string, string> = {
  required: "обязателен",
  optional: "по желанию",
  none: "нет",
  unknown: "не указано",
}
const _MEET_LABEL: Record<string, string> = {
  low: "мало",
  medium: "средняя",
  high: "высокая",
  unknown: "не указано",
}

function _termsQuote(
  terms: { evidence?: { field: string; quote: string }[] } | null | undefined,
  field: string,
): string {
  return (terms?.evidence ?? []).find((e) => e.field === field)?.quote ?? ""
}

function WorkTermsBlock({
  job,
  activeQuote,
  onRevealQuote,
}: {
  job: Job
  activeQuote: string | null
  onRevealQuote: (quote: string) => void
}) {
  const { data: intl } = useQuery({
    queryKey: ["resume", "international"],
    queryFn: fetchInternationalReadiness,
    staleTime: 60_000,
    enabled: job.track === "second_job",
  })
  if (job.track !== "second_job" || !job.work_terms) return null
  const t = job.work_terms
  const engage = _ENGAGE_LABEL[t.engagement ?? ""] ?? t.engagement ?? "—"
  const scope = _SCOPE_LABEL[t.scope ?? ""] ?? t.scope ?? ""
  const hours = t.weekly_hours != null ? `${t.weekly_hours} ч/нед` : ""
  const overlap = overlapCaption(t, intl?.overlap)
  const rows: { label: string; value: string; quote: string }[] = [
    {
      label: "Занятость",
      value: [scope, hours].filter(Boolean).join(", ") || "—",
      quote: _termsQuote(t, "scope") || _termsQuote(t, "weekly_hours"),
    },
    {
      label: "Форма найма",
      value: engage,
      quote: _termsQuote(t, "engagement"),
    },
    {
      label: "География",
      value: [_GEO_LABEL[t.geo_scope ?? ""] ?? t.geo_scope, ...(t.hiring_geo ?? [])]
        .filter(Boolean)
        .join(" · "),
      quote: _termsQuote(t, "geo_scope") || _termsQuote(t, "hiring_geo"),
    },
  ]
  if (overlap) {
    rows.push({
      label: "Пересечение",
      value: overlap,
      quote: _termsQuote(t, "overlap_hours_required") || _termsQuote(t, "timezone_requirement"),
    })
  }
  rows.push(
    {
      label: "Синхронность",
      value: _ASYNC_LABEL[t.async_culture ?? ""] ?? t.async_culture ?? "—",
      quote: _termsQuote(t, "async_culture"),
    },
    {
      label: "Учёт времени",
      value: _TIME_TRACK_LABEL[t.time_tracking ?? ""] ?? t.time_tracking ?? "—",
      quote: _termsQuote(t, "time_tracking"),
    },
    {
      label: "Созвоны",
      value: [_MEET_LABEL[t.meeting_load ?? ""] ?? t.meeting_load, t.on_call ? "онколл" : ""]
        .filter(Boolean)
        .join(", "),
      quote: _termsQuote(t, "meeting_load") || _termsQuote(t, "on_call"),
    },
    {
      label: "Эксклюзивность",
      value: EXCLUSIVITY_LABEL[t.exclusivity ?? ""] ?? t.exclusivity ?? "—",
      quote: _termsQuote(t, "exclusivity"),
    },
  )
  const rateBits = [
    t.currency,
    t.rate_min != null || t.rate_max != null
      ? [t.rate_min, t.rate_max].filter((n) => n != null).join("–")
      : "",
    t.rate_period && t.rate_period !== "unknown" ? `/${t.rate_period}` : "",
  ].filter(Boolean)
  if (rateBits.length) {
    rows.push({
      label: "Ставка",
      value: rateBits.join(" "),
      quote: _termsQuote(t, "currency") || _termsQuote(t, "rate_min"),
    })
  }
  return (
    <div className="space-y-2">
      <SectionTitle>Условия</SectionTitle>
      <ul className="space-y-1 rounded-lg bg-slate-50 p-2.5">
        {rows.map((row) => (
          <li key={row.label}>
            {row.quote ? (
              <button
                type="button"
                onClick={() => onRevealQuote(row.quote)}
                title="Показать в тексте вакансии"
                className={cn(
                  "flex w-full items-baseline gap-2 rounded-md px-1 py-0.5 text-left text-sm transition-colors hover:bg-white",
                  activeQuote === row.quote && "bg-white ring-1 ring-amber-300",
                )}
              >
                <span className="w-28 shrink-0 text-slate-500">{row.label}</span>
                <span className="text-slate-800">{row.value || "—"}</span>
              </button>
            ) : (
              <div className="flex items-baseline gap-2 px-1 py-0.5 text-sm">
                <span className="w-28 shrink-0 text-slate-500">{row.label}</span>
                <span className="text-slate-800">{row.value || "—"}</span>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

// Вкладка «Вакансия» (V-07): полный текст JD на всю высоту вкладки, без спойлера и без
// вложенного скролла — единственный скроллящийся контейнер это тело вкладки (V-02). Метаданные
// площадки и сопроводительное письмо — над текстом (письмо ближе к тому, что реально читаешь и
// правишь по ходу разбора JD); подсветка цитаты из карточки «Формат» на «Решении» приходит сюда
// через activeQuote — клик там переключает вкладку и подсвечивает место в тексте.
// Feature 2: текст читается абзацами с **выделениями** (LLM), сырое полотно — только пока
// форматированная версия не подтянулась или недоступна.
// Э4.4 dual_employment_and_contracting_2026.md: переключалка языка письма. allowEmpty — пустой
// выбор означает «автоопределение по резюме», не «ru» по умолчанию визуально.
const LETTER_LANG_OPTIONS: ChipOption[] = [
  { value: "ru", label: "RU" },
  { value: "en", label: "EN" },
]

function TabVacancy({
  job,
  vacancyText,
  activeQuote,
  cover,
  setCover,
  canGenerate,
  genPending,
  onGenerate,
  hasCover,
  coverDirty,
  saveCoverPending,
  onSaveCover,
  letterLang,
  onLetterLangChange,
}: {
  job: Job
  vacancyText: string | null | undefined
  activeQuote: string | null
  cover: string
  setCover: (v: string) => void
  canGenerate: boolean
  genPending: boolean
  onGenerate: () => void
  hasCover: boolean
  coverDirty: boolean
  saveCoverPending: boolean
  onSaveCover: () => void
  letterLang: CoverLetterLang | null
  onLetterLangChange: (lang: CoverLetterLang | null) => void
}) {
  const hasText = Boolean(vacancyText?.trim())
  const listingUrl = resolveJobListingUrl(job)
  // Feature 2: LLM разбивает сплошной JD на абзацы + **выделения**, один раз (кэш на бэкенде).
  // Пока не пришло (или LLM недоступен) — сырой текст, без спиннера: не критично, чтобы ждать.
  const { data: textFormat } = useVacancyTextFormat(job.vacancy_id ?? null, hasText)
  const formattedText = textFormat?.formatted?.trim()

  return (
    <div className="space-y-4">
      <VacancyMeta job={job} />

      {/* Фаза 3.3/3.4: анкета работодателя ИЛИ простое подтверждение письма (режим «Тест»),
          если есть что подтверждать — выше письма, самое заметное место на вкладке (блокирует
          реальную отправку, пока владелец не решит). */}
      <AnketaPanel job={job} />

      {/* Сопроводительное письмо (JS-6.1) — выше текста вакансии: правится по ходу чтения JD. */}
      <div className="space-y-2">
        <div className="flex w-full items-center gap-1.5">
          <p className="flex min-w-0 flex-1 items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-slate-500">
            <Mail className="size-3.5 shrink-0" strokeWidth={2} />
            <span className="truncate">Сопроводительное письмо</span>
            {hasCover && (
              <span
                className="size-1.5 shrink-0 rounded-full bg-emerald-500"
                aria-label="Письмо есть"
              />
            )}
          </p>
          <HelpTip id="jobs.drawer-letter" />
          <Button
            variant="outline"
            size="sm"
            className="h-7 shrink-0 px-2 text-xs"
            disabled={!canGenerate || genPending}
            onClick={onGenerate}
            aria-label={
              !canGenerate
                ? "Нет текста вакансии для письма"
                : hasCover
                  ? "Перегенерировать письмо"
                  : "Сгенерировать письмо"
            }
          >
            {genPending ? (
              <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />
            ) : (
              <Sparkles className="size-3.5" strokeWidth={2} />
            )}
            {genPending ? "Пишу…" : hasCover ? "Перегенерировать" : "Сгенерировать"}
          </Button>
        </div>
        {canGenerate && (
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-slate-400">Язык</span>
            <ChipToggleGroup
              options={LETTER_LANG_OPTIONS}
              value={letterLang ? [letterLang] : []}
              onChange={([v]) => onLetterLangChange((v as CoverLetterLang) ?? null)}
              multiple={false}
            />
            {!letterLang && (
              <span className="text-xs text-slate-400">автоопределение по резюме</span>
            )}
          </div>
        )}
        {!canGenerate ? (
          <p className="text-sm text-slate-400">Нет текста вакансии для письма.</p>
        ) : (
          <div className="space-y-2">
            <Textarea
              value={cover}
              onChange={(e) => setCover(e.target.value)}
              placeholder="Сгенерируй черновик кнопкой рядом и поправь под себя…"
              className="min-h-24"
            />
            <div className="flex items-center gap-2">
              <Button onClick={onSaveCover} disabled={!coverDirty || saveCoverPending} size="sm">
                {saveCoverPending && <Loader2 className="size-4 animate-spin" strokeWidth={2} />}
                Сохранить
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={!cover.trim()}
                onClick={() => {
                  void navigator.clipboard?.writeText(cover)
                  toast.success("Скопировано")
                }}
              >
                <Copy className="size-4" strokeWidth={2} />
                Копировать
              </Button>
            </div>
          </div>
        )}
      </div>

      {hasText ? (
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-2">
            <SectionTitle>Текст вакансии</SectionTitle>
            <Button
              variant="outline"
              size="sm"
              className="h-7 shrink-0 px-2 text-xs"
              onClick={() => {
                void navigator.clipboard?.writeText(vacancyText as string)
                toast.success("Скопировано")
              }}
            >
              <Copy className="size-3.5" strokeWidth={2} />
              Копировать
            </Button>
          </div>
          {formattedText ? (
            <VacancyTextFormatted text={formattedText} highlight={activeQuote} />
          ) : (
            <VacancyText text={vacancyText as string} highlight={activeQuote} />
          )}
        </div>
      ) : (
        <div className="space-y-2 rounded-lg border border-amber-200 bg-amber-50/60 px-3 py-3">
          <div className="flex items-start gap-2">
            <VacancyTextNeededMark className="mt-0.5" />
            <div className="min-w-0 space-y-1">
              <p className="text-sm font-medium text-amber-900">Нет текста вакансии</p>
              <p className="text-sm text-amber-800/90">{VACANCY_TEXT_NEEDED_HINT}</p>
              {listingUrl && (
                <a
                  href={listingUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex text-sm font-medium text-sky-700 hover:underline"
                >
                  Открыть на {listingLinkLabel(jobSourceGroup(job))}
                </a>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// Вкладка «Действия»: цепочка этапов собеса и лента событий по вакансии. Остальное
// (формат, условия, история скора) ушло на «Решение» / в «События».
function TabWork({ job }: { job: Job }) {
  const navigate = useNavigate()
  // Этап 1.2 плана `plans/ui_slop_cleanup_2026_08_25.md`: перевод на «Скрининг» доступен прямо
  // с этой вкладки. Кнопка на карточке доски, которой это делали раньше, в открытом дровере
  // недоступна — она под ним.
  const stageM = useUpdateJobStage()
  return (
    <div className="space-y-4">
      {job.vacancy_id && (
        <div className="space-y-2">
          <SectionTitle>Этапы</SectionTitle>
          <StageChainFull
            vacancyId={job.vacancy_id}
            funnelStatus={resolveStage(job.status)}
            skipped={job.skipped}
            activeStageType=""
            onSelect={() => navigate(`/tech?vacancy=${encodeURIComponent(job.vacancy_id)}`)}
            onPromoteToScreening={
              job.id == null || stageM.isPending
                ? undefined
                : () => stageM.mutate({ id: job.id as number, stage: "Скрининг" })
            }
            className="w-full border-r-0 overflow-y-visible p-0"
          />
        </div>
      )}
      <VacancyEvents vacancyId={job.vacancy_id ?? null} />
    </div>
  )
}

// Действие, ждущее подтверждения через ConfirmDialog (F-11) — деструктивные пункты меню
// не бьют сразу по клику.
type PendingFooterAction = "hr-reject" | "skip" | null

// Липкий футер (V-10): главная кнопка-акцент по стадии (X-07 — переход в раздел, где вакансия
// сейчас готовится) и «Чат» слева, деструктивные «Отказ от HR»/«Пропустить» — явно справа
// (D-06: раньше прятались под «⋯», лишний клик ради того, что и так видно). Confirm-диалог
// всё равно гасит случайный клик. «Просмотрено HR» уехало в мета-строку шапки (DrawerHeader) —
// тут ему было не место среди действий.
function DrawerFooter({
  job,
  sectionJump,
  onSectionJump,
  hasConversation,
  onOpenChat,
  acted,
  onRevert,
  revertPending,
  onHrReject,
  hrRejectPending,
  onSkip,
  skipPending,
}: {
  job: Job
  sectionJump: { label: string; path: string } | undefined
  onSectionJump: () => void
  hasConversation: boolean
  onOpenChat: () => void
  acted: boolean
  onRevert: () => void
  revertPending: boolean
  onHrReject: () => void
  hrRejectPending: boolean
  onSkip: (reason?: string) => void
  skipPending: boolean
}) {
  const [pending, setPending] = useState<PendingFooterAction>(null)
  // Выбранная причина пропуска: LLM-чип (canonical), «Избегать компанию» или
  // undefined (пропустить без причины — легаси-дефолт «Пропущено вручную»).
  const [skipReason, setSkipReason] = useState<string | undefined>(undefined)
  // LLM-причины пропуска под эту вакансию (тянутся поллом, пока фон не сгенерирует).
  const llmReasons = useSkipReasonsPoll(job.vacancy_id ?? null)
  // hasConversation — живой запрос диалога дровера (актуальнее job.has_hr_dialog сразу после
  // первого сообщения), status/skipped берём из job — то же решение, что chatButtonLabel.
  const chatLabel = chatButtonLabel({
    status: job.status,
    skipped: job.skipped,
    has_hr_dialog: hasConversation,
  })
  const isArchivedChat = chatLabel === "Архивный чат"

  function resetPending() {
    setPending(null)
    setSkipReason(undefined)
  }

  return (
    <div className="flex flex-wrap items-center gap-2 border-t p-4">
      {job.vacancy_id && (
        <>
          {sectionJump && (
            <Button
              type="button"
              size="sm"
              aria-label={`Открыть вакансию в разделе «${sectionJump.label.replace(" →", "")}»`}
              onClick={onSectionJump}
            >
              {sectionJump.label}
            </Button>
          )}
          <Button
            type="button"
            size="sm"
            className={cn(
              "border",
              isArchivedChat
                ? "border-slate-200 bg-slate-50 text-slate-500 hover:bg-slate-100 hover:text-slate-700"
                : "border-sky-200 bg-sky-50 text-sky-700 hover:bg-sky-100 hover:text-sky-800",
            )}
            aria-label={chatLabel}
            title={getHelpText("jobs.drawer-dialog")}
            onClick={onOpenChat}
          >
            {/* X-07: рядом главная кнопка перехода в раздел — короткий лейбл "Чат" вместо
                двухсловного, чтобы пара кнопок не распирала футер. Отказ/Пропущено не показывают
                sectionJump, так что «Архивный чат» здесь всегда влезает как единственная кнопка. */}
            {sectionJump ? "Чат" : chatLabel}
          </Button>
          <TelegramPushButton kind="vacancy_card" vacancyId={job.vacancy_id} />
        </>
      )}
      {acted ? (
        <Button
          variant="outline"
          size="sm"
          className="ml-auto"
          onClick={onRevert}
          disabled={revertPending}
        >
          {revertPending ? (
            <Loader2 className="size-4 animate-spin" strokeWidth={2} />
          ) : (
            <RotateCcw className="size-4" strokeWidth={2} />
          )}
          Вернуть
        </Button>
      ) : (
        <div className="ml-auto flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100 hover:text-rose-800"
            disabled={hrRejectPending}
            onClick={() => setPending("hr-reject")}
          >
            <UserX className="size-4" strokeWidth={2} />
            Отказ от HR
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100 hover:text-rose-800"
            disabled={skipPending}
            onClick={() => setPending("skip")}
          >
            <CircleX className="size-4" strokeWidth={2} />
            Пропустить
          </Button>
        </div>
      )}

      <ConfirmDialog
        open={pending === "hr-reject"}
        onOpenChange={(open) => !open && resetPending()}
        title="Отказ от HR?"
        description="Вакансия перейдёт в «Отказ». Действие можно отменить кнопкой «Вернуть»."
        confirmLabel="Отказ от HR"
        onConfirm={() => {
          onHrReject()
          resetPending()
        }}
      />

      {/* Диалог выбора причины пропуска: LLM-чипы (если сгенерированы) или статичный
          канон + отдельная кнопка «Избегать компанию». Под капотом чипы мапятся
          в канонические причины (backend сам канонизирует в POST /skip и web-skip). */}
      <SkipReasonDialog
        open={pending === "skip"}
        onOpenChange={(open) => !open && resetPending()}
        reasons={llmReasons}
        selected={skipReason}
        onSelect={setSkipReason}
        skipPending={skipPending}
        onConfirm={() => {
          onSkip(skipReason)
          resetPending()
        }}
      />
    </div>
  )
}

function DrawerBody({ job, onOpenChange }: { job: Job; onOpenChange: (open: boolean) => void }) {
  const s = job.score // B-03: типизировано контрактом (ScoreResult | null), не ручной проекцией
  const remote = remoteFeasibilityOf(job) // под-скор реальности удалёнки (feature 2.2)
  const remoteChip = remote?.verdict ? REMOTE_FEASIBILITY[remote.verdict] : undefined
  const stage = resolveStage(job.status)
  const salaryMin = useCandidateSalaryMin()
  const salary = resolveJobSalary(job, salaryMin) // зарплата всегда, включая оценку (Этап 3)
  const sourceGroup = jobSourceGroup(job)
  const listingUrl = resolveJobListingUrl(job)
  const estimatePending = isSalaryStillPending(s?.salary?.estimate_pending, salary.text)
  const salaryLocked = s?.salary?.source === "explicit"
  usePendingSalaryRefresh(estimatePending)
  const recomputeSalary = useRecomputeSalary()
  const salaryAction = job.vacancy_id ? (
    <SalaryRefreshButton
      pending={estimatePending}
      locked={salaryLocked}
      onClick={() => recomputeSalary.mutate(job.vacancy_id!)}
    />
  ) : undefined

  // Тип компании и формат работы (UX6-6/8) — строкой под названием компании, не прямоугольниками
  // в метриках: currencyRemote тем же паттерном, что в JobsList/JobCard.
  const companyType =
    s && s.company_type !== "unknown" ? levelLabel(COMPANY_TYPE_LABEL, s.company_type) : undefined
  const formatChip = workFormatChip(effectiveWorkFormat(job), s?.currency_remote)
  // Просмотр резюме HR (JS-9.1): актуален, пока вакансия не продвинулась дальше «Отклика» —
  // после Скрининга вопрос «просмотрено ли» больше не значим.
  const hrViewedDaysAgo = ageDays(job.hr_viewed_at)

  // Быстрые действия шапки (как панель расширения): сменить этап, пропустить/вернуть в воронку.
  // Состояние берём из props (job обновляется по ссылке из кэша) — без локального дублирования.
  const stageM = useUpdateJobStage()
  const skipM = useSkipJob()
  const unskipM = useUnskipJob()
  const deleteM = useDeleteJob()
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false)

  // «Удалить» — необратимо (в отличие от Отказа/Пропуска, у которых есть «Вернуть»), поэтому
  // отдельный ConfirmDialog у переключалки вкладок, а не общий pending футера снизу.
  function onDelete() {
    if (job.id == null) return
    deleteM.mutate({ id: job.id }, { onSuccess: () => onOpenChange(false) })
  }

  // Последний известный НЕ-«Отказ» этап — чтобы «Вернуть» после «Отказа от HR» восстанавливал
  // именно исходный этап, а не общий дефолт. Обновляется эффектом, пока стадия не «Отказ»; после
  // смены на «Отказ» замораживается на предыдущем значении.
  const lastEngagedStageRef = useRef(stage)
  useEffect(() => {
    if (stage !== "Отказ") lastEngagedStageRef.current = stage
  }, [stage])

  const rejected = stage === "Отказ"
  const acted = rejected || job.skipped // одна из кнопок уже нажата — вместо пары показываем «Вернуть»

  // Отказ от HR — единственное продвижение по воронке, доступное кнопкой в дровере (JS-1.1: перевод
  // в остальные этапы — перетаскиванием карточки по канбану). Снимает «Пропущено», если было.
  function onHrReject() {
    if (job.id == null || stage === "Отказ") return
    stageM.mutate({ id: job.id, stage: "Отказ" })
    if (job.skipped) unskipM.mutate({ id: job.id })
  }

  // «Вернуть» — отмена «Отказа от HR» либо «Пропустить» (на случай случайного клика): восстанавливает
  // именно тот этап, на котором вакансия была до отказа.
  function onRevert() {
    if (job.id == null) return
    if (rejected) {
      stageM.mutate({ id: job.id, stage: lastEngagedStageRef.current })
      if (job.skipped) unskipM.mutate({ id: job.id })
    } else if (job.skipped) {
      unskipM.mutate({ id: job.id })
    }
  }

  // DrawerBody монтируется с key={job.id} — состояние формы и диалога сбрасывается сменой карточки
  // через remount (idiomatic React вместо setState-в-эффекте), поэтому сидим прямо из инициализаторов.
  // V-02/V-11: вкладка — тоже часть этого локального состояния, но с фолбэком на sessionStorage той
  // же вакансии (readStoredDrawerTab возвращает «decision» для любой другой), чтобы F5 сохранял
  // вкладку, а открытие другой карточки — сбрасывало на «Решение».
  const vacancyId = job.vacancy_id ?? ""
  const [activeTab, setActiveTabState] = useState<DrawerTab>(() => readStoredDrawerTab(vacancyId))
  const setActiveTab = (tab: DrawerTab) => {
    setActiveTabState(tab)
    writeStoredDrawerTab(vacancyId, tab)
  }

  // Цитата сигналов формата (карточка «Формат» на «Решении») подсвечивается в тексте
  // вакансии — клик по сигналу ещё и переключает на вкладку «Вакансия».
  const [activeQuote, setActiveQuote] = useState<string | null>(null)
  const [formatOpen, setFormatOpen] = useState(false)
  function revealQuote(quote: string) {
    setActiveQuote(quote)
    setActiveTab("vacancy")
  }

  // Сопроводительное (JS-6.1): своя вкладка «Действия» (V-02) — редактор виден всегда, без
  // отдельного спойлера (был нужен, пока письмо делило место с текстом вакансии в одной колонке).
  // Генерим LLM-ручкой, текст пишется в jobs.cover_letter_text. Поле редактора сидим из onSuccess
  // результата (карточка не ремонтится по id); правку шлём отдельной инстансой той же мутации.
  // FR3-65/67: letter_required не трогаем — это сигнал расширения («площадка требует»), не факт текста.
  const gen = useGenerateCoverLetter()
  const saveCover = useUpdateJobApplyFields()
  const [cover, setCover] = useState(job.cover_letter_text ?? "")
  const coverDirty = cover !== (job.cover_letter_text ?? "")
  const hasCover = cover.trim().length > 0
  const canGenerate = (job.vacancy_text?.trim().length ?? 0) >= 50
  // Переключалка RU/EN (Э4.4 dual_employment_and_contracting_2026.md). null = автоопределение
  // по языку резюме — бэкенд решает сам и возвращает фактический выбор в ответе. Клик по чипу
  // ставит явный оверрайд для следующей генерации; после успеха синхронизируем с тем, что реально
  // сгенерировано (job.cover_letter_lang с прошлого раза — начальное значение при открытии).
  const [letterLang, setLetterLang] = useState<CoverLetterLang | null>(
    (job.cover_letter_lang as CoverLetterLang | null) ?? null,
  )

  const navigate = useNavigate()

  // Наличие диалога (UX5-18): «Начать чат»/«Продолжить чат» — кнопка в футере рядом с Отказ от HR/
  // Пропустить.
  const conv = useVacancyConversation(job)
  const hasConversation = !!conv.thread || conv.messages.length > 0
  const sectionJump = sectionJumpFor(job)

  function onGenerate() {
    if (job.id == null) return
    gen.mutate(
      { jobId: job.id, lang: letterLang ?? undefined },
      {
        onSuccess: (res) => {
          setCover(res.cover_letter_text)
          setLetterLang(res.lang as CoverLetterLang)
        },
      },
    )
  }

  function onSaveCover() {
    if (job.id == null) return
    saveCover.mutate({ id: job.id, cover_letter_text: cover })
  }

  // Сокращённый формат + суффикс оценки (шаг 22) — как на карточке воронки.
  const salaryValue = formatSalaryCardText(salary)
  const salaryProvenance = salaryProvenanceLabel(job)

  return (
    <>
      <DrawerHeader
        job={job}
        listingUrl={listingUrl}
        sourceGroup={sourceGroup}
        companyType={companyType}
        stage={stage}
        hrViewedDaysAgo={hrViewedDaysAgo}
      />

      {/* V-02: каркас — шапка (выше) · Tabs · футер (ниже), тело каждой вкладки — единственный
          скроллящийся контейнер. min-h-0 на Tabs и TabsContent обязателен: без него flex-child
          не сжимается и overflow-y-auto не срабатывает внутри flex-колонки Sheet. */}
      <Tabs
        value={activeTab}
        onValueChange={(v) => setActiveTab(v as DrawerTab)}
        className="min-h-0 flex-1 gap-0"
      >
        <div className="mx-4 mt-3 flex flex-nowrap items-center justify-between gap-2">
          <TabsList className="w-fit">
            <TabsTrigger value="decision">Решение</TabsTrigger>
            <TabsTrigger value="vacancy">Вакансия</TabsTrigger>
            <TabsTrigger value="work">
              Действия
              {/* V-08: точка — есть несохранённый черновик письма; state живёт в DrawerBody, а не
                  размонтируется переключением вкладок, поэтому видна независимо от того, где открыт. */}
              {coverDirty && (
                <span
                  className="size-1.5 shrink-0 rounded-full bg-amber-500"
                  title="Есть несохранённые правки письма"
                  aria-label="Есть несохранённые правки письма"
                />
              )}
            </TabsTrigger>
          </TabsList>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="shrink-0 border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100 hover:text-rose-800"
            disabled={deleteM.isPending}
            onClick={() => setDeleteConfirmOpen(true)}
          >
            {deleteM.isPending ? (
              <Loader2 className="size-4 animate-spin" strokeWidth={2} />
            ) : (
              <Trash2 className="size-4" strokeWidth={2} />
            )}
            Удалить
          </Button>
        </div>
        <ConfirmDialog
          open={deleteConfirmOpen}
          onOpenChange={setDeleteConfirmOpen}
          title="Удалить вакансию?"
          description="Вакансия и её история удалятся безвозвратно. Действие нельзя отменить."
          confirmLabel="Удалить"
          onConfirm={() => {
            setDeleteConfirmOpen(false)
            onDelete()
          }}
        />
        <TabsContent value="decision" className="min-h-0 overflow-y-auto p-4">
          <div className="space-y-4">
            <TabDecision
              s={s}
              vacancyId={job.vacancy_id}
              salaryValue={salaryValue}
              salary={salary}
              formatChip={formatChip}
              salaryProvenance={salaryProvenance}
              remote={remote}
              remoteChip={remoteChip}
              salaryAction={salaryAction}
              formatOpen={formatOpen}
              onFormatOpenChange={setFormatOpen}
              activeQuote={activeQuote}
              onRevealQuote={revealQuote}
            />
            <WorkTermsBlock job={job} activeQuote={activeQuote} onRevealQuote={revealQuote} />
          </div>
        </TabsContent>
        <TabsContent value="vacancy" className="min-h-0 overflow-y-auto p-4">
          <TabVacancy
            job={job}
            vacancyText={job.vacancy_text}
            activeQuote={activeQuote}
            cover={cover}
            setCover={setCover}
            canGenerate={canGenerate}
            genPending={gen.isPending}
            onGenerate={onGenerate}
            hasCover={hasCover}
            coverDirty={coverDirty}
            saveCoverPending={saveCover.isPending}
            onSaveCover={onSaveCover}
            letterLang={letterLang}
            onLetterLangChange={setLetterLang}
          />
        </TabsContent>
        <TabsContent value="work" className="min-h-0 overflow-y-auto p-4">
          <TabWork job={job} />
        </TabsContent>
      </Tabs>

      {/* S12: блок ссылок — та же вакансия на других площадках (дедупликация). */}
      {job.links && job.links.length > 0 && (
        <div className="mx-4 mb-2 border-t border-slate-200 pt-2">
          <p className="mb-1 text-xs font-medium text-slate-500">
            Эта же вакансия на других площадках
          </p>
          <div className="flex flex-wrap gap-1.5">
            {job.links.map((link) => {
              const sourceKey = link.source
              const group: SourceGroup = resolveSourceGroup(sourceKey)
              const label = group ? (SOURCE_GROUP_LABEL[group] ?? sourceKey) : sourceKey
              const href = link.url ?? undefined
              if (href) {
                return (
                  <a
                    key={link.source}
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 rounded border border-slate-200 px-2 py-1 text-xs text-slate-600 transition-colors hover:border-slate-400 hover:text-slate-900"
                  >
                    <SourceIcon group={group} size={16} />
                    {label}
                  </a>
                )
              }
              return (
                <span
                  key={link.source}
                  className="inline-flex items-center gap-1 rounded border border-slate-200 px-2 py-1 text-xs text-slate-500"
                >
                  <SourceIcon group={group} size={16} />
                  {label}
                </span>
              )
            })}
          </div>
        </div>
      )}

      <DrawerFooter
        job={job}
        sectionJump={sectionJump}
        onSectionJump={() =>
          sectionJump &&
          job.vacancy_id &&
          navigate(`${sectionJump.path}?vacancy=${encodeURIComponent(job.vacancy_id)}`)
        }
        hasConversation={hasConversation}
        onOpenChat={() => navigate(`/chat?vacancy=${encodeURIComponent(job.vacancy_id)}`)}
        acted={acted}
        onRevert={onRevert}
        revertPending={job.id == null || stageM.isPending || unskipM.isPending}
        onHrReject={onHrReject}
        hrRejectPending={job.id == null || stageM.isPending}
        onSkip={(reason) => job.id != null && skipM.mutate({ id: job.id, reason })}
        skipPending={skipM.isPending}
      />
    </>
  )
}

// Резиновая ширина ящика (решение #12): раньше фикс 640px (V-01). Границы держат тот же смысл,
// что раньше объяснял комментарий в sheet.tsx — не уже вкладки «Решение», не шире, чем не мешать
// второй колонке канбана на типичном 1280-экране; дальше — свобода пользователя, персистится.
const DRAWER_MIN_WIDTH = 440
const DRAWER_MAX_WIDTH = 900
const DRAWER_DEFAULT_WIDTH = 640
const DRAWER_WIDTH_STORAGE_KEY = "jobs.drawer.width"

function clampDrawerWidth(w: number): number {
  return Math.min(DRAWER_MAX_WIDTH, Math.max(DRAWER_MIN_WIDTH, w))
}

// Тонкая ручка на левом крае дровера — тянет ширину курсором (pointer capture, без libraries).
function DrawerResizeHandle({ onResize }: { onResize: (width: number) => void }) {
  const draggingRef = useRef(false)

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Изменить ширину панели"
      onPointerDown={(e) => {
        draggingRef.current = true
        e.currentTarget.setPointerCapture(e.pointerId)
      }}
      onPointerMove={(e) => {
        if (!draggingRef.current) return
        // Дровер прижат к правому краю окна — ширина равна расстоянию от курсора до этого края.
        onResize(window.innerWidth - e.clientX)
      }}
      onPointerUp={(e) => {
        draggingRef.current = false
        e.currentTarget.releasePointerCapture(e.pointerId)
      }}
      className="absolute left-0 top-0 z-10 h-full w-1.5 -translate-x-1/2 cursor-col-resize touch-none select-none hover:bg-sky-300/50 active:bg-sky-400/60"
    />
  )
}

// Дровер карточки вакансии (JS-1.2): открывается кликом по карточке доски. Снимок job держим
// локально, чтобы при закрытии отыграла анимация ухода (radix размонтирует после неё).
export function JobDetailDrawer({
  job,
  onOpenChange,
}: {
  job: Job | null
  onOpenChange: (open: boolean) => void
}) {
  // Снимок последней непустой вакансии: при закрытии (job=null) контент остаётся для анимации ухода,
  // radix размонтирует после неё. Подстройка во время рендера (паттерн React «adjust state on prop
  // change») — без эффекта; обновляем по ссылке, чтобы свежий объект после правки тоже долетал.
  const [shown, setShown] = useState<Job | null>(job)
  if (job && job !== shown) setShown(job)

  const [width, setWidth] = usePersistedNumber(DRAWER_WIDTH_STORAGE_KEY, DRAWER_DEFAULT_WIDTH)
  const resize = useCallback((next: number) => setWidth(clampDrawerWidth(next)), [setWidth])

  return (
    <Sheet open={!!job} onOpenChange={onOpenChange}>
      <SheetContent
        className="max-w-none"
        style={{ width: `min(100%, ${clampDrawerWidth(width)}px)` }}
      >
        <DrawerResizeHandle onResize={resize} />
        {shown && <DrawerBody key={shown.id} job={shown} onOpenChange={onOpenChange} />}
      </SheetContent>
    </Sheet>
  )
}
