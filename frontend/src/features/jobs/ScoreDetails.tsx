import { useState, type ReactNode } from "react"
import { Loader2, RefreshCw, TriangleAlert } from "lucide-react"
import type { Job } from "@/api/jobs"
import { cn } from "@/lib/utils"
import { splitHighlight } from "../../../../shared/highlight"
import type { CriterionTone } from "../../../../shared/criteria"
import { isSecondJobScoreBreakdown } from "../../../../shared/criteria"
import { gradeFactCard } from "../../../../shared/fact-cards"
import { parseScoreGate } from "../../../../shared/score-breakdown"
import { HelpTip } from "@/components/ui/help-tip"
import { SectionTitle } from "@/components/ui/section-title"
import { type StatusTone } from "@/components/ui/status-chip"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import {
  formatConflictOf,
  type RemoteFeasibilityView,
  type ResolvedJobSalary,
  scoreBreakdownRows,
} from "./funnel"
import { useCurrentWeightsVersion, useRecomputeWeights } from "./use-recompute-weights"
import { useScoringWeights } from "@/features/settings/use-settings"

// Вынесено из JobDetailDrawer.tsx (Расширение — ховер-превью, Фаза A): второй потребитель этих
// компонентов — VacancyHoverPreview (мини-дровер в очередях «Расширения»), не дублировать вёрстку.

// Тон текста по StatusTone (D-04) — тот же словарь, что красит чипы (StatusChip), для значений
// карточек фактов, у которых тон приходит уже как StatusTone (формат) или сведён к нему
// (грейд — через CRITERION_TO_STATUS_TONE ниже, значение приходит уже как CriterionTone из
// shared/fact-cards::gradeFactCard).
const STATUS_TEXT_CLASS: Record<StatusTone, string> = {
  strong: "text-status-strong-fg",
  good: "text-status-good-fg",
  warn: "text-status-warn-fg",
  bad: "text-status-bad-fg",
  info: "text-status-info-fg",
}
// Сведение нейтральной классификации good/mid/bad/neutral (shared/criteria, E-02) к StatusTone —
// то же соответствие, что в funnel.ts (CRITERION_TO_STATUS_TONE), нужно и здесь для тона текста
// значения карточки «Грейд».
const CRITERION_TO_STATUS_TONE: Record<CriterionTone, StatusTone> = {
  good: "good",
  mid: "warn",
  bad: "bad",
  neutral: "info",
}

// Шкала критериев «Почему N» — своя, локальная для этого бара палитра (унификация с
// расширением, U-06): интуитивные зелёный/жёлтый/красный вместо синего/фиолетового StatusTone.
// «strong» здесь больше ни для чего не занят — переиспользуем его (уже зелёный в globals.css)
// вместо заведения нового токена; «info» (нейтрально) — просто серый, не про хорошо/плохо.
// Глобальные --status-good-dot/-info-dot не трогаем — они общие с другими чипами приложения.
const BREAKDOWN_TONE_DOT: Record<StatusTone, string> = {
  strong: "bg-status-strong-dot",
  good: "bg-status-strong-dot",
  warn: "bg-status-warn-dot",
  bad: "bg-status-bad-dot",
  info: "bg-slate-300",
}
const BREAKDOWN_TONE_TEXT: Record<StatusTone, string> = {
  strong: "text-status-strong-fg",
  good: "text-status-strong-fg",
  warn: "text-status-warn-fg",
  bad: "text-status-bad-fg",
  info: "text-slate-500",
}

// V-03: карточка факта — значение + подпись, рендерится всегда (пустое значение — «—», а не
// исчезнувшая карточка: ряд не должен разваливаться на вакансии без зарплаты/формата/грейда).
function FactCard({
  label,
  value,
  caption,
  tone,
  title,
  action,
  onClick,
  expanded,
}: {
  label: string
  value: string
  caption: string
  tone?: string
  title?: string
  action?: ReactNode
  onClick?: () => void
  expanded?: boolean
}) {
  const body = (
    <>
      <div className="flex items-center justify-between gap-1">
        <p className="text-xs font-medium uppercase tracking-wider text-slate-500">{label}</p>
        {action}
      </div>
      <p className={cn("mt-0.5 truncate text-sm font-medium text-slate-900", tone)}>{value}</p>
      <p className="mt-0.5 line-clamp-2 text-xs text-slate-500">{caption}</p>
    </>
  )
  const cls = cn(
    "rounded-lg bg-slate-50 p-2.5",
    onClick && "text-left hover:bg-slate-100",
    expanded && "ring-1 ring-slate-300",
  )
  if (onClick) {
    return (
      <button
        type="button"
        onClick={onClick}
        title={title}
        aria-expanded={expanded}
        className={cls}
      >
        {body}
      </button>
    )
  }
  return (
    <div className={cls} title={title}>
      {body}
    </div>
  )
}

// Ряд карточек фактов (V-03): Зарплата · Формат · Грейд — заменяет прежние четыре поверхности
// (строка зарплаты + чип формата + плитка «Грейд» + плитка «Управление»). Первый экран вкладки
// «Решение»; разбор балла встанет следующей строкой (V-04).
export function FactCards({
  s,
  salaryValue,
  salary,
  salaryProvenance,
  formatChip,
  remoteChip,
  remote,
  salaryAction,
  formatOpen,
  onFormatClick,
}: {
  s: Job["score"]
  salaryValue: string
  salary: ResolvedJobSalary
  salaryProvenance: string | null
  formatChip: { label: string; tone: StatusTone } | null | undefined
  remoteChip: { label: string; short: string; tone: StatusTone } | undefined
  remote: RemoteFeasibilityView | undefined
  salaryAction?: ReactNode
  formatOpen?: boolean
  onFormatClick?: () => void
}) {
  const salaryTone =
    salary.text === "оценка…"
      ? "text-slate-400"
      : salary.meetsMin === true
        ? "text-emerald-700"
        : "text-slate-800"
  // Подпись — вердикт по порогу/оценке; провенанс («по резюме»/«по HR» и т.п.) уходит в подпись
  // только когда вердикта нет, иначе — в тултип карточки (было отдельной строкой шапки).
  const salaryCaption =
    salary.meetsMin === true
      ? "выше цели"
      : salary.meetsMin === false
        ? "ниже цели"
        : salary.isEstimate
          ? "оценка"
          : (salaryProvenance ?? "—")

  const gradeCard = s ? gradeFactCard(s) : null
  // V-05: заявленный формат хвалит вакансию, но по тексту это вряд ли/условно так — карточка
  // красится по вердикту реальности, а подпись — короткий вердикт (не цитата из JD).
  const conflict = formatConflictOf(formatChip, remote)
  const formatCaption =
    conflict?.caption ??
    (remote?.note && remote.note.length <= 42 ? remote.note : remoteChip?.short) ??
    "—"
  const contra = remote?.signals?.find((sig) => sig.polarity === "contra")

  return (
    <div className="grid grid-cols-3 gap-2">
      <FactCard
        label="Зарплата"
        value={salaryValue}
        caption={salaryCaption}
        tone={cn(salaryTone, "font-semibold")}
        title={salaryProvenance ?? undefined}
        action={salaryAction}
      />
      <FactCard
        label="Формат"
        value={formatChip?.label ?? "—"}
        caption={formatCaption}
        tone={
          conflict
            ? STATUS_TEXT_CLASS[conflict.tone]
            : formatChip
              ? STATUS_TEXT_CLASS[formatChip.tone]
              : undefined
        }
        title={
          conflict
            ? contra?.text
              ? `В тексте: ${contra.text}`
              : "Заявлен формат, но по тексту вакансии это под вопросом"
            : remote?.note && remote.note.length > 42
              ? remote.note
              : "Показать сигналы формата"
        }
        onClick={onFormatClick}
        expanded={formatOpen}
      />
      <FactCard
        label="Грейд"
        value={gradeCard?.value ?? "—"}
        caption={gradeCard?.caption ?? "—"}
        tone={gradeCard ? STATUS_TEXT_CLASS[CRITERION_TO_STATUS_TONE[gradeCard.tone]] : undefined}
        title={gradeCard?.title}
      />
    </div>
  )
}

// Слово-подпись строки разбора (Формат/Грейд/…): при наличии `reasoning` наводится
// стилизованной подсказкой (белый текст на тёмном фоне) вместо нативного title браузера.
function ScoreBreakdownLabel({ label, reasoning }: { label: string; reasoning?: string | null }) {
  if (!reasoning) {
    return <span className="w-20 shrink-0 truncate text-slate-500">{label}</span>
  }
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="w-20 shrink-0 cursor-help truncate text-slate-500 underline decoration-dotted decoration-slate-300 underline-offset-2">
          {label}
        </span>
      </TooltipTrigger>
      <TooltipContent variant="dark" side="top" align="start">
        {reasoning}
      </TooltipContent>
    </Tooltip>
  )
}

// V-04: разбор балла «Почему N» — первый экран вкладки «Решение» после карточек фактов. Шесть
// подписанных строк (мини-полоса значение/максимум + число) в сетке 2×3 — компактнее прежнего
// столбца из шести строк; тот же цвет good/mid/bad, что красит карточки фактов и панель
// расширения (Решение 3). Легаси-запись (score_breakdown пуст или в старой пятиключевой форме,
// см. план раздел 0) не рендерит полосу вовсе — заведомо не сходящаяся сумма читалась бы как
// баг, а не как факт формата данных.
// Этап 5 §5.3 (plans/scoring_precision_2026_08_17.md): веса пересчитываются от резюме на каждом
// скоринге — если резюме правили ПОСЛЕ того, как эта вакансия была оценена, `s.weights_version`
// отстал от текущей рубрики. Пересчёт без LLM — та же гарантия, что у Этапа 5.2.
function WeightsStaleBadge({
  vacancyId,
  weightsVersion,
  secondJob,
}: {
  vacancyId: string | null | undefined
  weightsVersion: string
  secondJob?: boolean
}) {
  const { data: current } = useCurrentWeightsVersion()
  const recompute = useRecomputeWeights()
  const expected = secondJob ? current?.second_job_weights_version : current?.weights_version
  if (!vacancyId || !weightsVersion || !expected) return null
  if (expected === weightsVersion) return null

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          onClick={() => recompute.mutate(vacancyId)}
          disabled={recompute.isPending}
          className="ml-auto inline-flex shrink-0 items-center gap-1 rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-xs font-medium normal-case tracking-normal text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {recompute.isPending ? (
            <Loader2 className="size-3 shrink-0 animate-spin" strokeWidth={2} />
          ) : (
            <RefreshCw className="size-3 shrink-0" strokeWidth={2} />
          )}
          Рубрика обновилась
        </button>
      </TooltipTrigger>
      <TooltipContent variant="dark" side="top">
        Веса скоринга изменились с тех пор, как посчитан этот балл — пересчитать без LLM
      </TooltipContent>
    </Tooltip>
  )
}

export function ScoreBreakdown({
  s,
  vacancyId,
  hideScale,
}: {
  s: Job["score"]
  vacancyId: string | null | undefined
  /** Пункт 7 редизайна «Расширения» (2026-08-19): в ховер-превью (узкий попап) цветовые полосы
   * сжимаются некрасиво и не несут больше смысла, чем сами цифры «X / Y» — скрываем полосу,
   * оставляем только подписанные критерии с баллом. Полный дровер вакансии полосу показывает
   * как раньше. */
  hideScale?: boolean
}) {
  const weights = useScoringWeights()
  if (!s) return null
  const rows = scoreBreakdownRows(s, weights)
  if (!rows) {
    return (
      <p className="text-sm text-slate-400">
        Разбор недоступен — вакансия скорена до перехода на новый формат.
      </p>
    )
  }
  // Барьер (гейт), если сыграл — иконка-«!» прямо у фактора-виновника вместо отдельного
  // текстового лейбла «Калибровка +N» / «Балл срезан: …» (унификация с расширением, U-06).
  const gate = s.gate_triggered ? parseScoreGate(s.gate_triggered) : null

  return (
    <div className="space-y-2">
      <TooltipProvider delayDuration={150} skipDelayDuration={0}>
        <div className="flex items-center gap-2">
          <SectionTitle>Почему {s.overall_score}</SectionTitle>
          <WeightsStaleBadge
            vacancyId={vacancyId}
            weightsVersion={s.weights_version ?? ""}
            secondJob={isSecondJobScoreBreakdown(s.score_breakdown)}
          />
        </div>
        <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
          {rows.map((r) => {
            const pct = Math.max(4, Math.min(100, Math.round((Math.max(0, r.value) / r.max) * 100)))
            const isGate = gate?.key === r.key
            return (
              <div
                key={r.key}
                className={cn("flex items-center gap-2 text-sm", hideScale && "justify-between")}
              >
                <ScoreBreakdownLabel label={r.label} reasoning={r.reasoning} />
                {isGate && gate && (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <TriangleAlert
                        className="size-3.5 shrink-0 cursor-help text-status-warn-fg"
                        strokeWidth={2}
                      />
                    </TooltipTrigger>
                    <TooltipContent variant="dark" side="top">
                      Барьер: {gate.label}
                    </TooltipContent>
                  </Tooltip>
                )}
                {!hideScale && (
                  <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100">
                    <span
                      className={cn("block h-full rounded-full", BREAKDOWN_TONE_DOT[r.tone])}
                      style={{ width: `${pct}%` }}
                    />
                  </span>
                )}
                <span
                  className={cn(
                    "w-16 shrink-0 text-right tabular-nums",
                    BREAKDOWN_TONE_TEXT[r.tone],
                  )}
                >
                  {r.value} / {r.max}
                </span>
              </div>
            )
          })}
        </div>
      </TooltipProvider>
    </div>
  )
}

// Список плюсов/минусов/флагов с цветной точкой-маркером. Суть пункта — жирным до тире
// (`splitHighlight`, общий с панелью расширения — Решение 3: один способ выделять суть).
// Всегда весь список — прятать хвост за «Ещё N» вынуждает лишний клик ради того, что и так
// можно проскроллить (UX-разбор дровера).
export function BulletList({ items, tone }: { items: string[]; tone: string }) {
  return (
    <ul className="space-y-1.5">
      {items.map((it, i) => {
        const { bold, rest } = splitHighlight(it)
        return (
          <li key={i} className="flex gap-2 text-sm text-slate-700">
            <span className={cn("mt-1.5 size-1.5 shrink-0 rounded-full", tone)} />
            <span>
              <strong className="font-semibold text-slate-900">{bold}</strong>
              {rest}
            </span>
          </li>
        )
      })}
    </ul>
  )
}

// Пояснение формата под рядом карточек: без заголовка и без внутреннего балла (он дублирует
// ось «Формат» в «Почему N» и не отвечает на вопрос «удалёнка ли это»). Клик по цитате
// подсвечивает место в тексте вакансии, если обработчик передан.
function FormatSignals({
  remote,
  activeQuote,
  onRevealQuote,
}: {
  remote: RemoteFeasibilityView | undefined
  activeQuote: string | null
  onRevealQuote?: (quote: string) => void
}) {
  if (!remote) {
    return <p className="text-sm text-slate-400">Сигналов по формату в тексте нет.</p>
  }
  return (
    <div className="space-y-2 rounded-lg bg-slate-50 p-2.5">
      {remote.note && <p className="text-sm text-slate-700">{remote.note}</p>}
      {remote.signals?.length ? (
        <ul className="space-y-1">
          {remote.signals.map((sig, i) => (
            <li key={i}>
              <button
                type="button"
                onClick={() => onRevealQuote?.(sig.text)}
                title={onRevealQuote ? "Показать в тексте вакансии" : undefined}
                className={cn(
                  "flex w-full items-start gap-2 rounded-md px-1 py-0.5 text-left text-sm text-slate-700 transition-colors hover:bg-white",
                  activeQuote === sig.text && "bg-white ring-1 ring-amber-300",
                )}
              >
                <span
                  className={cn(
                    "mt-1.5 size-1.5 shrink-0 rounded-full",
                    sig.polarity === "pro" ? "bg-emerald-500" : "bg-rose-500",
                  )}
                />
                <span className="min-w-0">{sig.text}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : (
        !remote.note && <p className="text-sm text-slate-400">Сигналов по формату в тексте нет.</p>
      )}
    </div>
  )
}

// V-04/V-03 в сборе: карточки фактов → разбор балла → бриф → плюсы/красные флаги/минусы. Первый
// экран вкладки «Решение» дровера; тот же состав рендерит VacancyHoverPreview (мини-дровер в
// очередях «Расширения», Фаза A/C редизайна) — переиспользуем композицию, а не собираем заново.
export function TabDecision({
  s,
  vacancyId,
  salaryValue,
  salary,
  formatChip,
  salaryProvenance,
  remote,
  remoteChip,
  salaryAction,
  hideScale,
  formatOpen: formatOpenProp,
  onFormatOpenChange,
  activeQuote = null,
  onRevealQuote,
}: {
  s: Job["score"]
  vacancyId: string | null | undefined
  salaryValue: string
  salary: ResolvedJobSalary
  formatChip: { label: string; tone: StatusTone } | null | undefined
  salaryProvenance: string | null
  remote: RemoteFeasibilityView | undefined
  remoteChip: { label: string; short: string; tone: StatusTone } | undefined
  salaryAction?: ReactNode
  /** Пункт 7 редизайна «Расширения» — см. `ScoreBreakdown`. */
  hideScale?: boolean
  formatOpen?: boolean
  onFormatOpenChange?: (open: boolean) => void
  activeQuote?: string | null
  onRevealQuote?: (quote: string) => void
}) {
  const [localFormatOpen, setLocalFormatOpen] = useState(false)
  const formatOpen = formatOpenProp ?? localFormatOpen
  const setFormatOpen = onFormatOpenChange ?? setLocalFormatOpen
  return (
    <>
      <FactCards
        s={s}
        salaryValue={salaryValue}
        salary={salary}
        salaryProvenance={salaryProvenance}
        formatChip={formatChip}
        remoteChip={remoteChip}
        remote={remote}
        salaryAction={salaryAction}
        formatOpen={formatOpen}
        onFormatClick={() => setFormatOpen(!formatOpen)}
      />
      {formatOpen && (
        <FormatSignals remote={remote} activeQuote={activeQuote} onRevealQuote={onRevealQuote} />
      )}

      <ScoreBreakdown s={s} vacancyId={vacancyId} hideScale={hideScale} />

      {s && s.one_line_verdict && (
        <div className="flex items-start gap-1.5 rounded-lg border border-slate-200 bg-slate-50 p-2.5">
          <p className="min-w-0 flex-1 text-sm text-slate-800">{s.one_line_verdict}</p>
          <HelpTip id="jobs.drawer-brief" side="left" className="mt-0.5" />
        </div>
      )}

      {/* Плюсы / красные флаги / минусы (V-06: флаги — выше минусов, тот же порядок, что в
          панели расширения, Решение 3). Все сразу, без «ещё N» — списки короткие, а хвост
          проще проскроллить, чем кликать разворот каждый раз. */}
      {s && s.pros.length > 0 && (
        <div className="space-y-2">
          <SectionTitle>Плюсы</SectionTitle>
          <BulletList items={s.pros} tone="bg-emerald-500" />
        </div>
      )}
      {s && s.red_flags.length > 0 && (
        <div className="space-y-2">
          <SectionTitle>Красные флаги</SectionTitle>
          <BulletList items={s.red_flags} tone="bg-rose-500" />
        </div>
      )}
      {s && s.cons.length > 0 && (
        <div className="space-y-2">
          <SectionTitle>Минусы</SectionTitle>
          <BulletList items={s.cons} tone="bg-amber-500" />
        </div>
      )}
    </>
  )
}
