import { useMemo, useState } from "react"
import { ChevronDown, LineChart, Loader2, Sparkles } from "lucide-react"
import type { Job } from "@/api/jobs"
import type { PrepTopicOut } from "@/api/prep"
import type { DebriefResult } from "@/api/debrief"
import { Button } from "@/components/ui/button"
import { EmptyState } from "@/components/ui/empty-state"
import { SkeletonCard } from "@/components/ui/skeleton"
import { StatusChip, StatusDot } from "@/components/ui/status-chip"
import { MarkdownView } from "@/components/markdown-view"
import { cn } from "@/lib/utils"
import { formatElapsedMs, useElapsedMs } from "@/lib/use-elapsed-ms"
import { MASTERY_LABEL, MASTERY_TONE } from "./mastery"
import { useDebriefHistory } from "./use-debrief"
import { useExpandPrepTopic, useGeneratePrepTopics, usePrepTopics } from "./use-prep"

const LEVEL_RANK = { weak: 0, medium: 1, confident: 2 } as const

function TopicRow({ topic }: { topic: PrepTopicOut }) {
  return (
    <div className="flex items-center gap-3 rounded-lg border bg-white p-3">
      <StatusDot tone={MASTERY_TONE[topic.level]} className="size-2.5" />
      <p className="min-w-0 flex-1 truncate text-sm font-medium text-slate-900">{topic.topic}</p>
      <span className="shrink-0 text-xs tabular-nums text-slate-400">
        {topic.packs_reviewed} пач.
      </span>
      <StatusChip tone={MASTERY_TONE[topic.level]} className="shrink-0 rounded-full text-xs">
        {MASTERY_LABEL[topic.level]}
      </StatusChip>
    </div>
  )
}

function ProgressSkeleton() {
  return (
    <div className="space-y-2">
      {[0, 1, 2, 3].map((i) => (
        <SkeletonCard key={i} className="h-12" />
      ))}
    </div>
  )
}

// П.5c: одна тема из разбора реального собеса — кликабельная. По клику запускает basic-tier
// LLM-раскрытие (useExpandPrepTopic): что входит в тему, как обычно отвечают.
// Результат кэшируется на 5 мин, повторный клик не бьёт в LLM.
function DebriefTopicRow({
  topic,
  level,
  evidence,
  vacancyId,
  stage,
}: {
  topic: string
  level: "weak" | "medium" | "confident"
  evidence?: string | null
  vacancyId: string | null
  stage: string
}) {
  const [open, setOpen] = useState(false)
  const expand = useExpandPrepTopic(vacancyId, stage, open ? topic : null)

  return (
    <div className="rounded-lg border bg-white">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-start gap-2.5 p-3 text-left"
      >
        <StatusDot tone={MASTERY_TONE[level]} className="mt-1.5 shrink-0" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-slate-900">
            {topic}
            <span className="ml-2 text-xs font-normal text-slate-400">
              {MASTERY_LABEL[level]}
            </span>
          </p>
          {evidence && <p className="mt-0.5 text-sm text-slate-500">{evidence}</p>}
        </div>
        <ChevronDown
          className={cn(
            "mt-1 size-4 shrink-0 text-slate-400 transition-transform",
            open && "rotate-180",
          )}
          strokeWidth={2}
        />
      </button>
      {open && (
        <div className="border-t px-3 py-2.5">
          {expand.isLoading ? (
            <div className="flex items-center gap-2 py-2 text-sm text-slate-500">
              <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />
              Раскрываю тему…
            </div>
          ) : expand.isError ? (
            <p className="py-2 text-sm text-rose-600">
              {expand.error instanceof Error
                ? expand.error.message
                : "Не удалось раскрыть тему"}
            </p>
          ) : expand.data?.markdown ? (
            <MarkdownView markdown={expand.data.markdown} />
          ) : null}
        </div>
      )}
    </div>
  )
}

// Карта компетенций из последнего реального разбора собеса этого этапа — владение темами по
// ответам на собесе, а не по заготовкам (в разборе, не в «Подготовке»). Показываем только если
// расшифровка реального собеса вставлена (debrief для этого этапа есть).
function DebriefInsights({
  debrief,
  vacancyId,
  stage,
}: {
  debrief: DebriefResult | null
  vacancyId: string | null
  stage: string
}) {
  const competency = debrief?.analysis.competency_map ?? []
  const discussed = (debrief?.analysis.topics_to_study ?? [])
    .map((t) => t.trim())
    .filter(Boolean)

  if (!debrief || (competency.length === 0 && discussed.length === 0)) return null

  return (
    <section className="space-y-3">
      {competency.length > 0 && (
        <div className="space-y-2">
          {competency.map((c, i) => (
            <DebriefTopicRow
              key={`${c.topic}-${i}`}
              topic={c.topic}
              level={c.level}
              evidence={c.evidence}
              vacancyId={vacancyId}
              stage={stage}
            />
          ))}
        </div>
      )}

      {discussed.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {discussed.map((t, i) => (
            <DebriefTopicRow
              key={`discussed-${t}-${i}`}
              topic={t}
              level="weak"
              vacancyId={vacancyId}
              stage={stage}
            />
          ))}
        </div>
      )}
    </section>
  )
}

/** «Прогресс» под выбранную вакансию: готовность по темам (слабые сверху) + карта компетенций и
 * темы реального собеса (из разбора), если расшифровка была вставлена. */
export function ProgressPanel({
  job,
  stage,
  stageChosen,
}: {
  job: Job | null
  stage: string
  stageChosen: boolean
}) {
  const vacancyId = job?.vacancy_id ?? null
  // UX9: HR-скрининг в Техичках — внутренний флаг stage="hr_screening", но бэкенд prep-тем
  // оперирует PrepStage, где HR-скрининг это "screening". Нормализуем stage для запросов тем и
  // поиска разбора (в БД хранится под stage="screening"), чтобы карта компетенций из реального
  // разбора скрининга показывалась в «Прогрессе» для HR-скрининга как для любого тех. этапа.
  const isHrScreening = stage === "hr_screening"
  const genStage = isHrScreening ? "screening" : stage
  const { data, isLoading } = usePrepTopics(vacancyId, genStage)
  const generate = useGeneratePrepTopics(vacancyId, genStage)
  const generating = generate.isPending
  const elapsedMs = useElapsedMs(generating)

  // Последний разбор собеса именно этого этапа — карта компетенций и темы, которые обсуждали,
  // показываются только если владелец вставил расшифровку реального собеса. Для HR-скрининга
  // разбор в БД под stage="screening" — ищем по нормализованному genStage.
  const { data: debriefHistory } = useDebriefHistory(vacancyId)
  const stageDebrief = useMemo(() => {
    const items = debriefHistory?.items ?? []
    return items.find((d) => d.stage === genStage) ?? null
  }, [debriefHistory, genStage])

  if (!job) {
    return (
      <EmptyState
        icon={LineChart}
        title="Выберите вакансию"
        note="Прогресс по темам считается под конкретную вакансию — сначала выберите карточку сверху."
        action={{ label: "К воронке", to: "/jobs" }}
      />
    )
  }

  if (!stageChosen) {
    // Действие уже под рукой на этом же экране (кнопка формата в шапке), а не за роутом или
    // колбэком — кнопки нет намеренно (D-09: описательная подсказка, не самостоятельное состояние).
    return (
      <EmptyState
        icon={LineChart}
        title="Выберите формат собеса"
        note="Кнопка формата — в шапке рядом с режимами. Темы подготовки зависят от этапа."
      />
    )
  }

  if (isLoading) {
    return (
      <div className="space-y-6 p-6">
        <ProgressSkeleton />
      </div>
    )
  }

  const items = [...(data?.items ?? [])].sort(
    (a, b) => LEVEL_RANK[a.level] - LEVEL_RANK[b.level] || a.topic.localeCompare(b.topic, "ru"),
  )
  const hasRealDebrief = Boolean(stageDebrief)

  function runGenerate(force = false) {
    if (!job) return
    const hasScore = job.score && Object.keys(job.score).length > 0
    generate.mutate({
      stage: genStage as never,
      vacancy_text: job.vacancy_text,
      title: job.title,
      company: job.company,
      salary_text: job.salary_text,
      score: hasScore ? (job.score as never) : null,
      force,
    })
  }

  return (
    <div className="space-y-6 p-6">
      <section className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-xs font-medium uppercase tracking-wider text-slate-500">
            Темы
          </h2>
          {/* П.5c: после реального разбора мок-темы теряют смысл — генерацию всё равно держим
              под рукой (мок-темы могут пригодиться для следующего этапа), но рендерим реальные. */}
          {!hasRealDebrief && (
            <Button
              size="sm"
              variant="outline"
              className="gap-1.5"
              disabled={generate.isPending}
              onClick={() => runGenerate(items.length > 0)}
            >
              {generate.isPending ? (
                <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />
              ) : (
                <Sparkles className="size-3.5" strokeWidth={2} />
              )}
              {items.length > 0 ? "Обновить темы" : "Собрать темы"}
            </Button>
          )}
        </div>
        {!hasRealDebrief && (
          <p className="text-sm text-slate-500">
            Слабые темы сверху. Уровень растёт, когда открываешь ответы в пачках вопросов (обычно
            ~2 пачки на ступень).
          </p>
        )}
        {/* P-14: честный прогресс вместо голого спиннера в кнопке — генерация тем на advanced-тире
            может занять больше минуты (budget_ms=120000, LlmFeature "prep"). */}
        {!hasRealDebrief && generating && (
          <div className="flex items-center justify-between gap-3 rounded-lg border border-sky-200/80 bg-sky-50/60 px-4 py-2.5">
            <p className="text-sm text-sky-800">Собираю темы под вакансию…</p>
            <p className="text-sm font-semibold tabular-nums text-sky-700">
              {formatElapsedMs(elapsedMs)}
            </p>
          </div>
        )}
        {/* П.5c: есть реальный разбор — показываем темы из собеса (кликабельны, раскрываются LLM).
            Мока нет. Нет разбора — мок-темы подготовки как раньше. */}
        {hasRealDebrief ? (
          <DebriefInsights debrief={stageDebrief} vacancyId={vacancyId} stage={genStage} />
        ) : items.length > 0 ? (
          <div className="space-y-2">
            {items.map((t) => (
              <TopicRow key={t.topic} topic={t} />
            ))}
          </div>
        ) : generating ? (
          <ProgressSkeleton />
        ) : (
          /* Без кнопки: «Собрать темы» уже стоит в заголовке этой же секции (D-09). */
          <EmptyState
            icon={Sparkles}
            title="Тем ещё нет"
            note="Нажмите «Собрать темы» справа сверху — LLM предложит, что могут спросить по этой вакансии."
          />
        )}
      </section>
    </div>
  )
}
