import type { components } from "@/api/schema"
import { api, ApiError, LLM_TIMEOUT_MS } from "@/api/client"
import { eventKind, streamSse } from "@/api/sse"

export type ResumeGapReport = components["schemas"]["ResumeGapReport"]
export type GapConcept = components["schemas"]["GapConcept"]
export type ResumeData = components["schemas"]["ResumeData"]
export type ResumeExperience = components["schemas"]["Experience"]
export type ResumeEducation = components["schemas"]["Education"]
export type ResumeLanguage = components["schemas"]["Language"]
export type ResumeScoreBreakdown = components["schemas"]["ResumeScoreBreakdown"]
export type WeakBullet = components["schemas"]["WeakBullet"]
export type ResumeScoreSnapshot = components["schemas"]["ResumeScoreSnapshot"]

// GET /api/resume/score-history — история снимков скора (старые → новые), тренд между итерациями.
export function fetchResumeScoreHistory(limit = 30) {
  return api.get<ResumeScoreSnapshot[]>(`/api/resume/score-history?limit=${limit}`)
}

// GET /api/resume/data — структурное резюме по полям hh.ru (источник правды вкладки).
export function fetchResumeData() {
  return api.get<ResumeData>("/api/resume/data")
}

export type InternationalReadiness = components["schemas"]["InternationalReadiness"]

/** GET /api/resume/international — вывод международного профиля (без полей ввода). */
export function fetchInternationalReadiness() {
  return api.get<InternationalReadiness>("/api/resume/international")
}

export type EmployerDescriptor = components["schemas"]["EmployerDescriptor"]

// POST /api/resume/employer-descriptor — дескриптор текущего работодателя для превью тумблера
// «Скрывать текущее место» (Э4.2). POST, не GET — кэш-или-создать может дёрнуть LLM на первый
// вызов; повторные вызовы для того же работодателя из кэша. Нет текущего места — null.
export function fetchEmployerDescriptor() {
  return api.post<EmployerDescriptor | null>("/api/resume/employer-descriptor")
}

// PUT /api/resume/data — сохранить структурное резюме (скоринг рендерит markdown из JSON в рантайме).
export function saveResumeData(data: ResumeData) {
  return api.put<ResumeData>("/api/resume/data", data)
}

export type ResumeDataPatch = components["schemas"]["ResumeDataPatch"]

// PATCH /api/resume/data — точечный автосейв (UX4-0): только явно перечисленные поля,
// не весь ResumeData целиком. Для полей с мгновенным сохранением по клику (без общей «Сохранить»).
export function patchResumeData(patch: ResumeDataPatch) {
  return api.patch<ResumeData>("/api/resume/data", patch)
}

// strengthen/gap-audit роуты удалены (F-19, без потребителей) — оставался только внутренний
// пайплайн ats-fit. Клиентских обёрток и типов CritiqueResult / pipeline ensemble|single
// не держим — иначе снова появятся бейджи ok/needs_work/rewrite и трейс «Как получилось».

export type AtsFitResult = components["schemas"]["AtsFitResult"]
export type AtsFitExperiencePatch = components["schemas"]["AtsFitExperiencePatch"]
export type AtsFitAboutPatch = components["schemas"]["AtsFitAboutPatch"]

// POST /api/resume/ats-fit/experience/{index} — подогнать под ATS одно описание места работы.
// Ничего не сохраняет: правку владелец принимает в форме (LLM_TIMEOUT_MS: один critique-loop).
export function strengthenResumeExperience(index: number) {
  return api.post<AtsFitExperiencePatch>(
    `/api/resume/ats-fit/experience/${index}`,
    {},
    {
      timeoutMs: LLM_TIMEOUT_MS,
    },
  )
}

// POST /api/resume/ats-fit/about — подогнать под ATS блок «Обо мне».
export function strengthenResumeAbout() {
  return api.post<AtsFitAboutPatch>(
    "/api/resume/ats-fit/about",
    {},
    {
      timeoutMs: LLM_TIMEOUT_MS,
    },
  )
}

export type AtsFitProgress = {
  done: number
  total: number
  label: string
}

export type AtsFitStreamEvent =
  | { type: "start"; done: number; total: number; label?: string }
  | { type: "progress"; done: number; total: number; label: string }
  | { type: "result"; data: AtsFitResult }
  | { type: "error"; detail: string }

// Параллельный пайплайн может идти дольше одного LLM-вызова.
const ATS_FIT_STREAM_TIMEOUT_MS = 300_000

// POST /api/resume/ats-fit/stream — SSE прогресс FR2-38 / A-14 («3/6 блоков готово»).
export async function atsFitResumeStream(
  onEvent: (ev: AtsFitStreamEvent) => void,
  signal?: AbortSignal,
): Promise<AtsFitResult> {
  let result: AtsFitResult | null = null
  let streamError: string | null = null

  await streamSse("/api/resume/ats-fit/stream", {
    body: {},
    signal,
    timeoutMs: ATS_FIT_STREAM_TIMEOUT_MS,
    rumInteraction: "ats_fit",
    onEvent: (e) => {
      const kind = eventKind(e)
      if (kind === "error" || e.event === "error") {
        const detail =
          (typeof e.data.detail === "string" && e.data.detail) ||
          (typeof e.data.message === "string" && e.data.message) ||
          "Не удалось подогнать под ATS"
        streamError = detail
        onEvent({ type: "error", detail })
        return
      }
      if (kind === "start" || kind === "progress") {
        onEvent({
          type: kind,
          done: Number(e.data.done ?? 0),
          total: Number(e.data.total ?? 0),
          label: typeof e.data.label === "string" ? e.data.label : "",
        })
        return
      }
      if (kind === "result") {
        const data = e.data.data as AtsFitResult
        result = data
        onEvent({ type: "result", data })
        return
      }
      if (kind === "done" || e.event === "done") {
        const data = e.data.data as AtsFitResult | undefined
        if (data) {
          result = data
          onEvent({ type: "result", data })
        }
      }
    },
  })

  if (streamError) throw new ApiError(502, streamError)
  if (!result) throw new ApiError(502, "Пайплайн ats-fit завершился без результата")
  return result
}

// POST /api/resume/parse-pdf — PDF → structured ResumeData (LLM, ничего не сохраняет).
export function parseResumePdf(file: File) {
  const fd = new FormData()
  fd.append("file", file)
  return api.upload<ResumeData>("/api/resume/parse-pdf", fd)
}

// GET /api/resume/gap — быстрый срез + балл (LLM writing/role_fit — фоном, score_meta.stale).
export function fetchResumeGap() {
  return api.get<ResumeGapReport>("/api/resume/gap")
}

export type SearchProfileSuggestRequest = components["schemas"]["SearchProfileSuggestRequest"]
export type SearchProfileSuggestResponse = components["schemas"]["SearchProfileSuggestResponse"]

// POST /api/resume/search-profile/suggest — подбор типа роли / рынка / приоритетов по резюме.
export function suggestSearchProfile(req: SearchProfileSuggestRequest) {
  return api.post<SearchProfileSuggestResponse>("/api/resume/search-profile/suggest", req, {
    timeoutMs: LLM_TIMEOUT_MS,
  })
}

export type ResumeChatMessage = components["schemas"]["ResumeChatMessageOut"]
export type ResumeChatHistory = components["schemas"]["ResumeChatHistory"]

// GET /api/resume/chat — история чата по резюме (персист на бэкенде; пусто при нет PG).
export function fetchResumeChat() {
  return api.get<ResumeChatHistory>("/api/resume/chat")
}

// DELETE /api/resume/chat — очистить чат по резюме. Возвращает число удалённых строк.
export function clearResumeChat() {
  return api.del<{ removed: number }>("/api/resume/chat")
}

// DELETE /api/resume/chat/messages/{id} — удалить одну реплику (выделение → Удалить, зеркало
// deleteMarketChatMessage чата по рынку).
export function deleteResumeChatMessage(messageId: number) {
  return api.del<{ deleted: boolean }>(`/api/resume/chat/messages/${messageId}`)
}

// GM-13: расхождения getmatch-профиля с Copilot-резюме.

export type GmProfileDiffResponse = components["schemas"]["GmProfileDiffResponse"]
export type GmProfileDiscrepancyOut = components["schemas"]["GmProfileDiscrepancyOut"]

// GET /api/resume/gm-profile-diff — последние расхождения (для вкладки «Резюме»).
export function fetchGmProfileDiff() {
  return api.get<GmProfileDiffResponse>("/api/resume/gm-profile-diff")
}

// GM-12: заполненность профиля getmatch (чеклист доверия /api/trust).

export type GmTrustStatus = components["schemas"]["GmTrustStatusOut"]

// GET /api/resume/gm-trust — состояние заполненности профиля getmatch (для вкладки «Резюме»).
export function fetchGmTrust() {
  return api.get<GmTrustStatus>("/api/resume/gm-trust")
}

export type SkillsPanel = components["schemas"]["SkillsPanel"]
export type SkillSuggestionRow = components["schemas"]["SkillSuggestionRow"]
export type SkillSnapshot = components["schemas"]["SkillSnapshot"]
export type SkillStateUpdate = components["schemas"]["SkillStateUpdate"]

// GET /api/resume/skills — единый список «Навыки и спрос» (S-05, U-01): сохранённый снимок
// целиком (держу/добавить/лишний/переименовать). Только чтение, никогда не зовёт LLM.
export function fetchResumeSkills() {
  return api.get<SkillsPanel>("/api/resume/skills")
}

// PATCH /api/resume/skills — «скрыть» / «вернуть» одно предложение снимка (Решение 6).
export function patchResumeSkillState(body: SkillStateUpdate) {
  return api.patch<SkillSuggestionRow>("/api/resume/skills", body)
}

export type SkillsRefreshStreamEvent =
  | { type: "start"; done: number; total: number; label?: string }
  | { type: "progress"; done: number; total: number; label: string }
  | { type: "done"; data: SkillSnapshot }
  | { type: "error"; detail: string }

// Один reasoning-вызов (budget_ms 90s) — запас на сетевые задержки, как у ats-fit/stream.
const SKILLS_REFRESH_TIMEOUT_MS = 150_000

// POST /api/resume/skills/refresh — SSE-прогресс пересборки снимка навыков (S-05, как A-14).
export async function refreshResumeSkillsStream(
  onProgress?: (p: { done: number; total: number; label: string }) => void,
  signal?: AbortSignal,
): Promise<SkillSnapshot> {
  let result: SkillSnapshot | null = null
  let streamError: string | null = null

  await streamSse("/api/resume/skills/refresh", {
    body: {},
    signal,
    timeoutMs: SKILLS_REFRESH_TIMEOUT_MS,
    rumInteraction: "resume_skills_refresh",
    onEvent: (e) => {
      const kind = eventKind(e)
      if (kind === "error" || e.event === "error") {
        const detail =
          (typeof e.data.detail === "string" && e.data.detail) ||
          (typeof e.data.message === "string" && e.data.message) ||
          "Не удалось пересобрать навыки"
        streamError = detail
        return
      }
      if (kind === "start" || kind === "progress") {
        onProgress?.({
          done: Number(e.data.done ?? 0),
          total: Number(e.data.total ?? 0),
          label: typeof e.data.label === "string" ? e.data.label : "",
        })
        return
      }
      if (kind === "done" || e.event === "done") {
        const data = e.data.data as SkillSnapshot | undefined
        if (data) result = data
      }
    },
  })

  if (streamError) throw new ApiError(502, streamError)
  if (!result) throw new ApiError(502, "Пересборка навыков завершилась без результата")
  return result
}
