// Сборка расширения на esbuild. Без React-рантайма в content-script (запрет ux_plan.md).
// Каждый content-script — самодостаточный IIFE-бандл; CSS-вход @import-ит токены + panel.
// Запуск: `npm run build:ext` (разовая сборка) / `npm run watch:ext` (пересборка на лету).
import * as esbuild from 'esbuild'
import { readFileSync, writeFileSync } from 'node:fs'

const watch = process.argv.includes('--watch')

// EX-15 (§4.1): единственная точка подстановки прод-домена в собранный код — дефолт API
// подменяется при сборке .zip для прод-выкладки (EXT_API_BASE_URL=https://домен npm run build:ext),
// не правкой config.ts руками. Без переменной окружения поведение прежнее (localhost:8000).
// Тот же apiBaseUrl подставляется и как дефолт «Адреса сайта» (WEB_BASE_URL) — на проде за Caddy
// это один и тот же домен (config.ts: deriveApiBaseUrl не трогает non-localhost origin), поэтому
// свежая установка друга сразу целится в прод, а не в localhost:5173/8000 хозяйской машины (баг:
// друг из коробки получал «Failed to fetch», пока сам не открывал options и не менял адрес).
const apiBaseUrl = process.env.EXT_API_BASE_URL || 'http://localhost:8000'
const define = {
  API_BASE_URL: JSON.stringify(apiBaseUrl),
  WEB_BASE_URL: JSON.stringify(apiBaseUrl),
}

// EX-15 (§4.1, вторая половина): host_permissions[0] в manifest.json тоже подменяется доменом
// сборки — иначе у только что скачавшего .zip пользователя первый же запрос к API упрётся в
// chrome.permissions.request на пустом месте. Пишем обратно в исходник manifest.json: ship-набор
// (_SHIP_ROOT_FILES в core/repo/extension_bundle.py) берёт именно его, dist/ не содержит манифеста.
// В git-рабочем дереве localhost-манифест неизменен (дефолт), правка появляется только при сборке
// с явным EXT_API_BASE_URL (прод-слой в deploy/Dockerfile) — dist/ и переписанный manifest
// уезжают в .zip / Docker-образ, не в коммит.
// Строковая замена, а не JSON.parse+stringify — не переформатирует весь файл (diff чистый).
const manifestPath = 'manifest.json'
const localhostPermission = 'http://localhost:8000/*'
const prodPermission = `${apiBaseUrl.replace(/\/$/, '')}/*`
if (prodPermission !== localhostPermission) {
  const src = readFileSync(manifestPath, 'utf8')
  if (src.includes(localhostPermission)) {
    writeFileSync(manifestPath, src.replace(localhostPermission, prodPermission))
    console.log(`[ext] manifest host_permissions[0] → ${prodPermission}`)
  }
}

/** @type {import('esbuild').BuildOptions} */
const options = {
  define,
  entryPoints: {
    // service worker
    background: 'src/background.ts',
    // MAIN world: перехват XHR/fetch /api/frontend/responses на career.habr.com (S13)
    'habr-xhr-interceptor': 'src/content/habr-xhr-interceptor.ts',
    // document_idle: единый бандл контент-скрипта
    content: 'src/content/main.ts',
    // страница настроек
    options: 'src/options/options.ts',
    // popup по клику на иконку (manifest action.default_popup)
    popup: 'src/popup/popup.ts',
    // CSS shadow-DOM панели → dist/panel.css (tokens + panel, инлайн @import)
    panel: 'src/ui/index.css',
    // CSS options.html/popup.html (не shadow DOM, токены на :root) → dist/settings-chrome.css
    'settings-chrome': 'src/ui/settings-chrome.css',
  },
  outdir: 'dist',
  bundle: true,
  format: 'iife',
  target: ['chrome114'],
  platform: 'browser',
  charset: 'utf8',
  legalComments: 'none',
  logLevel: 'info',
  sourcemap: watch ? 'inline' : false,
  minify: false,
}

if (watch) {
  const ctx = await esbuild.context(options)
  await ctx.watch()
  console.log('[ext] watch: жду изменений в src/…')
} else {
  await esbuild.build(options)
  console.log('[ext] сборка готова → dist/')
}
