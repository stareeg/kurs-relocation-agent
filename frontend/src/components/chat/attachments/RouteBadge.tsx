import { MessageSquareText, Paperclip } from "lucide-react"
import { cn } from "@/lib/utils"
import type { AttachmentRoute } from "@/api/attachments"

// Ярлык-переключатель ветки на чипе (план §3, Э4-3): в режимах-парсерах (HR-импорт, разбор
// внешнего ИИ) картинка идёт либо в текстовый дамп («Переписка → импортирую реплики»), либо
// вложением диалога («Материал → приложу к сообщению»). Классификатор угадывает по
// `analysis.kind`, владелец правит одним кликом — решение видно ДО «Отправить», без немой магии.
// Дефолт/порог уверенности — в соседнем route.ts (чистые функции, без React).

const ROUTE_LABEL: Record<AttachmentRoute, string> = {
  correspondence: "Переписка",
  material: "Материал",
}

const ROUTE_TITLE: Record<AttachmentRoute, string> = {
  correspondence: "Переписка → импортирую реплики. Нажмите, чтобы приложить как материал.",
  material: "Материал → приложу к сообщению. Нажмите, чтобы импортировать как переписку.",
}

export function RouteBadge({
  route,
  onChange,
  expanded = false,
}: {
  route: AttachmentRoute
  onChange: (route: AttachmentRoute) => void
  /** Раскрытая форма (с подписью) — используется при низкой уверенности классификатора. */
  expanded?: boolean
}) {
  const isCorrespondence = route === "correspondence"
  return (
    <button
      type="button"
      aria-label={ROUTE_TITLE[route]}
      title={ROUTE_TITLE[route]}
      onClick={(e) => {
        e.stopPropagation()
        onChange(isCorrespondence ? "material" : "correspondence")
      }}
      className={cn(
        "absolute left-1 top-1 inline-flex items-center gap-0.5 rounded-full px-1 py-0.5 text-[9px] font-medium leading-none text-white shadow-sm transition-colors",
        isCorrespondence ? "bg-sky-600/90 hover:bg-sky-600" : "bg-slate-700/85 hover:bg-slate-700",
      )}
    >
      {isCorrespondence ? (
        <MessageSquareText className="size-2.5 shrink-0" strokeWidth={2} />
      ) : (
        <Paperclip className="size-2.5 shrink-0" strokeWidth={2} />
      )}
      {expanded ? <span>{ROUTE_LABEL[route]}</span> : null}
    </button>
  )
}
