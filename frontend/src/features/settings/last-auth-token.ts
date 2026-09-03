/** Токен на бэке хранится только как sha256 — сырое значение нигде не восстановить.
 * Единственный момент, когда браузер его видит, — вставка в «Аккаунт»; сохраняем в
 * localStorage для «Копировать токен» (сюда и в инструкцию установки расширения). */
export const LAST_TOKEN_STORAGE_KEY = "copilot.lastAuthToken"

export function readLastAuthToken(): string | null {
  try {
    return localStorage.getItem(LAST_TOKEN_STORAGE_KEY)
  } catch {
    return null
  }
}

export function writeLastAuthToken(token: string): void {
  try {
    localStorage.setItem(LAST_TOKEN_STORAGE_KEY, token)
  } catch {
    /* приватный режим/квота — кнопка «Копировать» просто не появится */
  }
}
