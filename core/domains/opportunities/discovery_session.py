"""Сессия фонового авто-открытия вакансий (discovery) — конфиг + живой статус.

Отдельно от `discovery.py` (тот — чистый HTTP-парсинг SERP hh.ru, без состояния) намеренно:
здесь — то, чем управляет владелец из «Расширения» (какой search-URL смотреть, темп) и что
видит в реальном времени (сколько открыто/оценено, лог решений). Механика открытия вкладок и
парсинга карточек листинга живёт в расширении (`extension/src/background/discovery-runner.ts`)
— этот модуль только хранит конфиг/статус и решает, к какой корзине (auto/manual_review/
excluded) отнести только что проскоренную вакансию, переиспользуя ЖИВУЮ очередь автооткликов
(`pipeline.auto_apply.preview_queue`) — без дублирования гейт-логики.

Реальная отправка отклика этим модулем не занимается вообще — discovery только копит
«Просмотрено», дальше решает уже существующая очередь автооткликов.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from core.domains.opportunities.jobs import get_job_by_vacancy_id, get_jobs_by_vacancy_ids
from core.domains.opportunities.skipped import get_skipped_ids
from core.domains.pipeline.auto_apply import preview_queue
from core.kernel.errors import InvalidInput
from core.platform.db.pool import Executor
from core.platform.observability import event
from core.platform.repo.settings import (
    get_runner_tick,
    get_setting,
    record_runner_tick,
    set_setting,
    should_log_runner_tick,
)

logger = logging.getLogger(__name__)

KEY_RUNNER_TICK = "discovery_runner_tick"

KEY_DISCOVERY_CONFIG = "discovery_config"
KEY_DISCOVERY_RUNTIME = "discovery_runtime_state"

# Ключ-сосед `raw[platform]` в jsonb `discovery_runtime_state`: счётчик просмотренных вакансий
# за КАЛЕНДАРНЫЙ день на площадку. Отдельно от per-сессионного `status.opened` (тот обнуляется
# на каждом «Начать») — чтобы «запустить новую очередь» нельзя было спамить бесконечно
# (owner's spec 2026-08-28). Переживает `start_session` (тот трогает только `raw[platform]`).
_KEY_DAILY_COUNTS = "daily_counts"

DiscoveryPlatform = Literal["hh", "getmatch", "habr"]

# Жёсткий потолок автопросмотра на площадку в календарные сутки — НЕ ручка пользователя
# (слайдер «Лимит за очередь» убран), защита от бесконтрольного LLM-расхода. Каждое открытие
# вакансии = вызов скоринга через OpenRouter. hh отдаёт заметно больше вакансий, чем
# getmatch/habr.
DISCOVERY_DAILY_HARD_CAP: dict[str, int] = {"hh": 200, "getmatch": 60, "habr": 60}

# Столько `parse_error` подряд (без ни одного успешного скора между ними) = площадка сломалась
# (редизайн вёрстки / капча-стена / рейт-лимит), а не «одна вакансия нечитаема» — дальше
# открывать вкладки бессмысленно, встаём на паузу (`report_tick`).
_PARSE_ERROR_BREAKER = 6


def discovery_daily_hard_cap(platform: str) -> int:
    """Потолок просмотренных вакансий площадки за сутки. Неизвестная площадка → консервативно."""
    return DISCOVERY_DAILY_HARD_CAP.get(platform, 60)


DiscoveryState = Literal[
    "idle",
    "running",
    "paused_by_user",
    "paused_daily_cap",
    "paused_pages_exhausted",
    "paused_suspected_block",
]
DiscoveryPauseReason = Literal["user", "daily_cap", "pages_exhausted", "suspected_block"]
DiscoveryOutcome = Literal["scored", "already_known", "parse_error"]

# Правка 2026-08-19: раньше 20 — лог обрезался задолго до того, как раннер реально останавливался
# (daily_cap до 300), счётчик «Просмотрено» в шапке при этом продолжал расти — выглядело как
# нерабочий лимит. Верхняя граница держит jsonb в разумных пределах на весь daily_cap площадки.
_MAX_EVENTS = 300
_STATE_BY_REASON: dict[DiscoveryPauseReason, DiscoveryState] = {
    "user": "paused_by_user",
    "daily_cap": "paused_daily_cap",
    "pages_exhausted": "paused_pages_exhausted",
    "suspected_block": "paused_suspected_block",
}
# Правка 2026-08-20 (пункт 8): текст маркера-разделителя в логе «Просмотра» на момент паузы —
# см. `_set_state(boundary_label=...)`.
_PAUSE_BOUNDARY_LABEL: dict[DiscoveryPauseReason, str] = {
    "user": "Очередь поставлена на паузу",
    "daily_cap": "Дневной лимит автопросмотра исчерпан",
    "pages_exhausted": "Выдача просмотрена — очередь на паузе",
    "suspected_block": "Похоже на блокировку площадки — очередь на паузе",
}


class DiscoveryPlatformConfig(BaseModel):
    """Настройки discovery одной площадки — независимая ручка, как у автооткликов."""

    model_config = ConfigDict(extra="ignore")

    enabled: bool = False
    # Сырые search-URL (hh.ru поиск / getmatch.ru каталог) — раннер обходит их по кругу за сессию
    # (Этап 5 редизайна «Расширения»: один и тот же сохранённый поиск даёт одни и те же
    # «рекомендованные», несколько поисков — разные выдачи). Без отдельной CRUD-фичи пресетов —
    # просто список строк. Пустые/whitespace-only элементы допустимы в хранилище (фронт их не
    # чистит на каждый кейстрок — см. `PlatformPipelineSection.tsx`), фильтруются потребителями
    # (`start_session` ниже, расширение).
    search_urls: list[str] = Field(default_factory=list)
    # 2026-08-28 (owner's spec): строго последовательный просмотр — одна вкладка за тик,
    # не пара. Раннер жёстко берёт 1 (`discovery-runner.ts::createRealDeps`), поле оставлено
    # для совместимости со старыми сохранёнными конфигами.
    batch_size: int = Field(default=1, ge=1, le=3)
    # Legacy: раньше «Лимит за очередь» с ползунком в UI. Заменён жёстким суточным потолком
    # `discovery_daily_hard_cap` (не ручка пользователя). Поле не читается ни раннером, ни
    # гейтом — оставлено для совместимости с сохранёнными конфигами.
    daily_cap: int = Field(default=60, ge=0, le=300)
    # Поле больше не выведено на фронт (Этап 3 редизайна «Расширения» — плавающее числовое поле
    # без ощущения прогресса убрано с экрана), но раннер всё ещё его использует — дефолт чуть
    # выше прежнего (10 → 15), чтобы одна сессия не упиралась в предел раньше реальных причин
    # паузы (нехватка буфера/бан площадки).
    max_pages_per_session: int = Field(default=15, ge=1, le=50)


class DiscoveryConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    hh: DiscoveryPlatformConfig = Field(default_factory=DiscoveryPlatformConfig)
    getmatch: DiscoveryPlatformConfig = Field(default_factory=DiscoveryPlatformConfig)
    habr: DiscoveryPlatformConfig = Field(default_factory=DiscoveryPlatformConfig)

    def platform(self, name: DiscoveryPlatform) -> DiscoveryPlatformConfig:
        return getattr(self, name)


DEFAULT_DISCOVERY_CONFIG = DiscoveryConfig()


def default_discovery_config_dict() -> dict[str, Any]:
    return DEFAULT_DISCOVERY_CONFIG.model_dump()


def _migrate_platform_config_dict(raw: Any) -> Any:
    """Этап 5 редизайна «Расширения»: старый `search_url: str | None` → новый `search_urls:
    list[str]`. Без отдельной SQL-миграции — `discovery_config` живёт в `app_settings` jsonb,
    конвертация на чтении. `search_urls`, если уже есть в сохранённых данных, не трогаем —
    старое поле только досыпает в пустой список, никогда не перезаписывает новый формат."""
    if not isinstance(raw, dict):
        return raw
    old_url = raw.get("search_url")
    if raw.get("search_urls") or not old_url:
        return raw
    return {**raw, "search_urls": [old_url]}


def discovery_config_from_mapping(raw: Any) -> DiscoveryConfig:
    if not isinstance(raw, dict):
        return DiscoveryConfig()
    try:
        migrated = {
            **raw,
            **{
                platform: _migrate_platform_config_dict(raw[platform])
                for platform in ("hh", "getmatch")
                if platform in raw
            },
        }
        return DiscoveryConfig.model_validate(migrated)
    except Exception:
        logger.debug("discovery_config: некорректные данные, использую дефолты: %r", raw)
        return DiscoveryConfig()


async def get_discovery_config(
    *, account_id: int | None, db: Executor | None = None
) -> DiscoveryConfig:
    raw = await get_setting(KEY_DISCOVERY_CONFIG, default=None, account_id=account_id, db=db)
    return discovery_config_from_mapping(raw)


async def set_discovery_config(
    config: DiscoveryConfig, *, account_id: int | None, db: Executor | None = None
) -> None:
    await set_setting(KEY_DISCOVERY_CONFIG, config.model_dump(), account_id=account_id, db=db)


DiscoveryEventBucket = Literal[
    "queued_auto",
    "queued_manual",
    "excluded",
    "already_known",
    "parse_error",
    # Правка 2026-08-20 (пункт 8): не решение по вакансии, а разделитель в логе «Просмотра» —
    # момент старта новой очереди/паузы. `vacancy_id` для таких строк — пустая строка, `title`/
    # `company`/`overall_score`/`job_id` — None; фронт рендерит их отдельной строкой-разделителем,
    # не обычной строкой вакансии.
    "session_boundary",
]


class DiscoveryEvent(BaseModel):
    """Одна строка лога решений — детерминированный шаблон, без LLM-генерации подписи.

    `bucket` — машиночитаемый исход (для тона/иконки на фронте), `label` — уже готовый текст
    того же решения; фронт не обязан парсить `label`, чтобы понять, что за исход.
    """

    ts: str
    vacancy_id: str
    title: str | None = None
    company: str | None = None
    label: str
    bucket: DiscoveryEventBucket
    overall_score: int | None = None
    # Фаза E (редизайна «Расширения»): квик-экшены в строке лога («Пропустить»/«В Отклик»)
    # нужен job_id, а не только vacancy_id — та же вакансия, что уже загружена ниже в report_tick.
    job_id: int | None = None
    # Правка 2026-08-20 (кнопки решения на уже известных вакансиях): АКТУАЛЬНЫЙ статус воронки
    # + флаг пропуска — подмешиваются live в `get_discovery_status` (см. `_attach_live_job_state`),
    # не персистятся вместе с событием. Нужны фронту, чтобы не показывать Автоотклик/Вручную/
    # Пропуск поверх вакансии, которая уже продвинулась по воронке (Скрининг/Техничка/Финал/
    # Оффер) или уже пропущена — раньше кнопки жили только по факту обнаружения и вводили в
    # заблуждение, а «Пропуск» на такой строке реально ломал этап воронки (`skip_job` не смотрит
    # на текущий status).
    job_status: str | None = None
    job_skipped: bool = False


class DiscoveryStatus(BaseModel):
    """Живой статус сессии одной площадки — jsonb в app_settings, без персиста истории."""

    model_config = ConfigDict(extra="ignore")

    platform: DiscoveryPlatform
    state: DiscoveryState = "idle"
    opened: int = 0
    scored: int = 0
    already_known: int = 0
    parse_error: int = 0
    queued_auto: int = 0
    queued_manual: int = 0
    excluded: int = 0
    session_started_at: str | None = None
    updated_at: str | None = None
    # Сколько `parse_error` подряд (без единого `scored`/`already_known` между ними) — сигнал
    # «парсер вакансий сломан / площадка режет», а не «одна вакансия нечитаема». На пороге
    # `_PARSE_ERROR_BREAKER` площадка встаёт на паузу, не выжигая весь суточный потолок битыми
    # вкладками. Сбрасывается любым не-parse_error исходом.
    consecutive_parse_errors: int = 0
    events: list[DiscoveryEvent] = Field(default_factory=list)
    # Этап 4 редизайна «Расширения» (plans/extension_pipeline_redesign_2026_08_18.md) — сколько
    # страниц листинга уже открыто за текущий проход, прокидывается расширением на каждом тике
    # (discovery-runner.ts::DiscoveryCursor.pagesVisited) — для подписи «страница N» в UI рядом
    # с прогресс-баром просмотра, живой факт продвижения по страницам, не только по логам.
    pages_visited: int = 0
    # Жёсткий суточный потолок площадки (`discovery_daily_hard_cap`) и сколько уже просмотрено
    # за КАЛЕНДАРНЫЙ день (не за сессию — `opened` выше обнуляется на «Начать»). Подмешиваются
    # на чтении из `raw[_KEY_DAILY_COUNTS]`, не персистятся в снимке площадки как правда.
    daily_cap: int = 0
    daily_used: int = 0


async def _load_runtime_raw(*, account_id: int | None, db: Executor | None) -> dict[str, Any]:
    raw = await get_setting(KEY_DISCOVERY_RUNTIME, default=None, account_id=account_id, db=db)
    return dict(raw) if isinstance(raw, dict) else {}


async def _save_runtime_raw(
    raw: dict[str, Any], *, account_id: int | None, db: Executor | None
) -> None:
    await set_setting(KEY_DISCOVERY_RUNTIME, raw, account_id=account_id, db=db)


def _daily_count_today(raw: dict[str, Any], platform: str) -> int:
    """Сколько вакансий площадки просмотрено за СЕГОДНЯ (по дате в `raw[_KEY_DAILY_COUNTS]`).
    Запись за другой день = 0 (новые сутки — свежий бюджет)."""
    counts = raw.get(_KEY_DAILY_COUNTS)
    entry = counts.get(platform) if isinstance(counts, dict) else None
    if not isinstance(entry, dict) or entry.get("date") != datetime.now(UTC).date().isoformat():
        return 0
    value = entry.get("count")
    return int(value) if isinstance(value, int) and value >= 0 else 0


def _bump_daily_count(raw: dict[str, Any], platform: str, *, by: int = 1) -> int:
    """Изменить суточный счётчик площадки на `by` (мутирует `raw`), вернуть новое значение.
    `by` может быть отрицательным (возврат слота при долечивании parse_error→scored) — итог
    зажат снизу нулём. Сбрасывает счётчик, если последняя запись за прошлый день."""
    today = datetime.now(UTC).date().isoformat()
    counts = raw.get(_KEY_DAILY_COUNTS)
    if not isinstance(counts, dict):
        counts = {}
        raw[_KEY_DAILY_COUNTS] = counts
    current = _daily_count_today(raw, platform)
    new_value = max(0, current + by)
    counts[platform] = {"date": today, "count": new_value}
    return new_value


def _attach_daily(status: DiscoveryStatus, raw: dict[str, Any]) -> DiscoveryStatus:
    status.daily_cap = discovery_daily_hard_cap(status.platform)
    status.daily_used = _daily_count_today(raw, status.platform)
    return status


def _status_from_raw(platform: DiscoveryPlatform, raw: dict[str, Any]) -> DiscoveryStatus:
    entry = raw.get(platform)
    if not isinstance(entry, dict):
        return _attach_daily(DiscoveryStatus(platform=platform), raw)
    try:
        status = DiscoveryStatus.model_validate({**entry, "platform": platform})
    except Exception:  # noqa: BLE001 — битый снимок не должен ронять статус
        logger.debug("discovery_runtime_state: некорректный снимок %s: %r", platform, entry)
        status = DiscoveryStatus(platform=platform)
    return _attach_daily(status, raw)


# Правка 2026-08-19 (пост-инцидент): без бюджета `_heal_stale_scores` уходила в БД на КАЖДОЕ
# событие без балла на КАЖДЫЙ опрос статуса (веб дергает его раз в 2.5с, пока сессия running) —
# при _MAX_EVENTS=300 и накопившемся хвосте «не удалось оценить» это сотни последовательных
# запросов в Postgres на один HTTP-запрос. Бюджет режет это до разумного числа за тик; события,
# что не влезли, долечатся следующим опросом (уже вылеченные выше пропускаются мгновенно —
# `overall_score is not None`, так что бюджет естественно продвигается по хвосту, а не топчется).
_HEAL_LOOKUP_BUDGET = 20


async def _classify_scored_bucket(
    platform: DiscoveryPlatform, vacancy_id: str, score: int, *, account_id: int
) -> tuple[DiscoveryEventBucket, str]:
    """Куда девать успешно проскоренную вакансию — auto/manual/excluded по ЖИВОЙ очереди
    автооткликов. Общая логика для `report_tick` (сразу на тике) и `_heal_stale_scores`
    (задним числом, для события, которое раньше записалось как `parse_error`/без балла)."""
    preview = await preview_queue(platform, account_id=account_id)
    if any(j.vacancy_id == vacancy_id for j in preview.auto):
        return "queued_auto", f"{score} баллов → в очередь автооткликов"
    if any(j.vacancy_id == vacancy_id for j in preview.manual_review):
        return "queued_manual", f"{score} баллов → на ручной разбор"
    return "excluded", f"{score} баллов → пропущено"


async def _heal_stale_scores(
    status: DiscoveryStatus, *, account_id: int, db: Executor | None
) -> bool:
    """Правка 2026-08-19 (баг 5): вакансия могла не заскориться в момент тика (LLM-сбой,
    таймаут) — владелец открывает её вручную, скор считается — но строка лога так и оставалась
    навсегда «не удалось оценить», хотя в системе уже есть хороший скор. Подтягиваем актуальный
    job по каждому событию без балла и чиним запись на месте — тот же приём, что уже завёл для
    «already_known» в `report_tick`, просто догоняет события, записанные до вакансии/до фикса.

    Правка 2026-08-20: `parse_error` больше не исключение из починки. Реальная причина этой
    корзины почти всегда не «вакансия нечитаема», а то, что расширение переставало ждать скора
    (`waitForVacancyReady` в extension/src/content/main.ts) РАНЬШЕ, чем бэк успевал доскорить —
    job_search может занимать до 60с (budget_ms), старый клиентский таймаут ждал только 20с.
    Вакансия при этом читается и скорится нормально, просто чуть позже, чем расширение готово
    ждать — а строка лога навсегда застревала как «Ошибка чтения», хотя job со скором уже есть
    в БД. Задним числом пересчитываем настоящую корзину (auto/manual/excluded) той же логикой,
    что и живой тик, и поправляем счётчики карточки — иначе «Пропущено» продолжало бы считать
    уже не пропущенную вакансию."""
    changed = False
    lookups = 0
    for evt in status.events:
        if evt.bucket == "session_boundary":
            continue
        if evt.overall_score is not None and evt.bucket != "parse_error":
            continue
        if lookups >= _HEAL_LOOKUP_BUDGET:
            break
        lookups += 1
        job = await get_job_by_vacancy_id(evt.vacancy_id, account_id=account_id, db=db)
        if job is None or job.overall_score is None:
            continue
        evt.overall_score = job.overall_score
        evt.job_id = job.id
        if evt.bucket == "parse_error":
            status.parse_error = max(0, status.parse_error - 1)
            new_bucket, evt.label = await _classify_scored_bucket(
                status.platform, evt.vacancy_id, job.overall_score, account_id=account_id
            )
            evt.bucket = new_bucket
            setattr(status, new_bucket, getattr(status, new_bucket) + 1)
        elif evt.bucket == "already_known":
            evt.label = f"{job.overall_score} баллов — уже в системе"
        else:
            evt.label = f"{job.overall_score} баллов → пропущено"
        changed = True
    return changed


async def _attach_live_job_state(
    status: DiscoveryStatus, *, account_id: int, db: Executor | None
) -> None:
    """Подмешивает АКТУАЛЬНЫЙ статус воронки/пропуска в строки лога — только для ответа, не
    персистится (не пишет `raw` обратно, поэтому безопасно вызывать на каждом опросе). Вакансия
    могла продвинуться (Скрининг/Техничка/Финал/Оффер) или быть пропущена уже ПОСЛЕ того, как
    попала в лог «Просмотра» — без этого фронт показывал бы Автоотклик/Вручную/Пропуск поверх
    вакансии, которая уже не в «Просмотрено», и клик по «Пропуск» ломал её реальный этап
    воронки (`skip_job` пишет только в `skipped_vacancies`, не смотрит на текущий status)."""
    ids = [evt.vacancy_id for evt in status.events if evt.job_id is not None and evt.vacancy_id]
    if not ids:
        return
    jobs_by_vacancy = await get_jobs_by_vacancy_ids(ids, account_id=account_id, db=db)
    skipped_ids = await get_skipped_ids(ids, account_id=account_id, db=db)
    for evt in status.events:
        job = jobs_by_vacancy.get(evt.vacancy_id)
        if job is None:
            continue
        evt.job_status = job.status
        evt.job_skipped = evt.vacancy_id in skipped_ids


async def get_discovery_status(
    platform: DiscoveryPlatform, *, account_id: int, db: Executor | None = None
) -> DiscoveryStatus:
    raw = await _load_runtime_raw(account_id=account_id, db=db)
    status = _status_from_raw(platform, raw)
    if await _heal_stale_scores(status, account_id=account_id, db=db):
        # Инцидент 2026-08-19 («Автопросмотр» переставал открывать вкладки): эта запись раньше
        # брала весь `raw` из снимка НАЧАЛА функции и переписывала его целиком — включая `state`.
        # Статус опрашивается на этом же snapshot-хвосте каждые 2.5с (веб) плюс раз в минуту
        # (раннер расширения); за время починки одного события (поход в БД) параллельный
        # старт/пауза/резюм/стоп/тик успевал переписать raw[platform] заново — эта запись
        # затирала его своим устаревшим снимком, откатывая, например, только что нажатый
        # «Начать» обратно в «idle» (расширение переставало видеть running и не открывало
        # вкладки — молча, без единой ошибки в логах). Перечитываем raw ПРЯМО ПЕРЕД записью и
        # подмешиваем в свежий снимок только вылеченные поля конкретных событий (по ключу
        # vacancy_id+ts) — состояние сессии и события, добавленные за это время, не трогаем.
        #
        # Правка 2026-08-20: `bucket` тоже подмешиваем (раньше копировались только score/job_id/
        # label — переклассификация parse_error→queued_auto/manual/excluded из `_heal_stale_scores`
        # тихо терялась на этой перезаписи, тест это поймал). Счётчик корзины трогаем ТОЛЬКО если
        # свежий снимок ещё не переклассифицирован кем-то параллельным (`evt.bucket ==
        # "parse_error"` на fresh) — иначе рискуем посчитать переход дважды.
        fresh_raw = await _load_runtime_raw(account_id=account_id, db=db)
        fresh_status = _status_from_raw(platform, fresh_raw)
        healed_by_key = {(evt.vacancy_id, evt.ts): evt for evt in status.events}
        refunded = 0
        for evt in fresh_status.events:
            healed = healed_by_key.get((evt.vacancy_id, evt.ts))
            if healed is None:
                continue
            if evt.bucket == "parse_error" and healed.bucket != "parse_error":
                fresh_status.parse_error = max(0, fresh_status.parse_error - 1)
                setattr(fresh_status, healed.bucket, getattr(fresh_status, healed.bucket) + 1)
                # Вакансия была лишь МЕДЛЕННОЙ (скор доехал позже, чем расширение готово ждать),
                # а не нечитаемой — вернуть слот суточного потолка, вкладку зря не считаем.
                refunded += 1
            evt.overall_score = healed.overall_score
            evt.job_id = healed.job_id
            evt.label = healed.label
            evt.bucket = healed.bucket
        if refunded:
            _bump_daily_count(fresh_raw, platform, by=-refunded)
            _attach_daily(fresh_status, fresh_raw)
        fresh_raw[platform] = fresh_status.model_dump(mode="json")
        await _save_runtime_raw(fresh_raw, account_id=account_id, db=db)
        await _attach_live_job_state(fresh_status, account_id=account_id, db=db)
        return fresh_status
    await _attach_live_job_state(status, account_id=account_id, db=db)
    return status


async def start_session(
    platform: DiscoveryPlatform, *, account_id: int, db: Executor | None = None
) -> DiscoveryStatus:
    """Начать сессию — свежие счётчики. Требует хотя бы один непустой search-URL (иначе
    расширению нечего листать); площадку включает сама, если та ещё не была включена."""
    full_config = await get_discovery_config(account_id=account_id, db=db)
    config = full_config.platform(platform)
    if not any(u.strip() for u in config.search_urls):
        event(
            logger,
            "РАСШИРЕНИЕ",
            "discovery «%s»: старт отклонён — не задан search-URL",
            platform,
            level=logging.WARNING,
            platform=platform,
            account_id=account_id,
        )
        raise InvalidInput(f"не задан search-URL для discovery «{platform}»")
    if not config.enabled:
        # Инцидент 2026-08-19: переключатель «Просмотр/Отклик» показывает вкладку «Просмотр» по
        # умолчанию (см. computeMode во фронте), ещё ДО того, как реально включает площадку —
        # владелец жал «Начать» на уже видимой вкладке и получал отказ «discovery выключен в
        # настройках», хотя search-URL был давно сохранён; в логах при этом был только голый
        # HTTP 400 без причины. Явный клик «Начать» — однозначное намерение запустить именно эту
        # площадку, поэтому включаем её тут же вместо того, чтобы требовать отдельного шага,
        # который фронт не всегда успевает сделать сам.
        full_config = full_config.model_copy(
            update={platform: config.model_copy(update={"enabled": True})}
        )
        await set_discovery_config(full_config, account_id=account_id, db=db)
    now = datetime.now(UTC).isoformat()
    raw = await _load_runtime_raw(account_id=account_id, db=db)
    # Жёсткий суточный потолок: «новую очередь» нельзя запускать бесконечно за день —
    # per-сессионный `opened` обнуляется, а этот счётчик считает календарный день (owner's
    # spec 2026-08-28).
    cap = discovery_daily_hard_cap(platform)
    if _daily_count_today(raw, platform) >= cap:
        event(
            logger,
            "РАСШИРЕНИЕ",
            "discovery «%s»: старт отклонён — дневной лимит автопросмотра исчерпан (%d/%d)",
            platform,
            _daily_count_today(raw, platform),
            cap,
            level=logging.WARNING,
            platform=platform,
            account_id=account_id,
        )
        raise InvalidInput(
            f"дневной лимит автопросмотра «{platform}» ({cap}) исчерпан — продолжится завтра"
        )
    prev_status = _status_from_raw(platform, raw)
    # Правка 2026-08-20 (пункт 8, «Лимит за очередь»): «Начать» раньше полностью стирал `events` —
    # история предыдущей очереди этого дня пропадала бесследно, хотя счётчик открытий теперь явно
    # лимит ЗА ОЧЕРЕДЬ, а не на день (владелец рассчитывает запускать несколько очередей подряд).
    # Счётчики (opened/scored/...) всё ещё с нуля — свежий бюджет новой очереди; лог «Просмотра»
    # переживает рестарт, с маркером-разделителем на границе, чтобы было видно, где кончилась
    # старая очередь и началась новая.
    status = DiscoveryStatus(
        platform=platform,
        state="running",
        session_started_at=now,
        updated_at=now,
        events=prev_status.events,
    )
    _push_event(
        status,
        DiscoveryEvent(
            ts=now, vacancy_id="", label="Начало новой очереди", bucket="session_boundary"
        ),
    )
    raw[platform] = status.model_dump(mode="json")
    await _save_runtime_raw(raw, account_id=account_id, db=db)
    event(
        logger,
        "РАСШИРЕНИЕ",
        "discovery «%s»: старт сессии",
        platform,
        platform=platform,
        account_id=account_id,
    )
    return _attach_daily(status, raw)


async def _set_state(
    platform: DiscoveryPlatform,
    target: DiscoveryState,
    *,
    account_id: int,
    db: Executor | None,
    boundary_label: str | None = None,
) -> DiscoveryStatus:
    raw = await _load_runtime_raw(account_id=account_id, db=db)
    status = _status_from_raw(platform, raw)
    status.state = target
    if target == "running":
        # Возобновление после паузы (в т.ч. предохранителя parse_error) — даём площадке
        # честный новый заход, а не мгновенный ре-стоп на первом же следующем parse_error.
        status.consecutive_parse_errors = 0
    status.updated_at = datetime.now(UTC).isoformat()
    # Правка 2026-08-20 (пункт 8): маркер-разделитель в логе «Просмотра» на момент паузы — та же
    # пара, что и «Начало новой очереди» в `start_session`, чтобы владелец видел границы очередей
    # прямо в списке вакансий, не только по чипу статуса в шапке карточки.
    if boundary_label is not None:
        _push_event(
            status,
            DiscoveryEvent(
                ts=status.updated_at, vacancy_id="", label=boundary_label, bucket="session_boundary"
            ),
        )
    raw[platform] = status.model_dump(mode="json")
    await _save_runtime_raw(raw, account_id=account_id, db=db)
    return status


async def pause_session(
    platform: DiscoveryPlatform,
    *,
    account_id: int,
    reason: DiscoveryPauseReason = "user",
    db: Executor | None = None,
) -> DiscoveryStatus:
    # Этап 0 диагностики (plans/extension_pipeline_redesign_2026_08_18.md) нашёл дыру: ни тело
    # запроса паузы, ни platform в HTTP-лог не попадают (api/main.py пишет только method/path/
    # status/duration_ms) — без этой строки причину конкретной паузы на проде установить нельзя
    # никак, только гадать по косвенным признакам. `suspected_block` — WARNING, это сигнал
    # возможной проблемы с площадкой, а не рутинная остановка.
    event(
        logger,
        "РАСШИРЕНИЕ",
        "discovery «%s»: пауза — %s",
        platform,
        reason,
        level=logging.WARNING if reason == "suspected_block" else logging.INFO,
        platform=platform,
        reason=reason,
        account_id=account_id,
    )
    return await _set_state(
        platform,
        _STATE_BY_REASON[reason],
        account_id=account_id,
        db=db,
        boundary_label=_PAUSE_BOUNDARY_LABEL[reason],
    )


async def resume_session(
    platform: DiscoveryPlatform, *, account_id: int, db: Executor | None = None
) -> DiscoveryStatus:
    status = await get_discovery_status(platform, account_id=account_id, db=db)
    if status.state == "idle":
        raise InvalidInput(f"сессия discovery «{platform}» ещё не запускалась")
    event(
        logger,
        "РАСШИРЕНИЕ",
        "discovery «%s»: возобновление (была %s)",
        platform,
        status.state,
        platform=platform,
        account_id=account_id,
    )
    return await _set_state(platform, "running", account_id=account_id, db=db)


async def stop_session(
    platform: DiscoveryPlatform, *, account_id: int, db: Executor | None = None
) -> DiscoveryStatus:
    event(
        logger,
        "РАСШИРЕНИЕ",
        "discovery «%s»: стоп",
        platform,
        platform=platform,
        account_id=account_id,
    )
    return await _set_state(platform, "idle", account_id=account_id, db=db)


async def clear_events(
    platform: DiscoveryPlatform, *, account_id: int, db: Executor | None = None
) -> DiscoveryStatus:
    """Кнопка «Очистить» в шапке «Просмотра» — сбрасывает только видимый лог решений; счётчики и
    состояние сессии (running/paused/...) не трогает, идущий проход не прерывается."""
    raw = await _load_runtime_raw(account_id=account_id, db=db)
    status = _status_from_raw(platform, raw)
    status.events = []
    raw[platform] = status.model_dump(mode="json")
    await _save_runtime_raw(raw, account_id=account_id, db=db)
    return status


async def remove_event(
    platform: DiscoveryPlatform, *, vacancy_id: str, account_id: int, db: Executor | None = None
) -> DiscoveryStatus:
    """Убрать одну строку из лога «Просмотра» по её `vacancy_id` — кнопка «Удалить» на
    сломанной (`parse_error`) вакансии, которую самопочинка (`_heal_stale_scores`) не смогла
    долечить. Только видимый лог событий, счётчики карточки и состояние сессии не трогает —
    та же граница, что и у «Очистить» (`clear_events`), просто по одному vacancy_id."""
    raw = await _load_runtime_raw(account_id=account_id, db=db)
    status = _status_from_raw(platform, raw)
    status.events = [e for e in status.events if e.vacancy_id != vacancy_id]
    raw[platform] = status.model_dump(mode="json")
    await _save_runtime_raw(raw, account_id=account_id, db=db)
    return status


def _push_event(status: DiscoveryStatus, event: DiscoveryEvent) -> None:
    status.events = [event, *status.events][:_MAX_EVENTS]


async def report_tick_summary(
    *,
    account_id: int,
    platforms_running: list[str],
    opened: int,
    scored: int,
    already_known: int,
    parse_errors: int,
    paused: list[str],
    bail_reason: str | None,
    db: Executor | None = None,
) -> None:
    """Heartbeat раннера автопросмотра — одна строка АВТОПРОСМОТР в журнал + `last_tick`.

    `discovery` уже логирует старт/паузу/резюм, но когда сессия `running`, а SW усыплён/
    отвалился — НИЧЕГО (инцидент 2026-08-27..28, тот же класс). Уровень: WARNING при
    `bail_reason`/`paused`, иначе INFO — и рутинный «раннер жив» троттлится (раз в 30 мин).
    """
    problem = bool(bail_reason) or bool(paused)
    activity = opened > 0
    to_log = (
        problem
        or activity
        or await should_log_runner_tick(KEY_RUNNER_TICK, account_id=account_id, db=db)
    )
    await record_runner_tick(
        KEY_RUNNER_TICK,
        account_id=account_id,
        logged=to_log,
        summary={
            "platforms_running": platforms_running,
            "opened": opened,
            "scored": scored,
            "already_known": already_known,
            "parse_errors": parse_errors,
            "paused": paused,
            "bail_reason": bail_reason,
        },
        db=db,
    )
    if not to_log:
        return
    event(
        logger,
        "АВТОПРОСМОТР",
        "тик: площадки=%s открыто=%d оценено=%d уже_в_системе=%d сбоев=%d%s%s",
        ",".join(platforms_running) or "нет",
        opened,
        scored,
        already_known,
        parse_errors,
        f" пауза={','.join(paused)}" if paused else "",
        f" отказ={bail_reason}" if bail_reason else "",
        level=logging.WARNING if problem else logging.INFO,
        account_id=account_id,
        platforms_running=platforms_running,
        opened=opened,
        scored=scored,
        already_known=already_known,
        parse_errors=parse_errors,
        paused=paused,
        bail_reason=bail_reason,
    )


async def get_last_runner_tick(
    *, account_id: int, db: Executor | None = None
) -> dict[str, Any] | None:
    return await get_runner_tick(KEY_RUNNER_TICK, account_id=account_id, db=db)


async def report_tick(
    platform: DiscoveryPlatform,
    *,
    account_id: int,
    vacancy_id: str,
    outcome: DiscoveryOutcome,
    title: str | None = None,
    company: str | None = None,
    pages_visited: int | None = None,
    db: Executor | None = None,
) -> DiscoveryStatus:
    """Расширение репортит исход одной открытой вакансии — обновляет счётчики + лог.

    `scored` не несёт готового решения auto/manual_review сам по себе — оно вычисляется здесь
    через ЖИВУЮ `preview_queue` (та же логика, что видит владелец в «Автооткликах»), а не
    копируется в расширение отдельной реализацией гейта.
    """
    raw = await _load_runtime_raw(account_id=account_id, db=db)
    status = _status_from_raw(platform, raw)
    status.opened += 1
    if pages_visited is not None:
        status.pages_visited = pages_visited
    score: int | None = None
    job_id: int | None = None
    bucket: DiscoveryEventBucket

    if outcome == "already_known":
        status.already_known += 1
        status.consecutive_parse_errors = 0
        bucket = "already_known"
        # Правка 2026-08-19 (баг 3): вакансия уже была в системе — значит уже проскорена раньше,
        # но раньше здесь не подтягивали её job/score, и строка лога навсегда оставалась без
        # балла и без квик-экшенов (job_id нужен фронту, чтобы их показать). Смотрим текущую
        # запись — есть же способ узнать её балл, не гадать.
        job = await get_job_by_vacancy_id(vacancy_id, account_id=account_id, db=db)
        score = job.overall_score if job else None
        job_id = job.id if job else None
        label = "уже в системе — пропущено" if score is None else f"{score} баллов — уже в системе"
    elif outcome == "parse_error":
        status.parse_error += 1
        status.consecutive_parse_errors += 1
        bucket = "parse_error"
        label = "не удалось прочитать вакансию — пропущено"
    else:
        status.consecutive_parse_errors = 0
        status.scored += 1
        job = await get_job_by_vacancy_id(vacancy_id, account_id=account_id, db=db)
        score = job.overall_score if job else None
        job_id = job.id if job else None
        if job is None or score is None:
            status.excluded += 1
            bucket = "excluded"
            label = "не удалось оценить — пропущено"
        else:
            bucket, label = await _classify_scored_bucket(
                platform, vacancy_id, score, account_id=account_id
            )
            setattr(status, bucket, getattr(status, bucket) + 1)

    status.updated_at = datetime.now(UTC).isoformat()
    _push_event(
        status,
        DiscoveryEvent(
            ts=status.updated_at,
            vacancy_id=vacancy_id,
            title=title,
            company=company,
            label=label,
            bucket=bucket,
            overall_score=score,
            job_id=job_id,
        ),
    )
    # Суточный потолок автопросмотра: считаем реально открытые вкладки (`scored`/`parse_error`),
    # `already_known` вкладку не открывает и в бюджет не идёт. Достигли — площадка встаёт на
    # `paused_daily_cap` до завтра; раннер сам возобновит на новый день (тот же auto-resume,
    # что и у per-сессионной паузы).
    if outcome in ("scored", "parse_error"):
        daily_used = _bump_daily_count(raw, platform)
        cap = discovery_daily_hard_cap(platform)
        if daily_used >= cap and status.state == "running":
            status.state = "paused_daily_cap"
            _push_event(
                status,
                DiscoveryEvent(
                    ts=datetime.now(UTC).isoformat(),
                    vacancy_id="",
                    label="Дневной лимит автопросмотра исчерпан",
                    bucket="session_boundary",
                ),
            )
            event(
                logger,
                "АВТОПРОСМОТР",
                "discovery «%s»: дневной лимит исчерпан (%d/%d) — пауза до завтра",
                platform,
                daily_used,
                cap,
                platform=platform,
                account_id=account_id,
            )

    # Предохранитель: N `parse_error` подряд = парсер вакансий сломан / площадка режет, а не
    # «одна вакансия нечитаема». Не выжигаем остаток суточного потолка битыми вкладками — пауза
    # (ручная: владелец должен зайти и посмотреть, что с площадкой; auto-resume не для этого).
    if status.consecutive_parse_errors >= _PARSE_ERROR_BREAKER and status.state == "running":
        status.state = "paused_suspected_block"
        _push_event(
            status,
            DiscoveryEvent(
                ts=datetime.now(UTC).isoformat(),
                vacancy_id="",
                label="Подряд не читаются вакансии — очередь на паузе",
                bucket="session_boundary",
            ),
        )
        event(
            logger,
            "АВТОПРОСМОТР",
            "discovery «%s»: %d parse_error подряд — парсер/площадка сломаны, пауза",
            platform,
            status.consecutive_parse_errors,
            level=logging.WARNING,
            platform=platform,
            account_id=account_id,
            consecutive_parse_errors=status.consecutive_parse_errors,
        )

    _attach_daily(status, raw)
    raw[platform] = status.model_dump(mode="json")
    await _save_runtime_raw(raw, account_id=account_id, db=db)
    return status


__all__ = [
    "DEFAULT_DISCOVERY_CONFIG",
    "DISCOVERY_DAILY_HARD_CAP",
    "KEY_DISCOVERY_CONFIG",
    "KEY_DISCOVERY_RUNTIME",
    "DiscoveryConfig",
    "DiscoveryEvent",
    "DiscoveryEventBucket",
    "DiscoveryOutcome",
    "DiscoveryPauseReason",
    "DiscoveryPlatform",
    "DiscoveryPlatformConfig",
    "DiscoveryState",
    "DiscoveryStatus",
    "default_discovery_config_dict",
    "discovery_config_from_mapping",
    "discovery_daily_hard_cap",
    "KEY_RUNNER_TICK",
    "get_discovery_config",
    "get_discovery_status",
    "get_last_runner_tick",
    "pause_session",
    "report_tick",
    "report_tick_summary",
    "resume_session",
    "set_discovery_config",
    "start_session",
    "stop_session",
]
