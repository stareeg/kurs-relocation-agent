import { useEffect, useLayoutEffect, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { Bell } from "lucide-react"
import { cn } from "@/lib/utils"
import { NotificationsPanel, useNotificationBadgeCount } from "@/features/chat/NotificationsPanel"

const COUNT_BADGE_CLASS =
  "inline-flex h-5 min-w-5 shrink-0 items-center justify-center rounded-md bg-slate-200/70 px-1.5 text-xs font-medium tabular-nums text-slate-600"

const CLOSE_MS = 180
const PANEL_GAP = 10

/** «Сегодня» в шапке сайдбара — очередь дня по наведению, из любого раздела.
 *
 * Не Radix Popover: его FocusScope/DismissableLayer перехватывает клик по NavLink —
 * URL меняется, а Outlet остаётся на прежнем разделе.
 */
export function NavNotifications({ collapsed }: { collapsed: boolean }) {
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const count = useNotificationBadgeCount()
  const [pos, setPos] = useState({ top: 0, left: 0 })

  useEffect(() => {
    return () => {
      if (closeTimer.current) clearTimeout(closeTimer.current)
    }
  }, [])

  const openNow = () => {
    if (closeTimer.current) clearTimeout(closeTimer.current)
    setOpen(true)
  }
  const closeSoon = () => {
    if (closeTimer.current) clearTimeout(closeTimer.current)
    closeTimer.current = setTimeout(() => setOpen(false), CLOSE_MS)
  }
  const closeNow = () => {
    if (closeTimer.current) clearTimeout(closeTimer.current)
    setOpen(false)
  }

  useLayoutEffect(() => {
    if (!open) return
    const el = wrapRef.current
    if (!el) return
    const place = () => {
      const r = el.getBoundingClientRect()
      const width = 352
      const left = Math.min(r.right + PANEL_GAP, window.innerWidth - width - 8)
      const top = Math.min(r.top, window.innerHeight - 24)
      setPos({ top: Math.max(8, top), left: Math.max(8, left) })
    }
    place()
    window.addEventListener("resize", place)
    window.addEventListener("scroll", place, true)
    return () => {
      window.removeEventListener("resize", place)
      window.removeEventListener("scroll", place, true)
    }
  }, [open, collapsed])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeNow()
    }
    const onDown = (e: PointerEvent) => {
      const t = e.target as Node | null
      if (!t) return
      if (wrapRef.current?.contains(t) || panelRef.current?.contains(t)) return
      closeNow()
    }
    window.addEventListener("keydown", onKey)
    window.addEventListener("pointerdown", onDown)
    return () => {
      window.removeEventListener("keydown", onKey)
      window.removeEventListener("pointerdown", onDown)
    }
  }, [open])

  return (
    <div ref={wrapRef} className="relative min-w-0" onMouseEnter={openNow} onMouseLeave={closeSoon}>
      <button
        type="button"
        aria-label={count > 0 ? `Сегодня (${count})` : "Сегодня"}
        aria-expanded={open}
        onClick={() => (open ? closeNow() : openNow())}
        className={cn(
          "flex min-w-0 items-center rounded-lg text-sm leading-none text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-900",
          collapsed ? "size-8 justify-center px-0" : "h-9 w-full gap-2 px-2.5",
        )}
      >
        <span className="relative shrink-0">
          <Bell className="size-4" strokeWidth={2} />
          {collapsed && count > 0 ? (
            <span className="absolute -right-0.5 -top-0.5 size-1.5 rounded-full bg-rose-500" />
          ) : null}
        </span>
        {!collapsed && (
          <>
            <span className="min-w-0 flex-1 truncate text-left text-sm font-medium">
              Сегодня
            </span>
            {count > 0 ? <span className={COUNT_BADGE_CLASS}>{count}</span> : null}
          </>
        )}
      </button>
      {open
        ? createPortal(
            <div
              ref={panelRef}
              role="region"
              aria-label="Сегодня"
              onMouseEnter={openNow}
              onMouseLeave={closeSoon}
              style={{ top: pos.top, left: pos.left }}
              className="fixed z-50 w-[min(22rem,calc(100vw-1rem))] max-h-[min(70dvh,36rem)] overflow-y-auto rounded-lg border border-border bg-card text-foreground shadow-lg"
            >
              <NotificationsPanel onNavigate={closeNow} />
            </div>,
            document.body,
          )
        : null}
    </div>
  )
}
