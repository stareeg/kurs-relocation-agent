import { useEffect, useMemo, useState, type ReactNode } from "react"
import { AlertTriangle, ChevronDown, LayoutGrid } from "lucide-react"
import type { Job } from "@/api/jobs"
import { useJobs } from "@/features/jobs/use-jobs"
import { needsVacancyText, resolveStage, scoreTone } from "@/features/jobs/funnel"
import type { FunnelStage } from "@/features/jobs/funnel"
import { VacancyTextNeededMark } from "@/features/jobs/VacancyTextNeededMark"
import { SourceIcon } from "@/features/jobs/SourceIcon"
import { jobSourceGroup } from "@/features/jobs/source"
import { formatEventLabel } from "@/lib/format"
import { cn, useListAppearMotion } from "@/lib/utils"
import { ErrorState } from "@/components/ui/empty-state"
import { Skeleton } from "@/components/ui/skeleton"

// Порядок стадий по умолчанию для sort="byStage" — для раздела «Офферы»: ближе к финалу сначала.
// Другие разделы передают свой `stageOrder` (Технички / Скрининги) — текущая стадия раздела первой,
// затем остальные продвинутые в порядке убывания близости к финалу.
const DEFAULT_STAGE_ORDER: FunnelStage[] = ["Оффер", "Финал", "Техничка", "Скрининг"]

// Вертикальный рельс карточек вакансий (левая колонка Скринингов/Техничек/Офферов) вместо
// прежнего горизонтального — скроллить вверх/вниз удобнее, а колонка справа (чат/подготовка)
// получает всю высоту экрана. Первая карточка — «Общая» (вакансия не выбрана) — показывается
// только там, где общий режим осмыслен; сейчас ни один из трёх разделов её не использует
// (showGeneral={false}). Отказы и пропущенные в выборе не показываем по умолчанию — по ним
// готовиться/делать оффер незачем.
export function VacancyCardRail({
  value,
  onChange,
  showGeneral = true,
  // Режим сортировки под раздел: по умолчанию (active) — без отказов и пропущенных, порядок
  // как пришли. `sort="byStage"` — для Офферов/Техничек/Скринингов: показываем только вакансии
  // продвинутых стадий (`stageOrder`), в порядке этого списка; внутри — по убыванию скора.
  // «Просмотр»/«Отклик»/«Отказ»/пропущенные выкидываем — по ним раздел не строится.
  sort = "active",
  stageOrder = DEFAULT_STAGE_ORDER,
  // Внутри sort="byStage" вторичный компаратор по умолчанию — score desc; «Скрининги» передают
  // свой (по дате скрининга), Технички/Офферы — нет, их порядок не меняется.
  stageSecondarySort,
  // corner_case_1: Отказ/Пропущено раньше исчезали из рельса безвозвратно — если по вакансии уже
  // был технический этап (или HR-скрининг), владелец не мог вернуться и вставить расшифровку
  // задним числом (единственный способ — по-настоящему вернуть вакансию в воронку). Технички и
  // Скрининги передают true: скрытый по умолчанию переключатель показывает закрытые вакансии
  // отдельным хвостом рельса, не трогая ни статус чата, ни этап воронки.
  allowClosed = false,
  // В хвосте «закрытых» показывать и Пропущено, не только Отказ. Технички хотят оба (там сотни
  // Пропущено — не проблема, листается редко); Скрининги — только Отказ (Пропущено там не по
  // делу и их слишком много, чтобы листать).
  closedIncludeSkipped = true,
  // Ограничить хвост последними N (по `updated_at desc`) — для Скринингов: там отказов может быть
  // много, а места под них мало.
  closedLimit,
  // Кнопки быстрых действий под карточкой (Отказ/Пройдено, Отклонён/Принят — своя пара на
  // раздел) — не рендерятся для закрытых карточек (там действовать уже не над чем).
  renderActions,
  // Только Технички: раскрываемое дерево этапов вакансии внутри рельса — «подзадачи» под
  // карточкой. Без пропа карточка ведёт себя как раньше (без шеврона раскрытия).
  renderExpanded,
  // Отметка-факт в третьей строке карточки рядом с датой (Скрининги/Технички: вставлена ли
  // расшифровка). Раздел решает, что показать; рельс ничего про разборы не знает.
  renderMark,
}: {
  value: string | null
  onChange: (job: Job | null) => void
  showGeneral?: boolean
  sort?: "active" | "byStage"
  stageOrder?: FunnelStage[]
  stageSecondarySort?: (a: Job, b: Job) => number
  allowClosed?: boolean
  closedIncludeSkipped?: boolean
  closedLimit?: number
  renderActions?: (job: Job) => ReactNode
  renderExpanded?: (job: Job) => ReactNode
  renderMark?: (job: Job) => ReactNode
}) {
  const { data: jobs, isLoading, isError, refetch } = useJobs()
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set())

  const list = useMemo(() => {
    const all = jobs ?? []
    if (sort === "byStage") {
      // Ранг стадии по `stageOrder` (0 = первая в рельсе). Стадии вне списка — выкидываем.
      const rank = new Map<FunnelStage, number>()
      stageOrder.forEach((s, i) => rank.set(s, i))
      return all
        .filter((j) => !j.skipped)
        .map((j) => ({ job: j, stage: resolveStage(j.status) }))
        .filter((x) => rank.has(x.stage))
        .sort((a, b) => {
          const ra = rank.get(a.stage)!
          const rb = rank.get(b.stage)!
          if (ra !== rb) return ra - rb
          if (stageSecondarySort) return stageSecondarySort(a.job, b.job)
          // Внутри категории — по убыванию скора (без скора в хвост).
          const sa = a.job.overall_score ?? -1
          const sb = b.job.overall_score ?? -1
          return sb - sa
        })
        .map((x) => x.job)
    }
    // active: без отказов и без сознательно пропущенных.
    return all.filter((j) => !j.skipped && resolveStage(j.status) !== "Отказ")
  }, [jobs, sort, stageOrder, stageSecondarySort])

  // Отдельный хвост: закрытые вакансии (Отказ/Пропущено), только под `allowClosed` и только для
  // byStage-разделов — «active»-рельс (Легенда/новый чат) в этом различии не нуждается.
  const closedList = useMemo(() => {
    if (!allowClosed || sort !== "byStage") return []
    const filtered = (jobs ?? []).filter(
      (j) => (closedIncludeSkipped && j.skipped) || resolveStage(j.status) === "Отказ",
    )
    if (closedLimit == null) return filtered
    return [...filtered]
      .sort((a, b) => (b.updated_at ?? "").localeCompare(a.updated_at ?? ""))
      .slice(0, closedLimit)
  }, [jobs, allowClosed, sort, closedIncludeSkipped, closedLimit])
  const closedIds = useMemo(
    () => new Set(closedList.map((j) => j.vacancy_id).filter(Boolean)),
    [closedList],
  )

  // Закрытые вакансии (Отказ/Пропущено) всегда дописаны хвостом рельса — визуально отличимы
  // (пунктирная рамка, приглушённый фон), клик по ним больше не нужен: раньше был скрыт за
  // «Показать отказы», владелец предпочитает видеть сразу.
  const visibleList = useMemo(() => [...list, ...closedList], [list, closedList])

  // Раскрытая по умолчанию — выбранная вакансия (Технички: дерево этапов сразу видно у той, с
  // которой владелец работает). Ручной toggle дальше живёт независимо — можно и свернуть
  // выбранную, и держать раскрытыми сразу несколько (быстро переключаться между этапами разных
  // вакансий, не теряя дерево уже открытой).
  useEffect(() => {
    if (!value) return
    // eslint-disable-next-line react-hooks/set-state-in-effect -- авто-раскрытие выбранной вакансии
    setExpandedIds((prev) => (prev.has(value) ? prev : new Set(prev).add(value)))
  }, [value])

  function toggleExpanded(vacancyId: string) {
    setExpandedIds((prev) => {
      const next = new Set(prev)
      if (next.has(vacancyId)) next.delete(vacancyId)
      else next.add(vacancyId)
      return next
    })
  }

  const listSig = useMemo(
    () =>
      [...visibleList.map((j) => String(j.vacancy_id ?? j.id)), showGeneral ? "__general__" : ""]
        .filter(Boolean)
        .sort()
        .join("\0"),
    [visibleList, showGeneral],
  )
  const appear = useListAppearMotion(listSig)
  const generalOffset = showGeneral ? 1 : 0

  return (
    <div
      // min-h держит габарит рельса и когда список пуст (в разделе ещё нет вакансий) — иначе
      // колонка схлопывается и «прыгает» при появлении первой карточки.
      //
      // Правка 2026-08-20 (баг «не скроллится колесом»): этот div раньше был САМ скролл-
      // контейнером (`overflow-y-auto overscroll-contain`), пока `CollapsibleRail` (83ae44d) не
      // обернул его в свой собственный `overflow-y-auto` снаружи — реальный скролл теперь там.
      // Здесь контент почти всегда укладывается ровно в свою собственную высоту (нечего скроллить
      // внутри), но класс `overscroll-contain` на элементе с `overflow-y-auto` заставляет браузер
      // трактовать его как отдельную scroll-границу и НЕ пробрасывать колесо мыши/свайп родителю —
      // события тонут здесь, снаружи ничего не скроллится. Убираем оба класса, скролл и скрытие
      // скроллбара теперь на обёртке в CollapsibleRail.
      className="flex min-h-[120px] w-full min-w-0 flex-col gap-2 py-0.5 pr-0.5"
    >
      {/* «Общая» — легенда и общие вопросы вне привязки к вакансии (только где это осмысленно). */}
      {showGeneral && (
        <GeneralCard
          key={`general-${appear.appearKey}`}
          active={value === null}
          onClick={() => onChange(null)}
          className={appear.itemClass(0)}
        />
      )}

      {isError ? (
        <ErrorState
          compact
          icon={AlertTriangle}
          title="Вакансии не загрузились"
          note="Не удалось загрузить список вакансий."
          action={{ label: "Повторить", onClick: () => void refetch() }}
        />
      ) : isLoading && list.length === 0 ? (
        [0, 1, 2].map((i) => <Skeleton key={i} className="h-[72px] w-full shrink-0 rounded-xl" />)
      ) : (
        visibleList.map((job, index) => {
          const vacancyId = job.vacancy_id
          const closed = vacancyId != null && closedIds.has(vacancyId)
          const active = vacancyId != null && vacancyId === value
          const expanded = vacancyId != null && expandedIds.has(vacancyId)
          return (
            <div
              key={`${vacancyId ?? job.id}-${appear.appearKey}`}
              className={cn("flex flex-col gap-1.5", appear.itemClass(index + generalOffset))}
            >
              <VacancyCard
                job={job}
                active={active}
                onClick={() => onChange(job)}
                closed={closed}
                expandable={!closed && Boolean(renderExpanded)}
                expanded={expanded}
                onToggleExpanded={vacancyId ? () => toggleExpanded(vacancyId) : undefined}
                mark={renderMark?.(job)}
              />
              {!closed && renderExpanded && expanded && (
                <div className="pl-2.5">{renderExpanded(job)}</div>
              )}
              {!closed && renderActions && (
                <div className="flex items-center gap-1.5 pl-11">{renderActions(job)}</div>
              )}
            </div>
          )
        })
      )}
    </div>
  )
}

function GeneralCard({
  active,
  onClick,
  className,
}: {
  active: boolean
  onClick: () => void
  className?: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full shrink-0 items-center gap-1.5 rounded-xl border bg-white px-3 py-2.5 text-left transition-all duration-200 hover:border-slate-300",
        active ? "border-slate-900 ring-1 ring-slate-900" : "border-slate-200",
        className,
      )}
    >
      <LayoutGrid className="size-4 text-slate-500" strokeWidth={2} />
      <span className="text-sm font-medium text-slate-900">Рассказ об опыте</span>
    </button>
  )
}

function capitalizeFirst(s: string): string {
  return s.length > 0 ? s.charAt(0).toUpperCase() + s.slice(1) : s
}

// Строка даты/статуса (3-я строка карточки) — единая логика для всех разделов (раньше была
// только у footerMode="screeningDate" в Скринингах): закрытая вакансия → всегда «Отказ»;
// известна дата скрининга в прошлом → «Был <дата>»; в будущем → сама дата; неизвестна → «Дата не
// назначена».
function dateStatusLabel(job: Job, closed: boolean): string {
  if (closed) return "Отказ"
  const raw = job.hr_screening_at
  if (!raw) return "Дата не назначена"
  const label = formatEventLabel(raw)
  if (!label) return "Дата не назначена"
  const isPast = new Date(raw).getTime() < Date.now()
  return isPast ? `Был ${capitalizeFirst(label)}` : label
}

function VacancyCard({
  job,
  active,
  onClick,
  closed = false,
  expandable = false,
  expanded = false,
  onToggleExpanded,
  mark,
}: {
  job: Job
  active: boolean
  onClick: () => void
  closed?: boolean
  expandable?: boolean
  expanded?: boolean
  onToggleExpanded?: () => void
  /** Отметка-факт раздела (например «Расшифровка») — в одну строку с датой. */
  mark?: ReactNode
}) {
  const score = job.overall_score
  const dateLabel = dateStatusLabel(job, closed)
  // Оффер в руках (OF-7) — тонкая emerald-рамка, видна везде, где используется рельс (Технички/
  // Скрининги/Офферы). `active` (выбранная карточка) визуально доминирует при совпадении.
  const hasOffer = job.offer_status === "thinking" || job.offer_status === "accepted"
  return (
    <div
      className={cn(
        "flex w-full items-stretch gap-2.5 rounded-xl border bg-white py-2 pr-2 pl-2.5 text-left transition-all duration-200 hover:border-slate-300 hover:shadow-xs",
        closed && !active && "border-dashed bg-slate-50/60 opacity-70",
        active
          ? "border-slate-900 ring-1 ring-slate-900"
          : hasOffer
            ? "border-emerald-200 bg-emerald-50/50"
            : "border-slate-200",
      )}
    >
      <button
        type="button"
        onClick={onClick}
        className="flex min-w-0 flex-1 items-center gap-2.5 text-left"
      >
        <span className="flex w-8 shrink-0 flex-col items-center gap-1">
          <SourceIcon group={jobSourceGroup(job)} size={20} />
          {needsVacancyText(job) ? (
            <VacancyTextNeededMark size="sm" />
          ) : (
            score != null && (
              <span className={cn("text-sm font-semibold tabular-nums", scoreTone(score))}>
                {score}
              </span>
            )
          )}
        </span>
        <span className="min-w-0 flex-1 space-y-0.5">
          <span className="block truncate text-sm font-medium leading-snug text-slate-900">
            {job.title ?? "Без названия"}
          </span>
          <span className="block truncate text-xs leading-snug text-slate-500">
            {job.company ?? "—"}
          </span>
          <span className="flex items-center gap-1.5">
            <span
              className={cn(
                "min-w-0 truncate text-xs leading-snug",
                closed ? "text-rose-500" : "text-slate-400",
              )}
            >
              {dateLabel}
            </span>
            {mark}
          </span>
        </span>
      </button>
      {expandable && (
        <button
          type="button"
          onClick={onToggleExpanded}
          aria-expanded={expanded}
          aria-label={expanded ? "Скрыть этапы" : "Показать этапы"}
          title={expanded ? "Скрыть этапы" : "Показать этапы"}
          className="flex shrink-0 items-center self-center rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
        >
          <ChevronDown
            className={cn("size-4 transition-transform", expanded && "rotate-180")}
            strokeWidth={2}
          />
        </button>
      )}
    </div>
  )
}
