/**
 * Контракт динамического конфига селекторов hh (Шаг 0).
 *
 * Сервер меняет «как найти» (CSS-строки), не «что собрать»: неизвестный ключ
 * отбрасывается, регекс с сервера не принимается. Та же схема, что
 * `core/domains/opportunities/parser_config.py`. Битый кэш storage валидируется
 * тем же парсером — не должен заклинить расширение.
 */
import repoDefault from '../../../core/domains/opportunities/sources/hh_selectors.json'
import { loadConfig } from '../config'

export const MAX_SELECTOR_LEN = 200
export const MAX_ARRAY_LEN = 10

export const SELECTOR_GROUPS = [
  'vacancy',
  'serp',
  'responseLinks',
  'fallbacks',
  'negotiations',
  'hrThread',
] as const

export type SelectorGroup = (typeof SELECTOR_GROUPS)[number]
export type SelectorValueKind = 'str' | 'list'

export const SELECTOR_VALUE_KIND: Record<string, SelectorValueKind | Record<string, SelectorValueKind>> =
  {
    vacancy: {
      title: 'str',
      company: 'str',
      salary: 'str',
      description: 'str',
      schedule: 'str',
      remote: 'str',
      workFormat: 'str',
      employmentText: 'str',
      scheduleByDays: 'str',
      workingHours: 'str',
      experienceText: 'str',
      address: 'str',
      addressMap: 'str',
      addCoverLetter: 'str',
      addCoverLetterPopup: 'str',
      coverLetterInput: 'str',
      coverLetterInputPopup: 'str',
      modalOverlay: 'str',
      alreadyApplied: 'str',
      archiveDescription: 'str',
      archiveHeader: 'str',
      responsesCount: 'str',
      responsesInfo: 'str',
    },
    serp: {
      vacancyCard: 'str',
      title: 'str',
      titleLink: 'str',
      employer: 'str',
      employerLink: 'str',
      salary: 'str',
      address: 'str',
      metro: 'str',
      respondBtn: 'str',
      pagerNext: 'str',
    },
    responseLinks: 'list',
    fallbacks: {
      title: 'list',
      company: 'list',
      salary: 'list',
      description: 'list',
      serpTitleLink: 'list',
      serpEmployer: 'list',
      serpSalary: 'list',
    },
    negotiations: {
      card: 'list',
      titleLink: 'str',
      company: 'list',
      statusBadge: 'list',
      date: 'str',
      lastMessage: 'list',
    },
    hrThread: {
      vacancyLink: 'str',
      companyLink: 'str',
      messageItem: 'list',
      dayDivider: 'str',
    },
  }

export const PATTERN_SLOTS = ['appliedText', 'responsesText', 'negotiationStatus'] as const
export const PATTERN_NAMES = [
  'hh_applied',
  'hh_responses',
  'hh_negotiation_status',
] as const
export const PATTERN_SLOT_DEFAULT: Record<(typeof PATTERN_SLOTS)[number], (typeof PATTERN_NAMES)[number]> =
  {
    appliedText: 'hh_applied',
    responsesText: 'hh_responses',
    negotiationStatus: 'hh_negotiation_status',
  }

const ENVELOPE_KEYS = new Set(['version', 'selectors', 'patterns', 'updated_at', 'origin'])
const LOCAL_HTTP_HOSTS = new Set(['localhost', '127.0.0.1'])
const REGEX_VALUE_RE = /^\/.+\/[gimsuy]*$/

export type ConfigIssueReason =
  | 'unknown_selector_key'
  | 'invalid_selector'
  | 'config_schema_invalid'
  | 'config_http_insecure'

export type ConfigIssue = { reason: ConfigIssueReason; detail: string }

export type HhSelectorsPayload = Record<string, unknown>
export type HhPatternsPayload = Record<string, string | boolean>

export type ParsedSelectorsConfig = {
  version: number
  selectors: HhSelectorsPayload
  patterns: HhPatternsPayload
  issues: ConfigIssue[]
  schemaValid: boolean
  usedDefaults: boolean
}

export type RepoHhSelectorsConfig = {
  version: number
  selectors: HhSelectorsPayload
  patterns: HhPatternsPayload
}

export const DEFAULT_HH_SELECTORS_CONFIG = repoDefault as RepoHhSelectorsConfig

export function isConfigFetchAllowed(apiBaseUrl: string): boolean {
  if (!apiBaseUrl) return false
  try {
    const url = new URL(apiBaseUrl)
    if (url.protocol === 'https:') return true
    const host = url.hostname.toLowerCase()
    return url.protocol === 'http:' && LOCAL_HTTP_HOSTS.has(host)
  } catch {
    return false
  }
}

export function looksLikeRegex(value: string): boolean {
  const stripped = value.trim()
  if (REGEX_VALUE_RE.test(stripped)) return true
  return stripped.includes('(?')
}

function cssBracketsAndQuotesOk(s: string): boolean {
  let quote: string | null = null
  let square = 0
  let paren = 0
  for (let i = 0; i < s.length; i++) {
    const ch = s[i]
    if (quote) {
      if (ch === '\\' && i + 1 < s.length) {
        i += 1
        continue
      }
      if (ch === quote) quote = null
      continue
    }
    if (ch === "'" || ch === '"') quote = ch
    else if (ch === '[') square += 1
    else if (ch === ']') {
      square -= 1
      if (square < 0) return false
    } else if (ch === '(') paren += 1
    else if (ch === ')') {
      paren -= 1
      if (paren < 0) return false
    }
  }
  return quote === null && square === 0 && paren === 0
}

/** Синтаксис CSS: querySelector на пустом фрагменте, иначе консервативная проверка скобок. */
export function isValidCssSelector(value: unknown): boolean {
  if (typeof value !== 'string') return false
  const s = value.trim()
  if (!s || s.length > MAX_SELECTOR_LEN) return false
  if (s.includes('\0') || looksLikeRegex(s)) return false
  if ('>+~,'.includes(s[s.length - 1] || '')) return false
  if (typeof document !== 'undefined') {
    try {
      document.createDocumentFragment().querySelector(s)
      return true
    } catch {
      return false
    }
  }
  return cssBracketsAndQuotesOk(s)
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

function rollback(defaults: RepoHhSelectorsConfig, detail: string): ParsedSelectorsConfig {
  return {
    version: defaults.version,
    selectors: clone(defaults.selectors),
    patterns: { ...defaults.patterns },
    issues: [{ reason: 'config_schema_invalid', detail }],
    schemaValid: false,
    usedDefaults: true,
  }
}

function validVersion(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value > 0
}

function parseStringField(
  value: unknown,
  path: string,
  issues: ConfigIssue[],
): string | null {
  if (typeof value !== 'string' || !isValidCssSelector(value)) {
    issues.push({ reason: 'invalid_selector', detail: path })
    return null
  }
  return value.trim()
}

function parseListField(
  value: unknown,
  path: string,
  issues: ConfigIssue[],
): string[] | null {
  if (!Array.isArray(value)) {
    issues.push({ reason: 'invalid_selector', detail: path })
    return null
  }
  let items = value
  if (items.length > MAX_ARRAY_LEN) {
    issues.push({
      reason: 'invalid_selector',
      detail: `${path}: массив длиннее ${MAX_ARRAY_LEN}`,
    })
    items = items.slice(0, MAX_ARRAY_LEN)
  }
  const parsed: string[] = []
  items.forEach((item, i) => {
    const itemPath = `${path}[${i}]`
    if (typeof item !== 'string' || !isValidCssSelector(item)) {
      issues.push({ reason: 'invalid_selector', detail: itemPath })
      return
    }
    parsed.push(item.trim())
  })
  return parsed.length ? parsed : null
}

function overlayGroup(
  kind: SelectorValueKind | Record<string, SelectorValueKind>,
  incoming: unknown,
  current: unknown,
  path: string,
  issues: ConfigIssue[],
): unknown {
  if (kind === 'list') {
    const parsed = parseListField(incoming, path, issues)
    return parsed ?? current
  }
  if (typeof kind !== 'object' || incoming === null || typeof incoming !== 'object' || Array.isArray(incoming)) {
    if (typeof kind === 'object') issues.push({ reason: 'invalid_selector', detail: path })
    return current
  }
  if (current === null || typeof current !== 'object' || Array.isArray(current)) return current
  const out: Record<string, unknown> = clone(current as Record<string, unknown>)
  for (const [key, rawVal] of Object.entries(incoming as Record<string, unknown>)) {
    const keyKind = kind[key]
    const keyPath = `${path}.${key}`
    if (!keyKind) {
      issues.push({ reason: 'unknown_selector_key', detail: keyPath })
      continue
    }
    if (keyKind === 'str') {
      const parsed = parseStringField(rawVal, keyPath, issues)
      if (parsed !== null) out[key] = parsed
    } else {
      const parsed = parseListField(rawVal, keyPath, issues)
      if (parsed !== null) out[key] = parsed
    }
  }
  return out
}

function overlayPatterns(
  incoming: unknown,
  current: HhPatternsPayload,
  issues: ConfigIssue[],
): HhPatternsPayload {
  if (incoming === null || typeof incoming !== 'object' || Array.isArray(incoming)) {
    issues.push({ reason: 'invalid_selector', detail: 'patterns' })
    return current
  }
  const out: HhPatternsPayload = { ...current }
  const allowed = new Set<string>(PATTERN_SLOTS)
  const names = new Set<string>(PATTERN_NAMES)
  for (const [slot, rawVal] of Object.entries(incoming as Record<string, unknown>)) {
    const path = `patterns.${slot}`
    if (!allowed.has(slot)) {
      issues.push({ reason: 'unknown_selector_key', detail: path })
      continue
    }
    if (typeof rawVal === 'boolean') {
      out[slot] = rawVal
      continue
    }
    if (typeof rawVal === 'string' && names.has(rawVal)) {
      out[slot] = rawVal
      continue
    }
    issues.push({ reason: 'invalid_selector', detail: path })
  }
  return out
}

export function parseSelectorsConfig(
  raw: unknown,
  defaults: RepoHhSelectorsConfig = DEFAULT_HH_SELECTORS_CONFIG,
): ParsedSelectorsConfig {
  if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) {
    return rollback(defaults, 'не объект')
  }
  const obj = raw as Record<string, unknown>
  if (!validVersion(obj.version)) {
    return rollback(defaults, 'version: целое больше нуля')
  }

  const selectorsIn = obj.selectors === undefined || obj.selectors === null ? {} : obj.selectors
  if (typeof selectorsIn !== 'object' || Array.isArray(selectorsIn)) {
    return rollback(defaults, 'selectors: не объект')
  }

  let patternsIn: unknown = obj.patterns === undefined || obj.patterns === null ? {} : obj.patterns
  if (patternsIn !== null && typeof patternsIn === 'object' && !Array.isArray(patternsIn)) {
    /* ok */
  } else if (patternsIn === undefined) {
    patternsIn = {}
  } else {
    return rollback(defaults, 'patterns: не объект')
  }

  const issues: ConfigIssue[] = []
  for (const extra of Object.keys(obj)) {
    if (!ENVELOPE_KEYS.has(extra)) {
      issues.push({ reason: 'unknown_selector_key', detail: extra })
    }
  }

  const selectors: HhSelectorsPayload = clone(defaults.selectors)
  let patterns: HhPatternsPayload = { ...defaults.patterns }

  for (const [group, groupVal] of Object.entries(selectorsIn as Record<string, unknown>)) {
    const kind = SELECTOR_VALUE_KIND[group]
    if (!kind) {
      issues.push({ reason: 'unknown_selector_key', detail: `selectors.${group}` })
      continue
    }
    selectors[group] = overlayGroup(
      kind,
      groupVal,
      selectors[group],
      `selectors.${group}`,
      issues,
    )
  }

  if (patternsIn && typeof patternsIn === 'object' && Object.keys(patternsIn as object).length) {
    patterns = overlayPatterns(patternsIn, patterns, issues)
  }

  return {
    version: obj.version,
    selectors,
    patterns,
    issues,
    schemaValid: true,
    usedDefaults: false,
  }
}

/** Аудируемый dump (0.6): то, что реально применится. */
export function dumpSelectorsConfigJson(parsed: ParsedSelectorsConfig): string {
  return `${JSON.stringify(
    {
      version: parsed.version,
      selectors: parsed.selectors,
      patterns: parsed.patterns,
    },
    null,
    2,
  )}\n`
}

// ── Шаг 2: runtime pack (storage → память, сеть не блокирует разбор) ────────

export const HH_SELECTORS_STORAGE_KEY = 'hhParserSelectors'
export const HH_SELECTORS_ETAG_KEY = 'hhParserSelectorsEtag'

export type ConfigOrigin = 'server' | 'storage' | 'builtin'
export type ApiConfigOrigin = 'db_override' | 'repo'

export type HhSelectorPack = {
  vacancy: Record<string, string>
  serp: Record<string, string>
  responseLinks: string[]
  fallbacks: Record<string, string[]>
  negotiations: Record<string, string | string[]>
  hrThread: Record<string, string | string[]>
  patterns: HhPatternsPayload
  version: number
  origin: ConfigOrigin
  updatedAt: string | null
  apiOrigin: ApiConfigOrigin | null
}

type StoredSelectorsEnvelope = {
  version: number
  selectors: HhSelectorsPayload
  patterns: HhPatternsPayload
  updated_at?: string | null
  origin?: string
}

const PARSER_CONFIG_PATH = '/api/opportunities/parser-config/hh'
const CONFIG_HEALTH_URL = 'extension:parser-config'

let memoryPack: HhSelectorPack | null = null
let memoryEtag: string | null = null
let builtinPackCache: HhSelectorPack | null = null
let storageWatchInstalled = false
let loadInFlight: Promise<HhSelectorPack> | null = null

function builtinPack(): HhSelectorPack {
  if (!builtinPackCache) {
    builtinPackCache = packFromParsed(
      parseSelectorsConfig(DEFAULT_HH_SELECTORS_CONFIG),
      'builtin',
      null,
      null,
    )
  }
  return builtinPackCache
}

function packFromParsed(
  parsed: ParsedSelectorsConfig,
  origin: ConfigOrigin,
  updatedAt: string | null,
  apiOrigin: ApiConfigOrigin | null,
): HhSelectorPack {
  const selectors = parsed.selectors
  return {
    vacancy: (selectors.vacancy || {}) as Record<string, string>,
    serp: (selectors.serp || {}) as Record<string, string>,
    responseLinks: Array.isArray(selectors.responseLinks)
      ? (selectors.responseLinks as string[])
      : [],
    fallbacks: (selectors.fallbacks || {}) as Record<string, string[]>,
    negotiations: (selectors.negotiations || {}) as Record<string, string | string[]>,
    hrThread: (selectors.hrThread || {}) as Record<string, string | string[]>,
    patterns: parsed.patterns,
    version: parsed.version,
    origin,
    updatedAt,
    apiOrigin,
  }
}

function readUpdatedAt(raw: unknown): string | null {
  if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) return null
  const value = (raw as Record<string, unknown>).updated_at
  return typeof value === 'string' && value ? value : null
}

function readApiOrigin(raw: unknown): ApiConfigOrigin | null {
  if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) return null
  const value = (raw as Record<string, unknown>).origin
  return value === 'db_override' || value === 'repo' ? value : null
}

function applyParsed(
  parsed: ParsedSelectorsConfig,
  origin: ConfigOrigin,
  updatedAt: string | null,
  apiOrigin: ApiConfigOrigin | null,
): HhSelectorPack {
  memoryPack = packFromParsed(parsed, origin, updatedAt, apiOrigin)
  return memoryPack
}

/** Синхронный доступ: валидный сервер → валидный storage → зашитые дефолты. Никогда null. */
export function getSelectors(): HhSelectorPack {
  return memoryPack ?? builtinPack()
}

export function dumpSelectorPackJson(pack: HhSelectorPack = getSelectors()): string {
  return dumpSelectorsConfigJson({
    version: pack.version,
    selectors: {
      vacancy: pack.vacancy,
      serp: pack.serp,
      responseLinks: pack.responseLinks,
      fallbacks: pack.fallbacks,
      negotiations: pack.negotiations,
      hrThread: pack.hrThread,
    },
    patterns: pack.patterns,
    issues: [],
    schemaValid: true,
    usedDefaults: pack.origin === 'builtin',
  })
}

function reportConfigIssue(reason: ConfigIssueReason, detail: string): void {
  try {
    if (typeof chrome === 'undefined' || !chrome.runtime?.sendMessage) return
    chrome.runtime.sendMessage(
      {
        action: 'report_parse_health',
        payload: {
          site: 'hh',
          page: 'vacancy',
          reason,
          detail,
          url: CONFIG_HEALTH_URL,
        },
      },
      () => {
        void chrome.runtime.lastError
      },
    )
  } catch {
    /* SW / тесты без runtime */
  }
}

function reportParsedIssues(issues: ConfigIssue[]): void {
  const seen = new Set<string>()
  for (const issue of issues) {
    const key = `${issue.reason}:${issue.detail}`
    if (seen.has(key)) continue
    seen.add(key)
    reportConfigIssue(issue.reason, issue.detail)
  }
}

async function hydrateFromStorage(preferredOrigin?: ConfigOrigin): Promise<void> {
  if (typeof chrome === 'undefined' || !chrome.storage?.local) return
  try {
    const stored = await chrome.storage.local.get([
      HH_SELECTORS_STORAGE_KEY,
      HH_SELECTORS_ETAG_KEY,
    ])
    const raw = stored[HH_SELECTORS_STORAGE_KEY]
    if (raw === undefined || raw === null) return
    const parsed = parseSelectorsConfig(raw)
    if (!parsed.schemaValid) return
    applyParsed(
      parsed,
      preferredOrigin ?? 'storage',
      readUpdatedAt(raw),
      readApiOrigin(raw),
    )
    const etag = stored[HH_SELECTORS_ETAG_KEY]
    if (typeof etag === 'string' && etag) memoryEtag = etag
  } catch {
    /* битый кэш не должен заклинить расширение */
  }
}

function ensureStorageWatch(): void {
  if (storageWatchInstalled) return
  if (typeof chrome === 'undefined' || !chrome.storage?.onChanged) return
  storageWatchInstalled = true
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== 'local' || !changes[HH_SELECTORS_STORAGE_KEY]) return
    const next = changes[HH_SELECTORS_STORAGE_KEY].newValue
    if (next === undefined) return
    const parsed = parseSelectorsConfig(next)
    if (!parsed.schemaValid) return
    if (
      memoryPack &&
      memoryPack.version === parsed.version &&
      memoryPack.origin === 'server'
    ) {
      return
    }
    applyParsed(parsed, 'server', readUpdatedAt(next), readApiOrigin(next))
  })
}

/** Content/options имеют window + runtime.id — fetch с Origin hh.ru CORS не пройдёт. */
function shouldRelayToBackground(): boolean {
  try {
    return typeof window !== 'undefined' && Boolean(chrome?.runtime?.id)
  } catch {
    return false
  }
}

function extensionVersionHeader(): Record<string, string> {
  try {
    const version = chrome.runtime?.getManifest?.().version
    return version ? { 'X-Extension-Version': version } : {}
  } catch {
    return {}
  }
}

async function persistPack(
  parsed: ParsedSelectorsConfig,
  origin: ConfigOrigin,
  updatedAt: string | null,
  apiOrigin: ApiConfigOrigin | null,
  etag: string | null,
): Promise<HhSelectorPack> {
  const pack = applyParsed(parsed, origin, updatedAt, apiOrigin)
  memoryEtag = etag
  if (typeof chrome !== 'undefined' && chrome.storage?.local) {
    const envelope: StoredSelectorsEnvelope = {
      version: parsed.version,
      selectors: parsed.selectors,
      patterns: parsed.patterns,
      updated_at: updatedAt,
      origin: apiOrigin ?? undefined,
    }
    const toSet: Record<string, unknown> = { [HH_SELECTORS_STORAGE_KEY]: envelope }
    if (etag) toSet[HH_SELECTORS_ETAG_KEY] = etag
    await chrome.storage.local.set(toSet)
  }
  return pack
}

function relayToBackground(force?: boolean): Promise<ConfigOrigin | null> {
  return new Promise((resolve) => {
    try {
      chrome.runtime.sendMessage(
        { action: 'refresh_parser_selectors', force: Boolean(force) },
        (resp?: { ok?: boolean; origin?: ConfigOrigin }) => {
          void chrome.runtime.lastError
          resolve(resp?.ok && resp.origin ? resp.origin : null)
        },
      )
    } catch {
      resolve(null)
    }
  })
}

/**
 * Сеть: GET с If-None-Match, валидация, запись в storage.
 * Звать из service worker / тестов. Content-script — через loadSelectors().
 */
export async function fetchSelectorsFromApi(
  opts?: { force?: boolean },
): Promise<HhSelectorPack> {
  if (!memoryPack) await hydrateFromStorage()
  let cfg
  try {
    cfg = await loadConfig()
  } catch {
    return getSelectors()
  }

  if (!isConfigFetchAllowed(cfg.apiBaseUrl)) {
    reportConfigIssue('config_http_insecure', cfg.apiBaseUrl || '(пусто)')
    return getSelectors()
  }
  if (!cfg.authToken) return getSelectors()

  const headers: Record<string, string> = {
    'X-Auth-Token': cfg.authToken,
    ...extensionVersionHeader(),
  }
  if (!opts?.force && memoryEtag) {
    headers['If-None-Match'] = memoryEtag
  }

  let response: Response
  try {
    response = await fetch(`${cfg.apiBaseUrl}${PARSER_CONFIG_PATH}`, { headers })
  } catch {
    return getSelectors()
  }

  if (response.status === 304) {
    if (memoryPack && memoryPack.origin !== 'server') {
      memoryPack = { ...memoryPack, origin: 'server' }
    }
    return getSelectors()
  }
  if (!response.ok) return getSelectors()

  let raw: unknown
  try {
    raw = await response.json()
  } catch {
    reportConfigIssue('config_schema_invalid', 'тело ответа не JSON')
    return getSelectors()
  }

  const parsed = parseSelectorsConfig(raw)
  if (!parsed.schemaValid) {
    reportParsedIssues(parsed.issues)
    return getSelectors()
  }
  if (parsed.issues.length) reportParsedIssues(parsed.issues)

  const etag = response.headers.get('ETag')
  return persistPack(parsed, 'server', readUpdatedAt(raw), readApiOrigin(raw), etag)
}

/**
 * Сеть не блокирует парсинг: прилетающий конфиг влияет на следующий разбор.
 * Content/options релэят fetch в background (CORS: Origin страницы ≠ расширения).
 */
export async function loadSelectors(opts?: { force?: boolean }): Promise<HhSelectorPack> {
  if (loadInFlight) return loadInFlight
  loadInFlight = (async () => {
    if (shouldRelayToBackground()) {
      const origin = await relayToBackground(opts?.force)
      await hydrateFromStorage(origin === 'server' ? 'server' : undefined)
      return getSelectors()
    }
    return fetchSelectorsFromApi(opts)
  })()
  try {
    return await loadInFlight
  } finally {
    loadInFlight = null
  }
}

/** Старт: storage → память сразу, затем фоновое обновление. */
export async function initSelectors(): Promise<HhSelectorPack> {
  await hydrateFromStorage()
  ensureStorageWatch()
  void loadSelectors()
  return getSelectors()
}

/** Сброс in-memory — только для unit-тестов. */
export function _resetSelectorsForTests(): void {
  memoryPack = null
  memoryEtag = null
  builtinPackCache = null
  loadInFlight = null
}
