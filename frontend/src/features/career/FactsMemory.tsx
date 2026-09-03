import { useMemo, useState, type ReactNode } from "react"
import {
  Brain,
  ChevronDown,
  Pencil,
  Pin,
  Plus,
  Sparkles,
  Target,
  Trash2,
  Trophy,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ClampedText } from "@/components/ui/clamped-text"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { EmptyState, ErrorState } from "@/components/ui/empty-state"
import { HelpTip } from "@/components/ui/help-tip"
import { Input } from "@/components/ui/input"
import { SectionCard } from "@/components/ui/section-card"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { useJobs } from "@/features/jobs/use-jobs"
import { useDebriefHistory } from "@/features/tech/use-debrief"
import { useOffers } from "@/features/offers/use-offers"
import { formatDate, parseDate } from "@/lib/format"
import { CopyCodeButton } from "./CopyCodeButton"
import {
  useCreatePortfolioItem,
  useDeleteFact,
  useDeletePortfolioItem,
  useDraftPortfolioFromDebrief,
  useDraftPortfolioFromOffer,
  useDraftPortfolioFromResume,
  useFacts,
  usePatchFact,
  usePortfolioItems,
} from "./use-career"
import type { CareerFact, PortfolioItem } from "@/api/career"

// «Достижения»/«Пробелы» — единственные два подблока памяти, для которых владелец попросил
// свою вёрстку (правка 2026-08-26): бо́льшая дата слева, без строки источника, без «Поправить».
// Остальные типы факта (ограничения/предпочтения/компании/другое) идут старым FactCard ниже —
// их никто не просил трогать. `note` («Заметки») из показа убран целиком: подблок был лишним.
const REMAINING_FACT_TYPE_ORDER = ["constraint", "preference", "company", "other"] as const

const FACT_TYPE_LABEL: Record<string, string> = {
  constraint: "Ограничения",
  preference: "Предпочтения",
  company: "Компании",
  other: "Другое",
}

const SOURCE_LABEL: Record<string, string> = {
  vacancy: "вакансия",
  debrief: "разбор собеседования",
  chat: "чат",
  manual: "вручную",
  offer: "оффер",
  other: "другое",
}

// Этап 4.4 плана редизайна «Карьеры»: не больше 6 карточек на группу без явного «Показать все».
const GROUP_VISIBLE_LIMIT = 6

// Этап 4.3: длинные LLM-абзацы (разбор/summary) клипаются, короткие факты рендерятся как есть.
const LONG_FACT_THRESHOLD = 160

function groupByType(facts: CareerFact[]): [string, CareerFact[]][] {
  const groups = new Map<string, CareerFact[]>()
  for (const f of facts) {
    const bucket = groups.get(f.fact_type)
    if (bucket) bucket.push(f)
    else groups.set(f.fact_type, [f])
  }
  return REMAINING_FACT_TYPE_ORDER.filter((t) => groups.has(t)).map((t) => [t, groups.get(t)!])
}

// «Сегодня — время, иначе дата» (запрос владельца 2026-08-26): для свежей записи час важнее дня.
function whenLabel(value?: string | null): string {
  const d = parseDate(value)
  if (!d) return ""
  const now = new Date()
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()
  if (sameDay) return d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })
  return d.toLocaleDateString("ru-RU", { day: "numeric", month: "short" })
}

// Общая полка строки для «Достижений» и «Пробелов»: дата крупнее слева, действия — по ховеру
// справа. Единый вид для карточки факта и карточки портфолио — то самое «единообразно».
function MemoryRow({
  when,
  actions,
  children,
}: {
  when?: string | null
  actions?: ReactNode
  children: ReactNode
}) {
  return (
    <div className="group relative flex gap-3 rounded-lg border p-3">
      <div className="w-14 shrink-0 pt-0.5 text-sm font-semibold tabular-nums text-slate-500">
        {whenLabel(when)}
      </div>
      <div className="min-w-0 flex-1 pr-14">{children}</div>
      {actions ? (
        <div className="absolute right-2 top-2 flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
          {actions}
        </div>
      ) : null}
    </div>
  )
}

// Факт (сильная сторона или пробел) внутри новой строки: без строки источника (всегда была
// одним и тем же «разбор собеседования» и не несла пользы) и без «Поправить» (правка владельца:
// кнопка тут не имеет смысла) — только закрепить/удалить.
function FactRow({ fact }: { fact: CareerFact }) {
  const patch = usePatchFact()
  const remove = useDeleteFact()
  const pinned = fact.expires_at == null

  return (
    <MemoryRow
      when={fact.recorded_at}
      actions={
        <>
          {!pinned && (
            <button
              type="button"
              title="Закрепить"
              onClick={() => patch.mutate({ factId: fact.id!, patch: { pinned: true } })}
              className="rounded-md border bg-white p-1 text-slate-500 hover:bg-slate-50"
            >
              <Pin className="size-3.5" strokeWidth={2} />
            </button>
          )}
          <button
            type="button"
            title="Удалить"
            onClick={() => remove.mutate(fact.id!)}
            className="rounded-md border bg-white p-1 text-slate-500 hover:bg-status-bad-soft hover:text-status-bad-fg"
          >
            <Trash2 className="size-3.5" strokeWidth={2} />
          </button>
        </>
      }
    >
      <ClampedText text={fact.fact} className="text-sm text-slate-800" threshold={LONG_FACT_THRESHOLD} />
      {pinned && <span className="mt-1 inline-block text-xs font-medium text-slate-500">Закреплено</span>}
    </MemoryRow>
  )
}

function achievementText(item: { project: string; role: string; outcome: string }): string {
  const head = item.role ? `${item.project} — ${item.role}` : item.project
  return item.outcome ? `${head}\n${item.outcome}` : head
}

function PortfolioRow({ item }: { item: PortfolioItem }) {
  const remove = useDeletePortfolioItem()

  return (
    <MemoryRow
      when={item.created_at}
      actions={
        <button
          type="button"
          title="Удалить"
          onClick={() => item.id != null && remove.mutate(item.id)}
          className="rounded-md border bg-white p-1 text-slate-500 hover:bg-status-bad-soft hover:text-status-bad-fg"
        >
          <Trash2 className="size-3.5" strokeWidth={2} />
        </button>
      }
    >
      <div className="flex flex-wrap items-center gap-2">
        <p className="font-medium text-slate-800">{item.project}</p>
        {item.role && <Badge variant="outline">{item.role}</Badge>}
        <CopyCodeButton code={achievementText(item)} />
      </div>
      {item.outcome && (
        <ClampedText text={item.outcome} className="mt-1 text-sm text-muted-foreground" lines={3} />
      )}
      {item.notes && <p className="mt-1 text-xs text-muted-foreground">{item.notes}</p>}
    </MemoryRow>
  )
}

// «Достижения» объединяет сильные стороны (факты) и портфолио (Этап 5) в одну ленту, отсортированную
// по дате — владелец попросил один блок вместо двух похожих. Сортировка по факту/портфолио, не по типу.
type AchievementRow =
  | { kind: "fact"; key: string; when: string | null; fact: CareerFact }
  | { kind: "portfolio"; key: string; when: string | null; item: PortfolioItem }

function buildAchievementRows(facts: CareerFact[], items: PortfolioItem[]): AchievementRow[] {
  const rows: AchievementRow[] = [
    ...facts
      .filter((f) => f.fact_type === "strength")
      .map((f): AchievementRow => ({ kind: "fact", key: `fact-${f.id}`, when: f.recorded_at ?? null, fact: f })),
    ...items.map(
      (item): AchievementRow => ({
        kind: "portfolio",
        key: `portfolio-${item.id}`,
        when: item.created_at ?? null,
        item,
      }),
    ),
  ]
  return rows.sort((a, b) => (parseDate(b.when)?.getTime() ?? 0) - (parseDate(a.when)?.getTime() ?? 0))
}

function AchievementRowView({ row }: { row: AchievementRow }) {
  return row.kind === "portfolio" ? <PortfolioRow item={row.item} /> : <FactRow fact={row.fact} />
}

type FormKind = "debrief" | "offer" | "manual" | null

function ManualAddForm({ onDone }: { onDone: () => void }) {
  const [project, setProject] = useState("")
  const [role, setRole] = useState("")
  const [outcome, setOutcome] = useState("")
  const create = useCreatePortfolioItem()

  return (
    <form
      className="space-y-2 rounded-lg border border-dashed p-3"
      onSubmit={(e) => {
        e.preventDefault()
        if (!project.trim()) return
        create.mutate(
          { project: project.trim(), role: role.trim(), outcome: outcome.trim() },
          { onSuccess: onDone },
        )
      }}
    >
      <div className="flex gap-2">
        <Input
          placeholder="Проект/компания"
          value={project}
          onChange={(e) => setProject(e.target.value)}
          autoFocus
        />
        <Input placeholder="Роль" value={role} onChange={(e) => setRole(e.target.value)} />
      </div>
      <Textarea
        placeholder="Результат: что сделали, какой эффект в цифрах"
        value={outcome}
        onChange={(e) => setOutcome(e.target.value)}
      />
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" size="sm" onClick={onDone}>
          Отмена
        </Button>
        <Button type="submit" size="sm" disabled={!project.trim() || create.isPending}>
          Добавить
        </Button>
      </div>
    </form>
  )
}

function FromDebriefForm({ onDone }: { onDone: () => void }) {
  const { data: jobs } = useJobs()
  const [vacancyId, setVacancyId] = useState<string>("")
  const { data: history } = useDebriefHistory(vacancyId || null)
  const [debriefIdx, setDebriefIdx] = useState<string>("")
  const draft = useDraftPortfolioFromDebrief()
  const job = useMemo(() => (jobs ?? []).find((j) => j.vacancy_id === vacancyId), [jobs, vacancyId])
  const items = history?.items ?? []
  const selected = debriefIdx ? items[Number(debriefIdx)] : undefined

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-dashed p-3">
      <Select
        value={vacancyId}
        onValueChange={(v) => {
          setVacancyId(v)
          setDebriefIdx("")
        }}
      >
        <SelectTrigger className="h-8 w-56">
          <SelectValue placeholder="Вакансия с разбором" />
        </SelectTrigger>
        <SelectContent>
          {(jobs ?? [])
            .filter((j) => j.vacancy_id)
            .map((j) => (
              <SelectItem key={j.vacancy_id} value={j.vacancy_id!}>
                {j.title || j.vacancy_id} · {j.company}
              </SelectItem>
            ))}
        </SelectContent>
      </Select>
      <Select value={debriefIdx} onValueChange={setDebriefIdx}>
        <SelectTrigger className="h-8 w-48" disabled={!items.length}>
          <SelectValue placeholder="Разбор" />
        </SelectTrigger>
        <SelectContent>
          {items.map((d, i) => (
            <SelectItem key={i} value={String(i)}>
              {d.stage_label} · {d.analysis.strong_answers.length} сильных
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button type="button" variant="ghost" size="sm" onClick={onDone}>
        Отмена
      </Button>
      <Button
        type="button"
        size="sm"
        disabled={!selected || draft.isPending}
        onClick={() =>
          selected &&
          draft.mutate(
            {
              vacancy_id: vacancyId,
              company: job?.company ?? "",
              strong_answers: selected.analysis.strong_answers,
              summary: selected.analysis.summary,
              debrief_id: selected.id ?? undefined,
            },
            { onSuccess: onDone },
          )
        }
      >
        Добавить из разбора
      </Button>
    </div>
  )
}

function FromOfferForm({ onDone }: { onDone: () => void }) {
  const { data: offers } = useOffers()
  const [vacancyId, setVacancyId] = useState<string>("")
  const draft = useDraftPortfolioFromOffer()
  const offer = (offers ?? []).find((o) => o.vacancy_id === vacancyId)

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-dashed p-3">
      <Select value={vacancyId} onValueChange={setVacancyId}>
        <SelectTrigger className="h-8 w-56">
          <SelectValue placeholder="Оффер" />
        </SelectTrigger>
        <SelectContent>
          {(offers ?? []).map((o) => (
            <SelectItem key={o.vacancy_id} value={o.vacancy_id}>
              {o.company || o.vacancy_id} · {o.position}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button type="button" variant="ghost" size="sm" onClick={onDone}>
        Отмена
      </Button>
      <Button
        type="button"
        size="sm"
        disabled={!offer || draft.isPending}
        onClick={() =>
          offer &&
          draft.mutate(
            {
              vacancy_id: offer.vacancy_id,
              company: offer.company,
              position: offer.position,
              base_salary: offer.base_salary ?? undefined,
              base_salary_currency: offer.base_salary_currency,
              negotiation_points: (offer.negotiation?.arguments ?? []).map((a) => a.wording),
            },
            { onSuccess: onDone },
          )
        }
      >
        Добавить из оффера
      </Button>
    </div>
  )
}

// Старый вид строки — остаётся только для «остальных» типов факта (ограничения/предпочтения/
// компании/другое): их владелец трогать не просил, поэтому источник + дата снизу и «Поправить»
// на месте, как было до правки 2026-08-26.
function FactCard({ fact }: { fact: CareerFact }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(fact.fact)
  const patch = usePatchFact()
  const remove = useDeleteFact()
  const pinned = fact.expires_at == null

  return (
    <div className="group relative space-y-1.5 rounded-lg border p-3">
      {!editing && (
        <div className="absolute right-2 top-2 flex gap-1 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
          {!pinned && (
            <button
              type="button"
              title="Закрепить"
              onClick={() => patch.mutate({ factId: fact.id!, patch: { pinned: true } })}
              className="rounded-md border bg-white p-1 text-slate-500 hover:bg-slate-50"
            >
              <Pin className="size-3.5" strokeWidth={2} />
            </button>
          )}
          <button
            type="button"
            title="Поправить"
            onClick={() => {
              setDraft(fact.fact)
              setEditing(true)
            }}
            className="rounded-md border bg-white p-1 text-slate-500 hover:bg-slate-50"
          >
            <Pencil className="size-3.5" strokeWidth={2} />
          </button>
          <button
            type="button"
            title="Удалить"
            onClick={() => remove.mutate(fact.id!)}
            className="rounded-md border bg-white p-1 text-slate-500 hover:bg-status-bad-soft hover:text-status-bad-fg"
          >
            <Trash2 className="size-3.5" strokeWidth={2} />
          </button>
        </div>
      )}

      {editing ? (
        <div className="space-y-2 pr-16">
          <Textarea value={draft} onChange={(e) => setDraft(e.target.value)} autoFocus />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" size="sm" onClick={() => setEditing(false)}>
              Отмена
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={!draft.trim() || patch.isPending}
              onClick={() =>
                patch.mutate(
                  { factId: fact.id!, patch: { fact: draft.trim() } },
                  { onSuccess: () => setEditing(false) },
                )
              }
            >
              Сохранить
            </Button>
          </div>
        </div>
      ) : (
        <div className="pr-16">
          <ClampedText
            text={fact.fact}
            className="text-sm text-slate-800"
            threshold={LONG_FACT_THRESHOLD}
          />
        </div>
      )}

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-400">
        <span>{SOURCE_LABEL[fact.source_kind] ?? fact.source_kind}</span>
        {fact.recorded_at && <span>{formatDate(fact.recorded_at)}</span>}
        {pinned && <span className="font-medium text-slate-500">Закреплено</span>}
      </div>
    </div>
  )
}

function FactGroup({ type, items }: { type: string; items: CareerFact[] }) {
  const [expanded, setExpanded] = useState(false)
  const visible = expanded ? items : items.slice(0, GROUP_VISIBLE_LIMIT)

  return (
    <div className="space-y-2">
      <p className="text-xs font-medium text-slate-500">
        <span>{FACT_TYPE_LABEL[type] ?? type}</span>{" "}
        <span className="text-slate-400">({items.length})</span>
      </p>
      <div className="space-y-2">
        {visible.map((f) => (
          <FactCard key={f.id} fact={f} />
        ))}
      </div>
      {items.length > GROUP_VISIBLE_LIMIT ? (
        <Button type="button" variant="ghost" size="sm" onClick={() => setExpanded((v) => !v)}>
          {expanded ? "Свернуть" : `Показать все ${items.length}`}
        </Button>
      ) : null}
    </div>
  )
}

/**
 * Память (правка владельца 2026-08-26 поверх Этапа 4/5): «Заметки» убраны — подблок был лишним.
 * «Достижения» и «Пробелы» стоят двумя колонками; «Достижения» объединяет сильные стороны
 * (факты) и портфолио (было отдельной секцией `AchievementsSection`) в одну ленту по дате —
 * кнопка добавления переехала в шапку колонки и стала просто «Добавить». Остальные типы факта
 * (ограничения/предпочтения/компании/другое) идут ниже старым видом — их не просили менять.
 */
export function FactsMemory() {
  const {
    data: facts,
    isLoading: factsLoading,
    isError: factsError,
    refetch: refetchFacts,
  } = useFacts()
  const {
    data: portfolioItems,
    isLoading: portfolioLoading,
    isError: portfolioError,
    refetch: refetchPortfolio,
  } = usePortfolioItems()
  const [activeForm, setActiveForm] = useState<FormKind>(null)
  const [achievementsExpanded, setAchievementsExpanded] = useState(false)
  const [gapsExpanded, setGapsExpanded] = useState(false)
  const fromResume = useDraftPortfolioFromResume()

  const allFacts = useMemo(() => facts ?? [], [facts])
  const allItems = useMemo(() => portfolioItems ?? [], [portfolioItems])

  const achievementRows = useMemo(() => buildAchievementRows(allFacts, allItems), [allFacts, allItems])
  const gapFacts = useMemo(() => allFacts.filter((f) => f.fact_type === "skill_gap"), [allFacts])
  const remainingGroups = useMemo(() => groupByType(allFacts), [allFacts])

  const activeCount = allFacts.length
  const pinnedCount = useMemo(() => allFacts.filter((f) => f.expires_at == null).length, [allFacts])

  const visibleAchievements = achievementsExpanded
    ? achievementRows
    : achievementRows.slice(0, GROUP_VISIBLE_LIMIT)
  const visibleGaps = gapsExpanded ? gapFacts : gapFacts.slice(0, GROUP_VISIBLE_LIMIT)

  const isLoading = factsLoading || portfolioLoading
  const isError = factsError || portfolioError
  // Не гасим карточку целиком в "empty": кнопка "Добавить" в колонке "Достижения" должна
  // остаться доступной даже когда фактов и портфолио ещё нет вообще — иначе первое
  // достижение неоткуда завести. Пустоту каждая колонка показывает сама (см. ниже).
  const status = isLoading ? "loading" : isError ? "error" : "content"

  return (
    <SectionCard
      title="Память"
      helpId="career.facts"
      status={status}
      meta={
        status === "content" ? (
          <span className="text-xs font-normal text-slate-400">
            · {activeCount} активных{pinnedCount > 0 ? `, ${pinnedCount} закреплены` : ""}
          </span>
        ) : null
      }
      loading={<Skeleton className="h-32 w-full rounded-lg" />}
      error={
        <ErrorState
          compact
          icon={Brain}
          title="Память не загрузилась"
          note="Не удалось получить факты — они на месте, их сейчас не видно."
          action={{
            label: "Повторить",
            onClick: () => {
              void refetchFacts()
              void refetchPortfolio()
            },
          }}
        />
      }
    >
      <div className="space-y-6">
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <div className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="flex items-center gap-1.5 text-base font-semibold text-slate-800">
                Достижения
                <HelpTip id="career.achievements" showIcon />
                <span className="text-sm font-normal text-slate-400">({achievementRows.length})</span>
              </h3>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button type="button" size="sm" variant="outline">
                    <Plus className="size-3.5" strokeWidth={2} />
                    Добавить
                    <ChevronDown className="size-3.5 opacity-60" strokeWidth={2} />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem disabled={fromResume.isPending} onSelect={() => fromResume.mutate()}>
                    <Sparkles className="size-3.5" strokeWidth={2} />
                    Собрать из резюме
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => setActiveForm("debrief")}>Из разбора</DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => setActiveForm("offer")}>Из оффера</DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => setActiveForm("manual")}>Вручную</DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>

            {activeForm === "debrief" && <FromDebriefForm onDone={() => setActiveForm(null)} />}
            {activeForm === "offer" && <FromOfferForm onDone={() => setActiveForm(null)} />}
            {activeForm === "manual" && <ManualAddForm onDone={() => setActiveForm(null)} />}

            {!achievementRows.length ? (
              <EmptyState
                icon={Trophy}
                title="Достижений пока нет"
                note="Соберите через «Добавить» выше — или дождитесь сильного разбора/оффера, они попадут сюда сами."
              />
            ) : (
              <div className="space-y-2">
                {visibleAchievements.map((row) => (
                  <AchievementRowView key={row.key} row={row} />
                ))}
                {achievementRows.length > GROUP_VISIBLE_LIMIT ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => setAchievementsExpanded((v) => !v)}
                  >
                    {achievementsExpanded ? "Свернуть" : `Показать все ${achievementRows.length}`}
                  </Button>
                ) : null}
              </div>
            )}
          </div>

          <div className="space-y-3">
            <h3 className="text-base font-semibold text-slate-800">
              Пробелы <span className="text-sm font-normal text-slate-400">({gapFacts.length})</span>
            </h3>

            {!gapFacts.length ? (
              <EmptyState
                icon={Target}
                title="Пробелов нет"
                note="Появятся после разбора собеседования или диалога в чате."
              />
            ) : (
              <div className="space-y-2">
                {visibleGaps.map((f) => (
                  <FactRow key={f.id} fact={f} />
                ))}
                {gapFacts.length > GROUP_VISIBLE_LIMIT ? (
                  <Button type="button" variant="ghost" size="sm" onClick={() => setGapsExpanded((v) => !v)}>
                    {gapsExpanded ? "Свернуть" : `Показать все ${gapFacts.length}`}
                  </Button>
                ) : null}
              </div>
            )}
          </div>
        </div>

        {remainingGroups.length > 0 ? (
          <div className="space-y-4 border-t pt-4">
            {remainingGroups.map(([type, items]) => (
              <FactGroup key={type} type={type} items={items} />
            ))}
          </div>
        ) : null}
      </div>
    </SectionCard>
  )
}
