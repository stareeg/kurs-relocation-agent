import { describe, expect, it } from "vitest"
import type { AgentEvent, AgentRun } from "@/api/agent"
import { formatTokens, formatUsd } from "@/lib/format"
import { parseLimits, parseUsage, runBudget } from "./run-usage"
import { foldAll } from "./use-agent-runs"

function ev(id: number, type: string, payload: Record<string, unknown>): AgentEvent {
  return { id, type, payload, node: null, duration_ms: null, created_at: null }
}

const usage = (calls: number, tokensIn: number, tokensOut: number, cost: number, selfHosted = 0) => ({
  model_calls: calls,
  tokens_in: tokensIn,
  tokens_out: tokensOut,
  cost_usd: cost,
  cost_self_hosted_usd: selfHosted,
  by_group: {
    agent: { calls: calls - 2, tokens_in: tokensIn - 900, tokens_out: tokensOut - 60, cost_usd: selfHosted },
    judge: { calls: 2, tokens_in: 900, tokens_out: 60, cost_usd: cost - selfHosted },
  },
})

const LIMITS = { max_steps: 8, max_model_calls: 40, max_tokens: 200_000 }

const run: AgentRun = {
  id: 7,
  goal: "Найди вакансии",
  status: "done",
  session_id: null,
  stop_reason: "answered",
  answer: "Готово",
  error: null,
  created_at: "2026-11-16T10:00:00Z",
  updated_at: "2026-11-16T10:00:40Z",
}

describe("parseUsage / parseLimits", () => {
  it("снимок из payload; пустой объект и мусор — null", () => {
    expect(parseUsage({})).toBeNull()
    expect(parseUsage(null)).toBeNull()
    expect(parseUsage({ model_calls: "17" })).toBeNull()
    const parsed = parseUsage(usage(17, 52_000, 1_300, 0.0042, 0.0024))
    expect(parsed?.model_calls).toBe(17)
    expect(parsed?.by_group.judge?.calls).toBe(2)
    expect(parsed?.by_group.tools).toBeUndefined()
  })

  it("пределы только целиком", () => {
    expect(parseLimits(LIMITS)).toEqual(LIMITS)
    expect(parseLimits({ max_steps: 8 })).toBeNull()
    expect(parseLimits(undefined)).toBeNull()
  })
})

describe("runBudget", () => {
  it("шаги, вызовы и токены против пределов; цена делится на условную и оплаченную", () => {
    const budget = runBudget({
      usage: parseUsage(usage(17, 52_000, 1_300, 0.0042, 0.0024)),
      limits: LIMITS,
      stepsTaken: 3,
      stopReason: null,
    })
    expect(budget.meters.map((m) => [m.key, m.used, m.limit, m.hit])).toEqual([
      ["steps", 3, 8, false],
      ["calls", 17, 40, false],
      ["tokens", 53_300, 200_000, false],
    ])
    expect(budget.meters[1].pct).toBe(43)
    expect(budget.costSelfHosted).toBeCloseTo(0.0024)
    expect(budget.costPaid).toBeCloseTo(0.0018)
    expect(budget.groups.map((g) => [g.key, g.calls])).toEqual([
      ["agent", 15],
      ["judge", 2],
      ["tools", 0],
      ["subagents", 0],
    ])
  })

  it("исчерпанный предел подсвечен; шаги — и по stop_reason", () => {
    const calls = runBudget({
      usage: parseUsage(usage(40, 100_000, 9_000, 0.03)),
      limits: LIMITS,
      stepsTaken: 6,
      stopReason: "model_budget",
    })
    expect(calls.meters.find((m) => m.key === "calls")?.hit).toBe(true)
    expect(calls.meters.find((m) => m.key === "tokens")?.hit).toBe(false)
    const steps = runBudget({ usage: null, limits: LIMITS, stepsTaken: 8, stopReason: "step_limit" })
    expect(steps.meters[0].hit).toBe(true)
    expect(steps.recorded).toBe(false)
  })
})

describe("foldAll: расход в виде запуска", () => {
  it("пределы из run_started, последний снимок из событий", () => {
    const view = foldAll(run, [
      ev(1, "run_started", { goal: run.goal, limits: LIMITS }),
      ev(2, "node_timing", { node: "plan", usage: usage(3, 1_500, 100, 0.001) }),
      ev(3, "node_timing", { node: "step", usage: usage(6, 4_000, 200, 0.002) }),
      ev(4, "done", { stop_reason: "answered", usage: usage(8, 5_200, 260, 0.003) }),
    ])
    expect(view.limits).toEqual(LIMITS)
    expect(view.usage?.model_calls).toBe(8)
    expect(view.usage?.tokens_in).toBe(5_200)
  })

  it("без событий расхода — снимок из строки запуска; запуск до E-9 — без расхода", () => {
    const saved = foldAll({ ...run, usage: usage(5, 3_000, 90, 0.0011) }, [])
    expect(saved.usage?.model_calls).toBe(5)
    const old = foldAll({ ...run, usage: {} }, [ev(1, "run_started", { goal: run.goal })])
    expect(old.usage).toBeNull()
    expect(old.limits).toBeNull()
  })
})

describe("формат", () => {
  it("мелкие суммы с четырьмя знаками, токены с разрядами", () => {
    expect(formatUsd(0)).toBe("$0")
    expect(formatUsd(0.0042)).toBe("$0.0042")
    expect(formatUsd(0.00004)).toBe("<$0.0001")
    expect(formatUsd(1.234)).toBe("$1.23")
    expect(formatTokens(52_300)).toMatch(/^52\s300$/)
  })
})
