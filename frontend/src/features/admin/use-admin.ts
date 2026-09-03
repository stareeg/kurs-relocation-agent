import { useEffect, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import {
  cancelAdminTask,
  cancelAdminTasksKind,
  clearAdminAutoApplyQueue,
  clearAdminDiscoveryLog,
  disableAdminUser,
  downloadAdminUserLogs,
  enableAdminUser,
  fetchAdminAttention,
  fetchAdminAudit,
  fetchAdminLogs,
  fetchAdminPeople,
  fetchAdminSpend,
  fetchAdminSummary,
  fetchAdminSupportThread,
  fetchAdminTables,
  fetchAdminTasks,
  fetchAdminUser,
  fetchAdminUserDiagnosis,
  fetchAdminUserPipeline,
  issueAdminKey,
  pauseAdminAutoApply,
  purgeAdminLogs,
  reclaimAdminTasks,
  rejectAdminKey,
  refreshAdminKeyBalances,
  repairAdminFriendships,
  resumeAdminAutoApply,
  retryAdminTask,
  retryAdminTasksKind,
  revokeAdminKey,
  revokeAdminUserSession,
  revokeAdminUserSessions,
  sendAdminSupportMessage,
  sendAdminTelegram,
  stopAdminDiscovery,
  setAdminSpendAlert,
  setAdminUserNote,
  setAdminUserRole,
  verifyAdminKey,
  verifyStoredAdminKey,
  type AdminAuditQuery,
  type AdminLogsQuery,
  type AdminPeopleQuery,
  type AdminSpendGroup,
  type AdminTasksQuery,
} from "@/api/admin"

/** Шаг опроса витрины. Было 30 с и опрашивалось даже в скрытой вкладке (Этап 1.4). */
export const ADMIN_POLL_MS = 20_000
/** Живой хвост журнала — 5 с, выключается кнопкой (Этап 5.3). */
export const JOURNAL_LIVE_MS = 5_000
/** Лента поддержки в открытой карточке — реже журнала, без опроса скрытой вкладки. */
export const SUPPORT_POLL_MS = 8_000
/**
 * Бейдж дел в сайдбаре опрашивается реже раздела: он висит на каждом экране продукта весь
 * день, а «появилось дело» — не та новость, ради которой стоит ходить на сервер трижды в
 * минуту. Когда раздел открыт, react-query берёт наименьший интервал наблюдателей, то есть
 * `ADMIN_POLL_MS`, и лишнего запроса не возникает — ключ у запроса один и тот же.
 */
export const ADMIN_BADGE_POLL_MS = 120_000

/**
 * Видима ли вкладка. Скрытую опрашивать бессмысленно: оператор её не смотрит, а каждый опрос
 * — это полтора десятка агрегатов по всему флоту.
 */
export function useDocumentVisible(): boolean {
  const [visible, setVisible] = useState(
    () => typeof document === "undefined" || document.visibilityState !== "hidden",
  )
  useEffect(() => {
    if (typeof document === "undefined") return
    const onChange = () => setVisible(document.visibilityState !== "hidden")
    document.addEventListener("visibilitychange", onChange)
    return () => document.removeEventListener("visibilitychange", onChange)
  }, [])
  return visible
}

/** Интервал опроса для всех витрин админки разом: пауза, пока вкладка скрыта. */
export function useAdminPollInterval(enabled: boolean, everyMs = ADMIN_POLL_MS): number | false {
  const visible = useDocumentVisible()
  return enabled && visible ? everyMs : false
}

export function useAdminSummary(enabled: boolean) {
  return useQuery({
    queryKey: ["admin", "summary"],
    queryFn: fetchAdminSummary,
    enabled,
    staleTime: 10_000,
    refetchInterval: useAdminPollInterval(enabled),
  })
}

export function useAdminPeople(enabled: boolean, query: AdminPeopleQuery) {
  return useQuery({
    queryKey: ["admin", "people", query],
    queryFn: () => fetchAdminPeople(query),
    enabled,
    staleTime: 10_000,
    refetchInterval: useAdminPollInterval(enabled),
    // Смена фильтра не должна мигать спиннером поверх уже показанного списка.
    placeholderData: (previous) => previous,
  })
}

export function useAdminAttention(enabled: boolean, everyMs = ADMIN_POLL_MS) {
  return useQuery({
    queryKey: ["admin", "attention"],
    queryFn: fetchAdminAttention,
    enabled,
    staleTime: 10_000,
    refetchInterval: useAdminPollInterval(enabled, everyMs),
  })
}

export function useAdminSpend(
  enabled: boolean,
  days = 14,
  groupBy: AdminSpendGroup = "day",
  accountId?: number,
) {
  return useQuery({
    queryKey: ["admin", "spend", days, groupBy, accountId ?? null],
    queryFn: () => fetchAdminSpend(days, groupBy, accountId),
    enabled,
    staleTime: 60_000,
    refetchInterval: useAdminPollInterval(enabled),
    placeholderData: (previous) => previous,
  })
}

export function useAdminLogs(
  enabled: boolean,
  key: object,
  live: boolean,
  buildQuery: () => AdminLogsQuery,
) {
  const visible = useDocumentVisible()
  return useQuery({
    queryKey: ["admin", "logs", key],
    queryFn: () => fetchAdminLogs(buildQuery()),
    enabled,
    staleTime: live ? 0 : 10_000,
    refetchInterval: enabled && visible && live ? JOURNAL_LIVE_MS : false,
    placeholderData: (previous) => previous,
  })
}

export function useAdminAudit(
  enabled: boolean,
  key: object,
  live: boolean,
  buildQuery: () => AdminAuditQuery,
) {
  const visible = useDocumentVisible()
  return useQuery({
    queryKey: ["admin", "audit", key],
    queryFn: () => fetchAdminAudit(buildQuery()),
    enabled,
    staleTime: live ? 0 : 10_000,
    refetchInterval: enabled && visible && live ? JOURNAL_LIVE_MS : false,
    placeholderData: (previous) => previous,
  })
}

export function useAdminUser(accountId: number | null) {
  return useQuery({
    queryKey: ["admin", "user", accountId],
    queryFn: () => fetchAdminUser(accountId!),
    enabled: accountId != null,
    staleTime: 10_000,
    // Тот же шаг, что у списка: иначе «$ сегодня» в таблице и в открытой карточке расходятся.
    refetchInterval: useAdminPollInterval(accountId != null),
  })
}

export function useAdminUserDiagnosis(accountId: number | null) {
  return useQuery({
    queryKey: ["admin", "user", accountId, "diagnosis"],
    queryFn: () => fetchAdminUserDiagnosis(accountId!),
    enabled: accountId != null,
    staleTime: 10_000,
    refetchInterval: useAdminPollInterval(accountId != null),
  })
}

export function useAdminUserPipeline(accountId: number | null) {
  return useQuery({
    queryKey: ["admin", "user", accountId, "pipeline"],
    queryFn: () => fetchAdminUserPipeline(accountId!),
    enabled: accountId != null,
    staleTime: 5_000,
    refetchInterval: useAdminPollInterval(accountId != null),
  })
}

/** Операторские кнопки авто-процессов пользователя — все инвалидируют витрины админки. */
export function useAdminPauseAutoApply() {
  const invalidate = useOverviewInvalidate()
  return useMutation({
    mutationFn: pauseAdminAutoApply,
    onSuccess: () => {
      invalidate()
      toast.success("Автоотклики остановлены")
    },
    onError: () => toast.error("Не удалось остановить"),
  })
}

export function useAdminResumeAutoApply() {
  const invalidate = useOverviewInvalidate()
  return useMutation({
    mutationFn: resumeAdminAutoApply,
    onSuccess: () => {
      invalidate()
      toast.success("Автоотклики включены на всех площадках")
    },
    onError: () => toast.error("Не удалось включить"),
  })
}

export function useAdminClearAutoApplyQueue() {
  const invalidate = useOverviewInvalidate()
  return useMutation({
    mutationFn: clearAdminAutoApplyQueue,
    onSuccess: (res) => {
      invalidate()
      toast.success(res.cleared > 0 ? `Очередь очищена: ${res.cleared}` : "Очередь уже пуста")
    },
    onError: () => toast.error("Не удалось очистить очередь"),
  })
}

export function useAdminStopDiscovery() {
  const invalidate = useOverviewInvalidate()
  return useMutation({
    mutationFn: ({
      accountId,
      platform,
    }: {
      accountId: number
      platform?: "hh" | "getmatch" | "habr"
    }) => stopAdminDiscovery(accountId, platform),
    onSuccess: (res) => {
      invalidate()
      toast.success(
        res.stopped.length > 0
          ? `Автопросмотр остановлен: ${res.stopped.join(", ")}`
          : "Автопросмотр не был запущен",
      )
    },
    onError: () => toast.error("Не удалось остановить автопросмотр"),
  })
}

export function useAdminClearDiscoveryLog() {
  const invalidate = useOverviewInvalidate()
  return useMutation({
    mutationFn: clearAdminDiscoveryLog,
    onSuccess: () => {
      invalidate()
      toast.success("Лог автопросмотра очищен")
    },
    onError: () => toast.error("Не удалось очистить лог"),
  })
}

export function useAdminSupportThread(accountId: number | null) {
  return useQuery({
    queryKey: ["admin", "user", accountId, "support"],
    queryFn: () => fetchAdminSupportThread(accountId!),
    enabled: accountId != null,
    staleTime: 5_000,
    refetchInterval: useAdminPollInterval(accountId != null, SUPPORT_POLL_MS),
    placeholderData: (previous) => previous,
  })
}

/** Любая мутация освежает все витрины админки разом — они смотрят на одни и те же данные. */
function useOverviewInvalidate() {
  const qc = useQueryClient()
  return () => {
    void qc.invalidateQueries({ queryKey: ["admin"] })
  }
}

export function useDisableAdminUser() {
  const invalidate = useOverviewInvalidate()
  return useMutation({
    mutationFn: ({ accountId, reason }: { accountId: number; reason: string }) =>
      disableAdminUser(accountId, reason),
    onSuccess: () => {
      invalidate()
      toast.success("Аккаунт отключён")
    },
    onError: () => toast.error("Не удалось отключить"),
  })
}

export function useEnableAdminUser() {
  const invalidate = useOverviewInvalidate()
  return useMutation({
    mutationFn: enableAdminUser,
    onSuccess: () => {
      invalidate()
      toast.success("Аккаунт включён")
    },
    onError: () => toast.error("Не удалось включить"),
  })
}

export function useRevokeAdminSessions() {
  const invalidate = useOverviewInvalidate()
  return useMutation({
    mutationFn: revokeAdminUserSessions,
    onSuccess: (res) => {
      invalidate()
      toast.success(`Сессий отозвано: ${res.revoked}`)
    },
    onError: () => toast.error("Не удалось отозвать сессии"),
  })
}

export function useSendAdminTelegram() {
  const invalidate = useOverviewInvalidate()
  return useMutation({
    mutationFn: ({ accountId, text }: { accountId: number; text: string }) =>
      sendAdminTelegram(accountId, text),
    onSuccess: () => {
      invalidate()
      toast.success("Сообщение в очереди")
    },
    onError: () => toast.error("Не удалось отправить"),
  })
}

export function useSendAdminSupportMessage() {
  const qc = useQueryClient()
  const invalidate = useOverviewInvalidate()
  return useMutation({
    mutationFn: ({
      accountId,
      channel,
      text,
      replyToId,
    }: {
      accountId: number
      channel: "user" | "agent"
      text: string
      replyToId?: number | null
    }) => sendAdminSupportMessage(accountId, { channel, text, reply_to_id: replyToId }),
    onSuccess: (thread, vars) => {
      qc.setQueryData(["admin", "user", vars.accountId, "support"], thread)
      invalidate()
      toast.success(vars.channel === "agent" ? "Ответ агента готов" : "Сообщение в очереди")
    },
    onError: () => toast.error("Не удалось отправить"),
  })
}

export function useRevokeAdminUserSession() {
  const invalidate = useOverviewInvalidate()
  return useMutation({
    mutationFn: ({ accountId, sessionId }: { accountId: number; sessionId: number }) =>
      revokeAdminUserSession(accountId, sessionId),
    onSuccess: () => {
      invalidate()
      toast.success("Сессия завершена")
    },
    onError: () => toast.error("Не удалось завершить сессию"),
  })
}

export function useRejectAdminKey() {
  const invalidate = useOverviewInvalidate()
  return useMutation({
    mutationFn: rejectAdminKey,
    onSuccess: () => {
      invalidate()
      toast.success("Заявка отклонена")
    },
    onError: () => toast.error("Не удалось отклонить заявку"),
  })
}

/** Выдать или перевыпустить ключ человеку (адресуемся аккаунтом, не заявкой). */
export function useIssueAdminKey() {
  const invalidate = useOverviewInvalidate()
  return useMutation({
    mutationFn: ({ accountId, key, label }: { accountId: number; key: string; label?: string }) =>
      issueAdminKey(accountId, key, label),
    onSuccess: () => {
      invalidate()
      toast.success("Ключ выдан")
    },
    onError: () => toast.error("Не удалось выдать ключ"),
  })
}

export function useRevokeAdminKey() {
  const invalidate = useOverviewInvalidate()
  return useMutation({
    mutationFn: revokeAdminKey,
    onSuccess: () => {
      invalidate()
      toast.success("Ключ отозван")
    },
    onError: () => toast.error("Не удалось отозвать ключ"),
  })
}

export function useVerifyAdminKey() {
  return useMutation({
    mutationFn: verifyAdminKey,
    onError: () => toast.error("Не удалось проверить ключ"),
  })
}

export function useVerifyStoredAdminKey() {
  return useMutation({
    mutationFn: verifyStoredAdminKey,
    onError: () => toast.error("Не удалось проверить ключ"),
  })
}

export function useRefreshAdminKeyBalances() {
  return useMutation({
    mutationFn: refreshAdminKeyBalances,
    onError: () => toast.error("Не удалось обновить остатки"),
  })
}

export function useDownloadAdminLogs() {
  return useMutation({
    mutationFn: ({ accountId, hours }: { accountId: number; hours: number }) =>
      downloadAdminUserLogs(accountId, hours),
    onSuccess: () => toast.success("Архив скачан"),
    onError: () => toast.error("Не удалось скачать логи"),
  })
}

export function useSetAdminUserNote() {
  const invalidate = useOverviewInvalidate()
  return useMutation({
    mutationFn: ({ accountId, note }: { accountId: number; note: string }) =>
      setAdminUserNote(accountId, note),
    onSuccess: () => {
      invalidate()
      toast.success("Заметка сохранена")
    },
    onError: () => toast.error("Не удалось сохранить заметку"),
  })
}

export function useSetAdminUserRole() {
  const invalidate = useOverviewInvalidate()
  return useMutation({
    mutationFn: ({ accountId, role }: { accountId: number; role: "owner" | "member" }) =>
      setAdminUserRole(accountId, role),
    onSuccess: () => {
      invalidate()
      toast.success("Роль изменена")
    },
    onError: () => toast.error("Не удалось сменить роль"),
  })
}

export function useAdminTasks(enabled: boolean, query: AdminTasksQuery) {
  return useQuery({
    queryKey: ["admin", "tasks", query],
    queryFn: () => fetchAdminTasks(query),
    enabled,
    staleTime: 10_000,
    refetchInterval: useAdminPollInterval(enabled),
    placeholderData: (previous) => previous,
  })
}

export function useAdminTables(enabled: boolean) {
  return useQuery({
    queryKey: ["admin", "tables"],
    queryFn: fetchAdminTables,
    enabled,
    staleTime: 30_000,
    refetchInterval: useAdminPollInterval(enabled),
    placeholderData: (previous) => previous,
  })
}

export function useRetryAdminTask() {
  const invalidate = useOverviewInvalidate()
  return useMutation({
    mutationFn: retryAdminTask,
    onSuccess: () => {
      invalidate()
      toast.success("Задача снова в очереди")
    },
    onError: () => toast.error("Не удалось перезапустить"),
  })
}

export function useCancelAdminTask() {
  const invalidate = useOverviewInvalidate()
  return useMutation({
    mutationFn: cancelAdminTask,
    onSuccess: () => {
      invalidate()
      toast.success("Задача отменена")
    },
    onError: () => toast.error("Не удалось отменить"),
  })
}

export function useRetryAdminTasksKind() {
  const invalidate = useOverviewInvalidate()
  return useMutation({
    mutationFn: ({ kind, reason = "" }: { kind: string; reason?: string }) =>
      retryAdminTasksKind(kind, reason),
    onSuccess: (res) => {
      invalidate()
      toast.success(res.n > 0 ? `Перезапущено: ${res.n}` : "Нечего перезапускать")
    },
    onError: () => toast.error("Не удалось перезапустить пачку"),
  })
}

export function useCancelAdminTasksKind() {
  const invalidate = useOverviewInvalidate()
  return useMutation({
    mutationFn: ({ kind, reason = "" }: { kind: string; reason?: string }) =>
      cancelAdminTasksKind(kind, reason),
    onSuccess: (res) => {
      invalidate()
      toast.success(res.n > 0 ? `Отменено: ${res.n}` : "Нечего отменять")
    },
    onError: () => toast.error("Не удалось отменить пачку"),
  })
}

export function useReclaimAdminTasks() {
  const invalidate = useOverviewInvalidate()
  return useMutation({
    mutationFn: reclaimAdminTasks,
    onSuccess: (res) => {
      invalidate()
      toast.success(res.n > 0 ? `Вернули в очередь: ${res.n}` : "Зависших нет")
    },
    onError: () => toast.error("Не удалось вернуть зависшие"),
  })
}

export function usePurgeAdminLogs() {
  const invalidate = useOverviewInvalidate()
  return useMutation({
    mutationFn: purgeAdminLogs,
    onSuccess: (res) => {
      invalidate()
      toast.success(`Удалено строк журнала: ${res.n}`)
    },
    onError: () => toast.error("Не удалось удалить логи"),
  })
}

export function useRepairAdminFriendships() {
  const invalidate = useOverviewInvalidate()
  return useMutation({
    mutationFn: repairAdminFriendships,
    onSuccess: () => {
      invalidate()
      toast.success("Дружбы проверены")
    },
    onError: () => toast.error("Не удалось починить дружбы"),
  })
}

export function useSetAdminSpendAlert() {
  const invalidate = useOverviewInvalidate()
  return useMutation({
    mutationFn: setAdminSpendAlert,
    onSuccess: (res) => {
      invalidate()
      toast.success(res.usd > 0 ? `Порог ${res.usd.toFixed(2)} $` : "Порог выключен")
    },
    onError: () => toast.error("Не удалось сохранить порог"),
  })
}
