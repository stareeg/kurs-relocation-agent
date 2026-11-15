/**
 * Агент — главный экран (шаг U-0/U-1): один свободный чат с агентом. Раньше здесь жили
 * диалоги по вакансиям и контексты; переписка с HR переехала в правую панель раздела
 * «Вакансии» (вкладка «Чат» в дровере), «контексты» убраны, ручное добавление вакансии —
 * в тулбар «Вакансий». Старые ссылки `/chat?vacancy=…` (воронка, StageChain, расширение)
 * перенаправляем в дровер вакансии.
 */
import { useEffect } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"

import { AgentChat } from "@/features/agent/AgentChat"

export function ChatPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()

  // Совместимость: ссылки на чат конкретной вакансии теперь открывают её дровер в «Вакансиях».
  const deepVacancy = searchParams.get("vacancy")
  useEffect(() => {
    if (!deepVacancy) return
    navigate(`/jobs/${encodeURIComponent(deepVacancy)}`, { replace: true })
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        next.delete("vacancy")
        return next
      },
      { replace: true },
    )
  }, [deepVacancy, navigate, setSearchParams])

  return <AgentChat />
}
