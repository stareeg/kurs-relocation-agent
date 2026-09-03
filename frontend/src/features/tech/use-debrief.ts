import { useCallback, useEffect, useSyncExternalStore } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { queryClient } from "@/lib/query"
import {
  fetchDebriefHistory,
  fetchDebriefJobStatus,
  fetchDebriefStageIndex,
  patchDebriefTranscript,
  startDebriefAnalysis,
  type DebriefAnalyzeRequest,
  type DebriefHistory,
  type DebriefResult,
  type DebriefStageIndex,
  type TranscriptTurn,
} from "@/api/debrief"

// Накопленная история разборов по вакансии (UI-5). Тянем только когда выбрана вакансия; разборы
// стабильны — не перезапрашиваем при каждом фокусе.
export function useDebriefHistory(vacancyId: string | null) {
  return useQuery({
    queryKey: ["debrief", vacancyId],
    queryFn: () => fetchDebriefHistory(vacancyId!),
    enabled: !!vacancyId,
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  })
}

const POLL_MS = 1500
// DBR-2 п.4/DBR-7: жёсткий потолок ожидания на клиенте — дальше явная ошибка с «Повторить», не
// вечный спиннер. Бэкенд режет сам LLM-вызов на 150с (_LLM_TIMEOUT_S) + до ~40с best-effort
// пост-процессинга (5 шагов × 8с) — держим клиентский потолок заметно выше, чтобы не сдаваться
// раньше, чем реально мог успеть ответить бэкенд.
const HARD_LIMIT_MS = 210_000
// Сколько финальное (done/error) состояние задачи живёт в модульном сторе после завершения —
// чтобы подписчик, вернувшийся на экран чуть позже, успел прочитать результат/ошибку и
// отрисовать тост/состояние. После этого окно очищается, и хук снова показывает «не занято».
const DONE_TTL_MS = 8_000

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

// Фоновая задача разбора живёт на уровне модуля, а не в жизненном цикле компонента: бэкенд
// уже бежит независимо (POST /analyze → job_id), а клиентский опрос раньше привязывался к
// смонтированному TechPage — уход с экрана глушнул цикл, и готовый разбор терялся. Теперь
// опрос переживает размонтирование: результат пишется прямо в кэш ["debrief", vacancyId],
// а подписчик (useAnalyzeDebrief через useSyncExternalStore) при возвращении на экран видит
// актуальное состояние. На одну вакансию — не более одной активной задачи (новый старт
// перезаписывает предыдущую, как и прежний хук).
// `body` держим в задаче целиком: композер очищается сразу после старта (экран не должен
// «замирать» с заблокированным полем на минуту ожидания LLM), поэтому текст расшифровки живёт
// только здесь — из него рисуется черновой диалог в карточке прогресса, им же работают
// «Повторить» и «Вернуть текст в поле» при ошибке задачи.
type DebriefJob =
  | {
      status: "running"
      startedAt: number
      jobId: string
      body: DebriefAnalyzeRequest
      onSuccess?: (r: DebriefResult) => void
    }
  | { status: "done"; result: DebriefResult; startedAt: number }
  | { status: "error"; message: string; startedAt: number; body: DebriefAnalyzeRequest }

// Тикер elapsedMs — отдельный module-scope стор, тикающий только пока у него есть живые
// подписчики (т.е. смонтированный экран с running-задачей). useSyncExternalStore читает
// актуальный elapsed без локальных useState/useEffect — правило react-hooks/set-state-in-effect
// не нарушается. Когда задача не running, тикер не запущен, snapshot = 0.
//
// ВАЖНО: getSnapshot должен возвращать СТАБИЛЬНОЕ значение между уведомлениями store
// (React делает consistency-check, сравнивая результаты повторных вызовов через Object.is).
// Вычислять Date.now() прямо в getSnapshot — антипаттерн: каждый вызов даёт новое число,
// React видит расхождение и падает с "Maximum update depth exceeded" (#185). Поэтому
// храним текущий elapsed в module-scope переменной, обновляемой только тикером.
const elapsedSubscribers = new Set<() => void>()
let elapsedStartedAt: number | null = null
let elapsedValue = 0
let elapsedTimer: number | null = null

function elapsedNotify() {
  for (const cb of elapsedSubscribers) cb()
}

function elapsedSubscribe(cb: () => void): () => void {
  elapsedSubscribers.add(cb)
  if (elapsedSubscribers.size === 1 && elapsedStartedAt != null && elapsedTimer == null) {
    elapsedTimer = window.setInterval(elapsedTick, 500)
  }
  return () => {
    elapsedSubscribers.delete(cb)
    if (elapsedSubscribers.size === 0 && elapsedTimer != null) {
      window.clearInterval(elapsedTimer)
      elapsedTimer = null
    }
  }
}

function elapsedGetSnapshot(): number {
  return elapsedValue
}

function elapsedTick() {
  if (elapsedStartedAt != null) {
    elapsedValue = Date.now() - elapsedStartedAt
  }
  elapsedNotify()
}

function elapsedStart(startedAt: number) {
  elapsedStartedAt = startedAt
  elapsedValue = 0
  if (elapsedSubscribers.size > 0 && elapsedTimer == null) {
    elapsedTimer = window.setInterval(elapsedTick, 500)
  }
  elapsedNotify()
}

function elapsedStop() {
  elapsedStartedAt = null
  elapsedValue = 0
  if (elapsedTimer != null) {
    window.clearInterval(elapsedTimer)
    elapsedTimer = null
  }
  elapsedNotify()
}

const debriefJobs = new Map<string, DebriefJob>()
const debriefSubscribers = new Map<string, Set<() => void>>()

function notify(vacancyId: string) {
  const subs = debriefSubscribers.get(vacancyId)
  if (subs) for (const cb of subs) cb()
}

function subscribeDebriefJob(vacancyId: string, cb: () => void): () => void {
  const set = debriefSubscribers.get(vacancyId) ?? new Set()
  set.add(cb)
  debriefSubscribers.set(vacancyId, set)
  return () => {
    set.delete(cb)
    if (set.size === 0) debriefSubscribers.delete(vacancyId)
  }
}

function setDebriefJob(vacancyId: string, job: DebriefJob) {
  debriefJobs.set(vacancyId, job)
  notify(vacancyId)
}

function clearDebriefJob(vacancyId: string) {
  debriefJobs.delete(vacancyId)
  notify(vacancyId)
}

function getDebriefJob(vacancyId: string): DebriefJob | null {
  return debriefJobs.get(vacancyId) ?? null
}

// Собственно опрос. Живёт в module scope — не глушнится размонтированием. Результат кладётся в
// query-кэш сразу, поэтому даже если ни один подписчик не активен (пользователь ушёл с экрана),
// при возвращении useDebriefHistory покажет свежий разбор. onSuccess вызывается только при
// наличии живых подписчиков — иначе навигационные сайд-эффекты TechPage не актуальны.
async function runDebriefJob(
  vacancyId: string,
  body: DebriefAnalyzeRequest,
  onSuccess?: (r: DebriefResult) => void,
) {
  const startedAt = Date.now()
  try {
    const job = await startDebriefAnalysis(vacancyId, body)
    setDebriefJob(vacancyId, {
      status: "running",
      startedAt,
      jobId: job.job_id,
      body,
      onSuccess,
    })
    for (;;) {
      if (Date.now() - startedAt > HARD_LIMIT_MS) {
        const message = "Модель долго отвечает — попробуйте ещё раз или сократите транскрипт"
        setDebriefJob(vacancyId, { status: "error", message, startedAt, body })
        toast.error(message)
        scheduleCleanup(vacancyId, startedAt)
        return
      }
      await sleep(POLL_MS)
      const status = await fetchDebriefJobStatus(vacancyId, job.job_id)
      if (status.status === "done" && status.result) {
        const result = status.result
        queryClient.setQueryData<DebriefHistory>(["debrief", vacancyId], (prev) => {
          const items = prev?.items ?? []
          return { vacancy_id: vacancyId, items: [result, ...items] }
        })
        void queryClient.invalidateQueries({ queryKey: ["debrief-stage-index"] })
        setDebriefJob(vacancyId, { status: "done", result, startedAt })
        toast.success("Анализ готов")
        // onSuccess зовём только если на эту вакансию всё ещё кто-то подписан (экран Техичек/
        // Скринингов открыт) — иначе сайд-эффекты навигации бесполезны, результат уже в кэше.
        const subs = debriefSubscribers.get(vacancyId)
        if (subs && subs.size > 0) onSuccess?.(result)
        scheduleCleanup(vacancyId, startedAt)
        return
      }
      if (status.status === "error") {
        const message = status.error || "Не удалось разобрать собес"
        setDebriefJob(vacancyId, { status: "error", message, startedAt, body })
        toast.error(message)
        scheduleCleanup(vacancyId, startedAt)
        return
      }
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : "Не удалось разобрать собес"
    setDebriefJob(vacancyId, { status: "error", message, startedAt, body })
    toast.error(message)
    scheduleCleanup(vacancyId, startedAt)
  }
}

// Через DONE_TTL_MS очищаем финальное состояние — окно успевает показать «готово»/ошибку
// вернувшемуся подписчику, после чего хук снова считает задачу завершённой.
function scheduleCleanup(vacancyId: string, startedAt: number) {
  window.setTimeout(() => {
    const cur = getDebriefJob(vacancyId)
    if (cur && cur.startedAt === startedAt && cur.status !== "running") {
      clearDebriefJob(vacancyId)
    }
  }, DONE_TTL_MS)
}

// DBR-2: разбор транскрипта (LLM) — фоновая задача (202 сразу) + опрос статуса. Опрос переживает
// размонтирование экрана: если запустить разбор и уйти с Техичек/Скринингов, задача продолжит
// опрашиваться на уровне модуля, результат приземлится в кэш истории, и при возвращении будет
// виден. useSyncExternalStore читает актуальное состояние без ручных setState-ов в размонтированный
// компонент.
export function useAnalyzeDebrief(vacancyId: string | null) {
  const subscribe = useCallback(
    (cb: () => void) => (vacancyId ? subscribeDebriefJob(vacancyId, cb) : () => {}),
    [vacancyId],
  )
  const getSnapshot = useCallback(
    () => (vacancyId ? getDebriefJob(vacancyId) : null),
    [vacancyId],
  )
  const job = useSyncExternalStore(subscribe, getSnapshot, getSnapshot)

  const isPending = Boolean(job && job.status === "running")
  const error = job && job.status === "error" ? job.message : null
  const jobStartedAt = job?.startedAt ?? null
  // Текст расшифровки идущей/упавшей задачи — для чернового диалога в карточке прогресса и для
  // восстановления в поле после ошибки.
  const pendingBody = job && job.status !== "done" ? job.body : null
  const pendingTranscript = pendingBody?.transcript ?? null

  // Тикер elapsedMs — подписываемся на module-scope стор, который тикает только пока есть
  // живые подписчики и задача running. Запускаем/останавливаем тикер эффектом (сайд-эффект на
  // внешний стор — не setState в эффект), само значение читаем через useSyncExternalStore,
  // без локального useState.
  const elapsedMs = useSyncExternalStore(elapsedSubscribe, elapsedGetSnapshot, elapsedGetSnapshot)
  useEffect(() => {
    if (isPending && jobStartedAt != null) elapsedStart(jobStartedAt)
    else elapsedStop()
  }, [isPending, jobStartedAt])

  const mutate = useCallback(
    async (body: DebriefAnalyzeRequest, opts?: { onSuccess?: (result: DebriefResult) => void }) => {
      if (!vacancyId) return
      void runDebriefJob(vacancyId, body, opts?.onSuccess)
    },
    [vacancyId],
  )

  const cancel = useCallback(() => {
    if (vacancyId) clearDebriefJob(vacancyId)
  }, [vacancyId])

  /** Повторить упавший разбор тем же текстом (композер уже пуст — текст берём из задачи). */
  const retry = useCallback(() => {
    if (!vacancyId || !pendingBody) return
    void runDebriefJob(vacancyId, pendingBody)
  }, [vacancyId, pendingBody])

  return { isPending, elapsedMs, error, pendingTranscript, mutate, cancel, retry }
}

// Где у аккаунта уже есть разобранная расшифровка (vacancy_id → набор этапов). Один запрос на
// раздел вместо истории разборов на каждую карточку рельса; инвалидируется вместе с историей.
export function useDebriefStageIndex() {
  return useQuery({
    queryKey: ["debrief-stage-index"],
    queryFn: fetchDebriefStageIndex,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    select: (data: DebriefStageIndex) =>
      new Map((data.items ?? []).map((it) => [it.vacancy_id, new Set(it.stages ?? [])])),
  })
}

// UX5-5: правка текста транскрипта прямо из спойлера «звонка» в ленте диалога (Чаты) — без
// перезапуска LLM-анализа. Обновляет карточку в кэше истории по id, не рефетчит всю историю.
export function usePatchDebriefTranscript(vacancyId: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ debriefId, transcript }: { debriefId: number; transcript: string }) =>
      patchDebriefTranscript(vacancyId!, debriefId, transcript),
    onSuccess: (result) => {
      if (!vacancyId) return
      qc.setQueryData<DebriefHistory>(["debrief", vacancyId], (prev) =>
        prev
          ? { ...prev, items: prev.items.map((it) => (it.id === result.id ? result : it)) }
          : prev,
      )
      toast.success("Текст обновлён")
    },
    onError: (err) =>
      toast.error(err instanceof Error ? err.message : "Не удалось сохранить текст"),
  })
}

// «Удалить» реплику транскрипта (RD-25→слияние, парность с диалогами по вакансиям): у реплики
// нет своей строки в БД (один текст транскрипта, LLM режет на реплики при отображении) — как и
// «Изменить расшифровку», это точечная правка текста через тот же PATCH, без повторного
// LLM-разбора. Реплика(и) убираются из сохранённого текста (пересобираем его из оставшихся реплик)
// и сразу из `analysis.transcript_turns` в кэше — иначе PATCH обновит только `transcript`, а
// отображаемые пузыри (turns) останутся прежними до следующего полного анализа.
export function useDeleteTranscriptTurns(vacancyId: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (turns: { debriefId: number; turnIndex: number }[]) => {
      if (!vacancyId || turns.length === 0) return []
      const byDebrief = new Map<number, Set<number>>()
      for (const t of turns) {
        const set = byDebrief.get(t.debriefId) ?? new Set<number>()
        set.add(t.turnIndex)
        byDebrief.set(t.debriefId, set)
      }
      const current = qc.getQueryData<DebriefHistory>(["debrief", vacancyId])
      const updates: { debriefId: number; transcript: string; turns: TranscriptTurn[] }[] = []
      for (const [debriefId, indices] of byDebrief) {
        const rec = current?.items.find((r) => r.id === debriefId)
        if (!rec) continue
        const remaining = (rec.analysis.transcript_turns ?? []).filter((_, i) => !indices.has(i))
        updates.push({
          debriefId,
          transcript: remaining.map((t) => t.text).join("\n"),
          turns: remaining,
        })
      }
      for (const u of updates) {
        await patchDebriefTranscript(vacancyId, u.debriefId, u.transcript)
      }
      return updates
    },
    onSuccess: (updates) => {
      if (!vacancyId || updates.length === 0) return
      const byId = new Map(updates.map((u) => [u.debriefId, u]))
      qc.setQueryData<DebriefHistory>(["debrief", vacancyId], (prev) => {
        if (!prev) return prev
        return {
          ...prev,
          items: prev.items.map((r) => {
            const u = r.id != null ? byId.get(r.id) : undefined
            if (!u) return r
            return {
              ...r,
              transcript: u.transcript,
              analysis: { ...r.analysis, transcript_turns: u.turns },
            }
          }),
        }
      })
      toast.success("Реплика удалена")
    },
    onError: (err) =>
      toast.error(err instanceof Error ? err.message : "Не удалось удалить реплику"),
  })
}
