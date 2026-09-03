import { Check, FileSearch } from "lucide-react"
import { cn } from "@/lib/utils"

// Отметка на карточке рельса: расшифровка этапа вставлена и разобрана — или ещё нет.
// Именно подписью, а не «умным огоньком»: цветная точка без слова не отвечала на вопрос «что
// это значит», а понять «вставил я расшифровку по этой вакансии или нет» нужно взглядом по
// списку, не заходя в каждую карточку.
export function TranscriptMark({ done, className }: { done: boolean; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex w-fit shrink-0 items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs font-medium leading-none",
        done
          ? "border-status-strong-line bg-status-strong-soft text-status-strong-fg"
          : "border-dashed border-slate-200 text-slate-400",
        className,
      )}
      title={
        done
          ? "Расшифровка вставлена и разобрана"
          : "Расшифровки нет — вставьте её в режиме «Расшифровка» под чатом"
      }
    >
      {done ? (
        <Check className="size-3" strokeWidth={2.5} />
      ) : (
        <FileSearch className="size-3" strokeWidth={2} />
      )}
      Расшифровка
    </span>
  )
}
