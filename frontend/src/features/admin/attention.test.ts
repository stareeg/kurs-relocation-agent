import { describe, expect, it } from "vitest"
import type { AdminAttention } from "@/api/admin"
import type { AdminHealth } from "@/api/admin"
import { buildHealthItems } from "./admin-health"
import { buildAttentionItems, buildVerdict } from "./attention"

const EMPTY: AdminAttention = {
  key_requests: [],
  failed_tasks: [],
  failed_tasks_total: 0,
  errors: [],
  errors_total: 0,
  error_bursts: [],
  stale: [],
  no_key: [],
  spend_over: [],
  spend_alert_usd: 0,
  degraded: false,
  degraded_reason: "",
}

function attention(patch: Partial<AdminAttention>): AdminAttention {
  return { ...EMPTY, ...patch }
}

describe("buildAttentionItems", () => {
  it("пустая очередь — пустой список, а не карточка «всё хорошо»", () => {
    expect(buildAttentionItems(EMPTY)).toEqual([])
    expect(buildAttentionItems(undefined)).toEqual([])
  })

  it("ключи идут первыми: без ключа человеку не работает весь продукт", () => {
    const items = buildAttentionItems(
      attention({
        errors_total: 99,
        stale: [{ account_id: 3, telegram_username: "misha", days_silent: 30 }],
        failed_tasks_total: 4,
        failed_tasks: [
          { id: 1, kind: "tg_push", account_id: 1, last_error: "boom", finished_at: null },
        ],
        key_requests: [
          {
            id: 7,
            account_id: 2,
            telegram_username: "lena",
            status: "pending",
            requested_at: null,
            note: null,
          },
        ],
      }),
    )
    expect(items.map((item) => item.kind)).toEqual([
      "key_request",
      "failed_tasks",
      "errors",
      "stale",
    ])
  })

  it("заголовок — глагол и последствие, а не существительное со счётчиком", () => {
    const [item] = buildAttentionItems(
      attention({
        key_requests: [
          {
            id: 7,
            account_id: 2,
            telegram_username: "lena",
            status: "pending",
            requested_at: null,
            note: null,
          },
        ],
      }),
    )
    expect(item.title).toBe("Выдать ключ @lena")
    expect(item.accountId).toBe(2)
    expect(item.tone).toBe("bad")
    expect(item.action).toBe("issue_key")
  })

  it("заметка заявителя важнее общей подсказки", () => {
    const [item] = buildAttentionItems(
      attention({
        key_requests: [
          {
            id: 7,
            account_id: 2,
            telegram_username: "lena",
            status: "pending",
            requested_at: null,
            note: "  свой кончился  ",
          },
        ],
      }),
    )
    expect(item.note).toBe("свой кончился")
  })

  it("сбои задач названы полным числом и самым частым видом", () => {
    const [item] = buildAttentionItems(
      attention({
        failed_tasks_total: 137,
        failed_tasks: [
          { id: 1, kind: "tg_push", account_id: null, last_error: "", finished_at: null },
          { id: 2, kind: "tg_push", account_id: null, last_error: "", finished_at: null },
          { id: 3, kind: "salary_estimate", account_id: null, last_error: "", finished_at: null },
        ],
      }),
    )
    // Список урезан двадцатью, счётчик полный — в заголовке обязан быть счётчик.
    expect(item.title).toBe("137 задач упало")
    expect(item.note).toBe("Чаще других — tg_push")
    expect(item.action).toBe("open_system")
    expect(item.href).toBe("/admin/system?status=failed&kind=tg_push")
  })

  it("склоняет задачи и ошибки", () => {
    const one = buildAttentionItems(attention({ failed_tasks_total: 1 }))[0]
    const few = buildAttentionItems(attention({ failed_tasks_total: 3 }))[0]
    expect(one.title).toBe("1 задача упала")
    expect(few.title).toBe("3 задачи упали")
    expect(buildAttentionItems(attention({ errors_total: 1 }))[0].title).toBe("1 ошибка за сутки")
    expect(buildAttentionItems(attention({ errors_total: 22 }))[0].title).toBe("22 ошибки за сутки")
  })

  it("«не заходил ни разу» тонет наверх среди отвалившихся", () => {
    const items = buildAttentionItems(
      attention({
        stale: [
          { account_id: 1, telegram_username: "a", days_silent: 8 },
          { account_id: 2, telegram_username: "b", days_silent: null },
          { account_id: 3, telegram_username: "c", days_silent: 40 },
        ],
      }),
    )
    expect(items.map((item) => item.accountId)).toEqual([2, 3, 1])
    expect(items[0].title).toBe("@b не заходил ни разу")
  })

  it("порядок устойчив: одинаковый вес не тасует список между опросами", () => {
    const data = attention({
      key_requests: [
        {
          id: 2,
          account_id: 20,
          telegram_username: "b",
          status: "pending",
          requested_at: null,
          note: null,
        },
        {
          id: 1,
          account_id: 10,
          telegram_username: "a",
          status: "pending",
          requested_at: null,
          note: null,
        },
      ],
    })
    expect(buildAttentionItems(data).map((i) => i.id)).toEqual(
      buildAttentionItems(data).map((i) => i.id),
    )
    expect(buildAttentionItems(data).map((i) => i.accountId)).toEqual([10, 20])
  })

  it("пачка ошибок за час вытесняет суточный агрегат и ведёт в журнал", () => {
    const items = buildAttentionItems(
      attention({
        errors_total: 44,
        error_bursts: [{ account_id: 9, telegram_username: "kate", count: 7 }],
      }),
    )
    expect(items).toHaveLength(1)
    expect(items[0].title).toBe("У @kate 7 ошибок за час")
    expect(items[0].action).toBe("open_journal")
    expect(items[0].accountId).toBe(9)
    expect(items[0].href).toBe("/admin/journal?level=ERROR&account_id=9")
  })

  it("без ключа третий день — выдача, после заявок", () => {
    const items = buildAttentionItems(
      attention({
        no_key: [{ account_id: 4, telegram_username: "lena", days_waiting: 3 }],
        key_requests: [
          {
            id: 1,
            account_id: 2,
            telegram_username: "kate",
            status: "pending",
            requested_at: null,
            note: null,
          },
        ],
      }),
    )
    expect(items.map((item) => item.kind)).toEqual(["key_request", "no_key"])
    expect(items[1].title).toBe("Выдать ключ @lena")
    expect(items[1].note).toContain("3 дня")
    expect(items[1].action).toBe("issue_key")
  })

  it("превышение порога — после ключей, в карточку расхода", () => {
    const items = buildAttentionItems(
      attention({
        spend_alert_usd: 10,
        spend_over: [{ account_id: 4, telegram_username: "lena", month_usd: 12.4 }],
        key_requests: [
          {
            id: 1,
            account_id: 2,
            telegram_username: "kate",
            status: "pending",
            requested_at: null,
            note: null,
          },
        ],
      }),
    )
    expect(items.map((item) => item.kind)).toEqual(["key_request", "spend"])
    expect(items[1].title).toBe("У @lena расход $12.40 за месяц")
    expect(items[1].note).toContain("$10.00")
    expect(items[1].href).toBe("/admin/person/4?tab=spend")
    expect(items[1].tone).toBe("warn")
  })

  it("порог 0 — карточек расхода нет, даже если список непустой", () => {
    const items = buildAttentionItems(
      attention({
        spend_alert_usd: 0,
        spend_over: [{ account_id: 4, telegram_username: "lena", month_usd: 99 }],
      }),
    )
    expect(items.filter((item) => item.kind === "spend")).toEqual([])
  })
})

const HEALTHY: AdminHealth = {
  extension_version: "1.4.0",
  git_sha: "abc1234",
  postgres_ok: true,
  postgres_size_bytes: 128 * 1024 * 1024,
  worker_running: true,
  worker_last_finished_at: new Date().toISOString(),
  queue: { pending: 0, running: 0, failed: 0, done: 12, cancelled: 0 },
  migrations_applied: 141,
  migrations_available: 141,
  model_tier_advanced: "google/gemini-3.7-flash",
  model_tier_basic: "openai/gpt-5.6-luna",
  model_tier_reserve: "google/gemini-3.7-flash",
}

function health(patch: Partial<AdminHealth> = {}) {
  return buildHealthItems({ ...HEALTHY, ...patch })
}

describe("buildVerdict", () => {
  it("всё цело и дел нет — тон ok, и цвета на экране не появляется", () => {
    expect(buildVerdict(health(), [])).toEqual({ tone: "ok", text: "Всё живо · дел нет" })
  })

  it("есть дела — считает их и склоняет", () => {
    const items = buildAttentionItems(
      attention({
        stale: [
          { account_id: 2, telegram_username: "a", days_silent: 9 },
          { account_id: 3, telegram_username: "b", days_silent: 12 },
        ],
      }),
    )
    expect(buildVerdict(health(), items)).toEqual({ tone: "warn", text: "2 дела" })
  })

  it("дело, блокирующее человека, поднимает тон до bad", () => {
    const items = buildAttentionItems(
      attention({ no_key: [{ account_id: 4, telegram_username: "c", days_waiting: 3 }] }),
    )
    expect(buildVerdict(health(), items).tone).toBe("bad")
  })

  it("сломанная установка важнее дел и называется прямо", () => {
    const verdict = buildVerdict(health({ postgres_ok: false, postgres_size_bytes: null }), [])
    expect(verdict).toEqual({ tone: "bad", text: "Postgres не отвечает" })
  })

  it("поломка и дела вместе — сначала счёт дел, потом причина", () => {
    const items = buildAttentionItems(
      attention({
        failed_tasks_total: 23,
        failed_tasks: [{ id: 1, kind: "tg_cleanup", last_error: "", finished_at: null }],
      }),
    )
    const verdict = buildVerdict(
      health({ queue: { pending: 0, running: 0, failed: 23, done: 0, cancelled: 0 } }),
      items,
    )
    expect(verdict.tone).toBe("bad")
    expect(verdict.text).toBe("1 дело · очередь: 23 сбоя")
  })

  it("больше двух поломок — называет две и говорит, сколько ещё", () => {
    const verdict = buildVerdict(
      health({
        postgres_ok: false,
        worker_running: false,
        migrations_applied: 140,
        migrations_available: 141,
      }),
      [],
    )
    expect(verdict.text).toBe("Postgres не отвечает · воркер не запущен · и ещё 1")
  })

  it("без поломок и дел, но с предупреждением — тон warn, а не «всё живо»", () => {
    const verdict = buildVerdict(health({ git_sha: "" }), [])
    expect(verdict).toEqual({ tone: "warn", text: "сборка без коммита" })
  })
})
