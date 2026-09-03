// Резервная страница настроек: только секция «Аккаунт» (auth/render.ts, общий рендер с
// gate-панелью в dock.ts — EX-18). Обычный путь входа теперь — прямо в панели на странице
// вакансии; эта страница остаётся как fallback, доступный через chrome://extensions → «Параметры
// расширения», на случай если пользователь не на hh.ru/getmatch.ru. Адрес сайта/API больше не
// вводится руками — DEFAULT_API_BASE_URL зашит на сборке (build.mjs, EXT_API_BASE_URL).
import { fetchAuthStatus, loginWithToken } from '../auth/api'
import { renderAuthSection, type AuthSectionState } from '../auth/render'
import {
  clearAccountScopedStorage,
  clearStoredAuthToken,
  getStoredAuthToken,
  setStoredAuthToken,
} from '../auth/token'
import { DEFAULT_API_BASE_URL } from '../config'
import { iconMarkup } from '../ui/icons'
import {
  dumpSelectorPackJson,
  getSelectors,
  initSelectors,
  loadSelectors,
  type HhSelectorPack,
} from '../dom/selectors-config'

const byId = (id: string) => document.getElementById(id)

/** Бренд с lucide-иконкой (единый язык с панелью). */
function renderChrome(): void {
  const brand = byId('brand')
  if (brand) brand.innerHTML = `${iconMarkup('sparkles', { size: 14 })}<span>Copilot</span>`
}

// --- секция «Аккаунт» (общий рендер auth/render.ts — тот же, что в панели на странице вакансии) ---

let authState: AuthSectionState = { status: null, checking: false, error: null, pending: false }

function renderAuth(): void {
  const container = byId('auth')
  if (!container) return
  renderAuthSection(container, authState, { onLogin: handleLogin, onLogout: handleLogout })
}

async function checkAuth(): Promise<void> {
  const token = await getStoredAuthToken()
  if (!token) {
    authState = { status: null, checking: false, error: null, pending: false }
    renderAuth()
    return
  }
  authState = { ...authState, checking: true }
  renderAuth()
  try {
    const status = await fetchAuthStatus(DEFAULT_API_BASE_URL, token)
    authState = { status, checking: false, error: null, pending: false }
  } catch (err) {
    authState = { status: null, checking: false, error: (err as Error).message, pending: false }
  }
  renderAuth()
}

async function handleLogin(token: string): Promise<void> {
  authState = { ...authState, pending: true, error: null }
  renderAuth()
  try {
    const status = await loginWithToken(DEFAULT_API_BASE_URL, token)
    await clearAccountScopedStorage()
    await setStoredAuthToken(token)
    authState = { status, checking: false, error: null, pending: false }
  } catch (err) {
    authState = { status: null, checking: false, error: (err as Error).message, pending: false }
  }
  renderAuth()
}

async function handleLogout(): Promise<void> {
  await clearStoredAuthToken()
  await clearAccountScopedStorage()
  authState = { status: null, checking: false, error: null, pending: false }
  renderAuth()
}

renderChrome()
void bootParserConfig()
checkAuth()

function formatParserConfigLine(pack: HhSelectorPack): string {
  const originLabel =
    pack.origin === 'builtin'
      ? 'встроенный'
      : pack.apiOrigin === 'db_override'
        ? 'сервер (оверрайд БД)'
        : 'сервер'
  let datePart = ''
  if (pack.updatedAt) {
    const d = new Date(pack.updatedAt)
    if (!Number.isNaN(d.getTime())) {
      const dd = String(d.getDate()).padStart(2, '0')
      const mm = String(d.getMonth() + 1).padStart(2, '0')
      datePart = ` от ${dd}.${mm}`
    }
  }
  return `Конфиг парсера: версия ${pack.version}${datePart}, источник: ${originLabel}`
}

async function bootParserConfig(): Promise<void> {
  const line = byId('parser-config-meta')
  const dumpBtn = byId('parser-config-dump') as HTMLButtonElement | null
  const dumpPre = byId('parser-config-json')
  const render = () => {
    if (line) line.textContent = formatParserConfigLine(getSelectors())
  }
  await initSelectors()
  render()
  void loadSelectors().then(render)
  dumpBtn?.addEventListener('click', () => {
    if (!dumpPre || !dumpBtn) return
    const hidden = dumpPre.hidden
    dumpPre.hidden = !hidden
    if (!dumpPre.hidden) dumpPre.textContent = dumpSelectorPackJson(getSelectors())
    dumpBtn.textContent = dumpPre.hidden ? 'Показать конфиг' : 'Скрыть конфиг'
  })
}
