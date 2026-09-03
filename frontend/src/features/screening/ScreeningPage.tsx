import { useEffect, useMemo, useState } from "react"
import { useLocation } from "react-router-dom"
import { Speech } from "lucide-react"
import type { Job } from "@/api/jobs"
import { useJobs } from "@/features/jobs/use-jobs"
import { usePersistedRouteState } from "@/lib/use-persisted-route-state"
import { resolveStage, type FunnelStage } from "@/features/jobs/funnel"
import type { SavedScreeningQuestions } from "@/api/screening"
import { CollapsibleRail } from "@/components/job/CollapsibleRail"
import { RailFunnelActions } from "@/components/job/RailFunnelActions"
import { TranscriptMark } from "@/components/job/TranscriptMark"
import { VacancyCardRail } from "@/components/job/VacancyCardRail"
import { EmptyState } from "@/components/ui/empty-state"
import { SkeletonCard } from "@/components/ui/skeleton"
import { formatElapsedMs, useElapsedMs } from "@/lib/use-elapsed-ms"
import { useDebriefStageIndex } from "@/features/tech/use-debrief"
import { QuestionsChatPanel } from "./QuestionsChatPanel"
import { askQuestionCard, hrQuestionCard } from "./question-cards"
import {
  useEditScreeningPitch,
  useGenerateMoreScreeningQuestions,
  useGenerateScreeningQuestions,
  useRegenerateScreeningPitch,
  useScreeningQuestions,
} from "./use-screening"

const SCREENING_STAGE_ORDER: FunnelStage[] = ["Скрининг"]

// FR5: ближайший будущий скрининг — первым (по возрастанию даты), затем прошедшие — от самого
// свежего (по убыванию), затем вакансии без даты — по скору (как раньше). Отменённый скрининг
// (status="cancelled") приравнивается к «даты нет» — не тянет вакансию в «ближайшие»/«недавние».
function screeningDateSort(a: Job, b: Job): number {
  const now = Date.now()
  function timeOf(job: Job): number | null {
    if (!job.hr_screening_at || job.hr_screening_status === "cancelled") return null
    const t = new Date(job.hr_screening_at).getTime()
    return Number.isNaN(t) ? null : t
  }
  const ta = timeOf(a)
  const tb = timeOf(b)
  const tierOf = (t: number | null) => (t == null ? 2 : t >= now ? 0 : 1)
  const tierA = tierOf(ta)
  const tierB = tierOf(tb)
  if (tierA !== tierB) return tierA - tierB
  if (tierA === 0) return (ta as number) - (tb as number)
  if (tierA === 1) return (tb as number) - (ta as number)
  return (b.overall_score ?? -1) - (a.overall_score ?? -1)
}

function railJobs(jobs: Job[] | undefined): Job[] {
  const rank = new Map<FunnelStage, number>()
  SCREENING_STAGE_ORDER.forEach((s, i) => rank.set(s, i))
  return (jobs ?? [])
    .filter((j) => !j.skipped)
    .map((j) => ({ job: j, stage: resolveStage(j.status) }))
    .filter((x) => rank.has(x.stage))
    .sort((a, b) => {
      const ra = rank.get(a.stage)!
      const rb = rank.get(b.stage)!
      if (ra !== rb) return ra - rb
      return screeningDateSort(a.job, b.job)
    })
    .map((x) => x.job)
}

function packHasContent(saved: SavedScreeningQuestions | null | undefined): boolean {
  if (!saved) return false
  return Boolean(
    saved.oral_pitch?.trim() ||
    saved.pitch_blocks?.length ||
    saved.hr_questions?.length ||
    saved.why_company?.trim() ||
    saved.groups?.length,
  )
}

function prepStatusLabel(elapsedMs: number): string {
  if (elapsedMs < 8_000) return "Разбираю вакансию…"
  if (elapsedMs < 35_000) return "Пишу легенду под вакансию…"
  if (elapsedMs < 70_000) return "Готовлю вопросы…"
  return "Ещё чуть-чуть…"
}

function VacancyPrep({ vacancy }: { vacancy: Job }) {
  const vacancyId = vacancy.vacancy_id!
  const { data: saved, isLoading } = useScreeningQuestions(vacancyId)
  const gen = useGenerateScreeningQuestions()
  const regenPitch = useRegenerateScreeningPitch()
  const editPitch = useEditScreeningPitch()
  const moreHr = useGenerateMoreScreeningQuestions()
  const moreAsk = useGenerateMoreScreeningQuestions()
  const pack = saved as SavedScreeningQuestions | undefined
  const has = packHasContent(pack)
  const generating = gen.isPending
  const rebuildingPitch = regenPitch.isPending
  const elapsedMs = useElapsedMs(generating)

  const fromHr = useMemo(() => (pack?.hr_questions ?? []).map(hrQuestionCard), [pack?.hr_questions])

  const toHr = useMemo(
    () =>
      (pack?.groups ?? []).flatMap((g) =>
        (g.questions ?? [])
          .filter((q) => q.question?.trim())
          .map((q) => askQuestionCard(q, g.title)),
      ),
    [pack?.groups],
  )

  const inputBody = useMemo(
    () => ({
      title: vacancy.title ?? "",
      company: vacancy.company ?? "",
      vacancy_text: vacancy.vacancy_text ?? "",
    }),
    [vacancy.title, vacancy.company, vacancy.vacancy_text],
  )

  function run() {
    gen.mutate({ vacancyId, body: inputBody })
  }

  function runRebuildPitch() {
    regenPitch.mutate({ vacancyId, body: inputBody })
  }

  function runMoreHr() {
    moreHr.mutate({ vacancyId, body: { ...inputBody, kind: "hr", count: 6 } })
  }

  function runMoreAsk() {
    moreAsk.mutate({ vacancyId, body: { ...inputBody, kind: "ask", count: 6 } })
  }

  // FR3-52 UX8: раньше жил отдельным full-width баннером над сеткой и расталкивал уже видимые
  // блоки при каждой повторной генерации - теперь это строка статуса в шапке QuestionsChatPanel
  // (не меняет высоту шапки), «Подготовиться»/«Собираю…» там же.
  const progressLabel = generating
    ? `${prepStatusLabel(elapsedMs)} · ${formatElapsedMs(elapsedMs)}`
    : null

  // Правка 2026-08-19 пункт 4: чат виден сразу, даже когда пакета к скринингу ещё нет - раньше
  // на его месте стоял EmptyState с CTA «Подготовиться», и владелец не мог написать агенту, пока
  // не сгенерирует пакет. Кнопка «Подготовиться» никуда не делась — она в шапке QuestionsChatPanel
  // (см. hasContent/onGenerate ниже), просто больше не блокирует доступ к самому чату.
  return (
    <div className="flex h-full min-h-0 flex-col gap-6">
      {isLoading ? (
        <SkeletonCard className="h-full w-full" />
      ) : (
        <QuestionsChatPanel
          vacancyId={vacancyId}
          job={vacancy}
          hr={{
            items: fromHr,
            onAddMore: runMoreHr,
            addMorePending: moreHr.isPending,
            loading: generating,
          }}
          ask={{
            items: toHr,
            onAddMore: runMoreAsk,
            addMorePending: moreAsk.isPending,
            loading: generating,
          }}
          hasContent={has}
          onGenerate={run}
          generating={generating}
          progressLabel={progressLabel}
          pitch={{
            blocks: pack?.pitch_blocks ?? [],
            oralPitch: pack?.oral_pitch ?? "",
            whyCompany: pack?.why_company ?? "",
            generatedAt: pack?.generated_at,
            generating,
            onRebuild: runRebuildPitch,
            rebuilding: rebuildingPitch,
            onSave: (text) => editPitch.mutate({ vacancyId, oralPitch: text }),
            saving: editPitch.isPending,
          }}
        />
      )}
    </div>
  )
}

function PageSkeleton() {
  return (
    <div className="space-y-4 p-6">
      <SkeletonCard className="h-[68px] w-full" />
      <SkeletonCard className="h-[40vh] w-full" />
    </div>
  )
}

export function ScreeningPage() {
  const { data: jobs, isLoading } = useJobs()
  // Один запрос на раздел: по каким вакансиям расшифровка скрининга уже вставлена — отметка
  // прямо на карточке рельса, чтобы не заходить в каждую вакансию с вопросом «вставлял или нет».
  const { data: stageIndex } = useDebriefStageIndex()
  const navState = (useLocation().state ?? null) as { vacancyId?: string } | null
  const list = useMemo(() => railJobs(jobs), [jobs])
  // Рельс (allowClosed) дописывает хвостом отказы — их нет в `list` (активные этапы), поэтому и
  // выбор, и дефолт-эффект ниже должны знать об этих id отдельно, иначе клик по отказной карточке
  // тут же откатывается на первую активную вакансию (баг: нельзя было зайти в отказ и вставить
  // расшифровку).
  const closedList = useMemo(
    () => (jobs ?? []).filter((j) => resolveStage(j.status) === "Отказ"),
    [jobs],
  )

  // F-09: выбор — в URL (`?vacancy=`, переживает F5, шарится ссылкой), sessionStorage —
  // фолбэк-память между Скринингами и Техничками (тот же storageKey), пока в URL пусто.
  const [vacancyId, setVacancyId] = usePersistedRouteState<string>({
    param: "vacancy",
    storageKey: "prep-vacancy",
  })

  // Заход через location.state (без URL-параметра) — применяем один раз, дальше приоритет
  // у URL/сессии.
  const [navConsumed, setNavConsumed] = useState(false)
  if (!navConsumed && navState?.vacancyId && vacancyId == null) {
    setNavConsumed(true)
    setVacancyId(navState.vacancyId)
  }

  // Дефолт: если выбора нет или он больше не на экране - первая вакансия в рельсе (FR3-52).
  useEffect(() => {
    if (isLoading || list.length === 0) return
    const ids = new Set(
      [...list, ...closedList].map((j) => j.vacancy_id).filter(Boolean) as string[],
    )
    if (vacancyId && ids.has(vacancyId)) return
    const first = list[0]?.vacancy_id
    if (first) setVacancyId(first)
  }, [isLoading, list, closedList, vacancyId, setVacancyId])

  const vacancy = useMemo(
    () =>
      list.find((j) => j.vacancy_id === vacancyId) ??
      closedList.find((j) => j.vacancy_id === vacancyId) ??
      null,
    [list, closedList, vacancyId],
  )

  if (isLoading) {
    return (
      <div className="flex min-h-0 flex-1 flex-col">
        <PageSkeleton />
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div id="screen-start-screening" className="flex min-h-0 flex-1">
        <CollapsibleRail storageKey="copilot.rail.screening.collapsed">
          <VacancyCardRail
            value={vacancyId}
            onChange={(j) => setVacancyId(j?.vacancy_id ?? null)}
            sort="byStage"
            stageOrder={SCREENING_STAGE_ORDER}
            showGeneral={false}
            stageSecondarySort={screeningDateSort}
            allowClosed
            closedIncludeSkipped={false}
            closedLimit={10}
            renderActions={(job) => <RailFunnelActions job={job} nextStage="Техничка" />}
            renderMark={(job) => (
              <TranscriptMark
                done={Boolean(stageIndex?.get(job.vacancy_id ?? "")?.has("screening"))}
              />
            )}
          />
        </CollapsibleRail>

        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          {list.length === 0 ? (
            <EmptyState
              icon={Speech}
              title="Здесь будет подготовка к скринингу"
              note="Переведите вакансию на этап «Скрининг» в воронке — она появится в рельсе слева."
              action={{ label: "К воронке", to: "/jobs" }}
            />
          ) : vacancy ? (
            <VacancyPrep key={vacancy.vacancy_id ?? vacancy.id} vacancy={vacancy} />
          ) : (
            <EmptyState
              icon={Speech}
              title="Подготовка к конкретной вакансии"
              note="Выберите вакансию в рельсе слева."
              action={{
                label: "Выбрать в рельсе",
                onClick: () => setVacancyId(list[0]?.vacancy_id ?? null),
              }}
            />
          )}
        </div>
      </div>
    </div>
  )
}
