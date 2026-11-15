import type { AppSettings } from "@/api/settings"

/**
 * Состояние блока модели на «Аккаунте» — чистая функция, чтобы ветвление жило в одном
 * месте и проверялось тестом, а не расползалось тернарниками по разметке.
 *
 * Состояния:
 * - `own` — человек вставил свой ключ OpenRouter, он же им и распоряжается (есть «Сбросить»);
 * - `managed` — ключ выдал администратор: самого ключа человек не видит нигде и сбросить его
 *   не может (кнопка сброса отключила бы ему продукт), но вставить свой взамен вправе;
 * - `server` — A-0: ключ не нужен, модель курса выдаёт серверный провайдер; свой ключ можно
 *   вставить для тестов, расход тогда пойдёт на счёт OpenRouter человека;
 * - `requested` — заявка отправлена, ждём решения;
 * - `rejected` — по заявке отказали, ключа нет;
 * - `missing` — ключа нет, серверной модели нет и заявок не было.
 */
export type OpenRouterKeyView = "own" | "managed" | "server" | "requested" | "rejected" | "missing"

export function openRouterKeyView(settings: AppSettings): OpenRouterKeyView {
  if (settings.openrouter_key_configured) {
    return settings.openrouter_key_origin === "admin" ? "managed" : "own"
  }
  if (settings.server_llm_available) return "server"
  const status = settings.openrouter_key_request_status
  if (status === "pending" || status === "approved") return "requested"
  if (status === "rejected") return "rejected"
  return "missing"
}

/** Доступ к модели есть: свой ключ, ключ от администратора или серверный провайдер. */
export function hasOpenRouterKey(view: OpenRouterKeyView): boolean {
  return view === "own" || view === "managed" || view === "server"
}
