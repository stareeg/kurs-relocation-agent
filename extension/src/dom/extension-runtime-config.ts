/**
 * Рантайм-конфиг расширения: флаги (аварийный стоп), тюнинг темпа/таймаутов, селекторы отклика.
 *
 * Мотив (2026-08-28): пересборки расширения раздражают пользователей. MV3 запрещает исполнять
 * код не из пакета, поэтому плюмбинг service worker'а всё равно приезжает пересборкой — но всё,
 * что *реально* дёргается (селекторы `data-qa` площадок, задержки анти-детекта, дневной темп,
 * аварийный стоп), — это данные, не код. Их сервер отдаёт по
 * `GET /api/opportunities/parser-config/extension`, расширение тянет по alarm'у раз в 30 минут
 * и держит в `chrome.storage.local`. Тот же приём и контракт, что у `selectors-config.ts`.
 *
 * Контракт: сервер меняет *значения*, не *структуру*. Битый/отсутствующий конфиг → зашитый
 * дефолт, расширение никогда не остаётся без рабочих значений.
 */
import repoDefault from '../../../core/domains/opportunities/sources/extension_runtime_config.json'
import { loadConfig } from '../config'
import { isValidCssSelector } from './selectors-config'

export const FLAG_KEYS = [
  'auto_apply_enabled',
  'auto_apply_hh_enabled',
  'auto_apply_getmatch_enabled',
  'auto_apply_habr_enabled',
  'anketa_resume_enabled',
  'discovery_enabled',
] as const
export type FlagKey = (typeof FLAG_KEYS)[number]

// Ключ тюнинга → [min, max] клампа. Держать синхронно с backend
// `core/domains/opportunities/extension_runtime_config.py`.
// Скаляры, которым дробное значение осмысленно (период chrome.alarms в минутах) — не округляем
// до целого. `discovery_tick_minutes=0.5` → alarm раз в 30с (минимум chrome.alarms с Chrome 120).
const TUNING_FRACTIONAL: ReadonlySet<string> = new Set(['discovery_tick_minutes'])

const TUNING_SCALAR: Record<string, [number, number]> = {
  auto_apply_tick_minutes: [1, 60],
  discovery_tick_minutes: [0.5, 60],
  max_real_applications_per_tick: [1, 10],
  // Жёсткий пол паузы между реальными откликами одной площадки — не ниже 2 минут
  // (owner's spec 2026-08-28: не чаще 1 автоотклика в 2 минуты).
  auto_apply_min_real_interval_ms: [120_000, 600_000],
  tab_load_timeout_ms: [5_000, 120_000],
  post_load_settle_ms: [0, 10_000],
  vacancy_ready_timeout_ms: [10_000, 180_000],
  apply_confirm_timeout_ms: [2_000, 60_000],
}
const TUNING_RANGE: Record<string, [number, number]> = {
  auto_apply_delay_ms: [1_000, 600_000],
  apply_reading_delay_ms: [0, 60_000],
  // Темп автопросмотра: `discovery_tick_minutes` — период alarm (нижняя граница), раннер добирает
  // рандом до верхней. Дефолт [30с, 90с]; нижняя граница обязана совпадать с alarm-периодом.
  discovery_delay_ms: [30_000, 600_000],
}

const APPLY_SELECTOR_KEYS: Record<string, readonly string[]> = {
  hh: [
    'responseLinkTop',
    'responseLinkBottom',
    'alreadyApplied',
    'attachLetterButton',
    'letterTextarea',
    'letterSubmit',
    'anketaQuestionBody',
    'anketaQuestionText',
    'anketaSubmit',
  ],
  getmatch: ['form', 'coverLetterTextarea'],
}

const PARSE_SELECTOR_KEYS: Record<string, readonly string[]> = {
  getmatch: [
    'header',
    'title',
    'companyLink',
    'salary',
    'locations',
    'specs',
    'stack',
    'description',
    'applyButton',
    'archived',
    'appliedBanner',
  ],
}

const TEXT_SIGNAL_KEYS: Record<string, readonly string[]> = {
  hh: ['already_applied'],
  getmatch: ['already_applied', 'archived', 'letter_required'],
}
const TEXT_SIGNAL_MIN_LEN = 2
const TEXT_SIGNAL_MAX_LEN = 200
const TEXT_SIGNAL_MAX_ITEMS = 20

export type ExtensionRuntimeConfig = {
  version: number
  flags: Record<FlagKey, boolean>
  tuning: {
    auto_apply_tick_minutes: number
    discovery_tick_minutes: number
    max_real_applications_per_tick: number
    auto_apply_min_real_interval_ms: number
    tab_load_timeout_ms: number
    post_load_settle_ms: number
    vacancy_ready_timeout_ms: number
    apply_confirm_timeout_ms: number
    auto_apply_delay_ms: [number, number]
    apply_reading_delay_ms: [number, number]
    discovery_delay_ms: [number, number]
  }
  apply_selectors: Record<string, Record<string, string>>
  parse_selectors: Record<string, Record<string, string>>
  text_signals: Record<string, Record<string, string[]>>
  origin: 'server' | 'storage' | 'builtin'
}

type RawEnvelope = Record<string, unknown>

const DEFAULT_RAW = repoDefault as RawEnvelope

function clamp(value: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, value))
}

function isFiniteNumber(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v)
}

/** Разобрать сырой конверт поверх зашитого дефолта. Никогда не бросает; неизвестное/битое
 *  отбрасывается, число клампится, селектор проходит CSS-валидацию. */
export function parseRuntimeConfig(
  raw: unknown,
  origin: ExtensionRuntimeConfig['origin'],
): ExtensionRuntimeConfig {
  const base = buildFromRaw(DEFAULT_RAW, 'builtin')
  if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) return { ...base, origin }
  const env = raw as RawEnvelope

  const version =
    typeof env.version === 'number' && Number.isInteger(env.version) && env.version > 0
      ? env.version
      : base.version

  const flags = { ...base.flags }
  if (env.flags && typeof env.flags === 'object' && !Array.isArray(env.flags)) {
    for (const [k, v] of Object.entries(env.flags as Record<string, unknown>)) {
      if ((FLAG_KEYS as readonly string[]).includes(k) && typeof v === 'boolean') {
        flags[k as FlagKey] = v
      }
    }
  }

  const tuning = { ...base.tuning }
  if (env.tuning && typeof env.tuning === 'object' && !Array.isArray(env.tuning)) {
    for (const [k, v] of Object.entries(env.tuning as Record<string, unknown>)) {
      if (k in TUNING_SCALAR && isFiniteNumber(v)) {
        const [lo, hi] = TUNING_SCALAR[k]
        const c = clamp(v, lo, hi)
        ;(tuning as Record<string, unknown>)[k] = TUNING_FRACTIONAL.has(k)
          ? Math.round(c * 100) / 100
          : Math.round(c)
      } else if (
        k in TUNING_RANGE &&
        Array.isArray(v) &&
        v.length === 2 &&
        v.every(isFiniteNumber)
      ) {
        const [lo, hi] = TUNING_RANGE[k]
        const a = Math.round(clamp(v[0], lo, hi))
        const b = Math.round(clamp(v[1], lo, hi))
        ;(tuning as Record<string, unknown>)[k] = [Math.min(a, b), Math.max(a, b)]
      }
    }
  }

  const apply_selectors = mergeSelectorGroup(base.apply_selectors, env.apply_selectors, APPLY_SELECTOR_KEYS)
  const parse_selectors = mergeSelectorGroup(base.parse_selectors, env.parse_selectors, PARSE_SELECTOR_KEYS)
  const text_signals = mergeTextSignals(base.text_signals, env.text_signals)

  return { version, flags, tuning, apply_selectors, parse_selectors, text_signals, origin }
}

/** Оверлей CSS-селекторов площадок поверх базы: неизвестный ключ/площадка и не-CSS отбрасываются. */
function mergeSelectorGroup(
  base: Record<string, Record<string, string>>,
  incoming: unknown,
  allowedByPlatform: Record<string, readonly string[]>,
): Record<string, Record<string, string>> {
  const out: Record<string, Record<string, string>> = {}
  for (const platform of Object.keys(allowedByPlatform)) out[platform] = { ...(base[platform] || {}) }
  if (!incoming || typeof incoming !== 'object' || Array.isArray(incoming)) return out
  for (const [platform, group] of Object.entries(incoming as Record<string, unknown>)) {
    const allowed = allowedByPlatform[platform]
    if (!allowed || !group || typeof group !== 'object' || Array.isArray(group)) continue
    for (const [key, val] of Object.entries(group as Record<string, unknown>)) {
      if (allowed.includes(key) && typeof val === 'string' && isValidCssSelector(val)) {
        out[platform][key] = val.trim()
      }
    }
  }
  return out
}

/** Объединяет списки подстрок-сигналов с базой (не заменяет): plain-строки в нижнем регистре. */
function mergeTextSignals(
  base: Record<string, Record<string, string[]>>,
  incoming: unknown,
): Record<string, Record<string, string[]>> {
  const out: Record<string, Record<string, string[]>> = {}
  for (const platform of Object.keys(TEXT_SIGNAL_KEYS)) {
    out[platform] = {}
    for (const [k, v] of Object.entries(base[platform] || {})) out[platform][k] = [...v]
  }
  if (!incoming || typeof incoming !== 'object' || Array.isArray(incoming)) return out
  for (const [platform, group] of Object.entries(incoming as Record<string, unknown>)) {
    const allowed = TEXT_SIGNAL_KEYS[platform]
    if (!allowed || !group || typeof group !== 'object' || Array.isArray(group)) continue
    for (const [key, list] of Object.entries(group as Record<string, unknown>)) {
      if (!allowed.includes(key) || !Array.isArray(list)) continue
      const merged = [...(out[platform][key] || [])]
      for (const item of list.slice(0, TEXT_SIGNAL_MAX_ITEMS)) {
        if (typeof item !== 'string') continue
        const norm = item.replace(/\s+/g, ' ').trim().toLowerCase()
        if (norm.length < TEXT_SIGNAL_MIN_LEN || norm.length > TEXT_SIGNAL_MAX_LEN) continue
        if (!merged.includes(norm)) merged.push(norm)
      }
      out[platform][key] = merged.slice(0, TEXT_SIGNAL_MAX_ITEMS)
    }
  }
  return out
}

function buildFromRaw(
  raw: RawEnvelope,
  origin: ExtensionRuntimeConfig['origin'],
): ExtensionRuntimeConfig {
  const flags = {} as Record<FlagKey, boolean>
  const rawFlags = (raw.flags || {}) as Record<string, unknown>
  for (const key of FLAG_KEYS) flags[key] = rawFlags[key] !== false
  const rawTuning = (raw.tuning || {}) as Record<string, unknown>
  const tuning = {
    auto_apply_tick_minutes: Number(rawTuning.auto_apply_tick_minutes ?? 5),
    discovery_tick_minutes: Number(rawTuning.discovery_tick_minutes ?? 0.5),
    max_real_applications_per_tick: Number(rawTuning.max_real_applications_per_tick ?? 1),
    auto_apply_min_real_interval_ms: Number(rawTuning.auto_apply_min_real_interval_ms ?? 120_000),
    tab_load_timeout_ms: Number(rawTuning.tab_load_timeout_ms ?? 20_000),
    post_load_settle_ms: Number(rawTuning.post_load_settle_ms ?? 500),
    // 130с, а не 65: скоринг с фолбэком на резервную модель доезжает за ~90–120с (job_search
    // budget_ms=60000 + retries=1), а расширение до этого помечало вакансию parse_error, жгло
    // слот суточного лимита и ничего не показывало — владелец переоткрывал руками (2026-08-28).
    vacancy_ready_timeout_ms: Number(rawTuning.vacancy_ready_timeout_ms ?? 130_000),
    apply_confirm_timeout_ms: Number(rawTuning.apply_confirm_timeout_ms ?? 25_000),
    auto_apply_delay_ms: normPair(rawTuning.auto_apply_delay_ms, [120_000, 300_000]),
    apply_reading_delay_ms: normPair(rawTuning.apply_reading_delay_ms, [1_500, 4_000]),
    discovery_delay_ms: normPair(rawTuning.discovery_delay_ms, [30_000, 90_000]),
  }
  const rawApply = (raw.apply_selectors || {}) as Record<string, Record<string, string>>
  const apply_selectors: Record<string, Record<string, string>> = {}
  for (const p of Object.keys(APPLY_SELECTOR_KEYS)) apply_selectors[p] = { ...(rawApply[p] || {}) }
  const rawParse = (raw.parse_selectors || {}) as Record<string, Record<string, string>>
  const parse_selectors: Record<string, Record<string, string>> = {}
  for (const p of Object.keys(PARSE_SELECTOR_KEYS)) parse_selectors[p] = { ...(rawParse[p] || {}) }
  const rawSignals = (raw.text_signals || {}) as Record<string, Record<string, string[]>>
  const text_signals: Record<string, Record<string, string[]>> = {}
  for (const p of Object.keys(TEXT_SIGNAL_KEYS)) {
    text_signals[p] = {}
    for (const [k, v] of Object.entries(rawSignals[p] || {})) {
      text_signals[p][k] = (Array.isArray(v) ? v : []).map((s) => String(s).toLowerCase())
    }
  }
  return {
    version: Number(raw.version ?? 1),
    flags,
    tuning,
    apply_selectors,
    parse_selectors,
    text_signals,
    origin,
  }
}

function normPair(v: unknown, fallback: [number, number]): [number, number] {
  if (Array.isArray(v) && v.length === 2 && v.every(isFiniteNumber)) {
    return [Math.min(v[0], v[1]), Math.max(v[0], v[1])]
  }
  return fallback
}

// ── runtime pack (storage → память, сеть не блокирует) ─────────────────────────

export const RUNTIME_CONFIG_STORAGE_KEY = 'extensionRuntimeConfig'
export const RUNTIME_CONFIG_ETAG_KEY = 'extensionRuntimeConfigEtag'
const RUNTIME_CONFIG_PATH = '/api/opportunities/parser-config/extension'
const LOCAL_HTTP_HOSTS = new Set(['localhost', '127.0.0.1'])

let memoryConfig: ExtensionRuntimeConfig | null = null
let memoryEtag: string | null = null
let builtinCache: ExtensionRuntimeConfig | null = null
let storageWatchInstalled = false

function builtinConfig(): ExtensionRuntimeConfig {
  if (!builtinCache) builtinCache = parseRuntimeConfig(DEFAULT_RAW, 'builtin')
  return builtinCache
}

/** Синхронный доступ: сервер → storage → зашитый дефолт. Никогда null. */
export function getRuntimeConfig(): ExtensionRuntimeConfig {
  return memoryConfig ?? builtinConfig()
}

export function getFlag(key: FlagKey): boolean {
  return getRuntimeConfig().flags[key]
}

/** CSS-селектор разбора карточки вакансии из конфига; '' если площадки/ключа нет. */
export function getParseSelector(platform: string, key: string): string {
  return getRuntimeConfig().parse_selectors[platform]?.[key] ?? ''
}

/** true, если нормализованный текст содержит любую из подстрок-сигналов
 *  (`text_signals[platform][key]`). Пусто/нет ключа → false. */
export function matchesTextSignal(platform: string, key: string, text: string): boolean {
  const signals = getRuntimeConfig().text_signals[platform]?.[key]
  if (!signals || !signals.length) return false
  const hay = (text || '').replace(/\s+/g, ' ').toLowerCase()
  return signals.some((s) => hay.includes(s))
}

function isFetchAllowed(apiBaseUrl: string): boolean {
  if (!apiBaseUrl) return false
  try {
    const url = new URL(apiBaseUrl)
    if (url.protocol === 'https:') return true
    return url.protocol === 'http:' && LOCAL_HTTP_HOSTS.has(url.hostname.toLowerCase())
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

async function hydrateFromStorage(preferredOrigin?: ExtensionRuntimeConfig['origin']): Promise<void> {
  if (typeof chrome === 'undefined' || !chrome.storage?.local) return
  try {
    const stored = await chrome.storage.local.get([
      RUNTIME_CONFIG_STORAGE_KEY,
      RUNTIME_CONFIG_ETAG_KEY,
    ])
    const raw = stored[RUNTIME_CONFIG_STORAGE_KEY]
    if (raw === undefined || raw === null) return
    memoryConfig = parseRuntimeConfig(raw, preferredOrigin ?? 'storage')
    const etag = stored[RUNTIME_CONFIG_ETAG_KEY]
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
    if (area !== 'local' || !changes[RUNTIME_CONFIG_STORAGE_KEY]) return
    const next = changes[RUNTIME_CONFIG_STORAGE_KEY].newValue
    if (next === undefined) return
    memoryConfig = parseRuntimeConfig(next, 'server')
  })
}

/** Сеть: GET с If-None-Match, запись в storage. Звать из service worker.
 *  `onHttpError` — на не-ok ответ (напр. 401: токен протух): без него расширение молча
 *  продолжает жить на кэше/дефолте, включая аварийные kill-switch-флаги, и в логах пусто. */
export async function fetchRuntimeConfigFromApi(opts?: {
  force?: boolean
  onHttpError?: (status: number) => void
}): Promise<ExtensionRuntimeConfig> {
  if (!memoryConfig) await hydrateFromStorage()
  let cfg
  try {
    cfg = await loadConfig()
  } catch {
    return getRuntimeConfig()
  }
  if (!isFetchAllowed(cfg.apiBaseUrl) || !cfg.authToken) return getRuntimeConfig()

  const headers: Record<string, string> = {
    'X-Auth-Token': cfg.authToken,
    ...extensionVersionHeader(),
  }
  if (!opts?.force && memoryEtag) headers['If-None-Match'] = memoryEtag

  let response: Response
  try {
    response = await fetch(`${cfg.apiBaseUrl}${RUNTIME_CONFIG_PATH}`, { headers })
  } catch {
    return getRuntimeConfig()
  }
  if (response.status === 304) return getRuntimeConfig()
  if (!response.ok) {
    opts?.onHttpError?.(response.status)
    return getRuntimeConfig()
  }

  let raw: unknown
  try {
    raw = await response.json()
  } catch {
    return getRuntimeConfig()
  }

  const parsed = parseRuntimeConfig(raw, 'server')
  memoryConfig = parsed
  memoryEtag = response.headers.get('ETag')
  if (typeof chrome !== 'undefined' && chrome.storage?.local) {
    const toSet: Record<string, unknown> = { [RUNTIME_CONFIG_STORAGE_KEY]: raw }
    if (memoryEtag) toSet[RUNTIME_CONFIG_ETAG_KEY] = memoryEtag
    try {
      await chrome.storage.local.set(toSet)
    } catch {
      /* storage full / нет доступа — память всё равно обновлена */
    }
  }
  return parsed
}

/** Старт content-script: storage → память сразу + watch. Сеть тянет service worker. */
export async function initRuntimeConfig(): Promise<ExtensionRuntimeConfig> {
  await hydrateFromStorage()
  ensureStorageWatch()
  return getRuntimeConfig()
}

/** Сброс in-memory — только для unit-тестов. */
export function _resetRuntimeConfigForTests(): void {
  memoryConfig = null
  memoryEtag = null
  builtinCache = null
  storageWatchInstalled = false
}
