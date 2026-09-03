import { useMemo, type ReactNode } from "react"
import { useIsMutating } from "@tanstack/react-query"
import { CheckCheck, ChevronDown, Loader2, RefreshCw } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import type { SkillSuggestionRow } from "@/api/resume"
import { cn } from "@/lib/utils"
import { useDemandOpen } from "./demand-open"
import { SkillRow } from "./SkillRow"
import { selectActionRows } from "./select"
import {
  SKILLS_APPLY_ALL_MUTATION_KEY,
  SKILLS_APPLY_MUTATION_KEY,
  SKILLS_REFRESH_MUTATION_KEY,
  SKILLS_SWAP_MUTATION_KEY,
  useApplyAllSkillActions,
  useApplySkillAction,
  useDemandRefreshProgress,
  useRefreshResumeSkills,
  useResumeSkills,
  useSetSkillUserState,
  useSwapResumeSkill,
} from "./use-skills"

type RefreshProgress = { done: number; total: number; label: string }

// Единый ранжированный список «Спрос»: встаёт на место бывшего
// StackDemandStrip — эхо-механизм «спрос на мои теги» и 254 неактивных чипа корпусного
// словаря сведены в одну таблицу, где «есть у меня» — состояние строки, а не отдельный блок.
// Показывается только блок «Действия»: строки-действия (не «держу») компактными иконками
// «Применить»/«Обменять»/«Скрыть»; готовые строки выглядят как «✓ держу».
// Две копии (секция «Навыки» и спойлер шкалы «Навыки» в балле резюме) делят открытость
// и прогресс обновления — клик в одном месте двигает оба.

function PanelSkeleton() {
  return (
    <div className="space-y-3">
      <Skeleton className="h-4 w-40" />
      <div className="space-y-1.5">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-7" />
        ))}
      </div>
    </div>
  )
}

// Русское склонение «вакансия/вакансии/вакансий» — тот же счёт, что `_plural_vacancies` на
// бэкенде (skills_corpus.py), для строки U-06 «43 вакансии, разрывов нет».
function vacanciesLabel(n: number): string {
  const mod100 = n % 100
  const mod10 = n % 10
  let word: string
  if (mod100 >= 11 && mod100 <= 14) word = "вакансий"
  else if (mod10 === 1) word = "вакансия"
  else if (mod10 >= 2 && mod10 <= 4) word = "вакансии"
  else word = "вакансий"
  return `${n} ${word}`
}

// Из stale_reason «+12 новых вакансий с последнего разбора — …» достаём компактный «+12» —
// полная фраза остаётся в title-подсказке.
function corpusDelta(staleReason: string): string | null {
  const m = staleReason.match(/^\+(\d+)/u)
  return m ? `+${m[1]}` : null
}

// U-06: пока идёт пересборка — прогресс «18 из 43 разобрано», а не скелетон и не тишина.
function ProgressRow({ progress }: { progress: RefreshProgress | null }) {
  return (
    <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
      <Loader2 className="size-3.5 shrink-0 animate-spin" strokeWidth={2} />
      {progress && progress.total > 0 ? (
        <span>
          <span className="tabular-nums font-medium text-foreground">
            {progress.done} из {progress.total}
          </span>{" "}
          разобрано
          {progress.label ? (
            <span className="text-muted-foreground/70"> · {progress.label}</span>
          ) : null}
        </span>
      ) : (
        <span>Собираю снимок навыков…</span>
      )}
    </p>
  )
}

function DemandHeading({
  open,
  onToggle,
  extra,
}: {
  open: boolean
  onToggle: () => void
  extra?: ReactNode
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="inline-flex min-w-0 items-center gap-1.5 text-left hover:text-slate-900"
      >
        <ChevronDown
          className={cn(
            "size-3.5 shrink-0 text-slate-400 transition-transform duration-200",
            !open && "-rotate-90",
          )}
          strokeWidth={2}
        />
        <h3 className="text-sm font-semibold text-foreground">Спрос</h3>
      </button>
      {open ? extra : null}
    </div>
  )
}

export function SkillsPanel() {
  const { data: panel, isLoading } = useResumeSkills()
  const [open, setOpen] = useDemandOpen()
  const progress = useDemandRefreshProgress()
  const refresh = useRefreshResumeSkills()
  const setUserState = useSetSkillUserState()
  const swapSkill = useSwapResumeSkill()
  const applyAction = useApplySkillAction()
  const applyAll = useApplyAllSkillActions()
  const refreshPending = useIsMutating({ mutationKey: [...SKILLS_REFRESH_MUTATION_KEY] }) > 0
  const applyPending = useIsMutating({ mutationKey: [...SKILLS_APPLY_MUTATION_KEY] }) > 0
  const applyAllPending = useIsMutating({ mutationKey: [...SKILLS_APPLY_ALL_MUTATION_KEY] }) > 0
  const swapPending = useIsMutating({ mutationKey: [...SKILLS_SWAP_MUTATION_KEY] }) > 0

  function runRefresh() {
    refresh.mutate()
  }

  const rows = useMemo(() => panel?.rows ?? [], [panel])
  const isFull = panel ? panel.slots_used >= panel.slots_limit : false

  // U-04 / Решение 7: при заполненных слотах каждой add-строке ставится в пару свой
  // «слабейший» drop из этого же снимка — drop не предлагается на обмен дважды. Порядок строк
  // приходит уже отсортированным по спросу с бэка (`load_latest_snapshot`), так что зип по
  // порядку — это и есть «слабейший свободный».
  const swapPairs = useMemo(() => {
    const pairs = new Map<string, SkillSuggestionRow>()
    if (!isFull) return pairs
    // U-05: уже применённый drop (`user_state === "accepted"`) слот освободил — второй раз
    // в пару не предлагаем, до пересборки снимка это единственный источник правды.
    const pool = rows.filter((r) => r.state === "drop" && r.user_state !== "accepted")
    let i = 0
    for (const row of rows) {
      if (row.state !== "add") continue
      const drop = pool[i]
      if (drop) pairs.set(row.skill, drop)
      i += 1
    }
    return pairs
  }, [rows, isFull])

  // При 30/30 без единого drop в снимке add-строки не показываются вовсе (Решение 7) —
  // вместо ленты неактивных «Добавить» одна строка «слотов нет».
  const noSwapSlots =
    isFull &&
    !rows.some((r) => r.state === "drop" && r.user_state !== "accepted") &&
    rows.some((r) => r.state === "add")

  // Показываем только «Действия»: строки, которые требуют решения (add/drop/rename).
  const actionRows = useMemo(() => selectActionRows(panel), [panel])

  const hide = (skill: string) => setUserState.mutate({ skill, user_state: "hidden" })
  const show = (skill: string) => setUserState.mutate({ skill, user_state: "pending" })
  const swap = (add: string, drop: string) => swapSkill.mutate({ add, drop })
  const apply = (row: SkillSuggestionRow) => applyAction.mutate(row)
  const applyAllActions = () => {
    const pending = actionRows.filter((r) => r.user_state !== "accepted")
    if (pending.length === 0) return
    applyAll.mutate(pending)
  }

  const toggle = () => setOpen((v) => !v)

  if (isLoading) return <PanelSkeleton />

  if (!panel || rows.length === 0) {
    // U-06: «нет выборки» (расширение ещё не оценило ни одной вакансии) и «выборка есть, но
    // снимок ни разу не собран» — два разных сообщения и разное наличие кнопки: пересобирать
    // нечего, пока выборка пуста.
    const noSelection = (panel?.corpus_size ?? 0) === 0
    const noSnapshotYet = !noSelection && !panel?.created_at
    return (
      <div className="space-y-2">
        <DemandHeading open={open} onToggle={toggle} />
        {open && (
          <>
            <p className="text-sm text-muted-foreground">
              {noSelection
                ? "Оцените вакансии расширением — соберу разбор по ним"
                : noSnapshotYet
                  ? "Разбор ещё не собран"
                  : `${vacanciesLabel(panel?.corpus_size ?? 0)}, разрывов нет`}
            </p>
            {panel && <p className="text-xs text-muted-foreground">{panel.selection_rule}</p>}
            {refreshPending ? (
              <ProgressRow progress={progress} />
            ) : (
              noSnapshotYet && (
                <Button type="button" variant="secondary" size="sm" onClick={runRefresh}>
                  <RefreshCw strokeWidth={2} />
                  Пересобрать
                </Button>
              )
            )}
          </>
        )}
      </div>
    )
  }

  const delta = panel.stale_reason ? corpusDelta(panel.stale_reason) : null

  return (
    <div className="space-y-2.5">
      <DemandHeading
        open={open}
        onToggle={toggle}
        extra={
          <div className="flex items-center gap-2">
            <span
              className="text-xs tabular-nums text-muted-foreground"
              title={panel.stale_reason || `Корпус: ${vacanciesLabel(panel.corpus_size)}`}
            >
              {delta ?? panel.corpus_size}
            </span>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={refreshPending}
              onClick={runRefresh}
              className="h-7 px-2 text-xs"
              aria-label="Пересобрать снимок навыков"
              title={panel.stale_reason || "Пересобрать снимок навыков"}
            >
              {refreshPending ? (
                <Loader2 className="size-3 animate-spin" strokeWidth={2} />
              ) : (
                <RefreshCw className="size-3" strokeWidth={2} />
              )}
              Обновить
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={
                applyAllPending || actionRows.filter((r) => r.user_state !== "accepted").length === 0
              }
              onClick={applyAllActions}
              className="h-7 px-2 text-xs"
              aria-label="Применить все действия по навыкам"
              title="Добавить/убрать/переименовать все предложенные навыки разом"
            >
              {applyAllPending ? (
                <Loader2 className="size-3 animate-spin" strokeWidth={2} />
              ) : (
                <CheckCheck className="size-3" strokeWidth={2} />
              )}
              Применить все
            </Button>
          </div>
        }
      />

      {open && (
        <>
          {refreshPending && <ProgressRow progress={progress} />}

          {noSwapSlots && (
            <p className="text-xs text-muted-foreground">
              Слотов нет — все {panel.slots_limit} тегов востребованы
            </p>
          )}

          {/* Действий нет → сообщение об этом (U-06). Добавленные/скрытые строки-действия при
              пересборке снимка уходят из списка, так что «разрывов нет» — честный статус. */}
          {!noSwapSlots && actionRows.length === 0 && (
            <p className="text-xs text-muted-foreground">
              {vacanciesLabel(panel.corpus_size)}, разрывов нет
            </p>
          )}

          <div>
            {actionRows.map((row) => (
              <SkillRow
                key={row.skill}
                row={row}
                onHide={hide}
                onShow={show}
                swapDrop={row.state === "add" ? swapPairs.get(row.skill) : undefined}
                onSwap={swap}
                swapPending={swapPending}
                onApply={apply}
                applyPending={applyPending}
              />
            ))}
            {actionRows.length === 0 && (
              <p className="py-2 text-sm text-muted-foreground">Действий нет.</p>
            )}
          </div>
        </>
      )}
    </div>
  )
}
