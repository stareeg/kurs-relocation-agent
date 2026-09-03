"""Стор структурного резюме.

Источник правды переехал с
файла (`settings.resume_data_path`, поля как на hh) в Postgres — таблица `resumes`
(`account_id` → jsonb, `0098_resumes.sql`). Файл остаётся источником только для двух окон,
которые сюда и сводятся:

- **bootstrap** — ни одного аккаунта в системе ещё нет (`accounts` пуста, `require_account`
  отдаёт `None`, см. `api/security.py`) — писать в БД некуда, `account_id` физически нет;

M1 (plans/multitenancy_gaps_2026_08_06.md §3.1): раньше здесь жил один process-global
`_holder: ResumeData | None` — залитый на старте резюме владельца, но `save_resume_data` правил
его при сохранении ЛЮБОГО аккаунта. Друг сохранял своё резюме → `_holder` тихо становился резюме
для всех, включая скоринг владельца (тот самый S1-баг, «резюме друга стало резюме для всех»).
Теперь кэш — `_cache: dict[account_id, ResumeData]`; запись одного аккаунта трогает ровно его
запись. `read_resume_data_for_account(account_id)` — единственный путь чтения известного
аккаунта (используют скоринг, вкладка «Резюме», gap/skill_suggest/ats-fit — везде, где роутер
уже резолвил `account_id` из токена запроса).

Домены, ещё не получившие `account_id` параметром сверху (офферы/подготовка/HR-черновики/
рынок — свои M-этапы плана): `read_resume_data_for_default_account()` — асинхронный мост
(резолвит владельца через `resolve_default_account_id()` и читает БД); `read_default_resume_data()`
— его sync-эквивалент для мест, которые не готовы стать `async def` ради одной подстановки
(`prompt.py`/`profile.py`'s legacy кэш, ~15 доменов уровня pipeline/offers/preparation/market).
Он читает `_cache[_default_account_id]`, если процесс прогрет (`load_resume_into_runtime` на
старте `api.main`/`bot_app.run`) — тот же контент, что видел бы `read_resume_data_for_account`
для владельца, без похода в БД на каждый вызов; не прогрет (bootstrap/тесты) → файл. Важно: этот
слот трогает ТОЛЬКО прогрев на старте и сохранение самим владельцем (`_default_account_id` не
меняется от чужих `save_resume_data`) — в отличие от старого `_holder`, чужой accounт его
перезаписать не может.

`read_resume_data_from_file()` — чистая bootstrap/файловая функция без кэша и без БД:
используется тестами (фикстуры кладут JSON на `RESUME_DATA_PATH`) и как ветка `account_id=None`
внутри `read_resume_data_for_account`/`read_default_resume_data`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import OrderedDict
from pathlib import Path

from core.config import CoreSettings, get_settings
from core.domains.profile.events import publish_resume_updated
from core.domains.profile.model import ResumeData, apply_city_derived_countries
from core.platform.db.account_scope import account_scope
from core.platform.db.pool import Executor, get_pool

logger = logging.getLogger(__name__)

# Кэш на аккаунт — заменяет process-global _holder. Инвалидация — точечная, при сохранении
# именно этого account_id (`save_resume_data`) или при прогреве на старте
# (`load_resume_into_runtime`).
#
# Bounded LRU: ключ = account_id, значение = ResumeData. Число аккаунтов ограничено (несколько
# друзей владельца), но без верхней границы это тот же anti-pattern «dict растёт бесконечно» —
# при удалении аккаунта запись остаётся навсегда. Лимит с запасом над реальным числом аккаунтов;
# LRU-вытеснение защищает от тихого роста, сохраняя горячие аккаунты в памяти.
_RESUME_CACHE_MAX = 64
_cache: OrderedDict[int, ResumeData] = OrderedDict()

# Владелец инсталляции, прогретый на старте (`load_resume_into_runtime`) — единственный писатель
# этого слота (см. докстринг модуля). `read_default_resume_data()` читает
# `_cache[_default_account_id]` через него; чужой account_id его не меняет.
_default_account_id: int | None = None


def _cache_get(account_id: int) -> ResumeData | None:
    item = _cache.get(account_id)
    if item is None:
        return None
    _cache.move_to_end(account_id)
    return item


def _cache_put(account_id: int, data: ResumeData) -> None:
    _cache[account_id] = data
    _cache.move_to_end(account_id)
    while len(_cache) > _RESUME_CACHE_MAX:
        _cache.popitem(last=False)


def _data_path(settings: CoreSettings) -> Path:
    return Path(settings.resume_data_path)


def _read_file(settings: CoreSettings) -> ResumeData:
    """Нет файла / битый JSON → пустая модель (вкладка не падает)."""
    path = _data_path(settings)
    if not path.is_file():
        return ResumeData()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return ResumeData.model_validate(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error("Резюме: битый resume_data.json (%s) — отдаю пустую модель", exc)
        return ResumeData()


def _write_file(data: ResumeData, settings: CoreSettings) -> None:
    path = _data_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")


def _refresh_caches_and_publish(*, source: str, account_id: int | None) -> None:
    # Легаси sync-путь (prompt.py/profile.py, lru_cache по пути файла — тесты/bootstrap) без
    # сброса отдал бы старый текст. Продуктовый account-aware путь его не читает (данные
    # передаются явно), сброс для него — no-op, не вреден.
    from core.domains.opportunities.prompt import clear_resume_cache

    clear_resume_cache()
    # Кэш полного балла резюме (gap._score_cache) ключуется resume_hash+corpus_fp — после
    # изменения резюме/корпуса старые записи протухают, но без явного сброса висят до TTL/LRU.
    # Чистим сразу: «Обновляю» на вкладке «Резюме» должно показать свежий балл, а не старый.
    from core.domains.profile.gap import clear_score_cache

    clear_score_cache()
    # A-11: от резюме зависят скоринг, профиль поиска и ATS — событие вместо обзвона доменов.
    publish_resume_updated(source=source, account_id=account_id)


def read_resume_data_from_file(settings: CoreSettings | None = None) -> ResumeData:
    """Резюме из `resume_data.json` — без кэша, без БД, без понятия аккаунта.

    Единственный текущий продуктовый вызывающий — bootstrap-ветка
    `read_resume_data_for_account(None, ...)`. Остальные вызывающие — тесты (фикстуры на
    `RESUME_DATA_PATH`) и sync-кэш `prompt.py`/`profile.py`.
    """
    return _read_file(settings or get_settings())


async def read_resume_data_for_account(
    account_id: int | None, *, db: Executor | None = None
) -> ResumeData:
    """Прочитать резюме конкретного аккаунта запроса — канонический путь чтения.

    `account_id=None` — bootstrap (см. докстринг модуля): читает файл, не БД, без кэша (свежесть
    важнее — на этой стадии источника правды в БД ещё физически нет). Иначе — кэш аккаунта, а на
    промахе БД; нет строки в `resumes` (новый аккаунт без файла-предка) → пустая модель.
    """
    if account_id is None:
        return read_resume_data_from_file(get_settings())
    cached = _cache_get(account_id)
    if cached is not None:
        return cached
    try:
        if db is not None:
            row = await db.fetchrow("select data from resumes where account_id = $1", account_id)
        else:
            async with account_scope(account_id) as scoped:
                row = await scoped.fetchrow(
                    "select data from resumes where account_id = $1", account_id
                )
    except Exception as exc:
        logger.debug("Резюме: чтение БД (account_id=%s) недоступно: %s", account_id, exc)
        return ResumeData()
    data = ResumeData.model_validate(row["data"]) if row is not None else ResumeData()
    _cache_put(account_id, data)
    return data


def read_default_resume_data(settings: CoreSettings | None = None) -> ResumeData:
    """Sync-эквивалент `read_resume_data_for_default_account()` — см. докстринг модуля.

    Легаси-путь для доменов уровня pipeline/offers/preparation/market, ещё не получивших
    `account_id` параметром сверху (свои M-этапы плана), и для внутреннего sync-кэша
    `prompt.py`/`profile.py`. Прогретый кэш (прод, после `load_resume_into_runtime`) → мгновенно,
    без похода в БД; не прогрет (bootstrap/тесты) → файл.
    """
    if _default_account_id is not None:
        cached = _cache_get(_default_account_id)
        if cached is not None:
            return cached
    return read_resume_data_from_file(settings)


async def read_resume_data_for_default_account(*, db: Executor | None = None) -> ResumeData:
    """Мост для доменов, ещё не получивших `account_id` параметром сверху (офферы/подготовка/
    HR-черновики/рынок — свои M-этапы плана, plans/multitenancy_gaps_2026_08_06.md §6).
    Эквивалент старого `read_resume_data()` для единственного (владельческого) аккаунта.

    Как только вызывающий домен получит реальный `account_id` из своего контекста — звать
    `read_resume_data_for_account(account_id)` напрямую и убрать этот вызов.
    """
    from core.platform.repo.accounts import resolve_default_account_id

    account_id = await resolve_default_account_id()
    return await read_resume_data_for_account(account_id, db=db)


async def render_resume_markdown_for_account(
    account_id: int | None, *, db: Executor | None = None
) -> str:
    """Канонический markdown резюме конкретного аккаунта (gap-анализ, score_refresh)."""
    from core.domains.profile.model import to_markdown

    return to_markdown(await read_resume_data_for_account(account_id, db=db))


async def save_resume_data(
    data: ResumeData,
    settings: CoreSettings | None = None,
    *,
    source: str = "",
    account_id: int | None = None,
    db: Executor | None = None,
) -> ResumeData:
    """Сохранить структурное резюме — в БД аккаунта (`account_id` задан) или в файл (bootstrap).

    Обновляет кэш аккаунта сразу (только для БД-пути — файловый bootstrap-путь кэша не имеет,
    `read_resume_data_from_file`/`read_resume_data_for_account(None, ...)` и так перечитывают
    файл на каждый вызов). Кэш скоринга (`clear_resume_cache`) сбрасываем в обоих случаях —
    источник правды сначала, потом кэш/событие.
    """
    settings = settings or get_settings()
    data = apply_city_derived_countries(data)
    if account_id is None:
        await asyncio.to_thread(_write_file, data, settings)
    else:
        payload = data.model_dump(mode="json")
        upsert_sql = (
            "insert into resumes (account_id, data, updated_at) values ($1, $2, now()) "
            "on conflict (account_id) do update set "
            "data = excluded.data, updated_at = excluded.updated_at"
        )
        if db is not None:
            await db.execute(upsert_sql, account_id, payload)
        else:
            async with account_scope(account_id) as scoped:
                await scoped.execute(upsert_sql, account_id, payload)

        _cache_put(account_id, data)

    _refresh_caches_and_publish(source=source, account_id=account_id)
    return data


async def load_resume_into_runtime(*, account_id: int | None, db: Executor | None = None) -> None:
    """Прогреть кэш аккаунта на старте процесса (`api.main`/`bot_app.run`, зеркало
    `core.platform.repo.settings.load_openrouter_key_into_runtime`).

    `account_id=None` (bootstrap, ни одного аккаунта нет) — ничего не делает: чтения и так идут
    в файл при каждом вызове (см. докстринг модуля).

    `account_id` задан — разовый импорт файла в БД, если строки для этого аккаунта ещё нет
    (плана: «разовая миграция данных владельца»), затем кэш = содержимое БД. С этого момента
    файл на диске для этого аккаунта больше не читается (не удаляется — `resume/` гитигнорится,
    трогать не нужно), источник правды — БД. Заодно помечает этот `account_id` дефолтным для
    `read_default_resume_data()`/`peek` (см. докстринг модуля) — единственное место,
    которое его выставляет.
    """
    if account_id is None:
        return
    global _default_account_id
    _default_account_id = account_id
    executor = db or get_pool()
    try:
        row = await executor.fetchrow("select data from resumes where account_id = $1", account_id)
        if row is None:
            file_data = read_resume_data_from_file(get_settings())
            payload = file_data.model_dump(mode="json")
            row = await executor.fetchrow(
                "insert into resumes (account_id, data) values ($1, $2) "
                "on conflict (account_id) do nothing "
                "returning data",
                account_id,
                payload,
            )
            if row is None:
                # Гонка (второй процесс успел вставить первым) — читаем то, что реально в БД.
                row = await executor.fetchrow(
                    "select data from resumes where account_id = $1", account_id
                )
    except Exception as exc:
        logger.warning("Резюме: кэш не прогрет из БД (account_id=%s): %s", account_id, exc)
        return
    if row is not None:
        _cache_put(account_id, ResumeData.model_validate(row["data"]))


__all__ = [
    "load_resume_into_runtime",
    "read_default_resume_data",
    "read_resume_data_for_account",
    "read_resume_data_for_default_account",
    "read_resume_data_from_file",
    "render_resume_markdown_for_account",
    "save_resume_data",
]
