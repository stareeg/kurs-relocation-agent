import { MessageSquare } from "lucide-react"
import { useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"

// Компактный вход в чат по вакансии из рельса Скринингов/Техничек/Офферов — между «Отказ» и
// шагом вперёд. Раньше чат по этой же вакансии искали переключением разделов вслепую: рельс
// показывает, на каком этапе вакансия, но не давал открыть её переписку.
export function RailChatButton({ vacancyId }: { vacancyId: string | null | undefined }) {
  const navigate = useNavigate()
  if (!vacancyId) return null
  return (
    <Button
      size="sm"
      variant="outline"
      className="h-7 gap-1 border-sky-200 bg-sky-50 px-2 text-xs text-sky-700 hover:bg-sky-100"
      aria-label="Открыть чат по вакансии"
      title="Чат по вакансии — переписка с HR и агентом"
      onClick={() => navigate(`/chat?vacancy=${encodeURIComponent(vacancyId)}`)}
    >
      <MessageSquare className="size-3.5" strokeWidth={2} />
      Чат
    </Button>
  )
}
