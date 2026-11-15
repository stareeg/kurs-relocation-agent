/**
 * Диалог «Добавить вакансию» (шаг U-0/U-1): ручное добавление переехало из старого
 * раздела «Чаты» в тулбар «Вакансий» — та же форма (компания/должность/ссылка/HR/
 * переписка), после создания открываем дровер вакансии по deep-link.
 */
import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useQueryClient } from "@tanstack/react-query"

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { useConversations } from "@/features/chat/use-conversations"
import {
  NewVacancyForm,
  defaultOutreachDraft,
  type OutreachDraftFields,
} from "@/features/chat/NewVacancyConversationPane"

export function AddVacancyDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  // Ленты диалогов и вакансий: новая вакансия (или привязка к существующей) должна
  // засветиться сразу — инвалидируем обе (тот же приём, что был в ChatPage).
  const { refetch: refetchConversations } = useConversations(false)
  const [draft, setDraft] = useState<OutreachDraftFields>(defaultOutreachDraft)

  function onCreated(vacancyId: string) {
    setDraft(defaultOutreachDraft())
    void qc.invalidateQueries({ queryKey: ["jobs"] })
    void refetchConversations()
    onOpenChange(false)
    navigate(`/jobs/${encodeURIComponent(vacancyId)}`)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[90vh] flex-col overflow-hidden p-0 sm:max-w-lg">
        <DialogHeader className="shrink-0 px-4 pb-0 pt-4">
          <DialogTitle>Добавить вакансию</DialogTitle>
          <DialogDescription>
            Вручную: компания и переписка с HR, либо просто текст вакансии.
          </DialogDescription>
        </DialogHeader>
        <NewVacancyForm
          draft={draft}
          onDraftChange={setDraft}
          onCreated={onCreated}
        />
      </DialogContent>
    </Dialog>
  )
}
