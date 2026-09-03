import { useLayoutEffect, useRef, useState } from "react"
import { Dialog as DialogPrimitive } from "radix-ui"
import {
  ChevronLeft,
  ChevronRight,
  Copy,
  Crop,
  Download,
  ExternalLink,
  ImageOff,
  X,
} from "lucide-react"
import { TransformComponent, TransformWrapper } from "react-zoom-pan-pinch"
import { toast } from "sonner"
import { cn, prefersReducedMotion } from "@/lib/utils"
import { copyImageToClipboard } from "./copy-image"
import { flipKeyframes, FLIP_DURATION_MS, FLIP_EASING } from "./flip"
import type { AttachmentLike } from "./layout"

// Полноэкранный просмотрщик (план §6.4). Своя обвязка вокруг Radix-примитивов (не
// `components/ui/dialog.tsx` — тот рассчитан на маленькую центрированную карточку, а тут нужен
// fullscreen-фон и собственный тулбар); зум/пан — `react-zoom-pan-pinch` (не самопис, см. план).

export interface ImageViewerProps {
  attachments: AttachmentLike[]
  index: number
  onIndexChange: (index: number) => void
  onClose: () => void
  onCropRequested?: (attachment: AttachmentLike) => void
  /** Rect миниатюры, с которой открыли просмотрщик (план §6.4) — задаёт FLIP; `null`/reduced
   * motion → обычный fade без перелёта. */
  originRect?: DOMRect | null
}

// §6.4 правка 2026-08-04 (жалоба «кнопки мелкие и незаметные»): единый тулбар — одна тёмная
// пилюля по центру снизу изображения (не строка тонких иконок сверху), кнопки крупные (size-11,
// иконки size-5) с явным hover/focus-фоном — палец/курсор не должен целиться в 32px иконку.
const TOOLBAR_BUTTON_CLASS =
  "flex size-11 shrink-0 items-center justify-center rounded-full text-white/90 transition-colors hover:bg-white/20 hover:text-white focus-visible:bg-white/20 focus-visible:outline-none"

function ToolbarButton({
  icon: Icon,
  label,
  onClick,
}: {
  icon: typeof Copy
  label: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className={TOOLBAR_BUTTON_CLASS}
    >
      <Icon className="size-5" strokeWidth={2} />
    </button>
  )
}

function ToolbarLink({
  icon: Icon,
  label,
  href,
  downloadName,
  newTab,
}: {
  icon: typeof Copy
  label: string
  href: string
  downloadName?: string
  newTab?: boolean
}) {
  return (
    <a
      href={href}
      aria-label={label}
      title={label}
      className={TOOLBAR_BUTTON_CLASS}
      download={downloadName}
      target={newTab ? "_blank" : undefined}
      rel={newTab ? "noopener noreferrer" : undefined}
    >
      <Icon className="size-5" strokeWidth={2} />
    </a>
  )
}

export function ImageViewer({
  attachments,
  index,
  onIndexChange,
  onClose,
  onCropRequested,
  originRect = null,
}: ImageViewerProps) {
  const [showText, setShowText] = useState(false)
  const [shownIndex, setShownIndex] = useState(index)
  const [open, setOpen] = useState(true)
  const imgRef = useRef<HTMLImageElement>(null)
  const closingRef = useRef(false)
  const current = attachments[index]
  // Э5-3: битый блоб полноразмерной картинки — плитка с поводом и повтором вместо иконки
  // "битой картинки" браузера; `retryNonce` бьёт кэш неудачного ответа на повтор.
  const [broken, setBroken] = useState(false)
  const [retryNonce, setRetryNonce] = useState(0)

  // Смена картинки листанием ←/→ сворачивает раскрытый текст распознавания и сбрасывает состояние
  // отказа предыдущей картинки — подстраивается прямо при рендере (react-hooks/set-state-in-effect
  // против setState в эффекте).
  if (index !== shownIndex) {
    setShownIndex(index)
    setShowText(false)
    setBroken(false)
    setRetryNonce(0)
  }

  // §6.4: FLIP-открытие из rect миниатюры — только на первом кадре монтирования. useLayoutEffect,
  // а не useEffect: замер и первый keyframe должны быть готовы до отрисовки браузером, иначе один
  // кадр картинка мелькнёт в финальной позиции, а потом «прыгнет» в стартовую для WAAPI.
  useLayoutEffect(() => {
    const img = imgRef.current
    if (!img || !originRect || prefersReducedMotion()) return
    const finalRect = img.getBoundingClientRect()
    img.animate(flipKeyframes(originRect, finalRect), {
      duration: FLIP_DURATION_MS,
      easing: FLIP_EASING,
      fill: "both",
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps -- только на монтировании просмотрщика
  }, [])

  if (!current) return null

  const hasMultiple = attachments.length > 1
  const analysis = current.analysis

  function goPrev() {
    if (index > 0) onIndexChange(index - 1)
  }
  function goNext() {
    if (index < attachments.length - 1) onIndexChange(index + 1)
  }

  // §6.4: закрытие летит обратно в ту же миниатюру; без rect/reduced-motion — просто fade
  // (Overlay/Content уже несут data-[state=closed]:animate-out).
  function requestClose() {
    if (closingRef.current) return
    closingRef.current = true
    const img = imgRef.current
    if (!img || !originRect || prefersReducedMotion()) {
      setOpen(false)
      onClose()
      return
    }
    setOpen(false)
    const finalRect = img.getBoundingClientRect()
    const anim = img.animate(flipKeyframes(originRect, finalRect), {
      duration: FLIP_DURATION_MS,
      easing: FLIP_EASING,
      fill: "both",
      direction: "reverse",
    })
    anim.onfinish = onClose
  }

  return (
    <DialogPrimitive.Root
      open={open}
      onOpenChange={(next) => {
        if (!next) requestClose()
      }}
    >
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <DialogPrimitive.Content
          className="fixed inset-0 z-50 flex flex-col outline-none data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0"
          onKeyDown={(e) => {
            if (e.key === "ArrowLeft") {
              e.preventDefault()
              goPrev()
            } else if (e.key === "ArrowRight") {
              e.preventDefault()
              goNext()
            }
          }}
        >
          <DialogPrimitive.Title className="sr-only">
            {analysis?.title ?? "Просмотр картинки"}
          </DialogPrimitive.Title>

          {hasMultiple ? (
            <div className="flex shrink-0 justify-end px-3 py-2">
              <div className="rounded-full bg-black/40 px-2.5 py-1 text-xs text-white/85">
                {index + 1} / {attachments.length}
              </div>
            </div>
          ) : null}

          <div className="relative min-h-0 flex-1">
            {broken ? (
              <div className="flex size-full flex-col items-center justify-center gap-2 text-white/85">
                <ImageOff className="size-8" strokeWidth={1.5} />
                <p className="text-sm">Картинка не открылась</p>
                <button
                  type="button"
                  onClick={() => {
                    setBroken(false)
                    setRetryNonce((n) => n + 1)
                  }}
                  className="rounded-md bg-white/10 px-3 py-1 text-xs font-medium transition-colors hover:bg-white/20"
                >
                  Повторить
                </button>
              </div>
            ) : (
              <TransformWrapper
                key={current.id}
                minScale={1}
                maxScale={8}
                centerOnInit
                doubleClick={{ mode: "toggle" }}
              >
                <TransformComponent
                  wrapperClass="!size-full"
                  contentClass="!size-full flex items-center justify-center"
                >
                  <img
                    ref={imgRef}
                    src={retryNonce > 0 ? `${current.url}?retry=${retryNonce}` : current.url}
                    alt={analysis?.title ?? "Скриншот"}
                    className="max-h-full max-w-full object-contain"
                    onError={() => setBroken(true)}
                  />
                </TransformComponent>
              </TransformWrapper>
            )}

            {hasMultiple ? (
              <>
                <button
                  type="button"
                  onClick={goPrev}
                  disabled={index === 0}
                  aria-label="Предыдущая картинка"
                  className="absolute left-2 top-1/2 -translate-y-1/2 rounded-full bg-black/40 p-2 text-white transition-opacity hover:bg-black/60 disabled:opacity-30"
                >
                  <ChevronLeft className="size-5" strokeWidth={2} />
                </button>
                <button
                  type="button"
                  onClick={goNext}
                  disabled={index === attachments.length - 1}
                  aria-label="Следующая картинка"
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded-full bg-black/40 p-2 text-white transition-opacity hover:bg-black/60 disabled:opacity-30"
                >
                  <ChevronRight className="size-5" strokeWidth={2} />
                </button>
              </>
            ) : null}

            <div className="pointer-events-none absolute inset-x-0 bottom-4 flex justify-center px-3">
              <div className="pointer-events-auto flex items-center gap-1 rounded-full bg-black/70 p-1.5 shadow-lg backdrop-blur-sm">
                {onCropRequested ? (
                  <ToolbarButton
                    icon={Crop}
                    label="Кадрировать"
                    onClick={() => onCropRequested(current)}
                  />
                ) : null}
                <ToolbarButton
                  icon={Copy}
                  label="Копировать"
                  onClick={() => {
                    void copyImageToClipboard(current.url).then(
                      () => toast.success("Картинка скопирована"),
                      () => toast.error("Не удалось скопировать"),
                    )
                  }}
                />
                <ToolbarLink
                  icon={Download}
                  label="Скачать"
                  href={current.url}
                  downloadName={`attachment-${current.id}`}
                />
                <ToolbarLink
                  icon={ExternalLink}
                  label="Открыть в новой вкладке"
                  href={current.url}
                  newTab
                />
                <div className="mx-1 h-6 w-px shrink-0 bg-white/20" />
                <DialogPrimitive.Close asChild>
                  <ToolbarButton icon={X} label="Закрыть" onClick={() => {}} />
                </DialogPrimitive.Close>
              </div>
            </div>
          </div>

          {analysis ? (
            <div className="shrink-0 bg-black/70 px-3 py-2 text-white">
              <button
                type="button"
                onClick={() => setShowText((v) => !v)}
                className="w-full text-left"
              >
                <p className="text-sm font-medium">{analysis.title}</p>
                <p className="text-xs text-white/70">{analysis.summary}</p>
              </button>
              {showText ? (
                <div className="mt-2 max-h-40 space-y-2 overflow-auto rounded-md bg-black/40 p-2">
                  <p className="whitespace-pre-wrap text-xs text-white/90">{analysis.text}</p>
                  <button
                    type="button"
                    onClick={() => void navigator.clipboard.writeText(analysis.text)}
                    className={cn(
                      "rounded-md bg-white/10 px-2 py-1 text-xs text-white transition-colors hover:bg-white/20",
                    )}
                  >
                    Копировать текст
                  </button>
                </div>
              ) : null}
            </div>
          ) : null}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  )
}
