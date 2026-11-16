import type { AgentRunLimits, AgentRunUsage, AgentUsageBucket, AgentUsageGroup } from "@/api/agent"

// Расход запуска агента (E-9): снимок `RunBudget.snapshot()` приходит с каждым `node_timing`
// и терминальным событием, пределы — с `run_started`. Здесь — разбор payload без доверия
// к форме и строки секции «Расход» правой панели: шаги N из 8, вызовы модели N из 40,
// токены, цена. Чистые функции, тестируются без DOM (`run-usage.test.ts`).

export const USAGE_GROUPS: AgentUsageGroup[] = ["agent", "judge", "tools", "subagents"]

export const USAGE_GROUP_LABEL: Record<AgentUsageGroup, string> = {
  agent: "агент",
  judge: "судья",
  tools: "инструменты",
  subagents: "субагенты",
}

const USAGE_GROUP_HINT: Record<AgentUsageGroup, string> = {
  agent: "план, шаги и перестройка",
  judge: "самопроверка шагов и итога",
  tools: "LLM внутри инструментов: условия найма, письмо",
  subagents: "исследователь страны и оценщик вакансий",
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null
}

function parseBucket(raw: unknown): AgentUsageBucket | null {
  if (raw == null || typeof raw !== "object") return null
  const r = raw as Record<string, unknown>
  return {
    calls: num(r.calls) ?? 0,
    tokens_in: num(r.tokens_in) ?? 0,
    tokens_out: num(r.tokens_out) ?? 0,
    cost_usd: num(r.cost_usd) ?? 0,
  }
}

/** Снимок расхода из payload события или строки запуска; `{}` и мусор — null. */
export function parseUsage(raw: unknown): AgentRunUsage | null {
  if (raw == null || typeof raw !== "object") return null
  const r = raw as Record<string, unknown>
  const calls = num(r.model_calls)
  if (calls == null) return null
  const byGroup: AgentRunUsage["by_group"] = {}
  const groups = r.by_group
  if (groups != null && typeof groups === "object") {
    for (const group of USAGE_GROUPS) {
      const bucket = parseBucket((groups as Record<string, unknown>)[group])
      if (bucket) byGroup[group] = bucket
    }
  }
  return {
    model_calls: calls,
    tokens_in: num(r.tokens_in) ?? 0,
    tokens_out: num(r.tokens_out) ?? 0,
    cost_usd: num(r.cost_usd) ?? 0,
    cost_self_hosted_usd: num(r.cost_self_hosted_usd) ?? 0,
    by_group: byGroup,
  }
}

/** Пределы из `run_started.limits`; запуск до E-9 их не присылал — null. */
export function parseLimits(raw: unknown): AgentRunLimits | null {
  if (raw == null || typeof raw !== "object") return null
  const r = raw as Record<string, unknown>
  const steps = num(r.max_steps)
  const calls = num(r.max_model_calls)
  const tokens = num(r.max_tokens)
  if (steps == null || calls == null || tokens == null) return null
  return { max_steps: steps, max_model_calls: calls, max_tokens: tokens }
}

export type BudgetMeter = {
  key: "steps" | "calls" | "tokens"
  label: string
  used: number
  limit: number | null
  /** Заполнение полосы, 0–100. */
  pct: number
  /** Предел достигнут: строка подсвечивается, запуск на нём и встал. */
  hit: boolean
}

export type BudgetGroup = { key: AgentUsageGroup; label: string; hint: string; calls: number }

export type RunBudgetView = {
  meters: BudgetMeter[]
  /** Токены и цена записаны (запуск после E-9). */
  recorded: boolean
  tokensIn: number
  tokensOut: number
  cost: number
  /** Условная цена моделей своей ВМ по прайсу OpenRouter — её никто не платит. */
  costSelfHosted: number
  /** Реальные траты: OpenRouter (судья, личный ключ). */
  costPaid: number
  groups: BudgetGroup[]
}

function meter(
  key: BudgetMeter["key"],
  label: string,
  used: number,
  limit: number | null,
  stoppedHere: boolean,
): BudgetMeter {
  const pct = limit && limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0
  return { key, label, used, limit, pct, hit: stoppedHere || (limit != null && used >= limit) }
}

/** Строки секции «Расход»: шаги, вызовы и токены против пределов, цена и кто тратит. */
export function runBudget({
  usage,
  limits,
  stepsTaken,
  stopReason,
}: {
  usage: AgentRunUsage | null
  limits: AgentRunLimits | null
  stepsTaken: number
  stopReason: string | null
}): RunBudgetView {
  const calls = usage?.model_calls ?? 0
  const tokens = (usage?.tokens_in ?? 0) + (usage?.tokens_out ?? 0)
  const cost = usage?.cost_usd ?? 0
  const costSelfHosted = Math.min(cost, usage?.cost_self_hosted_usd ?? 0)
  // `model_budget` ставит любой из двух пределов модели — подсвечивается тот, что исчерпан
  // (used ≥ limit); шаги могут встать раньше счётчика, поэтому их подсвечивает и stop_reason.
  return {
    meters: [
      meter("steps", "Шаги", stepsTaken, limits?.max_steps ?? null, stopReason === "step_limit"),
      meter("calls", "Вызовы модели", calls, limits?.max_model_calls ?? null, false),
      meter("tokens", "Токены", tokens, limits?.max_tokens ?? null, false),
    ],
    recorded: usage != null,
    tokensIn: usage?.tokens_in ?? 0,
    tokensOut: usage?.tokens_out ?? 0,
    cost,
    costSelfHosted,
    costPaid: Math.max(0, cost - costSelfHosted),
    groups: USAGE_GROUPS.map((key) => ({
      key,
      label: USAGE_GROUP_LABEL[key],
      hint: USAGE_GROUP_HINT[key],
      calls: usage?.by_group[key]?.calls ?? 0,
    })),
  }
}
