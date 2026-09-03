import { lazy, Suspense, useEffect, type ComponentType } from "react"
import { Navigate, Route, Routes, useLocation } from "react-router-dom"
import { Loader2 } from "lucide-react"
import { Toaster } from "@/components/ui/sonner"
import { captureNav } from "@/lib/error-capture"
import { recordUiEvent } from "@/lib/ui-context"
import { importWithDeployRecovery } from "@/lib/chunk-load"
import { AuthProvider } from "@/features/auth/AuthProvider"
import { AuthGuard } from "@/app/AuthGuard"
import { ErrorBoundary } from "@/app/ErrorBoundary"
import { HomeRedirect } from "@/app/HomeRedirect"
import { NotFound } from "@/app/NotFound"
import { AppShell } from "@/app/layout/AppShell"
import { ROUTE_LOADERS } from "@/app/route-loaders"
import { useInitJobSources } from "@/features/jobs/use-job-sources"

// Разделы — по разделу на чанк (JS-42): раньше весь SPA (все 9 разделов) грузился одним
// бандлом при первом заходе на сайт, независимо от того, каким разделом человек пользуется.
// Suspense-фоллбек ниже — тот же спиннер, что и в HomeRedirect на время проверки авторизации.
// Загрузчики — из route-loaders.ts (тот же источник, что prefetch по hover в AppShell).
// importWithDeployRecovery: после деплоя старый tab 404-ит чанк — перезагрузка подхватит новый HTML.
function lazyPage<M>(loader: () => Promise<M>, pick: (mod: M) => ComponentType) {
  return lazy(() => importWithDeployRecovery(async () => ({ default: pick(await loader()) })))
}

const ChatPage = lazyPage(ROUTE_LOADERS["/chat"], (m) => m.ChatPage)
const JobsPage = lazyPage(ROUTE_LOADERS["/jobs"], (m) => m.JobsPage)
const ResumePage = lazyPage(ROUTE_LOADERS["/resume"], (m) => m.ResumePage)
const CareerPage = lazyPage(ROUTE_LOADERS["/career"], (m) => m.CareerPage)
const MultiplayerPage = lazyPage(ROUTE_LOADERS["/multiplayer"], (m) => m.MultiplayerPage)
const GfxShowcasePage = lazyPage(
  ROUTE_LOADERS["/multiplayer/dev/gfx"],
  (m) => m.GfxShowcasePage,
)
const ScreeningPage = lazyPage(ROUTE_LOADERS["/screening"], (m) => m.ScreeningPage)
const TechPage = lazyPage(ROUTE_LOADERS["/tech"], (m) => m.TechPage)
const OffersPage = lazyPage(ROUTE_LOADERS["/offers"], (m) => m.OffersPage)
const MarketPage = lazyPage(ROUTE_LOADERS["/market"], (m) => m.MarketPage)
const CompaniesPage = lazyPage(ROUTE_LOADERS["/companies"], (m) => m.CompaniesPage)
const SettingsPage = lazyPage(ROUTE_LOADERS["/settings"], (m) => m.SettingsPage)
const ExtensionPage = lazyPage(ROUTE_LOADERS["/extension"], (m) => m.ExtensionPage)
const AdminPage = lazyPage(ROUTE_LOADERS["/admin"], (m) => m.AdminPage)

function PageFallback() {
  return (
    <div className="flex flex-1 items-center justify-center">
      <Loader2 className="size-5 animate-spin text-slate-400" strokeWidth={2} />
    </div>
  )
}

/** Крошка на каждый переход между разделами: в бандле логов видно, где человек был перед сбоем.
 * Путь без query — в нём попадаются id вакансий, а бандл читает не только владелец аккаунта. */
function useNavBreadcrumbs() {
  const { pathname } = useLocation()
  useEffect(() => {
    captureNav(pathname)
    recordUiEvent({ type: "nav", path: pathname })
  }, [pathname])
}

export function App() {
  useInitJobSources()
  useNavBreadcrumbs()

  return (
    <AuthProvider>
      <ErrorBoundary>
        <Suspense fallback={<PageFallback />}>
          <Routes>
            {/* Формы логина нет: вход по токену из бота живёт в Параметрах. */}
            <Route path="/login" element={<Navigate to="/settings" replace />} />
            <Route element={<AuthGuard />}>
              <Route element={<AppShell />}>
                <Route index element={<HomeRedirect />} />
                <Route path="/chat" element={<ChatPage />} />
                <Route path="/jobs" element={<JobsPage />} />
                <Route path="/jobs/:vacancyId" element={<JobsPage />} />
                <Route path="/market" element={<MarketPage />} />
                <Route path="/companies" element={<CompaniesPage />} />
                <Route path="/resume" element={<ResumePage />} />
                <Route path="/career" element={<CareerPage />} />
                <Route path="/multiplayer" element={<MultiplayerPage />} />
                {import.meta.env.DEV ? (
                  <Route path="/multiplayer/dev/gfx" element={<GfxShowcasePage />} />
                ) : null}
                <Route path="/screening" element={<ScreeningPage />} />
                <Route path="/tech" element={<TechPage />} />
                <Route path="/offers" element={<OffersPage />} />
                <Route path="/extension" element={<ExtensionPage />} />
                {/* Разделы и выбранный человек — в адресе (Этап 1.2): ссылка воспроизводит
                    экран, «назад» закрывает карточку, а не раздел. Пульт — голый `/admin`,
                    Журнал и Система — свои адреса, карточка — `/admin/person/12` (Этап 3).
                    Старые адреса 404 не отдают: их приводит к новым `adminRedirectPath`. */}
                <Route path="/admin" element={<AdminPage />} />
                <Route path="/admin/:section" element={<AdminPage />} />
                <Route path="/admin/:section/:accountId" element={<AdminPage />} />
                <Route path="/settings" element={<SettingsPage />} />
                {/* Неизвестный путь (в т.ч. снесённый раздел) — честный экран «страницы нет»
                    внутри оболочки, чтобы меню осталось под рукой. Молчаливый редирект на
                    доску читался как «раздел удалили» (Этап 1.6). Незалогиненных и тех, у кого
                    гейт закрыт, сюда всё равно не пустит AuthGuard — он уведёт в «Аккаунт». */}
                <Route path="*" element={<NotFound />} />
              </Route>
            </Route>
          </Routes>
        </Suspense>
      </ErrorBoundary>
      <Toaster />
    </AuthProvider>
  )
}
