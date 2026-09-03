/**
 * Состояние списка людей ⇄ query-параметры URL (Этап 1.2, принцип «состояние — в URL»).
 *
 * Сама фильтрация и сортировка живут на сервере (`GET /api/admin/people`): дублировать их на
 * клиенте значит держать две правды об одном списке. Здесь — только разбор и сборка адреса,
 * чтобы ссылка на «отключённые без ключа, по расходу» воспроизводила экран.
 *
 * Ключи совпадают с белым списком бэкенда (`core/platform/admin/service.py`): переименование
 * ключа ломает сохранённые ссылки, поэтому имена — часть контракта, а не деталь.
 */

export const ADMIN_SECTIONS = ["dashboard", "system", "journal"] as const
export type AdminSection = (typeof ADMIN_SECTIONS)[number]
export const DEFAULT_ADMIN_SECTION: AdminSection = "dashboard"

/**
 * Сегмент адреса карточки человека: `/admin/person/12`. Разделом не является — карточка
 * открывается дровером поверх Пульта, поэтому в сегменте раздела ей места нет (Этап 3).
 */
export const ADMIN_PERSON_SEGMENT = "person"

export const ADMIN_USER_TABS = ["profile", "automation", "spend", "logs"] as const
export type AdminUserTab = (typeof ADMIN_USER_TABS)[number]
export const DEFAULT_ADMIN_USER_TAB: AdminUserTab = "profile"

export const ADMIN_USER_TAB_LABELS: Record<AdminUserTab, string> = {
  profile: "Профиль",
  automation: "Автоматизация",
  spend: "Расход",
  logs: "Логи",
}

export const ADMIN_STATUSES = ["active", "disabled"] as const
export type AdminStatusFilter = (typeof ADMIN_STATUSES)[number] | ""

export const ADMIN_ONBOARDING = ["no_key", "no_resume", "no_extension", "done"] as const
export type AdminOnboardingFilter = (typeof ADMIN_ONBOARDING)[number] | ""

export const ADMIN_SIGNALS = ["errors", "stale", "spend"] as const
export type AdminSignalFilter = (typeof ADMIN_SIGNALS)[number] | ""

/**
 * Сегмент в поповере «Фильтры»: все / кому нужна помощь / отключённые.
 *
 * «Проблемные» — не статус бэкенда (ручка принимает только `active`/`disabled`), поэтому в URL
 * уходит отдельный `scope=problem`. Старые ссылки `?status=active` по-прежнему работают.
 */
export const ADMIN_PEOPLE_SCOPES = ["all", "problem", "disabled"] as const
export type AdminPeopleScope = (typeof ADMIN_PEOPLE_SCOPES)[number]
export type AdminPeopleScopeFilter = "problem" | ""

/** Колонки, по которым разрешено сортировать. Направление — префикс «-» (по убыванию). */
export const ADMIN_SORT_COLUMNS = [
  "last_seen",
  "created",
  "username",
  "jobs",
  "cost_today",
  "cost_month",
  "errors",
  "status",
] as const
export type AdminSortColumn = (typeof ADMIN_SORT_COLUMNS)[number]

/**
 * Колонки таблицы людей. `person` нельзя скрыть: без имени строка не читается.
 * Порядок массива — порядок колонок.
 */
export const PEOPLE_IDENTITY_COLUMN = "person"
export const PEOPLE_SURFACE_COLUMNS = [
  "key",
  "resume",
  "extension",
  "seen",
  "jobs",
  "cost_today",
  "cost_month",
  "errors",
] as const
export const PEOPLE_ALL_COLUMNS = [
  PEOPLE_IDENTITY_COLUMN,
  ...PEOPLE_SURFACE_COLUMNS,
] as const
export type PeopleColumnKey = (typeof PEOPLE_ALL_COLUMNS)[number]

export const PEOPLE_COLUMN_LABELS: Record<PeopleColumnKey, string> = {
  person: "Человек",
  key: "Ключ",
  resume: "Резюме",
  extension: "Расширение",
  seen: "Был",
  jobs: "Вакансии",
  cost_today: "Сегодня, $",
  cost_month: "30 дней, $",
  errors: "Ошибки",
}

export const DEFAULT_PEOPLE_COLS: readonly PeopleColumnKey[] = [
  PEOPLE_IDENTITY_COLUMN,
  ...PEOPLE_SURFACE_COLUMNS,
]

export type AdminFilters = {
  q: string
  status: AdminStatusFilter
  onboarding: AdminOnboardingFilter
  signal: AdminSignalFilter
  /** Пустая строка — порядок по умолчанию (сначала активные, недавно заходившие). */
  sort: string
  /** «Проблемные» в сегменте фильтров; в API не уходит. */
  scope: AdminPeopleScopeFilter
  /** Видимые колонки в каноническом порядке; `person` всегда первый. */
  cols: readonly PeopleColumnKey[]
}

export const DEFAULT_ADMIN_FILTERS: AdminFilters = {
  q: "",
  status: "",
  onboarding: "",
  signal: "",
  sort: "",
  scope: "",
  cols: DEFAULT_PEOPLE_COLS,
}

/** Сегмент в поповере фильтров. Значение «all» в URL не пишем — это отсутствие фильтра. */
export const PEOPLE_STATUS_CHIPS = [
  { value: "all", label: "Все" },
  { value: "problem", label: "Проблемные" },
  { value: "disabled", label: "Отключённые" },
] as const

export const PEOPLE_ONBOARDING_CHIPS = [
  { value: "no_key", label: "Без ключа" },
  { value: "no_resume", label: "Без резюме" },
  { value: "no_extension", label: "Без расширения" },
] as const

export const PEOPLE_SIGNAL_CHIPS = [
  { value: "errors", label: "Есть ошибки" },
  { value: "stale", label: "Молчат > 7 дней" },
  { value: "spend", label: "Превышен порог" },
] as const

/**
 * Чекбоксы в поповере «Фильтры». «Есть ошибки» ушло в сегмент «Проблемные»: иначе `signal`
 * спорил бы сам с собой — и «ошибки», и «молчат» живут в одном query-параметре.
 */
export const PEOPLE_FILTER_CHECKBOXES = [
  ...PEOPLE_ONBOARDING_CHIPS,
  ...PEOPLE_SIGNAL_CHIPS.filter((chip) => chip.value !== "errors"),
] as const

/** Числовые колонки, по которым клик в шапке меняет `?sort=`. */
export const PEOPLE_SORTABLE_COLUMNS = [
  "last_seen",
  "jobs",
  "cost_today",
  "cost_month",
  "errors",
] as const satisfies readonly AdminSortColumn[]

/** Порог «молчит», тот же, что у бэкенда (`interval '7 days'` в `load_people`). */
export const PEOPLE_STALE_MS = 7 * 24 * 60 * 60 * 1000

/**
 * Ниже этого размера флота чипы фильтров на экране не рисуем: на трёх строках восемь чипов
 * выглядят как дамп, а не как инструмент. Кнопка «Фильтры» остаётся.
 */
export const PEOPLE_FILTER_CHIPS_MIN = 9

export function statusFromChip(value: string): AdminStatusFilter {
  return ADMIN_STATUSES.includes(value as never) ? (value as AdminStatusFilter) : ""
}

export function statusChipValue(status: AdminStatusFilter): string {
  return status || "all"
}

export function peopleScopeFromFilters(filters: AdminFilters): AdminPeopleScope {
  if (filters.status === "disabled") return "disabled"
  if (filters.scope === "problem") return "problem"
  return "all"
}

/** Сегмент «Все · Проблемные · Отключённые» — взаимоисключающие, одно значение в URL. */
export function applyPeopleScope(filters: AdminFilters, scope: AdminPeopleScope): AdminFilters {
  if (scope === "disabled") return { ...filters, status: "disabled", scope: "" }
  if (scope === "problem") return { ...filters, status: "", scope: "problem" }
  return { ...filters, status: "", scope: "" }
}

/**
 * Что отправить в `GET /people` как `status`. «Проблемные» — активные с чем-то не так;
 * отключённые живут в соседнем сегменте, смешивать их нельзя.
 */
export function peopleApiStatus(filters: AdminFilters): AdminStatusFilter {
  if (filters.status) return filters.status
  if (filters.scope === "problem") return "active"
  return ""
}

export function isStalePerson(
  lastSeenAt: string | null | undefined,
  now: number = Date.now(),
): boolean {
  if (!lastSeenAt) return true
  const at = new Date(lastSeenAt).getTime()
  if (Number.isNaN(at)) return true
  return now - at > PEOPLE_STALE_MS
}

/** Человек, которому стоит посмотреть: нет ступени, ошибки, порог, молчит. */
export function isProblemPerson(
  user: {
    status?: string
    errors_24h: number
    spend_alert: boolean
    has_openrouter_key: boolean
    has_resume: boolean
    extension_confirmed: boolean
    last_seen_at?: string | null
  },
  now: number = Date.now(),
): boolean {
  if (user.status && user.status !== "active") return false
  if (user.errors_24h > 0) return true
  if (user.spend_alert) return true
  if (!user.has_openrouter_key) return true
  if (!user.has_resume) return true
  if (!user.extension_confirmed) return true
  return isStalePerson(user.last_seen_at, now)
}

export function isAdminSection(value: string | undefined): value is AdminSection {
  return ADMIN_SECTIONS.includes((value ?? "") as AdminSection)
}

export function resolveAdminSection(value: string | undefined): AdminSection {
  return isAdminSection(value) ? value : DEFAULT_ADMIN_SECTION
}

/** `?a=b` из любого вида строки запроса; пустая строка — без «?», чтобы адрес не обрастал. */
function searchSuffix(search: string): string {
  const value = search.startsWith("?") ? search.slice(1) : search
  return value ? `?${value}` : ""
}

/** Канонический адрес раздела. Пульт — это голый `/admin`, а не `/admin/dashboard`. */
export function adminSectionPath(section: AdminSection): string {
  return section === DEFAULT_ADMIN_SECTION ? "/admin" : `/admin/${section}`
}

/** Адрес карточки человека. Под ней всегда Пульт — оттуда её и открывают. */
export function adminPersonPath(accountId: number, search = ""): string {
  return `/admin/${ADMIN_PERSON_SEGMENT}/${accountId}${searchSuffix(search)}`
}

/** id человека из адреса. Мусор вместо числа — как будто карточка не открыта. */
export function parseAdminAccountId(value: string | undefined): number | null {
  const id = Number(value)
  return Number.isSafeInteger(id) && id > 0 ? id : null
}

/**
 * Куда вести со старого адреса; `null` — адрес уже канонический (Этап 3).
 *
 * Пять вкладок стали тремя, а карточка человека — своим адресом, и ссылки на `/admin/overview`,
 * `/admin/people?status=disabled`, `/admin/keys` уже разосланы и лежат в закладках. Молчаливый
 * 404 на них читался бы как «раздел удалили», поэтому старый адрес приводится к новому вместе
 * с фильтрами: `/admin/people?status=disabled` → `/admin?status=disabled`.
 */
export function adminRedirectPath(
  segment: string | undefined,
  accountId: string | undefined,
  search = "",
): string | null {
  const suffix = searchSuffix(search)
  const person = parseAdminAccountId(accountId)

  if (segment === ADMIN_PERSON_SEGMENT) {
    // `/admin/person/abc` — вместо пустого дровера показываем Пульт.
    return person == null ? `/admin${suffix}` : null
  }
  // Старый адрес карточки: `/admin/people/12`, `/admin/keys/12`, `/admin/journal/12`.
  if (person != null) return adminPersonPath(person, suffix)
  if (segment === undefined) return null
  if (isAdminSection(segment) && segment !== DEFAULT_ADMIN_SECTION) return null
  return `${adminSectionPath(resolveAdminSection(segment))}${suffix}`
}

export function isAdminUserTab(value: string | null | undefined): value is AdminUserTab {
  return ADMIN_USER_TABS.includes((value ?? "") as AdminUserTab)
}

export function parseAdminUserTab(params: URLSearchParams): AdminUserTab {
  const tab = params.get("tab")
  // Старые ссылки `?tab=actions`: действия переехали в Профиль.
  if (tab === "actions") return DEFAULT_ADMIN_USER_TAB
  return isAdminUserTab(tab) ? tab : DEFAULT_ADMIN_USER_TAB
}

/** Сборка query с фильтрами людей, не затирая `tab` карточки (Этап 4.1). */
export function withPreservedTab(params: URLSearchParams, current: URLSearchParams): URLSearchParams {
  const tab = current.get("tab")
  if (isAdminUserTab(tab) && tab !== DEFAULT_ADMIN_USER_TAB) params.set("tab", tab)
  return params
}

/** Валиден ли ключ сортировки вместе с направлением (`cost_month` / `-cost_month`). */
export function isAdminSortKey(value: string): boolean {
  const column = value.startsWith("-") ? value.slice(1) : value
  return ADMIN_SORT_COLUMNS.includes(column as AdminSortColumn)
}

/**
 * Разбор адреса. Незнакомое значение — как будто фильтра нет: ссылка из старой версии обязана
 * открыть список, а не пустой экран с ошибкой.
 */
export function parseAdminFilters(params: URLSearchParams): AdminFilters {
  const statusRaw = params.get("status") ?? ""
  const status = ADMIN_STATUSES.includes(statusRaw as never) ? (statusRaw as AdminStatusFilter) : ""
  const onboarding = params.get("onboarding") ?? ""
  const signal = params.get("signal") ?? ""
  const sort = params.get("sort") ?? ""
  const scope = params.get("scope") ?? ""
  return {
    q: (params.get("q") ?? "").trim(),
    status,
    onboarding: ADMIN_ONBOARDING.includes(onboarding as never)
      ? (onboarding as AdminOnboardingFilter)
      : "",
    signal: ADMIN_SIGNALS.includes(signal as never) ? (signal as AdminSignalFilter) : "",
    sort: isAdminSortKey(sort) ? sort : "",
    scope: status === "disabled" ? "" : scope === "problem" ? "problem" : "",
    cols: parsePeopleCols(params.get("cols")),
  }
}

/** Сборка адреса: значения по умолчанию в query не пишем, иначе ссылка обрастает мусором. */
export function adminFiltersToParams(filters: AdminFilters): URLSearchParams {
  const params = new URLSearchParams()
  if (filters.q.trim()) params.set("q", filters.q.trim())
  if (filters.status) params.set("status", filters.status)
  if (filters.onboarding) params.set("onboarding", filters.onboarding)
  if (filters.signal) params.set("signal", filters.signal)
  if (filters.sort) params.set("sort", filters.sort)
  if (filters.scope) params.set("scope", filters.scope)
  const cols = canonicalizePeopleCols(filters.cols)
  if (!samePeopleCols(cols, DEFAULT_PEOPLE_COLS)) params.set("cols", cols.join(","))
  return params
}

export function adminFiltersActive(filters: AdminFilters): boolean {
  return adminPeopleFilterCount(filters) > 0 || Boolean(filters.q.trim())
}

/**
 * Сколько фильтров нажато в поповере. Поиск и сортировка не входят: поиск виден в поле,
 * сортировка ничего не прячет. Колонки — про вид таблицы, не про состав списка.
 */
export function adminPeopleFilterCount(filters: AdminFilters): number {
  return (
    (filters.status ? 1 : 0) +
    (filters.scope ? 1 : 0) +
    (filters.onboarding ? 1 : 0) +
    (filters.signal ? 1 : 0)
  )
}

/** Сброс поповера: список и вид таблицы остаются, прячутся только ограничения выборки. */
export function resetAdminPeopleFilters(filters: AdminFilters): AdminFilters {
  return {
    ...DEFAULT_ADMIN_FILTERS,
    q: filters.q,
    sort: filters.sort,
    cols: filters.cols,
  }
}

export function isPeopleColumnKey(value: string): value is PeopleColumnKey {
  return PEOPLE_ALL_COLUMNS.includes(value as PeopleColumnKey)
}

export function canonicalizePeopleCols(
  keys: readonly string[] | undefined,
): PeopleColumnKey[] {
  const set = new Set<PeopleColumnKey>()
  set.add(PEOPLE_IDENTITY_COLUMN)
  for (const key of keys ?? []) {
    if (isPeopleColumnKey(key)) set.add(key)
  }
  return PEOPLE_ALL_COLUMNS.filter((key) => set.has(key))
}

export function parsePeopleCols(raw: string | null): PeopleColumnKey[] {
  if (raw == null || raw.trim() === "") return [...DEFAULT_PEOPLE_COLS]
  return canonicalizePeopleCols(raw.split(",").map((key) => key.trim()))
}

export function samePeopleCols(
  left: readonly string[],
  right: readonly string[],
): boolean {
  return left.length === right.length && left.every((key, index) => key === right[index])
}

/** Чекбокс колонки: `person` снять нельзя. Порядок всегда канонический. */
export function togglePeopleCol(
  cols: readonly string[],
  key: PeopleColumnKey,
): PeopleColumnKey[] {
  if (key === PEOPLE_IDENTITY_COLUMN) return canonicalizePeopleCols(cols)
  const set = new Set(canonicalizePeopleCols(cols))
  if (set.has(key)) set.delete(key)
  else set.add(key)
  return canonicalizePeopleCols([...set])
}

/** Чекбокс в поповере: повторный клик снимает, соседний в той же оси заменяет. */
export function toggleExclusive<T extends string>(current: T | "", next: T): T | "" {
  return current === next ? "" : next
}

/**
 * Адрес списка людей с фильтрами — с Этапа 3 это блок «Люди» на Пульте, то есть `/admin`.
 * Клик по ступени подключения обязан попадать сюда, а не фильтровать список на месте:
 * иначе ссылка не воспроизводит экран.
 */
export function adminPeoplePath(filters: Partial<AdminFilters> = {}): string {
  const params = adminFiltersToParams({ ...DEFAULT_ADMIN_FILTERS, ...filters })
  return `/admin${searchSuffix(params.toString())}`
}

/**
 * Ступени подключения: число — сколько дошли, клик открывает тех, кто застрял.
 *
 * Подпись согласована с числом («3 с ключом»), а не названа существительным («Ключ»): с Этапа 3
 * ступени живут одной строкой в шапке блока «Люди», а не четырьмя плитками с полосками
 * прогресса — разницу между 3 и 2 в полоске не видно, а число стоит рядом.
 */
export const ONBOARDING_FUNNEL_STEPS = [
  {
    key: "telegram",
    label: "в Telegram",
    countKey: "telegram",
    stuck: "" as AdminOnboardingFilter,
  },
  { key: "key", label: "с ключом", countKey: "has_key", stuck: "no_key" as AdminOnboardingFilter },
  {
    key: "resume",
    label: "с резюме",
    countKey: "has_resume",
    stuck: "no_resume" as AdminOnboardingFilter,
  },
  {
    key: "extension",
    label: "с расширением",
    countKey: "has_extension",
    stuck: "no_extension" as AdminOnboardingFilter,
  },
] as const

/**
 * Клик по заголовку колонки: первый раз — по убыванию (интересное сверху), второй — по
 * возрастанию, третий — снимает сортировку. Текст — не число, ему естественнее начинать с «А».
 */
export function toggleAdminSort(current: string, column: AdminSortColumn): string {
  const startsAscending = column === "username" || column === "status"
  const first = startsAscending ? column : `-${column}`
  const second = startsAscending ? `-${column}` : column
  if (current === first) return second
  if (current === second) return ""
  return first
}

/** Направление стрелки в заголовке: null — по этой колонке сейчас не сортируем. */
export function adminSortDirection(
  current: string,
  column: AdminSortColumn,
): "asc" | "desc" | null {
  if (current === column) return "asc"
  if (current === `-${column}`) return "desc"
  return null
}
