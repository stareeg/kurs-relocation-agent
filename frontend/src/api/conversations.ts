import { api, LLM_TIMEOUT_MS } from "@/api/client"
import type { AttachmentOut, AttachmentRoute } from "@/api/attachments"

// Разговоры по вакансии (R-4): единая лента HR-переписки + уточняющего LLM-чата. Типы заданы
// локально (не из автогена schema.d.ts): поле kind появляется в схеме только после регена openapi,
// а клиент должен типизироваться сразу. После `npm run gen-api:offline` можно перевести на автоген.

export type MessageKind = "hr_in" | "hr_out" | "llm_user" | "llm_assistant"

export interface ConvMessage {
  id: number
  thread_id: number
  direction: string
  kind: MessageKind
  body: string
  sent_at?: string | null
  created_at?: string | null
  /** FR3-74: LLM не уверена в авторе при разборе дампа. */
  author_uncertain?: boolean
  /** Сообщение-источник, если это ответ через composer «Ответить». */
  reply_to_message_id?: number | null
  /** Картинки-вложения (план chat_image_attachments_2026_08_03.md, Э2-5 наполнит с бэкенда). */
  attachments?: AttachmentOut[]
}

export interface ConvThread {
  id: number
  vacancy_id: string
  contact_name: string
  channel: string
  company: string
  status: string
  pinned: boolean
  message_count: number
  last_message_at?: string | null
  // RD-13: направление/время последней РЕАЛЬНОЙ hr-реплики (без llm_* болтовни) — радар
  // «ждёт меня / ждём их» в сайдбаре. null — реальной переписки в треде ещё не было.
  last_hr_kind?: "hr_in" | "hr_out" | null
  last_hr_at?: string | null
  // RD-15: ближайший назначенный этап (interview_stages) — извлечён фоном из HR-переписки.
  next_stage_type?: string | null
  next_stage_at?: string | null
  // FR2-86: предложение сдвинуть воронку по сигналу из диалога (чип в шапке).
  suggested_funnel_status?: string | null
  suggested_stage_type?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface ConversationOut {
  vacancy_id: string
  thread: ConvThread | null
  messages: ConvMessage[]
  hr_link?: string
}

export interface ConversationListOut {
  items: ConvThread[]
}

export interface ConversationImportResult {
  vacancy_id: string
  thread: ConvThread | null
  messages: ConvMessage[]
  hr_link?: string
  added: number
  /** Картинки из запроса, не распознанные как переписка (Э4-1) — предложить приложить как вложение. */
  unrecognized_attachment_ids: number[]
}

export interface ConversationOutreachPayload {
  company?: string
  position?: string
  contact_name?: string
  hr_link?: string
  vacancy_url?: string
  initial_text?: string
  vacancy_text?: string
  first_contact_at?: string | null
}

export interface ConversationOutreachResult {
  vacancy_id: string
  thread: ConvThread
  scored: boolean
  conversation: ConversationOut
}

export interface ConversationVacancyTextResult {
  vacancy_id: string
  scored: boolean
  overall_score?: number | null
}

export interface ConversationIdentityResult {
  vacancy_id: string
  company: string
  title: string
  scored: boolean
  overall_score?: number | null
}

// RD-14: витрина дня «Чатов» — 4 SQL-агрегата, без LLM.
export interface AttentionStage {
  vacancy_id: string
  company: string
  stage_type: string
  scheduled_at?: string | null
  format: string
}

export interface AttentionStrongJob {
  vacancy_id: string
  title?: string | null
  company?: string | null
  overall_score?: number | null
  scored_at?: string | null
}

export interface TodayAttention {
  reply: ConvThread[]
  remind: ConvThread[]
  upcoming: AttentionStage[]
  strong_unapplied: AttentionStrongJob[]
}

// GET /api/conversations/attention — очередь дня для пустого состояния «Чатов».
export function fetchTodayAttention() {
  return api.get<TodayAttention>("/api/conversations/attention")
}

// GET /api/conversations/{vacancy_id} — разговор по вакансии (тред + лента). Нет PG → thread=null.
export function fetchConversation(vacancyId: string) {
  return api.get<ConversationOut>(`/api/conversations/${encodeURIComponent(vacancyId)}`)
}

// GET /api/conversations — все разговоры (свежие сверху) для хаба.
export function fetchConversations(includeArchived = false) {
  return api.get<ConversationListOut>(`/api/conversations?include_archived=${includeArchived}`)
}

// GET /api/conversations/active-count — активные (не в архиве) для бейджа в сайдбаре.
export function fetchActiveConversationsCount() {
  return api.get<{ count: number }>("/api/conversations/active-count")
}

// POST /api/conversations/{vacancy_id}/messages — добавить реплику (HR-сообщение / своё в HR).
export function addConversationMessage(
  vacancyId: string,
  body: { kind: MessageKind; body: string; sent_at?: string | null },
) {
  return api.post<ConversationOut>(
    `/api/conversations/${encodeURIComponent(vacancyId)}/messages`,
    body,
  )
}

// POST /api/conversations/{vacancy_id}/open — FR2-87: закрепить привязку к известной вакансии
// без вставленного дампа. Гарантирует запись в hr_threads, иначе диалог не появляется в списке
// слева и теряется при уходе со вкладки без единого сообщения.
export function openConversation(vacancyId: string) {
  return api.post<ConversationOut>(`/api/conversations/${encodeURIComponent(vacancyId)}/open`)
}

// DELETE /api/conversations/{vacancy_id}/messages/{message_id} — удалить одну реплику ленты.
export function deleteConversationMessage(vacancyId: string, messageId: number) {
  return api.del<ConversationOut>(
    `/api/conversations/${encodeURIComponent(vacancyId)}/messages/${messageId}`,
  )
}

// POST /api/conversations/{vacancy_id}/import — разобрать вставленный дамп переписки на реплики.
// attachmentIds (Э4-1) — скрины переписки: можно без текста, можно вместе с ним.
// attachmentRoutes (Э4-3) — ярлык-переключатель ветки с чипа композера, только для вложений, где
// владелец переопределил угадку классификатора (см. RouteBadge).
export function importConversationDump(
  vacancyId: string,
  text: string,
  attachmentIds: number[] = [],
  attachmentRoutes: Record<number, AttachmentRoute> = {},
) {
  return api.post<ConversationImportResult>(
    `/api/conversations/${encodeURIComponent(vacancyId)}/import`,
    { text, attachment_ids: attachmentIds, attachment_routes: attachmentRoutes },
    { timeoutMs: LLM_TIMEOUT_MS },
  )
}

export interface FunnelSuggestionApplyResult {
  vacancy_id: string
  status: string | null
  applied: boolean
}

export interface FunnelSuggestionDismissResult {
  vacancy_id: string
  dismissed: boolean
}

// POST /api/conversations/{vacancy_id}/funnel-suggestion/apply — FR2-86: клик по чипу.
export function applyFunnelSuggestion(vacancyId: string) {
  return api.post<FunnelSuggestionApplyResult>(
    `/api/conversations/${encodeURIComponent(vacancyId)}/funnel-suggestion/apply`,
  )
}

// POST /api/conversations/{vacancy_id}/funnel-suggestion/dismiss — FR2-86: снять чип.
export function dismissFunnelSuggestion(vacancyId: string) {
  return api.post<FunnelSuggestionDismissResult>(
    `/api/conversations/${encodeURIComponent(vacancyId)}/funnel-suggestion/dismiss`,
  )
}

// POST /api/conversations/outreach — HR-first: job в воронке + тред. Цепочка из нескольких
// последовательных LLM-вызовов (парсинг → скоринг → разбор переписки) легко занимает 30-40с —
// дефолтный DEFAULT_TIMEOUT_MS клиента обрывал запрос раньше бэкенда, хотя тот успешно создавал
// вакансию (ложный тост «не удалось создать»).
export function createOutreachVacancy(body: ConversationOutreachPayload) {
  return api.post<ConversationOutreachResult>("/api/conversations/outreach", body, {
    timeoutMs: LLM_TIMEOUT_MS,
  })
}

export interface VacancyAttachSuggestion {
  vacancy_id: string
  company: string
  title?: string | null
  match_via: string
  label: string
  status?: string | null
  activity_at?: string | null
}

export interface VacancyAttachSuggestResult {
  /** Ровно один кандидат — иначе null (FR3-72, без silent pick при коллизии). */
  suggestion: VacancyAttachSuggestion | null
  /** 0 / 1 / много: чип или пикер. */
  candidates: VacancyAttachSuggestion[]
}

// POST /api/conversations/suggest-attach — FR2-87 / FR3-72: найти вакансию(и) под дамп.
export function suggestVacancyAttach(body: {
  text?: string
  company?: string
  vacancy_url?: string
}) {
  return api.post<VacancyAttachSuggestResult>("/api/conversations/suggest-attach", body)
}

// POST /api/conversations/{vacancy_id}/vacancy-text — прикрепить полный текст вакансии (сайт без
// автопарсинга, скопирован вручную) вместо ссылки на hh/gm; заменяет бриф и пересчитывает скор.
export function attachVacancyText(vacancyId: string, text: string) {
  return api.post<ConversationVacancyTextResult>(
    `/api/conversations/${encodeURIComponent(vacancyId)}/vacancy-text`,
    { text },
    { timeoutMs: LLM_TIMEOUT_MS },
  )
}

// POST /api/conversations/{vacancy_id}/identity — карандаш в шапке: поправить компанию/должность
// (executive-recruiter кейс — роль ещё не названа на первый контакт). Пересчитывает скор, если
// уже есть текст вакансии.
export function updateConversationIdentity(
  vacancyId: string,
  body: { company: string; title: string },
) {
  return api.post<ConversationIdentityResult>(
    `/api/conversations/${encodeURIComponent(vacancyId)}/identity`,
    body,
    { timeoutMs: LLM_TIMEOUT_MS },
  )
}

// PATCH /api/conversations/by-thread/{thread_id} — статус разговора, имя HR, закреп.
export function patchConversationThread(
  threadId: number,
  body: {
    status?: string
    contact_name?: string
    hr_link?: string
    channel?: string
    company?: string
    pinned?: boolean
  },
) {
  return api.patch<ConvThread>(`/api/conversations/by-thread/${threadId}`, body)
}

// DELETE /api/conversations/by-thread/{thread_id} — удалить разговор (каскадом реплики).
export function deleteConversationThread(threadId: number) {
  return api.del<void>(`/api/conversations/by-thread/${threadId}`)
}

export function hrContactName(thread?: { contact_name?: string | null } | null): string {
  return (thread?.contact_name ?? "").trim()
}

/** Заголовок в шапке чата: компания · должность (не имя HR). */
export function vacancyHeading(
  job: { company?: string | null; title?: string | null },
  thread?: { company?: string | null } | null,
): string {
  const company = (job.company ?? thread?.company ?? "").trim()
  const title = (job.title ?? "").trim()
  if (company && title) return `${company} · ${title}`
  if (company) return company
  if (title) return title
  return "Вакансия"
}

/** URL для открытия Telegram-диалога с HR. */
export function resolveHrTelegramUrl(hrLink: string | null | undefined): string | null {
  const raw = (hrLink ?? "").trim()
  if (!raw) return null
  if (raw.startsWith("tg:@")) return `https://t.me/${raw.slice(4)}`
  if (/^https?:\/\/t\.me\//i.test(raw)) return raw
  if (raw.startsWith("@")) return `https://t.me/${raw.slice(1)}`
  if (raw.includes("t.me/")) {
    return raw.startsWith("http") ? raw : `https://${raw.replace(/^\/\//, "")}`
  }
  return null
}

/** Подпись HR-реплики / исходящей к HR в ленте. */
export function hrMessageLabel(kind: "hr_in" | "hr_out", contactName?: string | null): string {
  const hr = hrContactName({ contact_name: contactName }) || "HR"
  return kind === "hr_out" ? `Я → ${hr}` : hr
}

/** Текст диалога с HR для буфера обмена — только реальные реплики, без агента. */
export function formatHrDialogText(
  messages: { kind: MessageKind; body: string }[],
  contactName?: string | null,
): string {
  const hr = hrContactName({ contact_name: contactName }) || "HR"
  return messages
    .filter((m) => m.kind === "hr_in" || m.kind === "hr_out")
    .map((m) => `${m.kind === "hr_out" ? "Я" : hr}: ${m.body.trim()}`)
    .join("\n\n")
}

/** Подпись реплики любого типа (HR/агент/своя) — для копирования выделения сообщений. */
export function messageAuthorLabel(kind: MessageKind, contactName?: string | null): string {
  if (kind === "hr_in" || kind === "hr_out") return hrMessageLabel(kind, contactName)
  return kind === "llm_assistant" ? "Агент" : "Я"
}

// План §6.6: у сообщения без текста (картинка и есть пузырь) при копировании подставляется
// заголовок распознавания — иначе вставка выделения в Telegram теряет смысл.
function messageCopyBody(m: { body: string; attachments?: AttachmentOut[] }): string {
  const body = m.body.trim()
  if (body) return body
  const title = m.attachments?.[0]?.analysis?.title
  return m.attachments?.length ? `[картинка: ${title ?? "вложение"}]` : body
}

/** Текст выделенных сообщений (любого типа, в хронологическом порядке) для буфера обмена. */
export function formatMessagesForCopy(
  messages: { kind: MessageKind; body: string; attachments?: AttachmentOut[] }[],
  contactName?: string | null,
): string {
  return messages
    .map((m) => `${messageAuthorLabel(m.kind, contactName)}: ${messageCopyBody(m)}`)
    .join("\n\n")
}

// Заголовок разговора: имя HR (если задано), иначе компания или ID вакансии.
export function conversationTitle(t: {
  company?: string | null
  vacancy_id: string
  contact_name?: string | null
}): string {
  const name = hrContactName(t)
  if (name) return name
  const company = (t.company || "").trim()
  return company || `Вакансия ${t.vacancy_id}`
}

/** Подзаголовок в списке чатов: компания, когда в заголовке уже имя HR. */
export function conversationListSubtitle(t: {
  company?: string | null
  contact_name?: string | null
}): string | null {
  const name = hrContactName(t)
  const company = (t.company || "").trim()
  if (name && company) return company
  return null
}
