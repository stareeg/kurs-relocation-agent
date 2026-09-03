import type { ReactNode } from "react"
import { HelpTip } from "@/components/ui/help-tip"
import type { HelpTextId } from "@/lib/help-texts"

/** Подпись поля в левой панели скоринга.
 *
 * Чёрная и чуть жирнее чипов-значений, чтобы ось и выбор не сливались.
 * `needsFill` — янтарная точка «стоит заполнить», компактнее `NeedsFillMark` формы.
 */
export function PanelFieldLabel({
  children,
  helpId,
  needsFill,
}: {
  children: ReactNode
  helpId?: HelpTextId
  needsFill?: boolean
}) {
  return (
    <span className="flex items-center gap-1 text-sm font-semibold leading-tight text-slate-900">
      {children}
      {needsFill ? (
        <span className="text-amber-500" title="Стоит заполнить">
          ·
        </span>
      ) : null}
      {helpId ? <HelpTip id={helpId} /> : null}
    </span>
  )
}

/** Строка портрета: подпись слева, чипы справа. */
export function PanelFieldRow({
  label,
  helpId,
  needsFill,
  children,
}: {
  label: ReactNode
  helpId?: HelpTextId
  needsFill?: boolean
  children: ReactNode
}) {
  return (
    <div className="flex items-center gap-1">
      <div className="w-[7.25rem] shrink-0">
        <PanelFieldLabel helpId={helpId} needsFill={needsFill}>
          {label}
        </PanelFieldLabel>
      </div>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  )
}

/** Подблок скоринга: заголовок над карточкой. `action` — справа в строке заголовка
 *  (кнопка свернуть панель на одной линии со «Скоринг»). */
export function ScoringSubblock({
  title,
  action,
  children,
}: {
  title: string
  action?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="space-y-1">
      <div className="flex items-center gap-1">
        {action ? <span className="size-7 shrink-0" aria-hidden /> : null}
        <h4 className="min-w-0 flex-1 text-center text-sm font-semibold leading-none text-slate-900">
          {title}
        </h4>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
      <div className="rounded-xl border bg-white px-3 py-2.5">
        <div className="space-y-2">{children}</div>
      </div>
    </section>
  )
}
