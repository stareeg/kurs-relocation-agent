import { useState } from "react"
import ReactCrop, { centerCrop, makeAspectCrop, type PercentCrop } from "react-image-crop"
import "react-image-crop/dist/ReactCrop.css"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { cropAttachment, type AttachmentOut } from "@/api/attachments"
import { ApiError } from "@/api/client"
import type { AttachmentLike } from "./layout"

// Тонкая обвязка вокруг `react-image-crop` (план §6.5) — сам виджет кропа (8 ручек, touch,
// Shift/aspect) не пишем. Своё: подпись итогового размера в пикселях и конвертация `PercentCrop`
// в доли 0..1 для `POST /api/attachments/{id}/crop`.

function initialCrop(width: number, height: number): PercentCrop {
  return centerCrop(
    makeAspectCrop({ unit: "%", width: 90 }, width / height, width, height),
    width,
    height,
  )
}

export function ImageCropper({
  attachment,
  onOpenChange,
  onCropped,
}: {
  /** `null` — диалог закрыт. */
  attachment: AttachmentLike | null
  onOpenChange: (open: boolean) => void
  onCropped: (result: AttachmentOut) => void
}) {
  const [crop, setCrop] = useState<PercentCrop | undefined>(undefined)
  const [completed, setCompleted] = useState<PercentCrop | null>(null)
  const [busy, setBusy] = useState(false)

  function handleImageLoad() {
    if (!attachment) return
    const next = initialCrop(attachment.width, attachment.height)
    setCrop(next)
    setCompleted(next)
  }

  async function apply() {
    // Вырожденная область (клик без протяжки схлопывает выделение в 0×0) — backend всё равно
    // отклонит её `InvalidInput`, но лучше не гонять запрос впустую и не путать владельца общим
    // тостом на пустое выделение.
    if (!attachment || !completed || completed.width <= 0 || completed.height <= 0) return
    setBusy(true)
    try {
      const result = await cropAttachment(attachment.id, {
        x: completed.x / 100,
        y: completed.y / 100,
        w: completed.width / 100,
        h: completed.height / 100,
      })
      onCropped(result)
      onOpenChange(false)
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Не удалось обрезать картинку")
    } finally {
      setBusy(false)
    }
  }

  const pixelSize =
    completed && attachment
      ? {
          w: Math.round((completed.width / 100) * attachment.width),
          h: Math.round((completed.height / 100) * attachment.height),
        }
      : null

  return (
    <Dialog
      open={attachment != null}
      onOpenChange={(open) => {
        if (!open) onOpenChange(false)
      }}
    >
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Кадрирование</DialogTitle>
        </DialogHeader>
        {attachment ? (
          <div className="flex justify-center">
            <ReactCrop
              crop={crop}
              onChange={(_, percentCrop) => setCrop(percentCrop)}
              onComplete={(_, percentCrop) => setCompleted(percentCrop)}
            >
              <img
                src={attachment.url}
                onLoad={handleImageLoad}
                className="max-h-[70vh] w-auto"
                alt="Кадрирование"
              />
            </ReactCrop>
          </div>
        ) : null}
        {pixelSize ? (
          <p className="text-center text-xs text-muted-foreground">
            {pixelSize.w} × {pixelSize.h} px
          </p>
        ) : null}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            Отмена
          </Button>
          <Button
            onClick={() => void apply()}
            disabled={busy || !completed || completed.width <= 0 || completed.height <= 0}
          >
            Применить
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
