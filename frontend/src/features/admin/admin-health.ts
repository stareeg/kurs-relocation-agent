/**
 * Полоса здоровья установки: факты `AdminHealth` → строка фактов.
 *
 * Тон считает фронт, а не бэкенд: правило «когда краснеть» проверяется тестом,
 * а не глазами по экрану (Этап 2.1).
 *
 * `ok` — не «зелёная точка», а отсутствие точки (Этап 0 редизайна, §2.5): цвет в разделе
 * означает только «посмотри сюда». Раньше здоровая установка рисовала шесть цветных точек,
 * и красная среди них терялась.
 */
import type { AdminHealth } from "@/api/admin"
import { FAILURES, pluralize, relativeSeen } from "./admin-format"

/** Тон факта установки. `ok` рисуется без точки — см. HealthStrip. */
export type HealthTone = "ok" | "warn" | "bad"

export type HealthItem = {
  key: "extension" | "backend" | "postgres" | "worker" | "queue" | "migrations" | "llm"
  label: string
  value: string
  tone: HealthTone
  hint: string
  /**
   * Готовая фраза для строки-вердикта в шапке — «Postgres не отвечает», «очередь: 23 сбоя».
   * Есть только у `warn`/`bad`: у здорового факта сообщать нечего. Отдельным полем, а не
   * склейкой `label + value`, потому что читаемая фраза у каждого факта своя («Миграции 140 /
   * 141» в шапке должно звучать как «миграции отстают»).
   */
  alarm?: string
}

function bytes(n: number | null | undefined): string {
  if (n == null || n < 0) return "нет данных"
  if (n < 1024) return `${n} Б`
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} КБ`
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} МБ`
  return `${(n / (1024 * 1024 * 1024)).toFixed(1)} ГБ`
}

function shortSlug(slug: string): string {
  const trimmed = slug.trim()
  if (!trimmed) return "—"
  const slash = trimmed.lastIndexOf("/")
  return slash >= 0 ? trimmed.slice(slash + 1) : trimmed
}

/** Короткие имена моделей без повторов: advanced и reserve часто один и тот же slug. */
export function uniqueModelSlugs(health: AdminHealth | undefined): string[] {
  if (!health) return []
  const seen = new Set<string>()
  const out: string[] = []
  for (const slug of [
    health.model_tier_advanced,
    health.model_tier_basic,
    health.model_tier_reserve,
  ]) {
    const trimmed = slug.trim()
    if (!trimmed) continue
    const short = shortSlug(trimmed)
    if (seen.has(short)) continue
    seen.add(short)
    out.push(short)
  }
  return out
}

export function buildHealthItems(health: AdminHealth | undefined): HealthItem[] {
  if (!health) return []
  const queue = health.queue
  const queueFailed = queue.failed
  const queueBusy = queue.pending + queue.running
  const queueTone: HealthTone = queueFailed > 0 ? "bad" : queueBusy > 20 ? "warn" : "ok"
  const queueValue =
    queueFailed > 0
      ? pluralize(queueFailed, FAILURES)
      : queueBusy > 0
        ? `${queue.pending} ждут · ${queue.running} в работе`
        : "тихо"

  const applied = health.migrations_applied
  const available = health.migrations_available
  const migTone: HealthTone = available <= 0 ? "warn" : applied < available ? "bad" : "ok"

  const tiers = [
    health.model_tier_advanced,
    health.model_tier_basic,
    health.model_tier_reserve,
  ]
  const filled = tiers.filter((t) => t.trim()).length
  const llmTone: HealthTone = filled === 3 ? "ok" : filled === 0 ? "bad" : "warn"
  const models = uniqueModelSlugs(health)

  const lastFinished = health.worker_last_finished_at
    ? relativeSeen(health.worker_last_finished_at)
    : "ещё не было"

  return [
    {
      key: "extension",
      label: "Расширение",
      value: health.extension_version || "неизвестно",
      tone: health.extension_version ? "ok" : "warn",
      hint: "Версия из extension/manifest.json, которую отдаёт бэкенд.",
      alarm: health.extension_version ? undefined : "версия расширения неизвестна",
    },
    {
      key: "backend",
      label: "Бэкенд",
      value: health.git_sha || "неизвестно",
      tone: health.git_sha ? "ok" : "warn",
      hint: "COPILOT_GIT_SHA из образа. Пусто — сборка без коммита.",
      alarm: health.git_sha ? undefined : "сборка без коммита",
    },
    {
      key: "postgres",
      label: "Postgres",
      value: health.postgres_ok ? bytes(health.postgres_size_bytes) : "не отвечает",
      tone: health.postgres_ok ? "ok" : "bad",
      hint: "Факт успешного запроса и размер базы.",
      alarm: health.postgres_ok ? undefined : "Postgres не отвечает",
    },
    {
      key: "worker",
      label: "Воркер",
      value: health.worker_running ? `жив · ${lastFinished}` : "не запущен",
      tone: health.worker_running ? "ok" : "bad",
      alarm: health.worker_running ? undefined : "воркер не запущен",
      hint: health.worker_running
        ? "Последняя завершённая задача."
        : "Очередь не разбирается, пока процесс не поднят.",
    },
    {
      key: "queue",
      label: "Очередь",
      value: queueValue,
      tone: queueTone,
      alarm: queueTone === "ok" ? undefined : `очередь: ${queueValue}`,
      hint: `pending ${queue.pending} · running ${queue.running} · failed ${queue.failed} · done ${queue.done} · cancelled ${queue.cancelled ?? 0}`,
    },
    {
      key: "migrations",
      label: "Миграции",
      value: available > 0 ? `${applied} / ${available}` : "нет файлов",
      tone: migTone,
      alarm: migTone === "bad" ? "миграции отстают" : migTone === "warn" ? "миграций нет" : undefined,
      hint:
        applied < available
          ? "На диске есть миграции, которых нет в schema_migrations."
          : "Максимальный номер файла совпадает с применённым.",
    },
    {
      key: "llm",
      label: "Модели",
      value: models.join(" · ") || "—",
      tone: llmTone,
      alarm:
        llmTone === "bad" ? "модели не заданы" : llmTone === "warn" ? "модель не задана" : undefined,
      hint: `advanced ${shortSlug(health.model_tier_advanced)} · basic ${shortSlug(health.model_tier_basic)} · reserve ${shortSlug(health.model_tier_reserve)}`,
    },
  ]
}
