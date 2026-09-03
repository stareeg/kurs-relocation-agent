import { useRef, useState } from "react"
import { AlertTriangle, FileText, Sparkles, X } from "lucide-react"
import { cn, motionStaggerClass, prefersReducedMotion, MOTION_POP } from "@/lib/utils"
import type { AttachmentRoute } from "@/api/attachments"
import { documentExtLabel } from "./document-kind"
import { isLowConfidenceRoute } from "./route"
import { RouteBadge } from "./RouteBadge"
import type { PendingAttachment } from "./use-attachment-upload"
import { isImageFile } from "./use-paste-images"

// Ряд чипов над textarea композера (план §6.1). Мгновенный локальный превью — `previewUrl`
// (objectURL) хука `useAttachmentUpload`, а не серверная миниатюра: не ждём round-trip, чтобы
// показать то, что владелец только что вставил.

const CHIP_SIZE = "size-16"
const CHIP_SIZE_REM = 4 // size-16 = 4rem — держим в синхроне с CHIP_SIZE для схлопывания ширины
// §6.1: удаление — схлопывание ширины + fade, 120 мс.
const REMOVE_ANIM_MS = 120

// Э5-3: распознавание может упасть (LLM/сеть/бюджет) без того, чтобы сама картинка была
// повреждена — она всё равно рабочая и уйдёт в модель как есть (план §4.2/§8 Э5-3). Чип не
// становится "ошибкой" (красное кольцо зарезервировано за неудачной загрузкой байт), просто без
// подписи из распознавания — с явным поводом вместо тишины.
function chipCaption(item: PendingAttachment): string | null {
  const title = item.attachment?.analysis?.title
  if (title) return title
  if (item.attachment?.analysis_status === "failed") return "Не распознал"
  return null
}

export function AttachmentChips({
  items,
  onRemove,
  onRetry,
  onOpen,
  routes,
  onRouteChange,
}: {
  items: PendingAttachment[]
  onRemove: (key: string) => void
  onRetry: (key: string) => void
  onOpen?: (item: PendingAttachment, index: number) => void
  /**
   * Ярлык-переключатель ветки (план §3, Э4-3) — только в режимах-парсерах (HR-импорт, разбор
   * внешнего ИИ). `routes[item.key]` — разрешённая ветка (override композера ?? дефолт от
   * kind/confidence); ключ отсутствует или `onRouteChange` не задан → бейдж не рисуется.
   */
  routes?: Record<string, AttachmentRoute>
  onRouteChange?: (key: string, route: AttachmentRoute) => void
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [removingKeys, setRemovingKeys] = useState<Set<string>>(new Set())

  if (items.length === 0) return null

  function focusChip(index: number) {
    const nodes = containerRef.current?.querySelectorAll<HTMLElement>("[data-chip]")
    nodes?.[index]?.focus()
  }

  // §6.1: клик/Delete не убирает чип мгновенно — сперва схлопывание ширины+fade (120 мс), и
  // только потом уходит из состояния владельца композера. При reduced-motion — сразу, без кадра.
  function requestRemove(key: string) {
    if (removingKeys.has(key)) return
    if (prefersReducedMotion()) {
      onRemove(key)
      return
    }
    setRemovingKeys((prev) => new Set(prev).add(key))
    window.setTimeout(() => {
      onRemove(key)
      setRemovingKeys((prev) => {
        if (!prev.has(key)) return prev
        const next = new Set(prev)
        next.delete(key)
        return next
      })
    }, REMOVE_ANIM_MS)
  }

  return (
    <div ref={containerRef} className="flex flex-wrap gap-2 px-0.5">
      {items.map((item, index) => {
        const analysisStatus = item.attachment?.analysis_status
        const isAnalyzing = item.status === "ready" && analysisStatus === "pending"
        const analysisFailed = item.status === "ready" && analysisStatus === "failed"
        const caption = chipCaption(item)
        const route = analysisStatus === "ready" ? routes?.[item.key] : undefined
        const removing = removingKeys.has(item.key)
        return (
          <div
            key={item.key}
            className="shrink-0 overflow-hidden transition-[width,margin-right,opacity] ease-in"
            style={{
              width: removing ? 0 : `${CHIP_SIZE_REM}rem`,
              marginRight: removing ? "-0.5rem" : 0,
              opacity: removing ? 0 : 1,
              transitionDuration: `${REMOVE_ANIM_MS}ms`,
            }}
          >
            <div
              data-chip
              tabIndex={0}
              role="group"
              aria-label={caption ?? "Вложение"}
              className={cn(
                "group relative shrink-0 overflow-hidden rounded-lg outline-none",
                CHIP_SIZE,
                MOTION_POP,
                motionStaggerClass(index),
                item.status === "uploading" && "motion-shimmer",
                item.status === "error"
                  ? "ring-2 ring-status-bad-fg"
                  : "ring-1 ring-border focus-visible:ring-2 focus-visible:ring-ring",
              )}
              title={
                item.status === "error"
                  ? (item.errorMessage ?? "Не удалось загрузить")
                  : analysisFailed
                    ? "Не удалось распознать содержимое — вложение всё равно будет отправлено"
                    : undefined
              }
              onClick={() => {
                if (item.status === "error") onRetry(item.key)
                else onOpen?.(item, index)
              }}
              onKeyDown={(e) => {
                if (e.key === "Delete" || e.key === "Backspace") {
                  e.preventDefault()
                  requestRemove(item.key)
                } else if (e.key === "Enter") {
                  e.preventDefault()
                  if (item.status === "error") onRetry(item.key)
                  else onOpen?.(item, index)
                } else if (e.key === "ArrowLeft" && index > 0) {
                  e.preventDefault()
                  focusChip(index - 1)
                } else if (e.key === "ArrowRight" && index < items.length - 1) {
                  e.preventDefault()
                  focusChip(index + 1)
                }
              }}
            >
              {isImageFile(item.file) ? (
                <img
                  src={item.previewUrl}
                  alt={caption ?? "Скриншот"}
                  className={cn(
                    "size-full object-cover transition-opacity",
                    item.status === "uploading" && "opacity-55",
                  )}
                />
              ) : (
                <div
                  className={cn(
                    "flex size-full flex-col items-center justify-center gap-1 bg-slate-100 px-1 transition-opacity",
                    item.status === "uploading" && "opacity-55",
                  )}
                >
                  <FileText className="size-6 text-slate-400" strokeWidth={1.5} />
                  <span className="text-[10px] font-semibold tracking-wide text-slate-500">
                    {documentExtLabel(item.file.type, item.file.name)}
                  </span>
                </div>
              )}

              {item.status === "uploading" ? (
                <div
                  className="pointer-events-none absolute inset-0 animate-spin rounded-lg"
                  style={{
                    background: "conic-gradient(var(--color-sky-500) 0 75%, transparent 75% 100%)",
                    WebkitMaskImage:
                      "radial-gradient(farthest-side, transparent calc(100% - 2px), #000 calc(100% - 2px))",
                    maskImage:
                      "radial-gradient(farthest-side, transparent calc(100% - 2px), #000 calc(100% - 2px))",
                  }}
                />
              ) : null}

              {isAnalyzing ? (
                <Sparkles
                  className="absolute right-1 top-1 size-3 animate-pulse text-white drop-shadow"
                  strokeWidth={2}
                />
              ) : null}

              {analysisFailed ? (
                <AlertTriangle
                  className="absolute right-1 top-1 size-3 text-amber-300 drop-shadow"
                  strokeWidth={2}
                />
              ) : null}

              {onRouteChange && route != null ? (
                <RouteBadge
                  route={route}
                  expanded={isLowConfidenceRoute(item.attachment?.analysis)}
                  onChange={(next) => onRouteChange(item.key, next)}
                />
              ) : null}

              {caption ? (
                <div className="absolute inset-x-0 bottom-0 truncate bg-black/55 px-1 py-0.5 text-[10px] leading-tight text-white">
                  {caption}
                </div>
              ) : null}

              {item.status !== "error" ? (
                <div className="absolute inset-0 flex items-start justify-end p-1 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
                  <button
                    type="button"
                    aria-label="Убрать"
                    onClick={(e) => {
                      e.stopPropagation()
                      requestRemove(item.key)
                    }}
                    className="rounded-full bg-black/60 p-0.5 text-white shadow-sm transition-colors hover:bg-black/80"
                  >
                    <X className="size-3.5" strokeWidth={2} />
                  </button>
                </div>
              ) : (
                <div className="absolute inset-0 flex items-center justify-center bg-status-bad-soft/70">
                  <X className="size-5 text-status-bad-fg" strokeWidth={2} />
                </div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
