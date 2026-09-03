// EX-10: общая для popup (Шаг 3) и options (Шаг 4) разметка/логика двух состояний входа
// (не авторизован / авторизован) — параметризована контейнером и колбэками, без завязки на
// конкретную страницу. Пока не подключена ни к одной странице (§5 плана, Шаг 1 — чистая логика).
import { iconMarkup } from '../ui/icons'
import type { AuthStatus } from './api'
import { looksLikeBotAuthToken } from './token'

/** Эквивалент `active = status.authed && status.auth_token_configured` на фронте
 * (frontend/src/features/settings/AuthTokenSection.tsx) — единая логика «вход активен». */
export function isAuthActive(status: AuthStatus): boolean {
  return status.authed && status.auth_token_configured
}

export interface AuthSectionState {
  /** null — статус ещё не запрашивался (например, токена нет вовсе). */
  status: AuthStatus | null
  /** Токен есть в chrome.storage.local, но /auth/status ещё не ответил. */
  checking: boolean
  /** Текст ошибки последней попытки входа (неверный токен, нет связи и т.п.). */
  error: string | null
  /** Идёт login-запрос (авто-вход после вставки токена нужного вида). */
  pending: boolean
}

export interface AuthSectionCallbacks {
  /** Вызывается при вставке токена нужного вида (авто-вход, без отдельной кнопки). */
  onLogin: (token: string) => void
  /** Только локальная очистка chrome.storage.local — НИКОГДА не /auth/logout (§2.7). */
  onLogout: () => void
}

function botLink(status: AuthStatus | null): string | null {
  return status?.bot_username ? `https://t.me/${status.bot_username}` : null
}

/** Отрисовывает секцию входа в контейнер (полностью заменяет innerHTML) и навешивает
 * обработчики. Вызывающая сторона решает, когда перерисовывать (после ответа /auth/status,
 * после смены chrome.storage). */
export function renderAuthSection(
  container: HTMLElement,
  state: AuthSectionState,
  callbacks: AuthSectionCallbacks,
): void {
  const { status, checking, error, pending } = state

  if (checking) {
    container.innerHTML = `
      <div class="jh-auth-loading">
        ${iconMarkup('loader', { size: 16, className: 'jh-spin' })}
        <span>Проверяю токен…</span>
      </div>
    `
    return
  }

  if (status && isAuthActive(status)) {
    const accountName = status.account_username ? `@${status.account_username}` : null
    container.innerHTML = `
      <div class="jh-auth-active jh-pop">
        <div class="jh-auth-active-row">
          ${iconMarkup('circle-check', { size: 20 })}
          <div>
            <p class="jh-auth-title">Токен принят${accountName ? ` — вы вошли как ${accountName}` : ''}</p>
            <p class="jh-auth-hint">
              Новый токен — в боте, кнопкой «Токен авторизации»; аккаунт сохраняется.
            </p>
          </div>
        </div>
        <button type="button" class="jh-auth-logout" id="jh-auth-logout-btn">
          ${iconMarkup('log-out', { size: 16 })}<span>Выйти</span>
        </button>
      </div>
    `
    container.querySelector('#jh-auth-logout-btn')?.addEventListener('click', () => {
      callbacks.onLogout()
    })
    return
  }

  const link = botLink(status)
  const botLabel = status?.bot_username ? `@${status.bot_username}` : null
  // status !== null значит /auth/status уже отвечал (не первый заход) — токен, значит, был, но
  // не подошёл (отозван/просрочен): сообщение должно отличаться от «вставьте токен впервые».
  const revoked = status !== null
  container.innerHTML = `
    <div class="jh-auth-form">
      <ol class="jh-auth-steps">
        <li>Откройте бота${
          link
            ? ` <a href="${link}" target="_blank" rel="noopener noreferrer">${botLabel ?? 'в Telegram'}</a>`
            : ' в Telegram'
        } и нажмите /start</li>
        <li>Нажмите кнопку «Токен авторизации» — бот пришлёт токен</li>
        <li>Вставьте токен в поле ниже — вход выполнится сам</li>
      </ol>
      ${
        revoked
          ? `<p class="jh-auth-revoked">Токен больше не действителен — вставьте новый из бота</p>`
          : ''
      }
      <input
        type="password"
        autocomplete="off"
        placeholder="Токен из бота"
        aria-label="Токен из бота"
        id="jh-auth-token-input"
        class="jh-auth-input"
      />
      ${error ? `<p class="jh-auth-error">${error}</p>` : ''}
      ${
        pending
          ? `<p class="jh-auth-pending">${iconMarkup('loader', { size: 14, className: 'jh-spin' })}<span>Проверяю токен…</span></p>`
          : ''
      }
    </div>
  `
  const input = container.querySelector('#jh-auth-token-input') as HTMLInputElement | null
  if (!input) return
  let lastTried = ''
  let timer: number | undefined
  input.addEventListener('input', () => {
    const trimmed = input.value.trim()
    window.clearTimeout(timer)
    if (!looksLikeBotAuthToken(trimmed) || trimmed === lastTried || pending) return
    timer = window.setTimeout(() => {
      lastTried = trimmed
      callbacks.onLogin(trimmed)
    }, 500)
  })
}
