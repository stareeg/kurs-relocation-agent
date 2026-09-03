import { useCallback, useEffect, useRef } from "react"
import { useQuery, useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { ApiError } from "@/api/client"
import { OPENROUTER_MISSING_TOAST } from "@/lib/toasts"
import {
  atsFitResumeStream,
  fetchResumeData,
  fetchResumeGap,
  fetchResumeScoreHistory,
  parseResumePdf,
    patchResumeData,
    saveResumeData,
    strengthenResumeAbout,
    strengthenResumeExperience,
  suggestSearchProfile,
  type AtsFitProgress,
  type AtsFitResult,
  type ResumeData,
  type ResumeDataPatch,
  type ResumeGapReport,
  type ResumeScoreBreakdown,
  type ResumeScoreSnapshot,
  type SearchProfileSuggestRequest,
} from "@/api/resume"
import { applyResumePatch, patchTouchesSkillCorpus } from "./apply-resume-patch"
import { EMPTY_SUGGEST_STATE, type SuggestState } from "./priority-suggest"

export type { AtsFitProgress, AtsFitResult }

/** Инвалидация плашки балла + истории + снимка навыков (FR2-48). GET /gap сам решит, нужен
 * ли LLM-refresh. «Спрос» инвалидируем тоже: key_skills — часть input_fp снимка, правка
 * навыков/текста должна перекрасить его в stale. */
export function invalidateResumeScore(qc: QueryClient, opts?: { skills?: boolean }) {
  void qc.invalidateQueries({ queryKey: ["resume", "gap"] })
  void qc.invalidateQueries({ queryKey: ["resume", "score-history"] })
  if (opts?.skills !== false) {
    void qc.invalidateQueries({ queryKey: ["resume", "skills"] })
  }
}

// Хук для acceptAtsProposal в ResumeForm — без него принятые ATS-правки жили бы только
// в локальном стейте формы и потерялись бы при её unmount/перезагрузке.
let atsAppliedHook: (() => void) | null = null

/** Регистрирует колбэк «ATS-правка принята в форму» (вызывается из ResumeForm). */
export function setOnAtsApplied(fn: (() => void) | null) {
  atsAppliedHook = fn
}

/** Вызывается при принятии ATS-правки: сохранить черновик формы и инвалидировать балл. */
export function notifyAtsApplied() {
  atsAppliedHook?.()
}

function auditFixesFromSnapshot(
  s: ResumeScoreSnapshot,
): ResumeScoreBreakdown["score_fixes"] {
  const raw = s.audit_json?.fixes
  if (!Array.isArray(raw)) return []
  return raw as ResumeScoreBreakdown["score_fixes"]
}

function snapshotToScore(s: ResumeScoreSnapshot): ResumeScoreBreakdown {
  return {
    total: s.total,
    structure: s.structure,
    market_coverage: s.market_coverage ?? null,
    writing: s.writing,
    role_fit: s.role_fit,
    weak_bullets: [],
    role_fit_notes: [],
    score_fixes: auditFixesFromSnapshot(s),
    details: { structure: [], market_missing: [] },
  }
}

function gapPlaceholderFromHistory(
  history: ResumeScoreSnapshot[] | undefined,
): ResumeGapReport | undefined {
  if (!history?.length) return undefined
  const last = history[history.length - 1]
  return {
    available: false,
    corpus_size: 0,
    concepts_total: 0,
    concepts_covered: 0,
    demanded_total: 0,
    demanded_covered: 0,
    missing: [],
    strong: [],
    score: snapshotToScore(last),
    score_blocked: false,
    score_meta: {
      stale: true,
      refreshing: true,
      scored_at: last.created_at ?? null,
      writing_ready: last.writing_ready ?? false,
      role_fit_ready: last.role_fit_ready ?? false,
      resume_hash: last.resume_hash ?? "",
      corpus_fp: last.corpus_fp ?? "",
    },
  }
}

// История снимков — тренд + first-paint для плашки балла (FR2-46).
export function useResumeScoreHistory() {
  return useQuery({
    queryKey: ["resume", "score-history"],
    queryFn: () => fetchResumeScoreHistory(),
    staleTime: 60_000,
  })
}

// Срез «резюме vs рынок». GET быстрый; writing/role_fit — extract-LLM в фоне при stale
// (FR2-46/48). Поллим только пока refresh идёт; иначе раз в 3 мин + на фокус вкладки
// (market_coverage зависит от корпуса). Placeholder из истории → без минутного скелетона.
export function useResumeGap() {
  const qc = useQueryClient()
  const historyQ = useResumeScoreHistory()
  const placeholder = gapPlaceholderFromHistory(historyQ.data)
  const wasRefreshing = useRef(false)

  const query = useQuery({
    queryKey: ["resume", "gap"],
    queryFn: fetchResumeGap,
    staleTime: 180_000,
    gcTime: 10 * 60_000,
    placeholderData: () => placeholder,
    refetchOnWindowFocus: false,
    refetchInterval: (q) => {
      const meta = q.state.data?.score_meta
      // Пока бэк гоняет дешёвый extract (writing/role_fit) — частый поллинг.
      if (meta?.stale || meta?.refreshing) return 3_000
      // Иначе периодически подтянуть детерминированные части (structure/market).
      // LLM снова дернется только если resume_hash/corpus_fp сменились → stale.
      return 180_000
    },
  })

  // После завершения фонового LLM-refresh — обновить историю снимков (дельта «с прошлого»).
  useEffect(() => {
    const meta = query.data?.score_meta
    const refreshing = Boolean(meta?.stale || meta?.refreshing)
    if (wasRefreshing.current && !refreshing) {
      void qc.invalidateQueries({ queryKey: ["resume", "score-history"] })
    }
    wasRefreshing.current = refreshing
    // Намеренно только stale/refreshing, не весь score_meta - иначе лишние срабатывания на scored_at и т.п.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query.data?.score_meta?.stale, query.data?.score_meta?.refreshing, qc])

  return query
}

export function useResumeData() {
  return useQuery({
    queryKey: ["resume", "data"],
    queryFn: fetchResumeData,
    staleTime: 60_000,
  })
}

/** Целевой минимум из position.salary_min; null если не задан (не красить meetsMin на фронте). */
export function useCandidateSalaryMin(): number | null {
  const { data } = useResumeData()
  const v = data?.position?.salary_min
  return v != null && v > 0 ? v : null
}

export function useSaveResumeData() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: ResumeData) => saveResumeData(data),
    onSuccess: (saved) => {
      qc.setQueryData<ResumeData>(["resume", "data"], saved)
      invalidateResumeScore(qc)
      toast.success("Резюме сохранено — оценка вакансий возьмёт обновлённый текст")
    },
    onError: () => toast.error("Не удалось сохранить резюме"),
  })
}

// K-02: пишет через резюме (отдельного хранилища вердиктов по компаниям нет — правила
// скоринга читают именно search_criteria.*_companies, load_list_company_adjustments).
// Оптимистично патчит кэш ["resume","data"], чтобы доска компаний (CompaniesBoard) и точечные
// автосейвы в ResumeForm откликались мгновенно; при ошибке — откат к снимку до мутации + тост.
export function usePatchResumeField() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (patch: ResumeDataPatch) => patchResumeData(patch),
    onMutate: async (patch) => {
      await qc.cancelQueries({ queryKey: ["resume", "data"] })
      const prev = qc.getQueryData<ResumeData>(["resume", "data"])
      if (prev) {
        qc.setQueryData<ResumeData>(["resume", "data"], applyResumePatch(prev, patch))
      }
      return { prev }
    },
    onSuccess: (saved, patch) => {
      qc.setQueryData<ResumeData>(["resume", "data"], saved)
      // PUT/PATCH на бэке уже ставят refresh_resume_score в BackgroundTasks.
      invalidateResumeScore(qc, { skills: patchTouchesSkillCorpus(patch) })
      if (
        patch.search_criteria?.target_companies !== undefined ||
        patch.search_criteria?.avoid_companies !== undefined
      ) {
        void qc.invalidateQueries({ queryKey: ["companies", "candidates"] })
        void qc.invalidateQueries({ queryKey: ["companies"] })
      }
    },
    onError: (_err, _patch, ctx) => {
      if (ctx?.prev) qc.setQueryData<ResumeData>(["resume", "data"], ctx.prev)
      toast.error("Не удалось сохранить — попробуйте ещё раз")
    },
  })
}

export function useParseResumePdf() {
  return useMutation({
    mutationFn: (file: File) => parseResumePdf(file),
    onError: (err: Error) => {
      toast.error(err.message || "Не удалось разобрать PDF")
    },
  })
}

export function useSuggestSearchProfile() {
  return useMutation({
    mutationFn: (req: SearchProfileSuggestRequest) => suggestSearchProfile(req),
    // Раньше любая ошибка показывалась как «нет ключа OpenRouter» — при пустом резюме (400) или
    // таймауте это врало и вело искать проблему не там.
    onError: (err: Error) => {
      const status = err instanceof ApiError ? err.status : undefined
      if (status === 400) {
        toast.error("Заполните желаемую должность и навыки — по пустому резюме подобрать нечего")
        return
      }
      if (status === 503) {
        toast.error(OPENROUTER_MISSING_TOAST)
        return
      }
      toast.error(err.message || "Не удалось подобрать варианты — попробуйте ещё раз")
    },
  })
}

// Слайт подсказок профиля поиска. В query-кэше, а не в `useState` панели: панель размонтируется
// при переключении вкладок «Резюме», и подсказки терялись вместе с историей показанного — после
// возврата «Обновить» снова присылало то же самое. Плюс кэш делает состояние общим для двух
// панелей: приоритеты/отрасль живут в SearchProfilePanel, роль — в RolePrefsField.
const SEARCH_PROFILE_SUGGEST_KEY = ["resume", "search-profile", "suggest"] as const

export function useSearchProfileSuggestState() {
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: SEARCH_PROFILE_SUGGEST_KEY,
    queryFn: () => EMPTY_SUGGEST_STATE,
    // Клиентское состояние, а не серверные данные: не устаревает и не собирается сборщиком,
    // иначе слайт пропадёт ровно так же, как пропадал из useState.
    staleTime: Infinity,
    gcTime: Infinity,
  })
  const setState = useCallback(
    (next: SuggestState) => {
      qc.setQueryData<SuggestState>(SEARCH_PROFILE_SUGGEST_KEY, next)
    },
    [qc],
  )
  // Мердж с дефолтом, а не `data ?? EMPTY`: частичный объект (persist-гидратация старой формы,
  // ручной setQueryData) иначе даёт `seen === undefined` и падение в `buildExclude`.
  return { suggestState: { ...EMPTY_SUGGEST_STATE, ...data }, setSuggestState: setState }
}

// FR2-34/38: пайплайн «Подогнать под ATS» со стримом прогресса (SSE A-14).
export function useAtsFitResume(onProgress?: (p: AtsFitProgress) => void) {
  return useMutation({
    mutationFn: () =>
      atsFitResumeStream((ev) => {
        if (ev.type === "start" || ev.type === "progress") {
          onProgress?.({
            done: ev.done,
            total: ev.total,
            label: ev.label ?? "",
          })
        }
      }),
    onError: (err: Error) =>
      toast.error(err.message || `Не удалось подогнать под ATS. ${OPENROUTER_MISSING_TOAST}`),
  })
}

// «Подогнать под ATS» для одного описания места работы (кнопка у конкретного блока опыта).
// Возвращает правку блока; применять её — решение формы.
export function useStrengthenResumeExperience() {
  return useMutation({
    mutationFn: (index: number) => strengthenResumeExperience(index),
    onError: (err: Error) =>
      toast.error(err.message || `Не удалось подогнать описание. ${OPENROUTER_MISSING_TOAST}`),
  })
}

// «Подогнать под ATS» для блока «Обо мне» (кнопка над блоком Обо мне).
// Возвращает правку; применять её — решение формы.
export function useStrengthenResumeAbout() {
  return useMutation({
    mutationFn: () => strengthenResumeAbout(),
    onError: (err: Error) =>
      toast.error(err.message || `Не удалось подогнать блок «Обо мне». ${OPENROUTER_MISSING_TOAST}`),
  })
}
