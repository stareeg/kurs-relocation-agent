import { MessageCircle } from "lucide-react"
import { Button } from "@/components/ui/button"

/** Кнопка «Спросить» в заголовке карточки графика (Заход 6, п.9): прикладывает срез данных
 * этого графика в композер чата «Рынка» как убираемый контекст — «как ответ на график». */
export function AskAboutButton({ onClick }: { onClick: () => void }) {
  return (
    <Button
      size="sm"
      variant="ghost"
      className="h-7 gap-1 px-2 text-xs text-slate-400 hover:text-slate-700"
      onClick={onClick}
      title="Спросить агента про этот график"
    >
      <MessageCircle className="size-3.5" strokeWidth={2} />
      Спросить
    </Button>
  )
}
