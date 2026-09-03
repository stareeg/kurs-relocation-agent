// Popup по клику на иконку расширения (EX-10, Шаг 3 плана): минимальное окно входа — токен +
// статус + логаут, без дублирования настроек (адрес сайта и т.п. — только в options.html, ссылка
// «Параметры» внизу). Логика входа общая с options через auth/render.ts; адрес API выводится из
// сохранённого webBaseUrl (EX-17).
// Открытие options из popup — прямой chrome.runtime.openOptionsPage() (доступен в popup-
// контексте; релей через background нужен только content-script'у — dock.ts, Шаг 6).
import { fetchAuthStatus, loginWithToken } from '../auth/api'
import { renderAuthSection, type AuthSectionState } from '../auth/render'
import {
  clearAccountScopedStorage,
  clearStoredAuthToken,
  getStoredAuthToken,
  setStoredAuthToken,
} from '../auth/token'
import { loadConfig } from '../config'
import { iconMarkup } from '../ui/icons'

const byId = (id: string) => document.getElementById(id)

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
    const { apiBaseUrl } = await loadConfig()
    const status = await fetchAuthStatus(apiBaseUrl, token)
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
    const { apiBaseUrl } = await loadConfig()
    const status = await loginWithToken(apiBaseUrl, token)
    await clearAccountScopedStorage()
    await setStoredAuthToken(token)
    authState = { status, checking: false, error: null, pending: false }
  } catch (err) {
    authState = { status: null, checking: false, error: (err as Error).message, pending: false }
  }
  renderAuth()
}

// Только локальная очистка chrome.storage.local — НИКОГДА не /auth/logout (§2.7: логаут
// расширения не должен рвать веб-сессию того же человека на соседней вкладке).
async function handleLogout(): Promise<void> {
  await clearStoredAuthToken()
  await clearAccountScopedStorage()
  authState = { status: null, checking: false, error: null, pending: false }
  renderAuth()
}

function renderChrome(): void {
  const brand = byId('brand')
  if (brand) brand.innerHTML = `${iconMarkup('sparkles', { size: 14 })}<span>Copilot</span>`
  const optionsBtn = byId('open-options')
  if (optionsBtn) {
    optionsBtn.innerHTML = `${iconMarkup('settings', { size: 16 })}<span>Параметры</span>`
    optionsBtn.addEventListener('click', () => chrome.runtime.openOptionsPage())
  }
}

renderChrome()
checkAuth()
