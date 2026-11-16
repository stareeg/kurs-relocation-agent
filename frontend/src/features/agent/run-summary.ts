import type { AgentEvent, AgentRunStatus } from "@/api/agent"
import { extractChanges, type RunPlanItem, type RunView } from "./use-agent-runs"

// Сводка запуска агента из его событий (U-5): одна чистая функция на всё, что рисуют
// компактная карточка в ленте и правая панель «Ход работы» — журнал по шагам, вызовы по
// инструментам, вакансии запуска с баллом, прогресс плана и строка «Сейчас». Тестируется
// без DOM (`run-summary.test.ts`).

export const TERMINAL: AgentRunStatus[] = ["done", "failed", "cancelled"]

export const STOP_REASON_TEXT: Record<string, string> = {
  plan_exhausted: "план исчерпан",
  step_limit: "достигнут лимит шагов",
  replan_limit: "достигнут лимит перестроек",
  model_budget: "исчерпан бюджет модели",
  model_error: "сбой модели",
  model_schema: "модель ответила не по схеме",
  judge_failed: "судья не принял итог",
}

export const STATUS: Record<AgentRunStatus, { label: string; tone: string; dot: string }> = {
  queued: { label: "В очереди", tone: "text-muted-foreground", dot: "bg-slate-300" },
  running: {
    label: "Выполняется",
    tone: "text-status-info-fg",
    dot: "bg-status-info-dot animate-pulse",
  },
  waiting_approval: {
    label: "Ждёт подтверждения",
    tone: "text-status-warn-fg",
    dot: "bg-status-warn-dot animate-pulse",
  },
  done: { label: "Готово", tone: "text-status-strong-fg", dot: "bg-status-strong-dot" },
  failed: { label: "Ошибка", tone: "text-status-bad-fg", dot: "bg-status-bad-dot" },
  cancelled: { label: "Отменено", tone: "text-muted-foreground", dot: "bg-slate-300" },
}

const TOOL_LABEL: Record<string, string> = {
  read_profile: "Профиль",
  search_vacancies: "Поиск вакансий",
  read_work_terms: "Условия найма",
  score_vacancy: "Оценка вакансии",
  write_cover_letter: "Сопроводительное письмо",
  queue_application: "Отклик",
  task: "Субагент",
}

const SUBAGENT_LABEL: Record<string, string> = {
  country_researcher: "исследователь страны",
  vacancy_assessor: "оценщик вакансии",
}

export const ACTION_LABEL: Record<string, string> = {
  queue_application: "Поставить отклик в очередь автооткликов",
}

export const PARAM_LABEL: Record<string, string> = {
  vacancy_id: "Вакансия",
  cover_note: "Сообщение работодателю",
  lang: "Язык",
  query: "Запрос",
}

export const PLAN_CHANGE_LABEL: Record<string, string> = {
  rebuild: "План пересобран",
  continue: "План скорректирован",
  finish: "План завершён",
}

export function toolLabel(tool: string): string {
  return TOOL_LABEL[tool] ?? tool
}

function roleLabel(role: string): string {
  return SUBAGENT_LABEL[role] ?? role
}

/** Сводка инструмента без технического префикса `tool:` / `task(роль):`. */
export function cleanSummary(summary: string): string {
  return summary.replace(/^[a-z_]+(\([^)]*\))?:\s*/i, "")
}

export function fmtDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return ""
  const sec = Math.round(ms / 1000)
  if (sec < 60) return `${sec} с`
  return `${Math.floor(sec / 60)} мин ${sec % 60} с`
}

export function fmtClock(ms: number): string {
  const sec = Math.max(0, Math.floor(ms / 1000))
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`
}

export function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return one
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few
  return many
}

/** Вакансия из базы аккаунта: название вместо id, балл продукта, текст для цитат, карточка по клику. */
export type VacancyRef = {
  title: string
  company: string | null
  score?: number | null
  text?: string | null
}

export function vacancyName(v: VacancyRef): string {
  return v.company ? `${v.title} · ${v.company}` : v.title
}

// ---------------------------------------------------------------- журнал

export type LogRow = {
  id: number
  kind: "step" | "tool" | "tool-error" | "plan" | "check" | "judge-ok" | "judge-fail" | "info"
  title: string
  detail?: string
  stepId?: string | null
}

function toolTitle(tool: string, role: string | null): string {
  if (tool === "task") return `Субагент: ${role ? roleLabel(role) : "задача"}`
  return role ? `${roleLabel(role)} → ${toolLabel(tool)}` : toolLabel(tool)
}

function toolError(p: Record<string, unknown>): string {
  return typeof p.error === "string" && p.error ? p.error : cleanSummary(String(p.summary ?? ""))
}

function toLogRow(ev: AgentEvent): LogRow | null {
  const p = ev.payload
  const reason = typeof p.reason === "string" && p.reason ? p.reason : undefined
  switch (ev.type) {
    case "plan_created":
      return { id: ev.id, kind: "plan", title: "План составлен" }
    case "step_started":
      return {
        id: ev.id,
        kind: "step",
        title: `Шаг ${String(p.index ?? "")}`,
        detail: String(p.title ?? p.step_id ?? ""),
      }
    case "tool_called": {
      const role = typeof p.subagent === "string" ? p.subagent : null
      const title = toolTitle(String(p.tool ?? ""), role)
      if (p.ok === false) {
        return { id: ev.id, kind: "tool-error", title: `Ошибка инструмента · ${title}`, detail: toolError(p) }
      }
      return { id: ev.id, kind: "tool", title, detail: cleanSummary(String(p.summary ?? "")) }
    }
    case "plan_changed": {
      const action = String(p.action ?? "")
      if (action === "rebuild") return { id: ev.id, kind: "plan", title: "План пересобран", detail: reason }
      if (action === "finish") return { id: ev.id, kind: "plan", title: "Итог принят", detail: reason }
      return {
        id: ev.id,
        kind: "plan",
        title: extractChanges(p.diff).length > 0 ? "План скорректирован" : "План сверен",
        detail: reason,
      }
    }
    case "step_checked":
      return p.done === true
        ? { id: ev.id, kind: "check", title: "Шаг закрыт" }
        : { id: ev.id, kind: "tool-error", title: "Шаг не закрыт", detail: reason }
    case "judge_verdict": {
      const verdict = String(p.verdict ?? "")
      const who = p.level === "step" ? "Самопроверка шага" : "Судья итога"
      if (verdict === "pass") return { id: ev.id, kind: "judge-ok", title: who, detail: "пройдена" }
      if (verdict === "fail") return { id: ev.id, kind: "judge-fail", title: who, detail: reason ?? "не пройдена" }
      return { id: ev.id, kind: "info", title: who, detail: "не проверяется" }
    }
    case "needs_confirmation":
      return { id: ev.id, kind: "info", title: "Действие ждёт подтверждения человека" }
    case "confirmation_resolved": {
      if (p.auto === true) {
        return { id: ev.id, kind: "check", title: "Действие подтверждено автоматически" }
      }
      const edited = Array.isArray(p.edited) && p.edited.length > 0
      return {
        id: ev.id,
        kind: p.approved === true ? "check" : "info",
        title:
          p.approved !== true
            ? "Человек отклонил действие"
            : edited
              ? "Человек подтвердил действие с правкой текста"
              : "Человек подтвердил действие",
      }
    }
    case "failed":
      return { id: ev.id, kind: "tool-error", title: "Запуск упал", detail: typeof p.error === "string" ? p.error : undefined }
    default:
      return null
  }
}

// ---------------------------------------------------------------- инструменты

export type ToolCallRow = { id: number; ok: boolean; text: string; role: string | null }

export type ToolStat = { key: string; label: string; calls: ToolCallRow[]; errors: number }

// ---------------------------------------------------------------- «Сейчас»

const VACANCY_ID_RE = /"vacancy_id":\s*"([^"]+)"/

function vacancyShort(vid: string | undefined, vacancies: Map<string, VacancyRef>): string | null {
  if (!vid) return null
  const ref = vacancies.get(vid)
  return ref ? ref.company || ref.title : vid
}

/** Действие инструмента в настоящем времени: «читает условия Kestrel Analytics». */
export function toolActivity(
  payload: Record<string, unknown>,
  vacancies: Map<string, VacancyRef> = new Map(),
): string {
  const tool = String(payload.tool ?? "")
  const name = vacancyShort(String(payload.summary ?? "").match(VACANCY_ID_RE)?.[1], vacancies)
  switch (tool) {
    case "read_profile":
      return "читает профиль"
    case "search_vacancies":
      return "ищет вакансии в базе"
    case "read_work_terms":
      return name ? `читает условия ${name}` : "читает условия найма"
    case "score_vacancy":
      return name ? `оценивает ${name}` : "оценивает вакансию"
    case "write_cover_letter":
      return name ? `пишет письмо для ${name}` : "пишет сопроводительное письмо"
    case "queue_application":
      return "ставит отклик в очередь"
    case "task": {
      const role = typeof payload.subagent === "string" ? payload.subagent : ""
      if (role === "country_researcher") return "исследователь страны разбирает условия"
      if (role === "vacancy_assessor") return "оценщик разбирает вакансию"
      return "субагент разбирает задачу"
    }
    default:
      return toolLabel(tool).toLowerCase()
  }
}

/** Что агент делает по последнему событию; null — сказать нечего (шаг начался, пауза). */
export function currentActivity(
  events: AgentEvent[],
  vacancies: Map<string, VacancyRef> = new Map(),
): string | null {
  const last = events[events.length - 1]
  if (!last) return null
  switch (last.type) {
    case "run_started":
      return "составляет план"
    case "tool_called":
      return toolActivity(last.payload, vacancies)
    case "plan_changed": {
      const action = String(last.payload.action ?? "")
      if (action === "finish") return "судья проверяет итог по цитатам"
      if (action === "rebuild") return "перестраивает план"
      return null
    }
    default:
      return null
  }
}

// ---------------------------------------------------------------- сводка

export type RunSummary = {
  rows: LogRow[]
  rowsByStep: Map<string, LogRow[]>
  tools: ToolStat[]
  actions: number
  stepsTaken: number
  toolErrors: number
  currentStepId: string | null
  finalVerdict: { verdict: string; reason: string | null } | null
  /** Балл, который поставил `score_vacancy` в этом запуске, по id вакансии. */
  runScores: Map<string, number>
  /** Склейка payload инструментов и наблюдений — по ней ищем упомянутые вакансии. */
  mentions: string
  /** Действия, ушедшие без вопроса в режиме «подтверждать автоматически» (OQ-8). */
  autoActions: { id: number; action: string; params: Record<string, unknown> }[]
  /** Запуск стартовал в режиме «подтверждать автоматически». */
  autoConfirm: boolean
  /** Как планировщик понял цель (`note` первого `plan_created`). */
  understanding: string | null
}

const SCORE_RE = /"vacancy_id":\s*"([^"]+)",\s*"overall_score":\s*(-?\d+(?:\.\d+)?)/

export function summarize(events: AgentEvent[]): RunSummary {
  const rows: LogRow[] = []
  const rowsByStep = new Map<string, LogRow[]>()
  const tools = new Map<string, ToolStat>()
  const runScores = new Map<string, number>()
  const mentionParts: string[] = []
  const autoActions: RunSummary["autoActions"] = []
  let autoConfirm = false
  let understanding: string | null = null
  let actions = 0
  let stepsTaken = 0
  let toolErrors = 0
  let currentStepId: string | null = null
  let finalVerdict: RunSummary["finalVerdict"] = null

  for (const ev of events) {
    const p = ev.payload
    if (ev.type === "run_started" && p.auto_confirm === true) autoConfirm = true
    if (ev.type === "plan_created" && understanding == null && typeof p.note === "string" && p.note.trim()) {
      understanding = p.note.trim()
    }
    if (ev.type === "step_started") {
      stepsTaken += 1
      currentStepId = String(p.step_id ?? "")
    }
    const row = toLogRow(ev)
    if (row) {
      const own = typeof p.step_id === "string" ? p.step_id : null
      row.stepId = own ?? currentStepId
      rows.push(row)
      if (row.kind !== "step" && row.stepId) {
        const list = rowsByStep.get(row.stepId) ?? []
        list.push(row)
        rowsByStep.set(row.stepId, list)
      }
    }
    if (ev.type === "tool_called" || ev.type === "observation") mentionParts.push(JSON.stringify(p))
    if (ev.type === "tool_called") {
      actions += 1
      const tool = String(p.tool ?? "")
      const role = typeof p.subagent === "string" ? p.subagent : null
      const ok = p.ok !== false
      if (!ok) toolErrors += 1
      const key = tool === "task" ? `task:${role ?? ""}` : tool
      const stat = tools.get(key) ?? {
        key,
        label: tool === "task" ? `Субагент · ${role ? roleLabel(role) : "задача"}` : toolLabel(tool),
        calls: [],
        errors: 0,
      }
      stat.calls.push({
        id: ev.id,
        ok,
        text: ok ? cleanSummary(String(p.summary ?? "")) : toolError(p),
        role: role && tool !== "task" ? roleLabel(role) : null,
      })
      if (!ok) stat.errors += 1
      tools.set(key, stat)
      if (tool === "score_vacancy" && ok) {
        const m = String(p.summary ?? "").match(SCORE_RE)
        if (m) runScores.set(m[1], Number(m[2]))
      }
    }
    if (ev.type === "confirmation_resolved" && p.auto === true) {
      const card = (p.card ?? {}) as { action?: unknown; params?: unknown }
      autoActions.push({
        id: ev.id,
        action: String(card.action ?? ""),
        params: (card.params && typeof card.params === "object" ? card.params : {}) as Record<
          string,
          unknown
        >,
      })
      mentionParts.push(JSON.stringify(card.params ?? {}))
    }
    if (ev.type === "judge_verdict" && p.level !== "step") {
      finalVerdict = {
        verdict: String(p.verdict ?? ""),
        reason: typeof p.reason === "string" ? p.reason : null,
      }
    }
  }
  return {
    rows,
    rowsByStep,
    tools: [...tools.values()],
    actions,
    stepsTaken,
    toolErrors,
    currentStepId,
    finalVerdict,
    runScores,
    mentions: mentionParts.join("\n"),
    autoActions,
    autoConfirm,
    understanding,
  }
}

// ---------------------------------------------------------------- план и вакансии

export type PlanProgress = {
  total: number
  done: number
  /** Номер текущего шага среди неснятых (1…total); 0 — плана нет. */
  current: number
  currentTitle: string | null
  pct: number
}

export function planProgress(
  plan: RunPlanItem[] | null,
  currentStepId: string | null,
  live: boolean,
): PlanProgress {
  const active = (plan ?? []).filter((s) => s.status !== "dropped")
  const total = active.length
  const done = active.filter((s) => s.status === "done").length
  const idx = currentStepId ? active.findIndex((s) => s.id === currentStepId) : -1
  const pending = active.find((s) => s.status !== "done") ?? null
  const currentStep = live && idx >= 0 && active[idx].status !== "done" ? active[idx] : pending
  const current =
    total === 0 ? 0 : live ? (currentStep ? active.indexOf(currentStep) + 1 : total) : done
  return {
    total,
    done,
    current,
    currentTitle: currentStep?.title ?? null,
    pct: total > 0 ? Math.round((done / total) * 100) : 0,
  }
}

export type RunVacancy = { id: string; ref: VacancyRef; score: number | null; scoredInRun: boolean }

/** Вакансии, которые агент трогал: id в событиях, карточке и ответе плюс названия из ответа. */
export function runVacancies(
  view: RunView,
  summary: RunSummary,
  vacancies: Map<string, VacancyRef> | undefined,
): RunVacancy[] {
  if (!vacancies || vacancies.size === 0) return []
  const haystack = `${summary.mentions}\n${JSON.stringify(view.card?.params ?? {})}\n${view.answer ?? ""}`
  const answerLower = (view.answer ?? "").toLowerCase()
  const out: RunVacancy[] = []
  for (const [id, ref] of vacancies) {
    const hit =
      haystack.includes(id) || (ref.title.length >= 8 && answerLower.includes(ref.title.toLowerCase()))
    if (!hit) continue
    const runScore = summary.runScores.get(id)
    out.push({
      id,
      ref,
      score: runScore ?? ref.score ?? null,
      scoredInRun: runScore != null,
    })
  }
  return out
}

// ---------------------------------------------------------------- цитаты

/** Нормализация для сверки цитаты с текстом: регистр, «ё», пробелы (как сверка цитат судьёй). */
export function normalizeQuote(text: string): string {
  return text.toLowerCase().replace(/ё/g, "е").replace(/\s+/g, " ").trim()
}

/**
 * В тексте какой вакансии стоит цитата из ответа: сначала вакансии запуска, потом вся база.
 * Короче 8 знаков — не цитата (тот же порог, что у проверки цитат кодом в судье).
 */
export function findQuoteVacancy(
  quote: string,
  vacancies: Map<string, VacancyRef> | undefined,
  preferred: string[] = [],
): string | null {
  const needle = normalizeQuote(quote)
  if (needle.length < 8 || !vacancies) return null
  const order = [...preferred, ...[...vacancies.keys()].filter((id) => !preferred.includes(id))]
  for (const id of order) {
    const text = vacancies.get(id)?.text
    if (text && normalizedText(text).includes(needle)) return id
  }
  return null
}

// Тексты вакансий длинные, а ответ перерисовывается: нормализуем каждый текст один раз.
const NORMALIZED = new Map<string, string>()

function normalizedText(text: string): string {
  let hit = NORMALIZED.get(text)
  if (hit === undefined) {
    if (NORMALIZED.size > 300) NORMALIZED.clear()
    hit = normalizeQuote(text)
    NORMALIZED.set(text, hit)
  }
  return hit
}
