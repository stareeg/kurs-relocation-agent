"""Формы данных админ-консоли. Без I/O — и repo, и транспорт OpenAPI."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AdminError(Exception):
    """Ожидаемый отказ мутации (себе, не найден, пустой ключ)."""

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


class AdminPipelineBrief(BaseModel):
    """Компактный статус авто-процессов для строки таблицы «Люди»."""

    # platform -> "off" | "running" | "paused" | "idle"
    discovery: dict[str, str] = Field(default_factory=dict)
    # platform -> "off" | "live" | "stale" (stale = включено, но раннер молчит > 3 тиков)
    auto_apply: dict[str, str] = Field(default_factory=dict)
    viewed_24h: int = 0
    applied_24h: int = 0


class AdminUserRow(BaseModel):
    """Строка таблицы пользователей — то, что видно без клика."""

    account_id: int
    telegram_username: str | None = None
    telegram_user_id: int
    role: str
    status: str
    created_at: datetime | None = None
    last_seen_at: datetime | None = None
    last_seen_ip: str | None = None
    has_resume: bool = False
    has_openrouter_key: bool = False
    extension_confirmed: bool = False
    active_jobs: int = 0
    today_cost_usd: float = 0.0
    errors_24h: int = 0
    session_count: int = 0
    telegram_chat_id: int | None = None
    # Ключ OpenRouter: кто его поставил ('self' — сам человек, 'admin' — оператор), маска для
    # сверки с кабинетом OpenRouter, метка оператора и дата выдачи. Ключа нет → origin=None.
    key_origin: str | None = None
    key_hint: str = ""
    key_label: str | None = None
    key_issued_at: datetime | None = None
    # Когда ключ последний раз ставили или перевыпускали (`openrouter_account_keys.updated_at`).
    key_updated_at: datetime | None = None
    # Расход за 30 дней — «сколько человек жжёт», рядом с ключом, которым он это делает.
    month_cost_usd: float = 0.0
    month_tokens_in: int = 0
    month_tokens_out: int = 0
    # Календарный месяц — окно мягкого лимита (Этап 8.2). Не путать с month_cost_usd
    # (скользящие 30 дней): порог сравнивается с фактом месяца, как «за месяц» на Обзоре.
    spend_month_usd: float = 0.0
    spend_alert: bool = False
    # 14 точек спарклайна: старые слева, сегодня справа. Пустой список — расхода не было
    # или запрос серии не ответил (тогда фронт не рисует ложную плоскую линию).
    spend_14d: list[float] = Field(default_factory=list)
    # Заметка и причина отключения — только админ-витрина (миграция 0142).
    note: str | None = None
    disabled_at: datetime | None = None
    disabled_reason: str | None = None
    # Статус авто-процессов + счётчики за 24ч — цветные кольца площадок и колонки в таблице
    # «Люди» (см. AdminPipelineBrief). Заполняется отдельным батч-запросом, как spend_14d.
    pipeline: AdminPipelineBrief | None = None


class AdminPipelinePlatform(BaseModel):
    """Автопросмотр + автоотклик одной площадки в дровере пользователя (вкладка «Автоматизация»)."""

    platform: str
    # автопросмотр
    discovery_state: str = "idle"
    discovery_daily_cap: int = 0
    # Просмотрено за КАЛЕНДАРНЫЙ день (жёсткий суточный потолок, 2026-08-28) — против
    # `discovery_daily_cap`. `discovery_opened_session` — за текущую сессию, для истории.
    discovery_used_today: int = 0
    discovery_opened_session: int = 0
    discovery_search_urls: int = 0
    # автоотклик
    auto_apply_enabled: bool = False
    auto_apply_daily_cap: int = 0
    auto_apply_min_score: int = 0
    auto_apply_manual_band: int = 0
    auto_apply_dry_run: bool = False
    queue_auto: int = 0
    queue_manual: int = 0
    pending_confirm: int = 0
    applied_today: int = 0


class AdminUserPipeline(BaseModel):
    """Полная картина авто-процессов пользователя для операторского управления."""

    platforms: list[AdminPipelinePlatform] = Field(default_factory=list)
    discovery_last_tick_at: datetime | None = None
    auto_apply_last_tick_at: datetime | None = None
    auto_apply_next_tick_eta: datetime | None = None
    tick_seconds: int = 300
    discovery_tick_seconds: int = 60
    any_discovery_running: bool = False
    any_auto_apply_enabled: bool = False


class FunnelCounts(BaseModel):
    """Счётчики jobs по статусу (как есть в таблице, без колонок доски)."""

    counts: dict[str, int] = Field(default_factory=dict)


class AdminLogRow(BaseModel):
    """Строка журнала. Старые витрины (очередь внимания, карточка) id/fields не заполняют."""

    id: int | None = None
    ts: datetime | None = None
    level: str = ""
    logger: str = ""
    event: str = ""
    msg: str = ""
    account_id: int | None = None
    telegram_username: str | None = None
    telegram_user_id: int | None = None
    task_id: str | None = None
    fields: dict[str, Any] = Field(default_factory=dict)


class AdminTaskRow(BaseModel):
    id: int
    kind: str
    account_id: int | None = None
    last_error: str = ""
    finished_at: datetime | None = None


class AdminTaskDetail(BaseModel):
    """Строка очереди в разделе Система: payload, attempts, ошибка."""

    id: int
    kind: str
    account_id: int | None = None
    status: str
    payload: dict[str, Any] = Field(default_factory=dict)
    attempts: int = 0
    max_attempts: int = 3
    last_error: str = ""
    priority: int = 100
    idempotency_key: str | None = None
    run_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AdminTaskKindCount(BaseModel):
    kind: str
    pending: int = 0
    running: int = 0
    failed: int = 0
    done: int = 0
    cancelled: int = 0
    total: int = 0


class AdminTaskReasonCount(BaseModel):
    """Группа очереди: вид + статус + усечённая причина. `reason` = left(last_error, 120)."""

    kind: str
    status: str = ""
    reason: str = ""
    count: int = 0
    last_finished_at: datetime | None = None
    first_finished_at: datetime | None = None


class AdminTableSize(BaseModel):
    name: str
    bytes: int = 0
    approx_rows: int | None = None


class AdminCount(BaseModel):
    """Сколько строк затронула мутация (retry пачкой, reclaim, purge)."""

    n: int = 0


class AdminKeyRequest(BaseModel):
    id: int
    account_id: int
    telegram_username: str | None = None
    status: str
    requested_at: datetime | None = None
    note: str | None = None
    resolved_at: datetime | None = None
    resolved_by: int | None = None
    resolver_username: str | None = None


class AdminPartial(BaseModel):
    """Ответ мог собраться не полностью.

    Часть запросов не отдала данные: ноль и «не знаю» — разные состояния, и оператор должен
    их различать. Пустая витрина при лежащем Postgres не должна выглядеть как тихий флот.
    """

    degraded: bool = False
    degraded_reason: str = ""


class AdminHealthQueue(BaseModel):
    """Глубина очереди в разрезе статуса — факты, тон рисует фронт."""

    pending: int = 0
    running: int = 0
    failed: int = 0
    done: int = 0
    cancelled: int = 0


class AdminTasks(AdminPartial):
    """Витрина очереди: глубина по статусам, разрез по kind и причине, страница списка.

    Окно — последние 48 часов (`updated_at`). `reasons_total` — сколько групп без
    limit, чтобы фронт мог догружать «Ещё» без единовременной выгрузки всего.
    """

    by_status: AdminHealthQueue = Field(default_factory=AdminHealthQueue)
    by_kind: list[AdminTaskKindCount] = Field(default_factory=list)
    by_reason: list[AdminTaskReasonCount] = Field(default_factory=list)
    items: list[AdminTaskDetail] = Field(default_factory=list)
    total: int = 0
    reasons_total: int = 0


class AdminTables(AdminPartial):
    items: list[AdminTableSize] = Field(default_factory=list)
    database_bytes: int | None = None


class AdminHealth(BaseModel):
    """Здоровье установки (Этап 2.1). Факты, не вердикт: StatusDot считает фронт.

    Красная точка — сигнал «открой Действия» (Этап 7): очередь, версии, уборка.
    """

    extension_version: str = ""
    git_sha: str = ""
    postgres_ok: bool = False
    postgres_size_bytes: int | None = None
    worker_running: bool = False
    worker_last_finished_at: datetime | None = None
    queue: AdminHealthQueue = Field(default_factory=AdminHealthQueue)
    migrations_applied: int = 0
    migrations_available: int = 0
    model_tier_advanced: str = ""
    model_tier_basic: str = ""
    model_tier_reserve: str = ""


class AdminOnboardingFunnel(BaseModel):
    """Сколько активных дошли до ступени. Клик на фронте открывает застрявших."""

    telegram: int = 0
    has_key: int = 0
    has_resume: int = 0
    has_extension: int = 0


class AdminSummary(AdminPartial):
    """KPI-шапка + здоровье установки + воронка онбординга (Этапы 1.1 и 2).

    Правило витрины: каждое число считается тем же условием, что и список под ним
    (Этап 0). Счётчики — полные, списки в `/attention` урезаны `limit`; отсюда пары
    «всего ↔ показано», а не одно число на двоих.
    """

    accounts_active: int = 0
    seen_24h: int = 0
    # Расход за сегодня по всей таблице llm_usage — тем же условием, что `/spend`, иначе
    # столбик графика не сходится с числом над ним. `*_system` — часть без account_id
    # (market_snapshot_refresh / situation_refresh, миграция 0109): она и есть объяснение,
    # почему сумма по людям меньше общей.
    today_cost_usd: float = 0.0
    today_cost_system_usd: float = 0.0
    # Скользящие 30 дней (сегодня и 29 назад) — то же окно, что month_cost_usd у человека.
    month_cost_usd: float = 0.0
    errors_24h: int = 0
    errors_24h_system: int = 0
    pending_keys: int = 0
    failed_tasks: int = 0
    # Мягкий лимит на человека за календарный месяц. 0 = сигнал выключен (Этап 8.2).
    spend_alert_usd: float = 0.0
    health: AdminHealth = Field(default_factory=AdminHealth)
    onboarding: AdminOnboardingFunnel = Field(default_factory=AdminOnboardingFunnel)


class AdminPeoplePage(AdminPartial):
    """Страница списка людей. `total` — сколько подходит под фильтр, не сколько отдали."""

    items: list[AdminUserRow] = Field(default_factory=list)
    total: int = 0


class AdminStaleAccount(BaseModel):
    """«Отвалившийся»: резюме есть, а человек давно не заходил.

    `days_silent=None` — не заходил ни разу.
    """

    account_id: int
    telegram_username: str | None = None
    days_silent: int | None = None


class AdminErrorBurst(BaseModel):
    """Пачка свежих ошибок у одного человека (окно — час)."""

    account_id: int
    telegram_username: str | None = None
    count: int = 0


class AdminNoKeyWait(BaseModel):
    """Активный member без ключа, уже не первый день — кого пнуть выдачей."""

    account_id: int
    telegram_username: str | None = None
    days_waiting: int = 0


class AdminSpendOver(BaseModel):
    """Человек, у которого календарный месяц превысил мягкий порог (Этап 8.2)."""

    account_id: int
    telegram_username: str | None = None
    month_usd: float = 0.0


class AdminAttention(AdminPartial):
    """Очередь внимания: то, что требует решения оператора. Списки урезаны, счётчики полные."""

    key_requests: list[AdminKeyRequest] = Field(default_factory=list)
    failed_tasks: list[AdminTaskRow] = Field(default_factory=list)
    failed_tasks_total: int = 0
    errors: list[AdminLogRow] = Field(default_factory=list)
    errors_total: int = 0
    error_bursts: list[AdminErrorBurst] = Field(default_factory=list)
    stale: list[AdminStaleAccount] = Field(default_factory=list)
    no_key: list[AdminNoKeyWait] = Field(default_factory=list)
    spend_over: list[AdminSpendOver] = Field(default_factory=list)
    spend_alert_usd: float = 0.0


class AdminSpendSegment(BaseModel):
    """Кусок столбика «по дням»: доля одной модели в расходе дня."""

    key: str
    cost_usd: float = 0.0
    calls: int = 0


class AdminSpendRow(BaseModel):
    """Строка разреза расхода. `key` — день, модель, фича или человек, смотря по `group_by`."""

    key: str
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    calls: int = 0
    cache_hits: int = 0
    # None — в этой строке не было вызовов, «0%» врало бы как «кэш ничего не ловит».
    cache_hit_rate: float | None = None
    median_ms: float | None = None
    p95_ms: float | None = None
    retries: int = 0
    retry_share: float | None = None
    # Заполняется только в разрезе `day`: столбик складывается из моделей (как у OpenRouter).
    segments: list[AdminSpendSegment] = Field(default_factory=list)


class AdminSpend(AdminPartial):
    group_by: str = "day"
    days: int = 14
    rows: list[AdminSpendRow] = Field(default_factory=list)
    total_usd: float = 0.0
    # Сегодня и месяц — тем же условием, что KPI `/summary`, независимо от окна графика.
    today_usd: float = 0.0
    month_usd: float = 0.0
    # Линейная экстраполяция факта месяца на оставшиеся дни. Подпись на фронте — «прогноз».
    forecast_month_usd: float = 0.0
    cache_hits: int = 0
    cache_calls: int = 0
    # None — вызовов в окне не было, «0%» врало бы как «кэш ничего не ловит».
    cache_hit_rate: float | None = None
    median_ms: float | None = None
    p95_ms: float | None = None
    retries: int = 0
    retry_share: float | None = None


class AdminSpendAlert(BaseModel):
    """Мягкий порог расхода на человека за календарный месяц. 0 = сигнал выключен."""

    usd: float = 0.0


class AdminAccountSnapshot(BaseModel):
    """Снимок «почему у него не работает» — без psql (Этап 4.2)."""

    resume_updated_at: datetime | None = None
    resume_bytes: int | None = None
    search_title: str = ""
    search_grades: str = ""
    search_formats: str = ""
    extension_version: str = ""
    last_extension_at: datetime | None = None
    last_scored_at: datetime | None = None
    device_count: int = 0
    salary_min_override: int | None = None
    auto_apply: bool = False
    discovery: bool = False
    # Последний тик раннера расширения (heartbeat) — если автоотклики/автопросмотр включены, а
    # тут `None` или старая дата, значит SW расширения усыплён/не запущен (инцидент 2026-08-27..28).
    auto_apply_last_tick_at: datetime | None = None
    discovery_last_tick_at: datetime | None = None


class AdminTelegramSent(BaseModel):
    """Последние исходящие от имени «Администратор» — из журнала АДМИН, не из аудита Этапа 5."""

    ts: datetime | None = None
    preview: str = ""


class AdminDeviceSession(BaseModel):
    """Активная сессия входа человека — то же, что блок «Устройства» у него самого."""

    id: int
    issued_at: datetime | None = None
    login_ip: str | None = None
    login_user_agent: str | None = None


class AdminSupportMessage(BaseModel):
    """Реплика в ленте поддержки: канал user (Telegram) или agent (черновик с LLM)."""

    id: int
    channel: str
    role: str
    body: str
    reply_to_id: int | None = None
    created_at: datetime | None = None


class AdminSupportThread(AdminPartial):
    items: list[AdminSupportMessage] = Field(default_factory=list)


class AdminLogPage(AdminPartial):
    """Страница журнала. `next_cursor` пуст — старше в этом окне больше нет."""

    items: list[AdminLogRow] = Field(default_factory=list)
    next_cursor: str | None = None
    since: datetime | None = None
    until: datetime | None = None


class AdminAuditRow(BaseModel):
    """Строка реестра действий оператора (миграция 0144)."""

    id: int
    at: datetime | None = None
    actor_id: int
    actor_username: str | None = None
    action: str
    target_id: int | None = None
    target_username: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class AdminAuditPage(AdminPartial):
    items: list[AdminAuditRow] = Field(default_factory=list)
    next_cursor: str | None = None
    since: datetime | None = None
    until: datetime | None = None


class AdminRecentAction(BaseModel):
    """Краткое действие человека: раздел UI или LLM-фича."""

    at: datetime | None = None
    kind: str = ""
    label: str = ""


class AdminUserDetail(BaseModel):
    user: AdminUserRow
    funnel: FunnelCounts = Field(default_factory=FunnelCounts)
    today_cost_usd: float = 0.0
    month_cost_usd: float = 0.0
    month_tokens_in: int = 0
    month_tokens_out: int = 0
    recent_errors: list[AdminLogRow] = Field(default_factory=list)
    recent_actions: list[AdminRecentAction] = Field(default_factory=list)
    sessions: int = 0
    session_list: list[AdminDeviceSession] = Field(default_factory=list)
    snapshot: AdminAccountSnapshot = Field(default_factory=AdminAccountSnapshot)
    telegram_outbox: list[AdminTelegramSent] = Field(default_factory=list)


class AdminKeyVerify(BaseModel):
    """Проверка ключа перед выдачей. Сырого ключа в ответе нет."""

    alive: bool
    network_error: bool = False
    error: str = ""
    key_hint: str = ""
    label: str | None = None
    limit: float | None = None
    usage: float = 0.0
    limit_remaining: float | None = None
    is_free_tier: bool = False


class AdminKeyBalance(AdminKeyVerify):
    """Остаток по уже выданному origin=admin ключу."""

    account_id: int
    telegram_username: str | None = None


class AdminKeyBalances(BaseModel):
    items: list[AdminKeyBalance] = Field(default_factory=list)


class AdminKeyHistory(AdminPartial):
    """Закрытые заявки + строки аудита key_issue / key_revoke / key_reject."""

    items: list[AdminKeyRequest] = Field(default_factory=list)
    audit: list[AdminAuditRow] = Field(default_factory=list)


class AdminDiagnosisItem(BaseModel):
    """Одна проверка «почему у него не работает». Сырого ключа здесь нет."""

    id: str
    ok: bool
    title: str
    detail: str = ""
    action_label: str = ""
    action_kind: str = ""


class AdminDiagnosis(BaseModel):
    items: list[AdminDiagnosisItem] = Field(default_factory=list)
