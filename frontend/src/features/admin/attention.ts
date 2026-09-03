/**
 * Очередь внимания: ответ `GET /api/admin/attention` → упорядоченный список дел.
 *
 * Чистая функция без React и без запросов — правило «что срочнее» должно проверяться тестом,
 * а не глазами по экрану (Этап 1.3). Бэкенд отдаёт факты, порядок и формулировки живут здесь.
 *
 * Формулировка — глагол и последствие, а не существительное со счётчиком: «Выдать ключ @lena»
 * вместо «Заявки на ключ: 1» (§8.7 плана). Карточка несёт действие: выдача ключа, открытие
 * человека, журнал или раздел Действия (очередь задач, Этап 7).
 */
import type { AdminAttention } from "@/api/admin"
import type { HealthItem, HealthTone } from "./admin-health"
import {
  CASES,
  DAYS,
  ERRORS,
  TASKS_FELL,
  atHandle,
  pluralize,
  silenceLabel,
  usd,
} from "./admin-format"
import { adminPersonPath } from "./admin-filters"
import { adminJournalPath } from "./journal-filters"
import { adminSystemPath } from "./system-filters"

export type AttentionTone = "bad" | "warn" | "info"

export type AttentionAction = "issue_key" | "open_account" | "open_journal" | "open_system" | "none"

export type AttentionItem = {
  /** Стабильный ключ для React и для тестов. */
  id: string
  kind: "key_request" | "no_key" | "spend" | "failed_tasks" | "errors" | "stale"
  tone: AttentionTone
  title: string
  note: string
  /** Аккаунт, к которому ведёт дело; null — дело про установку в целом. */
  accountId: number | null
  /** Сколько сущностей за делом стоит: для сортировки внутри одного вида. */
  weight: number
  action: AttentionAction
  /** Заявка, если дело — выдача по запросу (кнопка «Отклонить»). */
  requestId?: number
  /** Готовый адрес журнала с фильтром (Этап 5). */
  href?: string
}

/** Чем меньше — тем выше в списке. Ключи блокируют человеку весь продукт, поэтому первые. */
const KIND_ORDER: Record<AttentionItem["kind"], number> = {
  key_request: 0,
  no_key: 1,
  spend: 2,
  failed_tasks: 3,
  errors: 4,
  stale: 5,
}

/** Самый частый вид задачи в пачке — чтобы заголовок называл причину, а не просто число. */
function topTaskKind(tasks: AdminAttention["failed_tasks"]): string {
  const counts = new Map<string, number>()
  for (const task of tasks) {
    const kind = task.kind || "без вида"
    counts.set(kind, (counts.get(kind) ?? 0) + 1)
  }
  let best = ""
  let bestCount = 0
  for (const [kind, count] of counts) {
    if (count > bestCount) {
      best = kind
      bestCount = count
    }
  }
  return best
}

export function buildAttentionItems(data: AdminAttention | undefined): AttentionItem[] {
  if (!data) return []
  const items: AttentionItem[] = []

  for (const request of data.key_requests) {
    items.push({
      id: `key_request:${request.id}`,
      kind: "key_request",
      tone: "bad",
      title: `Выдать ключ ${atHandle(request.telegram_username)}`,
      note: request.note?.trim() || "Без ключа LLM-функции не работают",
      accountId: request.account_id,
      weight: 1,
      action: "issue_key",
      requestId: request.id,
    })
  }

  for (const person of data.no_key ?? []) {
    items.push({
      id: `no_key:${person.account_id}`,
      kind: "no_key",
      tone: "bad",
      title: `Выдать ключ ${atHandle(person.telegram_username)}`,
      note: waitingNote(person.days_waiting),
      accountId: person.account_id,
      weight: person.days_waiting,
      action: "issue_key",
    })
  }

  const threshold = data.spend_alert_usd ?? 0
  if (threshold > 0) {
    for (const person of data.spend_over ?? []) {
      items.push({
        id: `spend:${person.account_id}`,
        kind: "spend",
        tone: "warn",
        title: `У ${atHandle(person.telegram_username)} расход ${usd(person.month_usd)} за месяц`,
        note: `Порог ${usd(threshold)} — мягкий сигнал, LLM не отключаем`,
        accountId: person.account_id,
        weight: person.month_usd,
        action: "open_account",
        href: adminPersonPath(person.account_id, "tab=spend"),
      })
    }
  }

  if (data.failed_tasks_total > 0) {
    const kind = topTaskKind(data.failed_tasks)
    items.push({
      id: "failed_tasks",
      kind: "failed_tasks",
      tone: "warn",
      title: pluralize(data.failed_tasks_total, TASKS_FELL),
      note: kind ? `Чаще других — ${kind}` : "Очередь фоновых задач",
      accountId: null,
      weight: data.failed_tasks_total,
      action: "open_system",
      href: adminSystemPath(kind ? { status: "failed", kind } : { status: "failed" }),
    })
  }

  const bursts = data.error_bursts ?? []
  if (bursts.length > 0) {
    for (const burst of bursts) {
      items.push({
        id: `errors:${burst.account_id}`,
        kind: "errors",
        tone: "warn",
        title: `У ${atHandle(burst.telegram_username)} ${pluralize(burst.count, ERRORS)} за час`,
        note: "Открыть журнал с фильтром по человеку",
        accountId: burst.account_id,
        weight: burst.count,
        action: "open_journal",
        href: adminJournalPath({
          accountId: String(burst.account_id),
          window: "1h",
          levels: ["ERROR"],
        }),
      })
    }
  } else if (data.errors_total > 0) {
    items.push({
      id: "errors",
      kind: "errors",
      tone: "warn",
      title: `${pluralize(data.errors_total, ERRORS)} за сутки`,
      note: data.errors[0]?.msg?.trim() || data.errors[0]?.event || "Смотреть журнал",
      accountId: null,
      weight: data.errors_total,
      action: "open_journal",
      href: adminJournalPath({ window: "24h", levels: ["ERROR"] }),
    })
  }

  for (const person of data.stale) {
    items.push({
      id: `stale:${person.account_id}`,
      kind: "stale",
      tone: "info",
      title: `${atHandle(person.telegram_username)} ${silenceLabel(person.days_silent)}`,
      note: "Резюме заполнено, но человек пропал",
      accountId: person.account_id,
      weight: person.days_silent ?? Number.MAX_SAFE_INTEGER,
      action: "open_account",
    })
  }

  return items.sort((a, b) => {
    const byKind = KIND_ORDER[a.kind] - KIND_ORDER[b.kind]
    if (byKind !== 0) return byKind
    if (a.weight !== b.weight) return b.weight - a.weight
    return a.id.localeCompare(b.id)
  })
}

function waitingNote(days: number): string {
  return `Уже ${pluralize(days, DAYS)} без ключа — LLM не работает`
}

/**
 * Строка-вердикт в шапке раздела: ответ на «надо ли мне сейчас что-то делать» одной фразой.
 *
 * Порядок важнее полноты. Сначала сломанная установка (её чинит только оператор и прямо
 * сейчас), потом дела (их можно разобрать по одному), и только если пусто и то и другое —
 * «Всё живо». Числа в шапке больше не живут: шесть KPI висели над каждой вкладкой, включая
 * Журнал и Систему, где ни одно из них не нужно, и ни одно не отвечало на главный вопрос.
 *
 * Тон — тот же словарь, что у точек: `ok` не красится вовсе (§2.5).
 */
export type AdminVerdict = { tone: HealthTone; text: string }

/** Сколько поломок установки называем в вердикте: дальше строка перестаёт читаться. */
const MAX_ALARMS = 2

export function buildVerdict(
  health: readonly HealthItem[],
  items: readonly AttentionItem[],
): AdminVerdict {
  const alarms = health.filter((item) => item.tone === "bad" && item.alarm)
  const cases = items.length
  const casesText = cases > 0 ? pluralize(cases, CASES) : ""

  if (alarms.length > 0) {
    const named = alarms.slice(0, MAX_ALARMS).map((item) => item.alarm!)
    const rest = alarms.length - named.length
    const parts = [casesText, ...named, rest > 0 ? `и ещё ${rest}` : ""].filter(Boolean)
    return { tone: "bad", text: parts.join(" · ") }
  }

  if (cases > 0) {
    const blocking = items.some((item) => item.tone === "bad")
    return { tone: blocking ? "bad" : "warn", text: casesText }
  }

  const warnings = health.filter((item) => item.tone === "warn" && item.alarm)
  if (warnings.length > 0) {
    return { tone: "warn", text: warnings.slice(0, MAX_ALARMS).map((item) => item.alarm!).join(" · ") }
  }

  return { tone: "ok", text: "Всё живо · дел нет" }
}
