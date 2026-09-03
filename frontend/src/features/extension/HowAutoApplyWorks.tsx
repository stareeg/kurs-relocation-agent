import { Check, ChevronDown, ChevronUp } from "lucide-react"
import { useState, type ReactNode } from "react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

// Жёсткие лимиты — те же числа, что на бэке (`auto_apply_daily_hard_cap` /
// `discovery_daily_hard_cap` / `extension_runtime_config.json`). Дублируются здесь только для
// показа пользователю; менять — вместе с бэком.
const LIMITS: { platform: string; view: number; apply: number }[] = [
  { platform: "hh.ru", view: 200, apply: 150 },
  { platform: "getmatch", view: 60, apply: 30 },
  { platform: "Habr Карьера", view: 60, apply: 30 },
]
const VIEW_INTERVAL = "30–90 сек"
const APPLY_INTERVAL = "2–5 мин"

const STEPS: ReactNode[] = [
  <>
    Включите <b className="font-semibold text-slate-800">Автопросмотр</b> на площадке — расширение
    оценит вакансии из ваших поисков.
  </>,
  <>
    В колонке «Просмотр» слева разложите вакансии:{" "}
    <b className="font-semibold text-slate-800">Автоотклик</b>,{" "}
    <b className="font-semibold text-slate-800">Вручную</b> или{" "}
    <b className="font-semibold text-slate-800">Пропуск</b>.
  </>,
  <>
    Переключите площадку на <b className="font-semibold text-slate-800">Отклики</b> и нажмите
    «Запустить».
  </>,
  <>
    Расширение откликается само по очереди. Не отправилось — вакансия уходит в «Ручной разбор».
  </>,
]

/** Инструкция + лимиты. Живёт в самом верху раздела «Расширение»; пока `acknowledged=false` —
 * карточки площадок ниже заблокированы (см. `ExtensionPage`). Кнопка «Прочитано» одноразовая,
 * состояние персистится в `ExtensionPage` (localStorage), повторно жать не нужно. */
export function HowAutoApplyWorks({
  acknowledged,
  onAcknowledge,
}: {
  acknowledged: boolean
  onAcknowledge: () => void
}) {
  // До подтверждения секция раскрыта и не сворачивается — прочитать нужно один раз.
  const [open, setOpen] = useState(!acknowledged)
  const expanded = acknowledged ? open : true

  return (
    <section
      className={cn(
        "rounded-xl border bg-white",
        !acknowledged && "border-sky-300 ring-1 ring-sky-100",
      )}
    >
      <button
        type="button"
        onClick={() => acknowledged && setOpen((v) => !v)}
        aria-expanded={expanded}
        className={cn(
          "flex w-full items-center justify-between gap-3 px-5 py-4 text-left",
          !acknowledged && "cursor-default",
        )}
      >
        <span className="flex items-center gap-2 text-base font-bold text-slate-900">
          Как работают автоотклики
          {!acknowledged && (
            <span className="rounded-full bg-sky-100 px-2 py-0.5 text-xs font-medium text-sky-700">
              прочитайте перед запуском
            </span>
          )}
        </span>
        {acknowledged ? (
          expanded ? (
            <ChevronUp className="size-4 shrink-0 text-slate-500" strokeWidth={2} />
          ) : (
            <ChevronDown className="size-4 shrink-0 text-slate-500" strokeWidth={2} />
          )
        ) : (
          <Check className="size-4 shrink-0 text-slate-300" strokeWidth={2} />
        )}
      </button>

      {expanded && (
        <div className="space-y-5 border-t px-5 pb-5 pt-4">
          <ol className="space-y-2.5">
            {STEPS.map((step, i) => (
              <li key={i} className="flex items-start gap-3">
                <span className="mt-px flex size-6 shrink-0 items-center justify-center rounded-full bg-sky-100 text-xs font-semibold text-sky-700">
                  {i + 1}
                </span>
                <span className="text-sm leading-6 text-slate-700">{step}</span>
              </li>
            ))}
          </ol>

          <div>
            <h3 className="text-base font-bold text-slate-900">Лимиты</h3>
            <div className="mt-2 overflow-x-auto rounded-lg border border-slate-200">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200 bg-slate-50 text-xs font-medium text-slate-500">
                    <th className="px-3 py-2 text-left">Площадка</th>
                    <th className="px-3 py-2 text-right">Просмотров&nbsp;в&nbsp;день</th>
                    <th className="px-3 py-2 text-right">Откликов&nbsp;в&nbsp;день</th>
                    <th className="px-3 py-2 text-right">Между&nbsp;просмотрами</th>
                    <th className="px-3 py-2 text-right">Между&nbsp;откликами</th>
                  </tr>
                </thead>
                <tbody>
                  {LIMITS.map((row) => (
                    <tr
                      key={row.platform}
                      className="border-b border-slate-100 last:border-b-0"
                    >
                      <td className="px-3 py-2 font-medium text-slate-800">{row.platform}</td>
                      <td className="px-3 py-2 text-right tabular-nums text-slate-700">
                        {row.view}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-slate-700">
                        {row.apply}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-slate-500">
                        {VIEW_INTERVAL}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-slate-500">
                        {APPLY_INTERVAL}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {!acknowledged && (
            <Button type="button" onClick={onAcknowledge}>
              <Check className="size-4" strokeWidth={2} />
              Прочитано
            </Button>
          )}
        </div>
      )}
    </section>
  )
}
