import { useState, type ReactNode } from "react"
import {
  DndContext,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core"
import { Building2, GripVertical, Loader2, Search, X } from "lucide-react"
import type { CompanyRegistryItem } from "@/api/companies"
import { ErrorState } from "@/components/ui/empty-state"
import { HelpTip } from "@/components/ui/help-tip"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { usePatchResumeField, useResumeData } from "@/features/resume/use-resume"
import { SectionCard } from "@/components/ui/section-card"
import { useMarketCompanies } from "../use-market-data"
import {
  MAX_TARGET,
  TARGET_COMPANY_DELTA,
  addCompany,
  canAccept,
  filterCandidates,
  formatLastSeen,
  matchesCompanyQuery,
  moveCompany,
  toListsValue,
  type CompanyBoardState,
  type CompanyListsValue,
  type CompanyZone,
} from "./companies-board"

type ChipMeta = {
  lastSeenAt?: string | null
}

/** Единственная подпись карточки: когда компания попадалась последний раз. */
function lastSeenLine(meta?: ChipMeta): string | null {
  if (!meta) return null
  return formatLastSeen(meta.lastSeenAt)
}

function DropZone({
  id,
  title,
  helpId,
  effect,
  companies,
  count,
  metaByName,
  accent,
  atLimit,
  emptyHint,
  onRemove,
  children,
}: {
  id: CompanyZone
  title: string
  helpId?: "resume.companies-target" | "resume.companies-avoid" | "resume.companies-candidates"
  /** Видимая подпись эффекта правила (K-03), напр. «+5 к баллу»; сама несёт HelpTip. */
  effect?: ReactNode
  companies: string[]
  /** Счётчик в шапке; по умолчанию — длина `companies` (для кандидатов — полный пул). */
  count?: number
  metaByName?: Map<string, ChipMeta>
  accent: "emerald" | "rose" | "slate"
  atLimit: boolean
  /** Если задан — вместо дефолтной подсказки пустой зоны. */
  emptyHint?: ReactNode
  onRemove?: (name: string) => void
  children?: ReactNode
}) {
  const { setNodeRef, isOver } = useDroppable({ id, disabled: atLimit && id !== "candidates" })

  const ring =
    accent === "emerald"
      ? "border-emerald-200 bg-emerald-50/40"
      : accent === "rose"
        ? "border-rose-200 bg-rose-50/40"
        : "border-slate-200 bg-slate-50/50"
  const ringOver =
    accent === "emerald"
      ? "ring-1 ring-emerald-300"
      : accent === "rose"
        ? "ring-1 ring-rose-300"
        : "ring-1 ring-slate-300"

  const n = count ?? companies.length
  // У «Избегать» лимита нет — счётчик без «/max», только фактическое число.
  const countLabel = id === "target" ? `${n}/${MAX_TARGET}` : String(n)

  return (
    <div
      ref={setNodeRef}
      data-testid={`company-zone-${id}`}
      className={cn(
        // Фикс. потолок высоты: иначе на пустой странице «Компании» колонки тянутся на весь
        // viewport (h-full + items-stretch). Список чипов скроллится внутри.
        "flex max-h-[22rem] min-h-[12rem] flex-col gap-2 rounded-xl border p-3 transition-all duration-200",
        ring,
        isOver && !atLimit && ringOver,
      )}
    >
      <div className="flex shrink-0 items-center gap-1">
        <span className="text-xs font-medium tracking-wider text-slate-500 uppercase">{title}</span>
        {helpId ? <HelpTip id={helpId} /> : null}
        <span className="ml-auto text-xs tabular-nums text-slate-400">{countLabel}</span>
      </div>
      {effect ? <div className="-mt-1 shrink-0">{effect}</div> : null}
      <div className="flex min-h-0 flex-1 flex-wrap content-start gap-1.5 overflow-y-auto overscroll-contain pr-1">
        {companies.length === 0
          ? (emptyHint ?? (
              <span className="px-0.5 text-sm text-slate-400">Перетащите сюда</span>
            ))
          : null}
        {companies.map((name) => (
          <CompanyChip
            key={name}
            company={name}
            from={id}
            meta={metaByName?.get(name)}
            accent={accent}
            onRemove={onRemove ? () => onRemove(name) : undefined}
          />
        ))}
      </div>
      {children ? <div className="shrink-0">{children}</div> : null}
    </div>
  )
}

function CompanyChip({
  company,
  from,
  meta,
  accent,
  onRemove,
}: {
  company: string
  from: CompanyZone
  meta?: ChipMeta
  accent: "emerald" | "rose" | "slate"
  onRemove?: () => void
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `${from}:${company}`,
    data: { company, from },
  })

  const chip =
    accent === "emerald"
      ? "border-emerald-200 bg-white text-emerald-800"
      : accent === "rose"
        ? "border-rose-200 bg-white text-rose-800"
        : "border-slate-200 bg-white text-slate-700 shadow-xs"

  // Без служебных цифр и стадий — только дата последнего контакта, если она есть.
  const dateLine = lastSeenLine(meta)

  return (
    <span
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      className={cn(
        "inline-flex cursor-grab touch-none flex-col items-start gap-0.5 rounded-lg border px-2 py-1.5 text-xs font-medium active:cursor-grabbing",
        chip,
        isDragging && "opacity-40",
      )}
    >
      <span className="inline-flex items-center gap-1">
        <GripVertical className="size-3 shrink-0 text-slate-300" strokeWidth={2} aria-hidden />
        <span>{company}</span>
        {onRemove ? (
          <button
            type="button"
            onPointerDown={(e) => e.stopPropagation()}
            onClick={onRemove}
            className="text-slate-400 transition-colors hover:text-slate-700"
            aria-label={`Убрать «${company}»`}
          >
            <X className="size-3" strokeWidth={2} />
          </button>
        ) : null}
      </span>
      {dateLine ? (
        <span className="pl-4 text-[10px] font-normal text-slate-400" title="Последний контакт">
          {dateLine}
        </span>
      ) : null}
    </span>
  )
}

function AddOwnInput({
  placeholder,
  disabled,
  onAdd,
}: {
  placeholder: string
  disabled: boolean
  onAdd: (name: string) => void
}) {
  const [draft, setDraft] = useState("")
  const commit = () => {
    const name = draft.trim()
    if (!name || disabled) return
    onAdd(name)
    setDraft("")
  }
  return (
    <Input
      value={draft}
      disabled={disabled}
      placeholder={placeholder}
      onChange={(e) => setDraft(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault()
          commit()
        }
      }}
      onBlur={commit}
      className="h-8 text-xs"
    />
  )
}

/** Поиск по компаниям — живёт в шапке секции «Компании», ищет по всем трём колонкам. */
export function CompanySearchInput({
  value,
  onChange,
}: {
  value: string
  onChange: (v: string) => void
}) {
  return (
    <div className="relative w-52">
      <Search
        className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-slate-400"
        strokeWidth={2}
      />
      <Input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Поиск по названию"
        aria-label="Поиск компании по названию"
        className="h-8 pl-7 text-xs"
      />
    </div>
  )
}

/**
 * Три колонки: Избегать ← Кандидаты → Целевые (K-01).
 * Контролируемый: списки снаружи, перемещения через onChange; поиск — снаружи, общий
 * по всем трём колонкам (query с шапки секции).
 */
export function CompaniesBoard({
  target,
  avoid,
  candidates,
  query = "",
  onChange,
  candidatesLoading,
  candidatesError,
}: {
  target: string[]
  avoid: string[]
  candidates: CompanyRegistryItem[]
  /** Общий поиск: фильтрует все три колонки по имени. */
  query?: string
  onChange: (next: CompanyListsValue) => void
  candidatesLoading?: boolean
  candidatesError?: boolean
}) {
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }))
  const board: CompanyBoardState = { target, avoid }
  const q = query.trim()

  const metaByName = new Map<string, ChipMeta>()
  for (const c of candidates) {
    metaByName.set(c.company, { lastSeenAt: c.last_seen_at })
  }

  // Поиск режет все три колонки, а не только «Кандидаты».
  const visibleTarget = q ? target.filter((n) => matchesCompanyQuery(n, q)) : target
  const visibleAvoid = q ? avoid.filter((n) => matchesCompanyQuery(n, q)) : avoid
  const unmarkedPool = filterCandidates(candidates, board)
  const visiblePool = q
    ? unmarkedPool.filter((c) => matchesCompanyQuery(c.company, q))
    : unmarkedPool
  const noMatchForQuery = q.length > 0 && visiblePool.length === 0

  const commit = (next: CompanyBoardState | null) => {
    if (!next) return
    onChange(toListsValue(next))
  }

  const onDragEnd = (event: DragEndEvent) => {
    const over = event.over?.id
    const company = event.active.data.current?.company as string | undefined
    if (!company || (over !== "target" && over !== "avoid" && over !== "candidates")) return
    commit(moveCompany(board, company, over))
  }

  const targetFull = !canAccept(board, "target")

  return (
    <DndContext sensors={sensors} onDragEnd={onDragEnd}>
      <div className="grid gap-3 lg:grid-cols-3 lg:items-start">
        <DropZone
          id="avoid"
          title="Избегать"
          effect={
            <HelpTip id="resume.companies-avoid">
              <span className="text-[11px] font-medium text-rose-700">
                вакансия уходит в Пропустить
              </span>
            </HelpTip>
          }
          companies={visibleAvoid}
          count={avoid.length}
          metaByName={metaByName}
          accent="rose"
          atLimit={false}
          onRemove={(name) => commit(moveCompany(board, name, "candidates"))}
        >
          <AddOwnInput
            placeholder="Добавить свою"
            disabled={false}
            onAdd={(name) => commit(addCompany(board, name, "avoid"))}
          />
        </DropZone>

        <DropZone
          id="candidates"
          title="Кандидаты"
          helpId="resume.companies-candidates"
          companies={visiblePool.map((c) => c.company)}
          count={visiblePool.length}
          metaByName={metaByName}
          accent="slate"
          atLimit={false}
          emptyHint={
            candidatesLoading ? (
              <span className="inline-flex items-center gap-1.5 px-0.5 py-1 text-sm text-slate-400">
                <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />
                Загрузка…
              </span>
            ) : candidatesError ? (
              <span className="px-0.5 py-1 text-sm text-rose-600">
                Не удалось загрузить кандидатов
              </span>
            ) : noMatchForQuery ? (
              <span className="px-0.5 text-sm text-slate-400">Ничего не найдено по «{q}»</span>
            ) : (
              <span className="px-0.5 text-sm text-slate-400">
                Пока пусто. Оцените вакансии или перетащите сюда.
              </span>
            )
          }
        />

        <DropZone
          id="target"
          title="Целевые"
          effect={
            <HelpTip id="resume.companies-target">
              <span className="text-[11px] font-medium text-emerald-700">
                +{TARGET_COMPANY_DELTA} к баллу
              </span>
            </HelpTip>
          }
          companies={visibleTarget}
          count={target.length}
          metaByName={metaByName}
          accent="emerald"
          atLimit={targetFull}
          onRemove={(name) => commit(moveCompany(board, name, "candidates"))}
        >
          <AddOwnInput
            placeholder="Добавить свою"
            disabled={targetFull}
            onAdd={(name) => commit(addCompany(board, name, "target"))}
          />
        </DropZone>
      </div>
    </DndContext>
  )
}

function BoardSkeleton() {
  return (
    <div className="grid gap-3 lg:grid-cols-3" aria-hidden>
      {Array.from({ length: 3 }).map((_, i) => (
        <Skeleton key={i} className="h-[12rem] max-h-[22rem] w-full rounded-xl" />
      ))}
    </div>
  )
}

/**
 * Секция «Компании» на «Рынке» (K-01).
 * Запись в резюме — через usePatchResumeField; оптимистичный откат — K-02.
 * Поиск — в строке заголовка (action), общий по всем колонкам.
 */
export function CompaniesBoardSection({ className }: { className?: string }) {
  const resume = useResumeData()
  const companies = useMarketCompanies()
  const patchField = usePatchResumeField()
  const [query, setQuery] = useState("")

  const target = resume.data?.search_criteria?.target_companies ?? []
  const avoid = resume.data?.search_criteria?.avoid_companies ?? []
  const items = companies.data?.items ?? []

  const status =
    resume.isLoading || (companies.isLoading && !companies.data)
      ? ("loading" as const)
      : resume.isError
        ? ("error" as const)
        : ("content" as const)

  return (
    <SectionCard
      id="kompanii"
      title="Компании"
      helpId="market.companies-board"
      className={className}
      status={status}
      meta={<CompanySearchInput value={query} onChange={setQuery} />}
      loading={<BoardSkeleton />}
      error={
        <ErrorState
          compact
          icon={Building2}
          title="Компании не загрузились"
          note="Не удалось прочитать списки из резюме."
          action={{ label: "Повторить", onClick: () => void resume.refetch() }}
        />
      }
    >
      <CompaniesBoard
        target={target}
        avoid={avoid}
        candidates={items}
        query={query}
        candidatesLoading={companies.isLoading}
        candidatesError={companies.isError}
        onChange={(next) => {
          patchField.mutate({ search_criteria: next })
        }}
      />
    </SectionCard>
  )
}
