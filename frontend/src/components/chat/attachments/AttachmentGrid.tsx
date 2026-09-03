import { useState } from "react"
import { Download, FileText, ImageOff } from "lucide-react"
import { cn } from "@/lib/utils"
import { documentExtLabel } from "./document-kind"
import {
  attachmentGridLayout,
  singleImageLayout,
  visibleAttachmentCount,
  type AttachmentLike,
} from "./layout"
import { useAttachmentMeta } from "./use-attachment-upload"
import { ImageViewer } from "./ImageViewer"

function isImageAttachment(a: AttachmentLike): boolean {
  return a.mime.startsWith("image/")
}

/** Документ (txt/md/pdf/docx) в ленте сообщения — нет пикселей для миниатюры, просто
 * иконка + имя + ссылка на скачивание. */
function DocumentChip({ attachment }: { attachment: AttachmentLike }) {
  const title = attachment.analysis?.title || "Документ"
  return (
    <a
      href={attachment.url}
      target="_blank"
      rel="noopener noreferrer"
      className="flex items-center gap-2 rounded-lg border bg-white px-2.5 py-2 text-sm transition-colors hover:bg-slate-50"
    >
      <FileText className="size-5 shrink-0 text-slate-400" strokeWidth={1.5} />
      <span className="min-w-0 flex-1 truncate font-medium text-slate-700">{title}</span>
      <span className="shrink-0 text-[10px] font-semibold tracking-wide text-slate-400">
        {documentExtLabel(attachment.mime, title)}
      </span>
      <Download className="size-3.5 shrink-0 text-slate-300" strokeWidth={2} />
    </a>
  )
}

// Сетка/одиночная картинка внутри пузыря (план §6.3) — общий код для «Чаты» и «Технички»
// (потребители в `features/jobs`/`features/tech`, обратный импорт дал бы цикл — см. заголовок
// `composer-widgets.tsx`).

/** Один снимок вложения, живо освежаемый по `["attachment", id]` (Э1-7) — отдельный компонент,
 * чтобы `useAttachmentMeta` не звался внутри `.map` (правило хуков). */
function LiveThumb({
  attachment,
  className,
  imgClassName,
  onClick,
  alt,
}: {
  attachment: AttachmentLike
  className: string
  imgClassName: string
  onClick: (rect: DOMRect) => void
  alt: string
}) {
  const { data } = useAttachmentMeta(attachment.id, attachment)
  const live = data ?? attachment
  // Э5-3: битый блоб (нет PG, GC снёс, сетевой сбой на `/thumb`) — не иконка "битой картинки"
  // браузера, а плитка с явным поводом и повтором. `retryNonce` в query-строке заставляет `<img>`
  // перезапросить байты, даже если браузер закэшировал именно неудачный ответ.
  const [broken, setBroken] = useState(false)
  const [retryNonce, setRetryNonce] = useState(0)

  if (broken) {
    return (
      <div
        className={cn(
          "flex flex-col items-center justify-center gap-1 bg-muted/60 p-2 text-center",
          className,
        )}
      >
        <ImageOff className="size-4 text-muted-foreground" strokeWidth={1.5} />
        <span className="text-[10px] leading-tight text-muted-foreground">
          Картинка не открылась
        </span>
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation()
            setBroken(false)
            setRetryNonce((n) => n + 1)
          }}
          className="text-[10px] font-medium text-primary underline-offset-2 hover:underline"
        >
          Повторить
        </button>
      </div>
    )
  }

  return (
    <button
      type="button"
      data-attachment-thumb
      onClick={(e) => onClick(e.currentTarget.getBoundingClientRect())}
      className={cn("relative block overflow-hidden", className)}
    >
      <img
        src={retryNonce > 0 ? `${live.thumb_url}?retry=${retryNonce}` : live.thumb_url}
        alt={alt}
        className={imgClassName}
        onError={() => setBroken(true)}
      />
    </button>
  )
}

export function AttachmentGrid({
  attachments,
  className,
  onCropRequested,
  onThumbnailClick,
}: {
  attachments: AttachmentLike[]
  className?: string
  onCropRequested?: (attachment: AttachmentLike) => void
  /** Вызывается перед открытием просмотрщика; вернуть `false` подавляет открытие (режим выделения). */
  onThumbnailClick?: (index: number) => boolean | void
}) {
  const [viewerIndex, setViewerIndex] = useState<number | null>(null)
  // §6.4: FLIP-открытие/закрытие просмотрщика из rect миниатюры, по которой кликнули. Один и тот
  // же rect используется и на закрытие, даже если успели полистать ←/→ — переизмерять на каждый
  // шаг незачем, это не тот масштаб задачи (см. план про pinch-zoom рядом).
  const [viewerOrigin, setViewerOrigin] = useState<DOMRect | null>(null)
  const [expanded, setExpanded] = useState(false)

  if (attachments.length === 0) return null

  // Документы (txt/md/pdf/docx, 2026-08-11) — нет пикселей для сетки/просмотрщика, свой
  // список ниже. Вся геометрия сетки/индексы просмотрщика остаются считаны только по картинкам.
  const images = attachments.filter(isImageAttachment)
  const docs = attachments.filter((a) => !isImageAttachment(a))

  function open(index: number, rect: DOMRect) {
    const proceed = onThumbnailClick?.(index)
    if (proceed === false) return
    setViewerOrigin(rect)
    setViewerIndex(index)
  }

  function closeViewer() {
    setViewerIndex(null)
    setViewerOrigin(null)
  }

  const docsBlock =
    docs.length > 0 ? (
      <div className={cn("flex flex-col gap-1.5", images.length > 0 && "mt-1.5", className)}>
        {docs.map((d) => (
          <DocumentChip key={d.id} attachment={d} />
        ))}
      </div>
    ) : null

  if (images.length === 0) return docsBlock

  if (images.length === 1) {
    const a = images[0]
    const layout = singleImageLayout(a.width, a.height, { expanded })
    return (
      <>
        <div className={cn("relative", layout.wrapClassName, className)}>
          <LiveThumb
            attachment={a}
            className="size-full rounded-[inherit]"
            imgClassName={layout.imgClassName}
            onClick={(rect) => open(0, rect)}
            alt={a.analysis?.title ?? "Скриншот"}
          />
          {layout.showFadeOverlay ? (
            <div className="pointer-events-none absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-black/55 to-transparent" />
          ) : null}
          {layout.showExpandButton ? (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                setExpanded(true)
              }}
              className="absolute inset-x-0 bottom-1 mx-auto w-fit rounded-full bg-black/55 px-2.5 py-1 text-xs text-white transition-colors hover:bg-black/70"
            >
              Вся картинка
            </button>
          ) : null}
        </div>
        {viewerIndex != null ? (
          <ImageViewer
            attachments={images}
            index={viewerIndex}
            onIndexChange={setViewerIndex}
            onClose={closeViewer}
            onCropRequested={onCropRequested}
            originRect={viewerOrigin}
          />
        ) : null}
        {docsBlock}
      </>
    )
  }

  const grid = attachmentGridLayout(images.length)
  const visible = visibleAttachmentCount(images.length)

  return (
    <>
      <div className={cn(grid.containerClassName, "overflow-hidden rounded-[inherit]", className)}>
        {images.slice(0, visible).map((a, i) => {
          const isLastOverflow = grid.overflowCount > 0 && i === visible - 1
          return (
            <div key={a.id} className={cn("relative", grid.cellClassNames[i])}>
              <LiveThumb
                attachment={a}
                className="size-full"
                imgClassName="size-full object-cover"
                onClick={(rect) => open(i, rect)}
                alt={a.analysis?.title ?? "Скриншот"}
              />
              {isLastOverflow ? (
                <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-black/45 text-sm font-medium text-white">
                  +{grid.overflowCount}
                </div>
              ) : null}
            </div>
          )
        })}
      </div>
      {viewerIndex != null ? (
        <ImageViewer
          attachments={images}
          index={viewerIndex}
          onIndexChange={setViewerIndex}
          onClose={closeViewer}
          onCropRequested={onCropRequested}
          originRect={viewerOrigin}
        />
      ) : null}
      {docsBlock}
    </>
  )
}
