import type { AppSettings } from "@/api/settings"

/**
 * Состояние блока OpenRouter на «Аккаунте» — чистая функция, чтобы ветвление жило в одном
 * месте и проверялось тестом, а не расползалось тернарниками по разметке.
 *
 * Пять состояний, а не два, потому что ключ теперь может прийти двумя путями:
 * - `own` — человек вставил свой ключ, он же им и распоряжается (есть «Сбросить»);
 * - `managed` — ключ выдал администратор: самого ключа человек не видит нигде и сбросить его
 *   не может (кнопка сброса отключила бы ему продукт), но вставить свой взамен вправе;
 * - `requested` — заявка отправлена, ждём решения;
 * - `rejected` — по заявке отказали, ключа нет;
 * - `missing` — ключа нет и заявок не было.
 */
export type OpenRouterKeyView = "own" | "managed" | "requested" | "rejected" | "missing"

export function openRouterKeyView(settings: AppSettings): OpenRouterKeyView {
  if (settings.openrouter_key_configured) {
    return settings.openrouter_key_origin === "admin" ? "managed" : "own"
  }
  const status = settings.openrouter_key_request_status
  if (status === "pending" || status === "approved") return "requested"
  if (status === "rejected") return "rejected"
  return "missing"
}

/** Ключ есть — разделы уже открыты, поле ввода не подсвечиваем. */
export function hasOpenRouterKey(view: OpenRouterKeyView): boolean {
  return view === "own" || view === "managed"
}
