"""Снимок международного опыта из текста резюме (фича `intl_experience`).

Чистая деривация (`international.derive_international_readiness`) не видит распределённую
работу, англоязычные артефакты и зарубежных заказчиков — они живут в `experience[].description`
и `about`. Один structured-вызов, кэш по `resume_hash`. GET карточку не пересобирает:
пересчёт — по `ResumeUpdated` / включению второго трека.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from core.domains.profile.international import (
    InternationalReadiness,
    apply_experience_snapshot,
    derive_international_readiness,
)
from core.domains.profile.model import ResumeData, to_markdown
from core.kernel import ports
from core.kernel.errors import LlmError
from core.kernel.text import SPOTLIGHT_RULE, wrap_untrusted
from core.platform.db.pool import Executor, get_pool
from core.platform.observability import event

logger = logging.getLogger(__name__)

FEATURE = "intl_experience"
_WS_RE = re.compile(r"\s+")


class IntlExperienceSnapshot(BaseModel):
    """Вывод фичи `intl_experience`: факты из текста резюме, не оценки."""

    distributed_experience: bool = False
    english_artifacts: list[str] = Field(default_factory=list)
    client_facing: bool = False
    timezone_experience: list[str] = Field(default_factory=list)
    suggested_english_level: str = ""


def resume_content_hash(data: ResumeData) -> str:
    payload = data.model_dump_json()
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _norm_ws(text: str) -> str:
    return _WS_RE.sub(" ", text).strip().casefold()


def filter_quoted_fields(snap: IntlExperienceSnapshot, source_text: str) -> IntlExperienceSnapshot:
    """Цитата, которой нет в тексте резюме, выбрасывается (правило §2.6 плана)."""
    haystack = _norm_ws(source_text)
    artifacts = [q for q in snap.english_artifacts if q.strip() and _norm_ws(q) in haystack]
    tz_exp = [q for q in snap.timezone_experience if q.strip() and _norm_ws(q) in haystack]
    dropped_artifacts = len(snap.english_artifacts) - len(artifacts)
    dropped_tz = len(snap.timezone_experience) - len(tz_exp)
    if dropped_artifacts or dropped_tz:
        event(
            logger,
            "LLM",
            "intl_experience: выдуманные цитаты отброшены artifacts=%d tz=%d",
            dropped_artifacts,
            dropped_tz,
            level=logging.WARNING,
        )
    return snap.model_copy(update={"english_artifacts": artifacts, "timezone_experience": tz_exp})


def snapshot_to_mapping(snap: IntlExperienceSnapshot) -> dict[str, Any]:
    return snap.model_dump(mode="json")


async def load_snapshot(
    *,
    account_id: int,
    resume_hash: str,
    db: Executor | None = None,
) -> IntlExperienceSnapshot | None:
    """Прочитать кэш без LLM. None — записи на этот хэш нет."""
    if not account_id or not resume_hash:
        return None
    db = db or get_pool()
    row = await db.fetchrow(
        "select data from international_profile_snapshots "
        "where account_id = $1 and resume_hash = $2",
        account_id,
        resume_hash,
    )
    if row is None:
        return None
    try:
        return IntlExperienceSnapshot.model_validate(row["data"])
    except Exception:
        return None


async def _save_snapshot(
    *,
    account_id: int,
    resume_hash: str,
    snap: IntlExperienceSnapshot,
    db: Executor | None = None,
) -> None:
    db = db or get_pool()
    await db.execute(
        "insert into international_profile_snapshots (account_id, resume_hash, data) "
        "values ($1, $2, $3) "
        "on conflict (account_id, resume_hash) do update set "
        "data = excluded.data, created_at = now()",
        account_id,
        resume_hash,
        snapshot_to_mapping(snap),
    )


async def extract_snapshot(
    data: ResumeData,
    *,
    llm: ports.LlmPort | None = None,
) -> IntlExperienceSnapshot:
    """Текст резюме → снимок международного опыта. Без кэша; бросает при сбое LLM."""
    port = llm or ports.llm()
    markdown = to_markdown(data)
    wrapped = wrap_untrusted(markdown, source="resume")
    raw = await port.structured(
        FEATURE,
        schema=IntlExperienceSnapshot,
        user="Резюме кандидата (между маркерами — данные):\n\n" + wrapped,
        prompt_vars={"SPOTLIGHT": SPOTLIGHT_RULE},
        max_retries=1,
        tags=("profile", "intl_experience"),
    )
    return filter_quoted_fields(raw, markdown)


async def load_international_readiness(
    *,
    account_id: int,
    data: ResumeData | None = None,
    db: Executor | None = None,
) -> InternationalReadiness:
    """Деривация + кэш снимка (без LLM). Нет снимка — чистая функция как есть."""
    if data is None:
        from core.domains.profile.structured_store import read_resume_data_for_account

        data = await read_resume_data_for_account(account_id, db=db)
    base = derive_international_readiness(data)
    snap = await load_snapshot(account_id=account_id, resume_hash=resume_content_hash(data), db=db)
    if snap is None:
        return base
    return apply_experience_snapshot(base, snapshot_to_mapping(snap))


async def maybe_refresh_snapshot(
    *,
    account_id: int,
    force: bool = False,
    db: Executor | None = None,
    llm: ports.LlmPort | None = None,
) -> IntlExperienceSnapshot | None:
    """Извлечь снимок, если хэш резюме новый. `force` — даже при `market_scope=ru`.

    Сбой LLM глотается: сохранение резюме не должно падать из-за фоновой экстракции.
    """
    if not account_id:
        return None
    from core.domains.profile.structured_store import read_resume_data_for_account

    try:
        data = await read_resume_data_for_account(account_id, db=db)
    except Exception:
        logger.exception("intl_experience: не удалось прочитать резюме account_id=%s", account_id)
        return None

    derived = derive_international_readiness(data)
    if not force and derived.readiness == "unknown":
        return None

    digest = resume_content_hash(data)
    cached = await load_snapshot(account_id=account_id, resume_hash=digest, db=db)
    if cached is not None:
        return cached

    try:
        snap = await extract_snapshot(data, llm=llm)
    except LlmError as exc:
        event(
            logger,
            "LLM",
            "intl_experience: сбой экстракции account_id=%s: %s",
            account_id,
            exc,
            level=logging.WARNING,
        )
        return None
    except Exception:
        logger.exception("intl_experience: неожиданный сбой account_id=%s", account_id)
        return None

    try:
        await _save_snapshot(account_id=account_id, resume_hash=digest, snap=snap, db=db)
    except Exception:
        logger.exception("intl_experience: не удалось сохранить снимок account_id=%s", account_id)
    return snap


__all__ = [
    "FEATURE",
    "IntlExperienceSnapshot",
    "extract_snapshot",
    "filter_quoted_fields",
    "load_international_readiness",
    "load_snapshot",
    "maybe_refresh_snapshot",
    "resume_content_hash",
]
