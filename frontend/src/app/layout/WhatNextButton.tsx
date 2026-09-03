import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { useLocation, useNavigate } from "react-router-dom"
import { CircleHelp } from "lucide-react"
import { cn } from "@/lib/utils"
import { useAppSettings } from "@/features/settings/use-settings"
import { useResumeGap } from "@/features/resume/use-resume"
import { useActiveJobsCount } from "@/features/jobs/use-jobs"
import { useActiveConversationsCount } from "@/features/chat/use-conversations"
import { useOffers } from "@/features/offers/use-offers"
import {
  buildWhatNextGuidance,
  type WhatNextContext,
  type WhatNextGuidance,
} from "@/lib/what-next"

const CLOSE_MS = 180
/** Панель не должна висеть бесконечно, даже если курсор остался на кнопке. */
const AUTO_HIDE_MS = 12000
const PANEL_GAP = 10
const PANEL_WIDTH = 380

function WhatNextPanelBody({
  guidance,
  onNavigate,
}: {
  guidance: WhatNextGuidance
  onNavigate: (href: string) => void
}) {
  const { last, next } = guidance
  return (
    <div className="flex flex-col gap-0">
      <div className="space-y-1 border-b px-4 py-3.5">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Последнее действие
        </p>
        <p className="text-base font-medium text-foreground">{last.title}</p>
        <p className="text-sm leading-relaxed text-muted-foreground">{last.body}</p>
      </div>

      <div className="space-y-1 px-4 py-3.5">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Дальше</p>
        <p className="text-base font-medium text-foreground">{next.title}</p>
        <p className="text-sm leading-relaxed text-muted-foreground">{next.body}</p>
        {next.href && next.cta ? (
          <button
            type="button"
            className="mt-2 text-sm font-medium text-sky-700 hover:text-sky-900"
            onClick={() => onNavigate(next.href!)}
          >
            {next.cta}
          </button>
        ) : null}
      </div>
    </div>
  )
}

function WhatNextShell({
  collapsed,
  guidance,
}: {
  collapsed: boolean
  guidance: WhatNextGuidance
}) {
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const autoHideTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [pos, setPos] = useState({ top: 0, left: 0 })
  const navigate = useNavigate()

  const clearTimers = useCallback(() => {
    if (closeTimer.current) clearTimeout(closeTimer.current)
    if (autoHideTimer.current) clearTimeout(autoHideTimer.current)
    closeTimer.current = null
    autoHideTimer.current = null
  }, [])

  useEffect(() => () => clearTimers(), [clearTimers])

  const openNow = useCallback(() => {
    if (closeTimer.current) clearTimeout(closeTimer.current)
    setOpen(true)
  }, [])
  const closeSoon = useCallback(() => {
    if (closeTimer.current) clearTimeout(closeTimer.current)
    closeTimer.current = setTimeout(() => setOpen(false), CLOSE_MS)
  }, [])
  const closeNow = useCallback(() => {
    clearTimers()
    setOpen(false)
  }, [clearTimers])

  // Автоскрытие: панель не перекрывает соседние кнопки бесконечно.
  useEffect(() => {
    if (!open) {
      if (autoHideTimer.current) {
        clearTimeout(autoHideTimer.current)
        autoHideTimer.current = null
      }
      return
    }
    autoHideTimer.current = setTimeout(() => setOpen(false), AUTO_HIDE_MS)
    return () => {
      if (autoHideTimer.current) clearTimeout(autoHideTimer.current)
    }
  }, [open, guidance.last.title, guidance.next.title])

  useLayoutEffect(() => {
    if (!open) return
    const el = wrapRef.current
    if (!el) return
    const place = () => {
      const r = el.getBoundingClientRect()
      const left = Math.min(r.right + PANEL_GAP, window.innerWidth - PANEL_WIDTH - 8)
      // Держим панель у кнопки (снизу вверх), без огромного «паруса» на весь сайдбар.
      const approxHeight = 320
      const top = Math.min(
        Math.max(8, r.bottom - approxHeight),
        window.innerHeight - approxHeight - 8,
      )
      setPos({ top, left: Math.max(8, left) })
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
  }, [open, closeNow])

  return (
    <div
      ref={wrapRef}
      className="relative min-w-0"
      onMouseEnter={openNow}
      onMouseLeave={closeSoon}
    >
      <button
        type="button"
        aria-label="Что делать?"
        aria-expanded={open}
        onClick={() => (open ? closeNow() : openNow())}
        className={cn(
          "flex min-w-0 items-center rounded-lg text-sm leading-none text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-900",
          collapsed ? "size-8 justify-center px-0" : "h-9 w-full gap-2 px-2.5",
        )}
      >
        <CircleHelp className="size-4 shrink-0" strokeWidth={2} />
        {!collapsed && <span className="min-w-0 flex-1 truncate text-left text-sm">Что делать?</span>}
      </button>
      {open
        ? createPortal(
            <div
              ref={panelRef}
              role="region"
              aria-label="Что делать?"
              onMouseEnter={openNow}
              onMouseLeave={closeSoon}
              style={{ top: pos.top, left: pos.left }}
              className="fixed z-50 w-[380px] max-h-[min(70vh,26rem)] overflow-y-auto rounded-lg border border-border bg-card text-foreground shadow-lg"
            >
              <WhatNextPanelBody
                guidance={guidance}
                onNavigate={(href) => {
                  closeNow()
                  navigate(href)
                }}
              />
            </div>,
            document.body,
          )
        : null}
    </div>
  )
}

function useWhatNextContext(): WhatNextContext {
  const location = useLocation()
  const { data: appSettings } = useAppSettings()
  const { data: resumeGap } = useResumeGap()
  const { data: activeCountData } = useActiveJobsCount()
  const { data: activeChatsData } = useActiveConversationsCount()
  const { data: offers } = useOffers()

  return useMemo(
    () => ({
      pathname: location.pathname,
      hasOpenRouterKey: Boolean(appSettings?.openrouter_key_configured),
      resumeReady: (resumeGap?.score?.total ?? 0) >= 40,
      activeJobsCount: activeCountData?.count ?? 0,
      activeChatsCount: activeChatsData?.count ?? 0,
      offersCount: (offers ?? []).filter((o) => o.status !== "declined").length,
    }),
    [
      location.pathname,
      appSettings?.openrouter_key_configured,
      resumeGap?.score?.total,
      activeCountData?.count,
      activeChatsData?.count,
      offers,
    ],
  )
}

/** Полная кнопка для FullShell — читает счётчики сама (не поднимает ре-рендер шелла от gap). */
export function WhatNextButton({ collapsed }: { collapsed: boolean }) {
  const ctx = useWhatNextContext()
  const guidance = useMemo(() => buildWhatNextGuidance(ctx), [ctx])
  return <WhatNextShell collapsed={collapsed} guidance={guidance} />
}

/** Онбординг-гейт: без вороночных API (иначе 401). */
export function WhatNextButtonGated({
  collapsed,
  hasOpenRouterKey,
}: {
  collapsed: boolean
  hasOpenRouterKey: boolean
}) {
  const location = useLocation()
  const guidance = useMemo(() => {
    const ctx: WhatNextContext = {
      pathname: location.pathname,
      hasOpenRouterKey,
      resumeReady: false,
      activeJobsCount: 0,
      activeChatsCount: 0,
      offersCount: 0,
    }
    return buildWhatNextGuidance(ctx)
  }, [location.pathname, hasOpenRouterKey])

  return <WhatNextShell collapsed={collapsed} guidance={guidance} />
}
