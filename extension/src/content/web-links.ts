import { DEFAULT_WEB_BASE_URL, loadConfig, type ExtensionConfig } from '../config'

let cachedConfig: ExtensionConfig | null = null

export async function ensureWebConfig(): Promise<ExtensionConfig> {
  if (!cachedConfig) cachedConfig = await loadConfig()
  return cachedConfig
}

/** Deep-link на дровер вакансии в web SPA: ${webBaseUrl}/jobs/{vacancy_id}. */
export function webJobUrl(vacancyId: string, base = DEFAULT_WEB_BASE_URL): string {
  return `${base.replace(/\/$/, '')}/jobs/${encodeURIComponent(vacancyId)}`
}

export function openExternal(url: string) {
  if (url) window.open(url, '_blank', 'noopener')
}
