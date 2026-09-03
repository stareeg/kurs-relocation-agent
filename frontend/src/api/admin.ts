import type { components } from "@/api/schema"
import { api, apiFetchBlob } from "@/api/client"

export type AdminSummary = components["schemas"]["AdminSummary"]
export type AdminPeoplePage = components["schemas"]["AdminPeoplePage"]
export type AdminAttention = components["schemas"]["AdminAttention"]
export type AdminSpend = components["schemas"]["AdminSpend"]
export type AdminSpendRow = components["schemas"]["AdminSpendRow"]
export type AdminSpendAlert = components["schemas"]["AdminSpendAlert"]
export type AdminSpendOver = components["schemas"]["AdminSpendOver"]
export type AdminStaleAccount = components["schemas"]["AdminStaleAccount"]
export type AdminUserRow = components["schemas"]["AdminUserRow"]
export type AdminUserDetail = components["schemas"]["AdminUserDetail"]
export type AdminKeyRequest = components["schemas"]["AdminKeyRequest"]
export type AdminLogRow = components["schemas"]["AdminLogRow"]
export type AdminTaskRow = components["schemas"]["AdminTaskRow"]
export type AdminHealth = components["schemas"]["AdminHealth"]
export type AdminOnboardingFunnel = components["schemas"]["AdminOnboardingFunnel"]
export type AdminLogPage = components["schemas"]["AdminLogPage"]
export type AdminAuditPage = components["schemas"]["AdminAuditPage"]
export type AdminAuditRow = components["schemas"]["AdminAuditRow"]
export type AdminKeyVerify = components["schemas"]["AdminKeyVerify"]
export type AdminKeyBalance = components["schemas"]["AdminKeyBalance"]
export type AdminKeyBalances = components["schemas"]["AdminKeyBalances"]
export type AdminTasks = components["schemas"]["AdminTasks"]
export type AdminTaskDetail = components["schemas"]["AdminTaskDetail"]
export type AdminTaskKindCount = components["schemas"]["AdminTaskKindCount"]
export type AdminTaskReasonCount = components["schemas"]["AdminTaskReasonCount"]
export type AdminDiagnosis = components["schemas"]["AdminDiagnosis"]
export type AdminDiagnosisItem = components["schemas"]["AdminDiagnosisItem"]
export type AdminTables = components["schemas"]["AdminTables"]
export type AdminTableSize = components["schemas"]["AdminTableSize"]
export type AdminCount = components["schemas"]["AdminCount"]
export type AdminDeviceSession = components["schemas"]["AdminDeviceSession"]
export type AdminSpendSegment = components["schemas"]["AdminSpendSegment"]
export type AdminSupportMessage = components["schemas"]["AdminSupportMessage"]
export type AdminSupportThread = components["schemas"]["AdminSupportThread"]
export type AdminRecentAction = components["schemas"]["AdminRecentAction"]
export type AdminUserPipeline = components["schemas"]["AdminUserPipeline"]
export type AdminPipelinePlatform = components["schemas"]["AdminPipelinePlatform"]
export type AdminPipelineBrief = components["schemas"]["AdminPipelineBrief"]

export function fetchAdminSummary() {
  return api.get<AdminSummary>("/api/admin/summary")
}

export type AdminPeopleQuery = {
  q?: string
  status?: string
  onboarding?: string
  signal?: string
  sort?: string
  limit?: number
  offset?: number
}

export function fetchAdminPeople(query: AdminPeopleQuery = {}) {
  const params = new URLSearchParams()
  if (query.q) params.set("q", query.q)
  if (query.status) params.set("status", query.status)
  if (query.onboarding) params.set("onboarding", query.onboarding)
  if (query.signal) params.set("signal", query.signal)
  if (query.sort) params.set("sort", query.sort)
  if (query.limit != null) params.set("limit", String(query.limit))
  if (query.offset != null) params.set("offset", String(query.offset))
  const suffix = params.toString()
  return api.get<AdminPeoplePage>(`/api/admin/people${suffix ? `?${suffix}` : ""}`)
}

export function fetchAdminAttention() {
  return api.get<AdminAttention>("/api/admin/attention")
}

export type AdminSpendGroup = "day" | "model" | "feature" | "account"

export function fetchAdminSpend(
  days = 14,
  groupBy: AdminSpendGroup = "day",
  accountId?: number,
) {
  const params = new URLSearchParams({ days: String(days), group_by: groupBy })
  if (accountId != null) params.set("account_id", String(accountId))
  return api.get<AdminSpend>(`/api/admin/spend?${params.toString()}`)
}

export function fetchAdminSupportThread(accountId: number) {
  return api.get<AdminSupportThread>(`/api/admin/users/${accountId}/support`)
}

export function sendAdminSupportMessage(
  accountId: number,
  body: { channel: "user" | "agent"; text: string; reply_to_id?: number | null },
) {
  return api.post<AdminSupportThread>(`/api/admin/users/${accountId}/support`, body)
}

export function revokeAdminUserSession(accountId: number, sessionId: number) {
  return api.post<{ ok: boolean }>(`/api/admin/users/${accountId}/sessions/${sessionId}/revoke`)
}

export function setAdminSpendAlert(usd: number) {
  return api.patch<AdminSpendAlert>("/api/admin/spend-alert", { usd })
}

export type AdminLogsQuery = {
  since?: string
  until?: string
  level?: string
  account_id?: number
  telegram_user_id?: number
  logger?: string
  event?: string
  q?: string
  cursor?: string
  limit?: number
}

export function fetchAdminLogs(query: AdminLogsQuery = {}) {
  const params = new URLSearchParams()
  if (query.since) params.set("since", query.since)
  if (query.until) params.set("until", query.until)
  if (query.level) params.set("level", query.level)
  if (query.account_id != null) params.set("account_id", String(query.account_id))
  if (query.telegram_user_id != null) params.set("telegram_user_id", String(query.telegram_user_id))
  if (query.logger) params.set("logger", query.logger)
  if (query.event) params.set("event", query.event)
  if (query.q) params.set("q", query.q)
  if (query.cursor) params.set("cursor", query.cursor)
  if (query.limit != null) params.set("limit", String(query.limit))
  const suffix = params.toString()
  return api.get<AdminLogPage>(`/api/admin/logs${suffix ? `?${suffix}` : ""}`)
}

export type AdminAuditQuery = {
  since?: string
  until?: string
  account_id?: number
  telegram_user_id?: number
  cursor?: string
  limit?: number
}

export function fetchAdminAudit(query: AdminAuditQuery = {}) {
  const params = new URLSearchParams()
  if (query.since) params.set("since", query.since)
  if (query.until) params.set("until", query.until)
  if (query.account_id != null) params.set("account_id", String(query.account_id))
  if (query.telegram_user_id != null) params.set("telegram_user_id", String(query.telegram_user_id))
  if (query.cursor) params.set("cursor", query.cursor)
  if (query.limit != null) params.set("limit", String(query.limit))
  const suffix = params.toString()
  return api.get<AdminAuditPage>(`/api/admin/audit${suffix ? `?${suffix}` : ""}`)
}

export function fetchAdminUser(accountId: number) {
  return api.get<AdminUserDetail>(`/api/admin/users/${accountId}`)
}

export function fetchAdminUserDiagnosis(accountId: number) {
  return api.get<AdminDiagnosis>(`/api/admin/users/${accountId}/diagnosis`)
}

// --- Автопросмотр / автоотклики пользователя (вкладка «Автоматизация») ---

export function fetchAdminUserPipeline(accountId: number) {
  return api.get<AdminUserPipeline>(`/api/admin/users/${accountId}/pipeline`)
}

export function pauseAdminAutoApply(accountId: number) {
  return api.post<{ ok: boolean }>(`/api/admin/users/${accountId}/auto-apply/pause`)
}

export function resumeAdminAutoApply(accountId: number) {
  return api.post<{ ok: boolean }>(`/api/admin/users/${accountId}/auto-apply/resume`)
}

export function clearAdminAutoApplyQueue(accountId: number) {
  return api.post<{ cleared: number }>(`/api/admin/users/${accountId}/auto-apply/clear`)
}

export function stopAdminDiscovery(accountId: number, platform?: "hh" | "getmatch" | "habr") {
  return api.post<{ stopped: string[] }>(`/api/admin/users/${accountId}/discovery/stop`, {
    platform: platform ?? null,
  })
}

export function clearAdminDiscoveryLog(accountId: number) {
  return api.post<{ ok: boolean }>(`/api/admin/users/${accountId}/discovery/clear-log`)
}

export function disableAdminUser(accountId: number, reason = "") {
  return api.post<{ ok: boolean }>(`/api/admin/users/${accountId}/disable`, { reason })
}

export function enableAdminUser(accountId: number) {
  return api.post<{ ok: boolean }>(`/api/admin/users/${accountId}/enable`)
}

export function revokeAdminUserSessions(accountId: number) {
  return api.post<{ revoked: number }>(`/api/admin/users/${accountId}/revoke-sessions`)
}

export function sendAdminTelegram(accountId: number, text: string) {
  return api.post<{ ok: boolean }>(`/api/admin/users/${accountId}/telegram`, { text })
}

export function rejectAdminKey(requestId: number) {
  return api.post<{ ok: boolean }>(`/api/admin/keys/${requestId}/reject`)
}

/** Выдать или перевыпустить ключ человеку — по аккаунту, не по заявке. */
export function issueAdminKey(accountId: number, key: string, label?: string) {
  return api.post<{ ok: boolean }>(`/api/admin/users/${accountId}/key`, {
    key,
    label: label || null,
  })
}

export function revokeAdminKey(accountId: number) {
  return api.del<{ ok: boolean }>(`/api/admin/users/${accountId}/key`)
}

export function verifyAdminKey(key: string) {
  return api.post<AdminKeyVerify>("/api/admin/keys/verify", { key })
}

export function verifyStoredAdminKey(accountId: number) {
  return api.post<AdminKeyVerify>(`/api/admin/users/${accountId}/key/verify`)
}

export function refreshAdminKeyBalances() {
  return api.post<AdminKeyBalances>("/api/admin/keys/balances")
}

export type AdminTasksQuery = {
  status?: string
  kind?: string
  limit?: number
}

export function fetchAdminTasks(query: AdminTasksQuery = {}) {
  const params = new URLSearchParams()
  if (query.status) params.set("status", query.status)
  if (query.kind) params.set("kind", query.kind)
  if (query.limit != null) params.set("limit", String(query.limit))
  const suffix = params.toString()
  return api.get<AdminTasks>(`/api/admin/tasks${suffix ? `?${suffix}` : ""}`)
}

export function fetchAdminTables() {
  return api.get<AdminTables>("/api/admin/tables")
}

export function retryAdminTask(taskId: number) {
  return api.post<AdminTaskDetail>(`/api/admin/tasks/${taskId}/retry`)
}

export function cancelAdminTask(taskId: number) {
  return api.post<AdminTaskDetail>(`/api/admin/tasks/${taskId}/cancel`)
}

export function retryAdminTasksKind(kind: string, reason = "") {
  return api.post<AdminCount>("/api/admin/tasks/retry", { kind, reason })
}

export function cancelAdminTasksKind(kind: string, reason = "") {
  return api.post<AdminCount>("/api/admin/tasks/cancel-kind", { kind, reason })
}

export function reclaimAdminTasks() {
  return api.post<AdminCount>("/api/admin/tasks/reclaim")
}

export function purgeAdminLogs(days: 30 | 60 | 90) {
  return api.post<AdminCount>("/api/admin/logs/purge", { days })
}

export function repairAdminFriendships() {
  return api.post<{ ok: boolean }>("/api/admin/friendships/repair")
}

export function setAdminUserNote(accountId: number, note: string) {
  return api.patch<{ ok: boolean }>(`/api/admin/users/${accountId}/note`, { note })
}

export function setAdminUserRole(accountId: number, role: "owner" | "member") {
  return api.post<{ ok: boolean }>(`/api/admin/users/${accountId}/role`, { role })
}

export async function downloadAdminUserLogs(accountId: number, hours = 72): Promise<void> {
  const { blob, filename } = await apiFetchBlob(
    `/api/admin/users/${accountId}/logs?hours=${hours}`,
    { skipSeriousToast: true },
  )
  const href = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = href
  a.download = filename ?? `support_bundle-${accountId}.zip`
  a.rel = "noopener"
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(href)
}
