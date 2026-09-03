import type { AdminUserRow } from "@/api/admin"
import { StatusDot } from "@/components/ui/status-chip"
import type { StatusTone } from "@/components/ui/status-chip"

const STEPS: {
  key: string
  label: string
  has: (user: AdminUserRow) => boolean
  missingTone: StatusTone
}[] = [
  { key: "key", label: "Ключ", has: (user) => user.has_openrouter_key, missingTone: "bad" },
  { key: "resume", label: "Резюме", has: (user) => user.has_resume, missingTone: "warn" },
  {
    key: "extension",
    label: "Расширение",
    has: (user) => user.extension_confirmed,
    missingTone: "warn",
  },
]

/**
 * Три точки подключения: ключ → резюме → расширение.
 *
 * Пройденная ступень — контурный кружок, а не залитая точка (Этап 0, §2.5). Раньше «всё на
 * месте» рисовалось насыщенным синим (токен `good` в продукте — синий, не зелёный), и в
 * каждой строке таблицы висели три ярких точки, которые ничего не сообщали.
 *
 * Подпись — нативный title, чтобы тултип работал и без тумблера «Подсказки»; на группе —
 * человеческая фраза целиком, иначе скринридер читает три отдельных «Ключ: есть».
 */
export function OnboardingDots({ user }: { user: AdminUserRow }) {
  const summary = STEPS.map((step) => `${step.label.toLowerCase()} ${step.has(user) ? "есть" : "нет"}`).join(", ")
  return (
    <span className="inline-flex items-center gap-1" aria-label={`Подключение: ${summary}`}>
      {STEPS.map((step) => {
        const ok = step.has(user)
        return (
          <span key={step.key} title={`${step.label}: ${ok ? "есть" : "нет"}`} className="inline-flex">
            {ok ? (
              <span
                aria-hidden
                className="inline-block size-2 shrink-0 rounded-full border border-slate-300"
              />
            ) : (
              <StatusDot tone={step.missingTone} />
            )}
          </span>
        )
      })}
    </span>
  )
}
