import { Check, X } from "lucide-react"
import { cn } from "@/lib/utils"

/**
 * Да/нет в таблице людей: зелёная галочка или красный крестик.
 *
 * Цвет здесь — ответ на вопрос «всё ли в порядке у ступени», а не декоративный статус
 * здоровой установки: без него три колонки Ключ / Резюме / Расширение не читаются.
 */
export function StatusMark({ ok, label }: { ok: boolean; label: string }) {
  const Icon = ok ? Check : X
  return (
    <span className="inline-flex justify-center" title={label} aria-label={label}>
      <Icon
        className={cn("size-4", ok ? "text-emerald-600" : "text-red-600")}
        strokeWidth={2.5}
      />
    </span>
  )
}
