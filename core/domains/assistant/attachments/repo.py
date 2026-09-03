"""Репозиторий вложений-картинок: контент-адресуемое хранилище `attachments` (Э0-3).

Upsert по (account_id, sha256) — повторная загрузка того же скрина одним аккаунтом не создаёт
вторую строку, чтение мета/байт по id, выборка кандидатов на GC. Персист вложений обязателен
(Э0-3: «нет PG → 503, тот же принцип, что у `assistant.prep_chat`») — здесь исключения не
глушатся, их превращает в `StorageUnavailable` вызывающий слой (`service.py`).

M4 (plans/multitenancy_gaps_2026_08_06.md §3.5, 0105): `attachments` перестала быть одной
таблицей на всю систему — дедуп по sha256 теперь per-account (было S1: перебор id выдавал чужие
скриншоты переписок/офферов). Все функции, читающие/пишущие конкретную строку, обязаны получать
`account_id`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from core.domains.assistant.attachments.models import (
    Attachment,
    AttachmentAnalysis,
    AttachmentMeta,
)
from core.platform.db.pool import Executor, get_pool, row_to_dict

_META_COLS = (
    "id, sha256, mime, width, height, bytes, thumb_width, thumb_height, "
    "derived_from, crop, analysis_status, analysis, analyzed_at, created_at"
)
_META_COLS_QUALIFIED = ", ".join(f"a.{col.strip()}" for col in _META_COLS.split(","))

# Реестр «поверхность ленты → таблица связок» — используется только GC (`gc_candidates`), которая
# проверяет отсутствие ссылок по имени таблицы и не заботится об аккаунте (системный путь). Каждая
# поверхность несёт свою пару account-aware функций (link_*/load_*) — HR_SURFACE ниже,
# PREP_CHAT_SURFACE в `service.link_to_prep_chat_message`/`load_for_prep_chat_messages`,
# DEBRIEF_SURFACE в `link_debrief_attachments`/`load_debrief_attachments`.
HR_SURFACE = "hr_message_attachments"
PREP_CHAT_SURFACE = "prep_chat_message_attachments"
DEBRIEF_SURFACE = "debrief_attachments"
MARKET_CHAT_SURFACE = "market_chat_message_attachments"
RESUME_CHAT_SURFACE = "resume_chat_message_attachments"
OFFERS_CHAT_SURFACE = "offers_chat_message_attachments"
_SURFACE_TABLES: tuple[str, ...] = (
    HR_SURFACE,
    PREP_CHAT_SURFACE,
    DEBRIEF_SURFACE,
    MARKET_CHAT_SURFACE,
    RESUME_CHAT_SURFACE,
    OFFERS_CHAT_SURFACE,
)


def _meta_from_dict(data: dict[str, Any]) -> AttachmentMeta:
    analysis = data.pop("analysis", None)
    return AttachmentMeta(analysis=AttachmentAnalysis(**analysis) if analysis else None, **data)


def _meta_from_row(row: Any) -> AttachmentMeta:
    return _meta_from_dict(row_to_dict(row))


def _attachment_from_row(row: Any) -> Attachment:
    data = row_to_dict(row)
    analysis = data.pop("analysis", None)
    return Attachment(analysis=AttachmentAnalysis(**analysis) if analysis else None, **data)


async def upsert_attachment(
    *,
    account_id: int,
    sha256: str,
    mime: str,
    width: int,
    height: int,
    data: bytes,
    thumb: bytes,
    thumb_width: int,
    thumb_height: int,
    derived_from: int | None = None,
    crop: dict | None = None,
    db: Executor | None = None,
) -> AttachmentMeta:
    """Тот же (account_id, sha256) → та же строка (дедуп «вставил тот же скрин дважды»).

    `on conflict ... do update set sha256 = excluded.sha256` — стандартный приём заставить
    `returning` сработать и на конфликте (`do nothing` вернул бы пустой результат, и вызывающий
    код остался бы без id существующей строки).
    """
    db = db or get_pool()
    row = await db.fetchrow(
        "insert into attachments "
        "(account_id, sha256, mime, width, height, bytes, data, thumb, thumb_width, "
        "thumb_height, derived_from, crop) "
        "values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12) "
        "on conflict (account_id, sha256) do update set sha256 = excluded.sha256 "
        f"returning {_META_COLS}",
        account_id,
        sha256,
        mime,
        width,
        height,
        len(data),
        data,
        thumb,
        thumb_width,
        thumb_height,
        derived_from,
        crop,
    )
    assert row is not None  # insert ... returning всегда отдаёт строку
    return _meta_from_row(row)


async def get_meta(
    attachment_id: int, *, account_id: int, db: Executor | None = None
) -> AttachmentMeta | None:
    """Мета без байт — для `GET /api/attachments/{id}/meta` и подгрузки в композер/ленту."""
    db = db or get_pool()
    row = await db.fetchrow(
        f"select {_META_COLS} from attachments where id = $1 and account_id = $2",
        attachment_id,
        account_id,
    )
    return _meta_from_row(row) if row is not None else None


async def get_data(
    attachment_id: int, *, account_id: int, db: Executor | None = None
) -> Attachment | None:
    """Полная строка с байтами (нормализованная картинка + превью) — отдача файла, кроп-источник."""
    db = db or get_pool()
    row = await db.fetchrow(
        f"select {_META_COLS}, data, thumb from attachments where id = $1 and account_id = $2",
        attachment_id,
        account_id,
    )
    return _attachment_from_row(row) if row is not None else None


async def set_analysis(
    attachment_id: int,
    *,
    account_id: int,
    status: str,
    analysis: AttachmentAnalysis | None,
    db: Executor | None = None,
) -> None:
    """Пишет результат распознавания (фоновая задача `attachment_read`, Этап 1)."""
    db = db or get_pool()
    await db.execute(
        "update attachments set analysis_status = $3, analysis = $4, analyzed_at = now() "
        "where id = $1 and account_id = $2",
        attachment_id,
        account_id,
        status,
        analysis.model_dump() if analysis is not None else None,
    )


async def reset_pending(attachment_id: int, *, account_id: int, db: Executor | None = None) -> None:
    """Форс-перезапуск распознавания (`POST /api/attachments/{id}/reanalyze`)."""
    db = db or get_pool()
    await db.execute(
        "update attachments set analysis_status = 'pending', analysis = null, analyzed_at = null "
        "where id = $1 and account_id = $2",
        attachment_id,
        account_id,
    )


async def gc_candidates(
    *, older_than: datetime, limit: int = 500, db: Executor | None = None
) -> list[int]:
    """Id несвязанных вложений старше `older_than` — кандидаты на удаление (Э0-5).

    Системный путь (не пользовательский запрос) — без фильтра по аккаунту, как маркет-агрегация/
    бэкапы (план §1 п.3). Не трогает строки, на которые ссылается `derived_from` живой строки
    (§2.1: обрезанная картинка — новая строка со ссылкой на исходную, оригинал не должен пропасть
    из-под неё), и — как только появится хотя бы одна таблица в `_SURFACE_TABLES` — строки, на
    которые есть связка в любой из них.
    """
    db = db or get_pool()
    clauses = [
        "a.created_at < $1",
        "not exists (select 1 from attachments d where d.derived_from = a.id)",
    ]
    clauses.extend(
        f"not exists (select 1 from {table} m where m.attachment_id = a.id)"
        for table in _SURFACE_TABLES
    )
    query = f"select a.id from attachments a where {' and '.join(clauses)} limit $2"
    rows = await db.fetch(query, older_than, limit)
    return [r["id"] for r in rows]


async def delete_attachments(ids: list[int], *, db: Executor | None = None) -> int:
    """Жёсткое удаление по id (GC-исполнение, системный путь). Возвращает число удалённых строк."""
    if not ids:
        return 0
    db = db or get_pool()
    result = await db.execute("delete from attachments where id = any($1::bigint[])", list(ids))
    # asyncpg возвращает "DELETE N" — достаём N.
    try:
        return int(result.split()[-1])
    except (ValueError, IndexError):
        return 0


async def link_hr_message_attachments(
    message_id: int, attachment_ids: Sequence[int], *, account_id: int, db: Executor | None = None
) -> None:
    """Привязать вложения к отправленному HR-сообщению (§2.3: черновик = отсутствие связки —
    связка появляется только в момент отправки). `position` — порядок в сообщении (сетка §6.3).

    M4 (plans/multitenancy_gaps_2026_08_06.md §3.5): своя пара функций, не общий реестр
    `_SURFACE_TABLES` — `hr_message_attachments` уже несёт `account_id` (денорм от `hr_messages`,
    0105), тот же приём, что `link_debrief_attachments`/`link_prep_chat_attachments` в M3.
    """
    if not attachment_ids:
        return
    db = db or get_pool()
    await db.executemany(
        f"insert into {HR_SURFACE} (account_id, message_id, attachment_id, position) "
        "values ($1, $2, $3, $4) on conflict (message_id, attachment_id) do nothing",
        [
            (account_id, message_id, attachment_id, i)
            for i, attachment_id in enumerate(attachment_ids)
        ],
    )


async def load_hr_message_attachments(
    message_ids: Sequence[int], *, account_id: int, db: Executor | None = None
) -> dict[int, list[AttachmentMeta]]:
    """Вложения нескольких HR-реплик (без байт), сгруппированные по message_id.

    Порядок внутри реплики — `position` (сетка §6.3); порядок между репликами — id связки, что
    для `message_ids` в хронологическом порядке даёт хронологию и по вложениям.
    """
    if not message_ids:
        return {}
    db = db or get_pool()
    rows = await db.fetch(
        f"select m.message_id, {_META_COLS_QUALIFIED} from {HR_SURFACE} m "
        "join attachments a on a.id = m.attachment_id "
        "where m.message_id = any($1::bigint[]) and m.account_id = $2 "
        "order by m.message_id, m.position",
        list(message_ids),
        account_id,
    )
    out: dict[int, list[AttachmentMeta]] = {}
    for row in rows:
        data = row_to_dict(row)
        message_id = data.pop("message_id")
        out.setdefault(message_id, []).append(_meta_from_dict(data))
    return out


async def link_debrief_attachments(
    debrief_id: int, attachment_ids: Sequence[int], *, account_id: int, db: Executor | None = None
) -> None:
    """Привязать вложения к сохранённому разбору собеса (Э4-4) — своя таблица, своя колонка
    (`debrief_id`), не общий реестр `_SURFACE_TABLES`-функций выше.

    M3 (plans/multitenancy_gaps_2026_08_06.md §3.3): `account_id` денормализован от
    `interview_debriefs` (0104) — пишем его сами, а не полагаемся на join.
    """
    if not attachment_ids:
        return
    db = db or get_pool()
    await db.executemany(
        f"insert into {DEBRIEF_SURFACE} (account_id, debrief_id, attachment_id, position) "
        "values ($1, $2, $3, $4) on conflict (debrief_id, attachment_id) do nothing",
        [
            (account_id, debrief_id, attachment_id, i)
            for i, attachment_id in enumerate(attachment_ids)
        ],
    )


async def load_debrief_attachments(
    debrief_ids: Sequence[int], *, account_id: int, db: Executor | None = None
) -> dict[int, list[AttachmentMeta]]:
    """Вложения нескольких разборов (без байт), сгруппированные по debrief_id — карточка разбора
    (Э4-4) и история (`GET /api/debrief/{vacancy_id}`)."""
    if not debrief_ids:
        return {}
    db = db or get_pool()
    rows = await db.fetch(
        f"select m.debrief_id, {_META_COLS_QUALIFIED} from {DEBRIEF_SURFACE} m "
        "join attachments a on a.id = m.attachment_id "
        "where m.debrief_id = any($1::bigint[]) and m.account_id = $2 "
        "order by m.debrief_id, m.position",
        list(debrief_ids),
        account_id,
    )
    out: dict[int, list[AttachmentMeta]] = {}
    for row in rows:
        data = row_to_dict(row)
        debrief_id = data.pop("debrief_id")
        out.setdefault(debrief_id, []).append(_meta_from_dict(data))
    return out


async def link_prep_chat_attachments(
    message_id: int, attachment_ids: Sequence[int], *, account_id: int, db: Executor | None = None
) -> None:
    """Привязать вложения к реплике чата подготовки (Э3-1) — своя функция, не общий реестр
    `_SURFACE_TABLES`: `prep_chat_message_attachments` уже несёт `account_id` (0104)."""
    if not attachment_ids:
        return
    db = db or get_pool()
    await db.executemany(
        f"insert into {PREP_CHAT_SURFACE} (account_id, message_id, attachment_id, position) "
        "values ($1, $2, $3, $4) on conflict (message_id, attachment_id) do nothing",
        [
            (account_id, message_id, attachment_id, i)
            for i, attachment_id in enumerate(attachment_ids)
        ],
    )


async def load_prep_chat_attachments(
    message_ids: Sequence[int], *, account_id: int, db: Executor | None = None
) -> dict[int, list[AttachmentMeta]]:
    """Вложения нескольких реплик чата подготовки (без байт), сгруппированные по message_id."""
    if not message_ids:
        return {}
    db = db or get_pool()
    rows = await db.fetch(
        f"select m.message_id, {_META_COLS_QUALIFIED} from {PREP_CHAT_SURFACE} m "
        "join attachments a on a.id = m.attachment_id "
        "where m.message_id = any($1::bigint[]) and m.account_id = $2 "
        "order by m.message_id, m.position",
        list(message_ids),
        account_id,
    )
    out: dict[int, list[AttachmentMeta]] = {}
    for row in rows:
        data = row_to_dict(row)
        message_id = data.pop("message_id")
        out.setdefault(message_id, []).append(_meta_from_dict(data))
    return out


async def link_market_chat_attachments(
    message_id: int, attachment_ids: Sequence[int], *, account_id: int, db: Executor | None = None
) -> None:
    """Привязать вложения к реплике чата «Рынка» (Заход 6, п.7) — своя функция, не общий реестр
    `_SURFACE_TABLES`: `market_chat_message_attachments` уже несёт `account_id` (миграция 0115,
    как `prep_chat_message_attachments`/0104)."""
    if not attachment_ids:
        return
    db = db or get_pool()
    await db.executemany(
        f"insert into {MARKET_CHAT_SURFACE} (account_id, message_id, attachment_id, position) "
        "values ($1, $2, $3, $4) on conflict (message_id, attachment_id) do nothing",
        [
            (account_id, message_id, attachment_id, i)
            for i, attachment_id in enumerate(attachment_ids)
        ],
    )


async def load_market_chat_attachments(
    message_ids: Sequence[int], *, account_id: int, db: Executor | None = None
) -> dict[int, list[AttachmentMeta]]:
    """Вложения нескольких реплик чата «Рынка» (без байт), сгруппированные по message_id."""
    if not message_ids:
        return {}
    db = db or get_pool()
    rows = await db.fetch(
        f"select m.message_id, {_META_COLS_QUALIFIED} from {MARKET_CHAT_SURFACE} m "
        "join attachments a on a.id = m.attachment_id "
        "where m.message_id = any($1::bigint[]) and m.account_id = $2 "
        "order by m.message_id, m.position",
        list(message_ids),
        account_id,
    )
    out: dict[int, list[AttachmentMeta]] = {}
    for row in rows:
        data = row_to_dict(row)
        message_id = data.pop("message_id")
        out.setdefault(message_id, []).append(_meta_from_dict(data))
    return out


async def link_resume_chat_attachments(
    message_id: int, attachment_ids: Sequence[int], *, account_id: int, db: Executor | None = None
) -> None:
    """Привязать вложения к реплике чата по резюме (паритет с чатом «Рынка», миграция 0120) —
    своя функция, не общий реестр `_SURFACE_TABLES`: `resume_chat_message_attachments` уже несёт
    `account_id`."""
    if not attachment_ids:
        return
    db = db or get_pool()
    await db.executemany(
        f"insert into {RESUME_CHAT_SURFACE} (account_id, message_id, attachment_id, position) "
        "values ($1, $2, $3, $4) on conflict (message_id, attachment_id) do nothing",
        [
            (account_id, message_id, attachment_id, i)
            for i, attachment_id in enumerate(attachment_ids)
        ],
    )


async def load_resume_chat_attachments(
    message_ids: Sequence[int], *, account_id: int, db: Executor | None = None
) -> dict[int, list[AttachmentMeta]]:
    """Вложения нескольких реплик чата по резюме (без байт), сгруппированные по message_id."""
    if not message_ids:
        return {}
    db = db or get_pool()
    rows = await db.fetch(
        f"select m.message_id, {_META_COLS_QUALIFIED} from {RESUME_CHAT_SURFACE} m "
        "join attachments a on a.id = m.attachment_id "
        "where m.message_id = any($1::bigint[]) and m.account_id = $2 "
        "order by m.message_id, m.position",
        list(message_ids),
        account_id,
    )
    out: dict[int, list[AttachmentMeta]] = {}
    for row in rows:
        data = row_to_dict(row)
        message_id = data.pop("message_id")
        out.setdefault(message_id, []).append(_meta_from_dict(data))
    return out


async def link_offers_chat_attachments(
    message_id: int, attachment_ids: Sequence[int], *, account_id: int, db: Executor | None = None
) -> None:
    """Привязать вложения к реплике чата «Офферы» — своя функция, не общий реестр
    `_SURFACE_TABLES`: `offers_chat_message_attachments` уже несёт `account_id`."""
    if not attachment_ids:
        return
    db = db or get_pool()
    await db.executemany(
        f"insert into {OFFERS_CHAT_SURFACE} (account_id, message_id, attachment_id, position) "
        "values ($1, $2, $3, $4) on conflict (message_id, attachment_id) do nothing",
        [
            (account_id, message_id, attachment_id, i)
            for i, attachment_id in enumerate(attachment_ids)
        ],
    )


async def load_offers_chat_attachments(
    message_ids: Sequence[int], *, account_id: int, db: Executor | None = None
) -> dict[int, list[AttachmentMeta]]:
    """Вложения нескольких реплик чата «Офферы» (без байт), сгруппированные по message_id."""
    if not message_ids:
        return {}
    db = db or get_pool()
    rows = await db.fetch(
        f"select m.message_id, {_META_COLS_QUALIFIED} from {OFFERS_CHAT_SURFACE} m "
        "join attachments a on a.id = m.attachment_id "
        "where m.message_id = any($1::bigint[]) and m.account_id = $2 "
        "order by m.message_id, m.position",
        list(message_ids),
        account_id,
    )
    out: dict[int, list[AttachmentMeta]] = {}
    for row in rows:
        data = row_to_dict(row)
        message_id = data.pop("message_id")
        out.setdefault(message_id, []).append(_meta_from_dict(data))
    return out


__all__ = [
    "DEBRIEF_SURFACE",
    "HR_SURFACE",
    "MARKET_CHAT_SURFACE",
    "OFFERS_CHAT_SURFACE",
    "PREP_CHAT_SURFACE",
    "RESUME_CHAT_SURFACE",
    "delete_attachments",
    "gc_candidates",
    "link_debrief_attachments",
    "link_hr_message_attachments",
    "link_market_chat_attachments",
    "link_offers_chat_attachments",
    "link_prep_chat_attachments",
    "link_resume_chat_attachments",
    "load_debrief_attachments",
    "load_hr_message_attachments",
    "load_market_chat_attachments",
    "load_offers_chat_attachments",
    "load_prep_chat_attachments",
    "load_resume_chat_attachments",
    "get_data",
    "get_meta",
    "reset_pending",
    "set_analysis",
    "upsert_attachment",
]
