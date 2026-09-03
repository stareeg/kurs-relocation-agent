// Один источник правды для динамических импортов разделов: App.tsx строит из этого React.lazy(),
// AppShell.tsx прогревает чанк по hover/focus на пункте меню (JS-43) — до клика код уже скачан.
export const ROUTE_LOADERS = {
  "/chat": () => import("@/features/chat/ChatPage"),
  "/jobs": () => import("@/features/jobs/JobsPage"),
  "/market": () => import("@/features/market/MarketPage"),
  "/companies": () => import("@/features/companies/CompaniesPage"),
  "/resume": () => import("@/features/resume/ResumePage"),
  "/career": () => import("@/features/career/CareerPage"),
  "/multiplayer": () => import("@/features/multiplayer/MultiplayerPage"),
  "/multiplayer/dev/gfx": () => import("@/features/multiplayer/GfxShowcasePage"),
  "/screening": () => import("@/features/screening/ScreeningPage"),
  "/tech": () => import("@/features/tech/TechPage"),
  "/offers": () => import("@/features/offers/OffersPage"),
  "/extension": () => import("@/features/extension/ExtensionPage"),
  "/admin": () => import("@/features/admin/AdminPage"),
  "/settings": () => import("@/features/settings/SettingsPage"),
}

type RoutePath = keyof typeof ROUTE_LOADERS

// Повторный вызов для уже скачанного чанка — no-op (модуль закеширован рантаймом), поэтому
// дедуп на нашей стороне не нужен.
export function prefetchRoute(path: string) {
  const loader = ROUTE_LOADERS[path as RoutePath]
  // .catch: после деплоя hover на пункт меню 404-ит старый чанк. Без catch это
  // unhandledrejection, а Chrome кеширует отказ — клик по тому же разделу тоже падает.
  if (loader) void loader().catch(() => {})
}
