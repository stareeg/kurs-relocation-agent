import { Fragment, useCallback, useEffect, useRef, useState, type ComponentProps } from "react"
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom"
import {
  Briefcase,
  Building2,
  Camera,
  Code2,
  FileText,
  Headset,
  Kanban,
  Loader2,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Puzzle,
  Scale,
  Settings,
  Shield,
  TrendingUp,
  User,
  UsersRound,
  X,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { prefetchRoute } from "@/app/route-loaders"
import { usePersistedBoolean } from "@/lib/use-persisted-boolean"
import { useOnboardingHints } from "@/lib/use-onboarding-hints"
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
import { HelpTip } from "@/components/ui/help-tip"
import { OnboardingHint } from "@/components/ui/tooltip"
import { ONBOARDING_HINT_IDS } from "@/lib/use-onboarding-hints"
import { useLiveEventInvalidation } from "@/app/use-live-invalidation"
import type { AuthStatus } from "@/api/auth"
import { useAuth } from "@/features/auth/auth-context"
import { useAuthStatusQuery } from "@/features/auth/use-auth-status"
import { isGateOpen, needsTokenLogin } from "@/features/auth/onboarding"
import { useActiveConversationsCount } from "@/features/chat/use-conversations"
import { useActiveJobsCount, useJobStageCounts } from "@/features/jobs/use-jobs"
import { useResumeData, useResumeGap } from "@/features/resume/use-resume"
import { useOffers } from "@/features/offers/use-offers"
import { useMarketOverview } from "@/features/market/use-market-data"
import { useAppSettings } from "@/features/settings/use-settings"
import { avatarImageUrl } from "@/api/avatar"
import { useAvatarMeta, useDeleteAvatar, useUploadAvatar } from "@/features/settings/use-avatar"
import { captureNavBlocked, captureNavClick } from "@/lib/error-capture"
import { AdminAttentionBadge } from "@/features/admin/components/AdminAttentionBadge"
import { useImmersive } from "@/features/multiplayer/immersive"
import { NavNotifications } from "./NavNotifications"
import { WhatNextButton, WhatNextButtonGated } from "./WhatNextButton"

type NavItem = { to: string; label: string; icon: typeof MessageSquare }

// Группы без заголовков, разделённые тонкой линией (решение #9). Порядок сверху вниз:
// «я» (резюме — основа всех оценок, поэтому первым и на месте бывшего логотипа), поток
// заявки/воронка, «Автоотклики» отдельной группой сразу под офферами (очередь discovery/apply,
// не аналитика), аналитика рынка вместе с «Карьерой» (долгий контекст поверх текущего поиска),
// «Мультиплеер» — отдельной группой под карьерой (игры/кооп с друзьями, не воронка).
// «Карьера» вернулась в меню из кликабельного футера профиля: раздел, который находят только
// случайным кликом по собственному имени, не существует. Сам футер теперь ведёт в «Аккаунт»
// (см. SidebarProfile) — и нижний пункт «Аккаунт» из рельса убран, чтобы не дублировать.
const NAV_GROUPS: ReadonlyArray<ReadonlyArray<NavItem>> = [
  [{ to: "/resume", label: "Резюме", icon: FileText }],
  [
    { to: "/chat", label: "Чаты", icon: MessageSquare },
    { to: "/jobs", label: "Вакансии", icon: Kanban },
    { to: "/screening", label: "Скрининги", icon: Headset },
    { to: "/tech", label: "Технички", icon: Code2 },
    { to: "/offers", label: "Офферы", icon: Scale },
  ],
  [{ to: "/extension", label: "Автоотклики", icon: Puzzle }],
  [
    { to: "/market", label: "Рынок", icon: TrendingUp },
    { to: "/companies", label: "Компании", icon: Building2 },
    { to: "/career", label: "Карьера", icon: Briefcase },
  ],
  [{ to: "/multiplayer", label: "Мультиплеер", icon: UsersRound }],
]

// Разделитель между группами меню — без заголовка, просто тонкая линия (решение #9). В
// свёрнутом состоянии остаётся во всю ширину узкой колонки, это ок — bar не несёт текста.
function NavGroupDivider() {
  return <div role="separator" aria-hidden="true" className="my-1 h-px shrink-0 bg-slate-200/70" />
}

// Бейджи различаются по смыслу (решение #9): счётчики штук (чаты/вакансии/скрининги/технички/
// офферы) — серая пилюля, как раньше; «балл резюме» (из 100) и «шанс офферов» (%) — это метрики
// с шкалой, а не количество, поэтому другой цветовой токен (sky), чтобы не читались как «7 штук».
const COUNT_BADGE_CLASS =
  "inline-flex h-5 min-w-5 shrink-0 items-center justify-center rounded-md bg-slate-200/70 px-1.5 text-xs font-medium tabular-nums text-slate-600"
const METRIC_BADGE_CLASS =
  "inline-flex h-5 min-w-5 shrink-0 items-center justify-center rounded-md bg-sky-50 px-1.5 text-xs font-medium tabular-nums text-sky-700 ring-1 ring-inset ring-sky-200/70"

function navItemClass({ isActive, collapsed }: { isActive: boolean; collapsed: boolean }) {
  return cn(
    "flex h-9 items-center whitespace-nowrap rounded-lg text-sm leading-none transition-all duration-200",
    collapsed ? "justify-center px-2" : "gap-2 px-2.5",
    isActive
      ? "bg-slate-200/60 font-medium text-slate-900"
      : "font-normal text-slate-600 hover:bg-slate-100",
  )
}

/** NavLink, который уходит в раздел на pointerdown.
 *
 * HelpTip/Select/Popover на «Резюме» порталятся с z-50 и могут перекрыть рельс: click
 * до роутера не доходит (URL не меняется). pointerdown на самой ссылке срабатывает раньше
 * DismissableLayer и раньше, чем click глушат. Cmd/Ctrl-клик не трогаем — новая вкладка.
 */
function SidebarNavLink({
  to,
  onClick,
  children,
  ...rest
}: ComponentProps<typeof NavLink>) {
  const navigate = useNavigate()
  const from = useLocation().pathname
  const dest = typeof to === "string" ? to : String(to)
  return (
    <NavLink
      to={to}
      {...rest}
      onPointerDown={(event) => {
        if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
          return
        }
        captureNavClick(from, dest)
        if (from !== dest) navigate(dest)
        window.setTimeout(() => {
          const now = window.location.pathname
          if (from !== dest && now !== dest && !now.startsWith(`${dest}/`)) {
            captureNavBlocked(from, dest)
          }
        }, 250)
      }}
      onClick={onClick}
    >
      {children}
    </NavLink>
  )
}

// AUTH-1: серый некликабельный пункт меню, пока онбординг не завершён (токен + ключ).
function disabledNavItemClass(collapsed: boolean) {
  return cn(
    "flex h-9 cursor-not-allowed select-none items-center whitespace-nowrap rounded-lg text-sm font-normal leading-none text-slate-300",
    collapsed ? "justify-center px-2" : "gap-2 px-2.5",
  )
}

function DisabledNavItem({
  label,
  icon: Icon,
  collapsed,
}: {
  label: string
  icon: typeof MessageSquare
  collapsed: boolean
}) {
  return (
    <div
      aria-disabled="true"
      title="Откроется после настройки: токен из бота и ключ OpenRouter в Аккаунте"
      className={disabledNavItemClass(collapsed)}
    >
      <Icon className="size-4 shrink-0" strokeWidth={2} />
      {!collapsed && <span className="min-w-0 flex-1 truncate text-sm">{label}</span>}
    </div>
  )
}

// Решение #10: вместо восьми серых пунктов — одна заметная строка-шаг со ссылкой на «Аккаунт»
// (единственный доступный маршрут, пока гейт закрыт). Состояние — из AuthStatus, логика уже
// есть в onboarding.ts (needsTokenLogin): шаг 1 — токен из бота, шаг 2 — ключ OpenRouter.
function OnboardingStepNav({
  authStatus,
  collapsed,
}: {
  authStatus: AuthStatus | undefined
  collapsed: boolean
}) {
  if (!authStatus) return null
  const step = needsTokenLogin(authStatus) ? 1 : 2
  const title = `Шаг ${step} из 2`
  const body = step === 1 ? "Получите токен в боте" : "Вставьте ключ OpenRouter"

  if (collapsed) {
    return (
      <HelpTip text={`${title}: ${body}`} side="right">
        <SidebarNavLink
          to="/settings"
          aria-label={`${title}: ${body}`}
          className="mx-auto flex size-8 items-center justify-center rounded-full border border-sky-300 bg-sky-50 text-xs font-semibold text-sky-700 transition-colors hover:bg-sky-100"
        >
          {step}
        </SidebarNavLink>
      </HelpTip>
    )
  }

  return (
    <SidebarNavLink
      to="/settings"
      className="block rounded-lg border border-sky-200 bg-sky-50 p-2.5 text-xs text-sky-900 transition-colors hover:bg-sky-100"
    >
      <p className="font-semibold">{title}</p>
      <p className="mt-0.5 leading-snug">{body}</p>
    </SidebarNavLink>
  )
}

// Фамилия/имя на разных строках (UX6-3): до первого пробела — фамилия (строка 1, усекается
// многоточием), после — имя/отчество (строка 2).
function splitName(fullName: string): { surname: string; rest: string } {
  const idx = fullName.indexOf(" ")
  if (idx === -1) return { surname: fullName, rest: "" }
  return { surname: fullName.slice(0, idx), rest: fullName.slice(idx + 1).trim() }
}

// UX6-13: фото профиля Telegram при входе (bot_app.services.avatar_sync) → фолбэк на дефолтную
// иконку; клик по кружку — своя картинка файлом (сжимается на канвасе перед загрузкой,
// `compress-image`). Крестик поверх — только когда источник ручной («custom»), возврат к
// Telegram-фото/дефолту.
function SidebarAvatar({ title }: { title: string | undefined }) {
  const { data: meta } = useAvatarMeta()
  const upload = useUploadAvatar()
  const del = useDeleteAvatar()
  const inputRef = useRef<HTMLInputElement>(null)
  const pending = upload.isPending || del.isPending
  const src = meta ? `${avatarImageUrl()}?v=${encodeURIComponent(meta.updated_at)}` : undefined

  return (
    <div className="group/avatar relative shrink-0">
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        disabled={pending}
        aria-label="Изменить фото профиля"
        title={title}
        className="block rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <Avatar className="size-7">
          {src && <AvatarImage src={src} alt="" />}
          <AvatarFallback>
            <User className="size-4" strokeWidth={2} />
          </AvatarFallback>
        </Avatar>
        <span
          className={cn(
            "absolute inset-0 flex items-center justify-center rounded-full bg-black/50 opacity-0 transition-opacity group-hover/avatar:opacity-100",
            pending && "opacity-100",
          )}
        >
          {pending ? (
            <Loader2 className="size-3.5 animate-spin text-white" strokeWidth={2} />
          ) : (
            <Camera className="size-3.5 text-white" strokeWidth={2} />
          )}
        </span>
      </button>
      {meta?.source === "custom" && !pending && (
        <button
          type="button"
          aria-label="Убрать своё фото"
          title="Убрать своё фото — вернуться к фото из Telegram"
          onClick={() => del.mutate()}
          className="absolute -right-1 -top-1 flex size-3.5 items-center justify-center rounded-full bg-slate-700 text-white opacity-0 shadow-sm transition-opacity hover:bg-slate-900 group-hover/avatar:opacity-100"
        >
          <X className="size-2.5" strokeWidth={2.5} />
        </button>
      )}
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0]
          e.target.value = ""
          if (file) upload.mutate(file)
        }}
      />
    </div>
  )
}

function SidebarProfile({ collapsed }: { collapsed: boolean }) {
  const { data: resume } = useResumeData()
  const fullName = resume?.personal?.full_name?.trim() || ""
  const { surname, rest } = splitName(fullName)
  const avatar = <SidebarAvatar title={fullName || undefined} />

  if (collapsed) {
    return (
      <div className="flex items-center justify-center py-1.5" title={fullName || undefined}>
        {avatar}
      </div>
    )
  }

  return (
    <div className="flex items-center gap-2 px-2.5 py-1.5">
      {avatar}
      {/* Клик по ФИО (не по кружку с фото — там своя кнопка смены аватара) открывает
          «Аккаунт»: свой профиль → свои настройки, друзья и устройства. Раньше вело в
          «Карьеру», причём тултип обещал «друзья, портфолио, релокация» уже после того, как
          друзья переехали в «Аккаунт» — вход врал о содержимом. «Карьера» вернулась в меню
          (NAV_GROUPS), отдельный пункт «Аккаунт» из рельса убран. */}
      {/* NavLink, а не Link: раз футер стал единственным входом в «Аккаунт», он же обязан
          показывать «вы здесь» — иначе на /settings в панели не подсвечено вообще ничего. */}
      <SidebarNavLink
        to="/settings"
        className={({ isActive }) =>
          cn(
            "group/profile-link -mx-1 flex min-w-0 flex-1 items-center gap-1 rounded-md px-1 py-0.5 transition-colors",
            isActive ? "bg-slate-200/60" : "hover:bg-slate-100",
          )
        }
        // HelpTip здесь не вешаем (у ссылки уже свой title, два тултипа на одном элементе —
        // шум); подсказка «что внутри» переехала в сам title вместе с ключом nav.settings.
        title={
          fullName
            ? `${fullName} — Аккаунт: токен, устройства, ключ OpenRouter, друзья`
            : "Аккаунт: токен, устройства, ключ OpenRouter, друзья"
        }
      >
        <span className="min-w-0 flex-1">
          {fullName ? (
            <>
              <p className="truncate text-sm font-medium leading-tight text-slate-800">{surname}</p>
              {rest && (
                <p className="truncate text-sm font-medium leading-tight text-slate-800">{rest}</p>
              )}
            </>
          ) : (
            <p className="truncate text-sm font-medium text-slate-800">Резюме не заполнено</p>
          )}
        </span>
        <Settings
          className="size-3.5 shrink-0 text-slate-300 opacity-0 transition-opacity group-hover/profile-link:opacity-100"
          strokeWidth={2}
        />
      </SidebarNavLink>
    </div>
  )
}

function ShellFrame({
  navCollapsed,
  onToggleCollapsed,
  onAutoCollapse,
  nav,
  bottom,
  notifications,
}: {
  navCollapsed: boolean
  onToggleCollapsed: () => void
  onAutoCollapse: () => void
  nav: React.ReactNode
  bottom: React.ReactNode
  notifications?: React.ReactNode
}) {
  const navHelpSide = navCollapsed ? "right" : "bottom"
  // iPhone Safari: развёрнутый w-52 + URL-бар съедают колонку. На узком экране — icon rail.
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return
    const mq = window.matchMedia("(max-width: 767px)")
    const collapseOnNarrow = () => {
      if (mq.matches) onAutoCollapse()
    }
    collapseOnNarrow()
    mq.addEventListener("change", collapseOnNarrow)
    return () => mq.removeEventListener("change", collapseOnNarrow)
  }, [onAutoCollapse])
  return (
    <div className="flex h-dvh overflow-hidden bg-slate-50 text-foreground">
      <aside
        className={cn(
          "flex h-full min-h-0 shrink-0 flex-col overflow-hidden border-r bg-sidebar transition-[width] duration-200",
          navCollapsed ? "w-12" : "w-52",
        )}
      >
        {/* «Сегодня» — на одной строке с кнопкой сворачивания, над «Резюме». Очередь дня
            смотрится по наведению из любого раздела, без захода в Чаты. */}
        <div
          className={cn(
            "flex shrink-0 items-center border-b border-slate-200/60",
            navCollapsed
              ? "h-auto flex-col justify-center gap-1 px-1 py-1.5"
              : notifications
                ? "h-10 justify-between gap-1 px-2"
                : "h-10 justify-end gap-1 px-2",
          )}
        >
          {notifications ? (
            <div className={cn(navCollapsed ? "flex justify-center" : "min-w-0 flex-1")}>
              {notifications}
            </div>
          ) : null}
          <HelpTip id="nav.menu-toggle" side={navHelpSide}>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="size-8 shrink-0 text-slate-500"
              aria-label={navCollapsed ? "Развернуть меню" : "Свернуть меню"}
              onClick={onToggleCollapsed}
            >
              {navCollapsed ? (
                <PanelLeftOpen className="size-4" strokeWidth={2} />
              ) : (
                <PanelLeftClose className="size-4" strokeWidth={2} />
              )}
            </Button>
          </HelpTip>
        </div>
        <nav className="min-h-0 flex-1 space-y-0.5 overflow-y-auto px-1.5 py-2">{nav}</nav>
        <div className="shrink-0 space-y-0.5 border-t p-1.5">{bottom}</div>
      </aside>
      <main className="flex flex-1 flex-col overflow-hidden">
        <Outlet />
      </main>
    </div>
  )
}

// Онбординг не завершён: вместо разделов — заметный шаг-ссылка (решение #10), доступен только
// «Аккаунт» (вход по токену + ключ). Данные-хуки не монтируем: часть из них без
// авторизации отвечает 401 и зря дёргает глобальный разлогин.
function GatedShell({ authStatus }: { authStatus: AuthStatus | undefined }) {
  const [navCollapsed, setNavCollapsed] = usePersistedBoolean("copilot.nav.collapsed")
  const onToggleCollapsed = useCallback(() => setNavCollapsed((v) => !v), [setNavCollapsed])
  const onAutoCollapse = useCallback(() => setNavCollapsed(true), [setNavCollapsed])

  return (
    <ShellFrame
      navCollapsed={navCollapsed}
      onToggleCollapsed={onToggleCollapsed}
      onAutoCollapse={onAutoCollapse}
      nav={<OnboardingStepNav authStatus={authStatus} collapsed={navCollapsed} />}
      bottom={
        <>
          <WhatNextButtonGated
            collapsed={navCollapsed}
            hasOpenRouterKey={Boolean(authStatus?.openrouter_key_configured)}
          />
          <DisabledNavItem label="Автоотклики" icon={Puzzle} collapsed={navCollapsed} />
          <SidebarNavLink
            to="/settings"
            aria-label="Аккаунт"
            className={({ isActive }) =>
              cn(
                navItemClass({ isActive, collapsed: navCollapsed }),
                "w-full",
                isActive && "text-sky-700",
              )
            }
          >
            <Settings className="size-4 shrink-0" strokeWidth={2} />
            {!navCollapsed && <span className="text-sm">Аккаунт</span>}
          </SidebarNavLink>
        </>
      }
    />
  )
}

function ResumeScoreBadge() {
  // Хук здесь, а не в FullShell: иначе поллинг gap (каждые 3с при stale) ре-рендерил
  // весь Outlet — на «Резюме» это сотни инпутов и заметный лаг скролла.
  const { data: resumeGap } = useResumeGap()
  const resumeScore = resumeGap?.score?.total
  if (resumeScore == null) return null
  return <span className={METRIC_BADGE_CLASS}>{resumeScore}</span>
}

function FullShell({ isAdmin }: { isAdmin: boolean }) {
  useLiveEventInvalidation()
  const { data: activeCountData } = useActiveJobsCount()
  const activeCount = activeCountData?.count
  const { data: activeChatsData } = useActiveConversationsCount()
  const activeChatsCount = activeChatsData?.count
  const { data: stageCounts } = useJobStageCounts()
  const screeningCount = stageCounts?.["Скрининг"] ?? 0
  const techCount = stageCounts?.["Техничка"] ?? 0
  // Офферы: активные — все, кроме отклонённых (тот же критерий, что фильтрует их из
  // LLM-сравнения на «Офферы»). Рынок: «Шанс оффера» из /api/market/overview.
  const { data: offers } = useOffers()
  const offersActiveCount = (offers ?? []).filter((o) => o.status !== "declined").length
  const { data: marketOverview } = useMarketOverview()
  const offerChancePct = marketOverview?.offer_chance?.score
  const [navCollapsedPref, setNavCollapsed] = usePersistedBoolean("copilot.nav.collapsed")
  // Живой стол «Мультиплеера» сворачивает рельс сам; кнопкой его всё ещё можно развернуть
  // (локальный флаг, преференс в localStorage не трогаем — по выходе всё как было).
  const immersive = useImmersive()
  const [expandedInImmersive, setExpandedInImmersive] = useState(false)
  const [prevImmersive, setPrevImmersive] = useState(immersive)
  if (prevImmersive !== immersive) {
    // Смена режима — сбрасываем ручное «развернул за столом» во время рендера, без эффекта.
    setPrevImmersive(immersive)
    setExpandedInImmersive(false)
  }
  const navCollapsed = immersive ? !expandedInImmersive : navCollapsedPref
  const onToggleCollapsed = useCallback(() => {
    if (immersive) setExpandedInImmersive((v) => !v)
    else setNavCollapsed((v) => !v)
  }, [immersive, setNavCollapsed])
  const onAutoCollapse = useCallback(() => setNavCollapsed(true), [setNavCollapsed])
  const { shouldShow, dismissHint } = useOnboardingHints()
  const { data: appSettings } = useAppSettings()
  const showResumeNextHint =
    Boolean(appSettings?.openrouter_key_configured) &&
    shouldShow(ONBOARDING_HINT_IDS.settingsAfterKeyResume)
  const navHelpSide = navCollapsed ? "right" : "bottom"
  const navHelpAlign = navCollapsed ? "center" : "start"

  return (
    <ShellFrame
      navCollapsed={navCollapsed}
      onToggleCollapsed={onToggleCollapsed}
      onAutoCollapse={onAutoCollapse}
      notifications={<NavNotifications collapsed={navCollapsed} />}
      nav={NAV_GROUPS.map((group, i) => (
        <Fragment key={i}>
          {i > 0 && <NavGroupDivider />}
          {group.map(({ to, label, icon: Icon }) => {
            const link = (
              <SidebarNavLink
                to={to}
                aria-label={label}
                title={navCollapsed ? label : undefined}
                className={({ isActive }) =>
                  cn(
                    navItemClass({ isActive, collapsed: navCollapsed }),
                    "min-w-0 flex-1",
                    to === "/resume" && showResumeNextHint && "ring-2 ring-sky-300 ring-offset-1",
                  )
                }
                onClick={() => {
                  if (to === "/resume" && showResumeNextHint) {
                    dismissHint(ONBOARDING_HINT_IDS.settingsAfterKeyResume)
                  }
                }}
                onMouseEnter={() => prefetchRoute(to)}
                onFocus={() => prefetchRoute(to)}
              >
                <span className="relative shrink-0">
                  <Icon className="size-4" strokeWidth={2} />
                </span>
                {!navCollapsed && (
                  <>
                    <span className="min-w-0 flex-1 truncate text-sm">{label}</span>
                    {to === "/chat" && activeChatsCount != null && (
                      <span className={COUNT_BADGE_CLASS}>{activeChatsCount}</span>
                    )}
                    {to === "/jobs" && activeCount != null && (
                      <span className={COUNT_BADGE_CLASS}>{activeCount}</span>
                    )}
                    {to === "/screening" && screeningCount > 0 && (
                      <span className={COUNT_BADGE_CLASS}>{screeningCount}</span>
                    )}
                    {to === "/tech" && techCount > 0 && (
                      <span className={COUNT_BADGE_CLASS}>{techCount}</span>
                    )}
                    {to === "/offers" && offersActiveCount > 0 && (
                      <span className={COUNT_BADGE_CLASS}>{offersActiveCount}</span>
                    )}
                    {to === "/resume" && <ResumeScoreBadge />}
                    {to === "/market" && offerChancePct != null && (
                      <span className={METRIC_BADGE_CLASS}>{offerChancePct}%</span>
                    )}
                  </>
                )}
              </SidebarNavLink>
            )

            if (to === "/resume" && showResumeNextHint) {
              return (
                <OnboardingHint
                  key={to}
                  open
                  onDismiss={() => dismissHint(ONBOARDING_HINT_IDS.settingsAfterKeyResume)}
                  content="Дальше — вкладка «Резюме»: критерии поиска и опыт. Без этого оценка вакансий слабая."
                  side={navHelpSide}
                  align={navHelpAlign}
                  autoHideMs={6000}
                >
                  {link}
                </OnboardingHint>
              )
            }

            return <Fragment key={to}>{link}</Fragment>
          })}
        </Fragment>
      ))}
      bottom={
        <>
          {isAdmin && (
            <SidebarNavLink
              to="/admin"
              aria-label="Админ"
              title={navCollapsed ? "Админ" : undefined}
              className={({ isActive }) =>
                cn(navItemClass({ isActive, collapsed: navCollapsed }), "w-full")
              }
              onMouseEnter={() => prefetchRoute("/admin")}
              onFocus={() => prefetchRoute("/admin")}
            >
              <Shield className="size-4 shrink-0" strokeWidth={2} />
              {!navCollapsed && (
                <>
                  <span className="min-w-0 flex-1 truncate text-sm">Админ</span>
                  <AdminAttentionBadge enabled={isAdmin} />
                </>
              )}
            </SidebarNavLink>
          )}
          <WhatNextButton collapsed={navCollapsed} />
          {/* Отдельного пункта «Аккаунт» здесь больше нет: вход в него — клик по своему
              профилю ниже. Две ссылки на один экран в одном рельсе — дубль.
              «Автоотклики» — в основном рельсе (NAV_GROUPS), сразу под «Офферы». */}
          <div className="border-t pt-1.5">
            <SidebarProfile collapsed={navCollapsed} />
          </div>
        </>
      }
    />
  )
}

export function AppShell() {
  const { status } = useAuth()
  const { data: authStatus } = useAuthStatusQuery()
  // Гейт (AUTH-1): anon или незавершённый онбординг → серое меню, только «Параметры».
  // Пока статус не загружен (data undefined), считаем гейт открытым — не мигать серым зря.
  const gated = status === "anon" || (authStatus ? !isGateOpen(authStatus) : false)
  return gated ? <GatedShell authStatus={authStatus} /> : <FullShell isAdmin={Boolean(authStatus?.is_admin)} />
}
