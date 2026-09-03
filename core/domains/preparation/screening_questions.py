"""Репозиторий канонического пакета скрининга под вакансию (FR3-49/50).

Кэш последней генерации: разбор вакансии (jd_brief) + рассказ блоками (pitch_blocks/oral_pitch) +
вопросы обеих сторон (hr_questions/groups). Перегенерация затирает.
vacancy_id = HH/getmatch id (с префиксом gm_), БЕЗ FK на jobs.

Требования вакансии к рассказу больше не идут отдельным списком «мосты» (`bridges`) - они уже
вплетены в сам рассказ (блок «Мост к вакансии») и в `requirement` каждого HR-вопроса
(`core.domains.preparation.screening.questions.HrQuestion`) - дублировать их отдельной колонкой
незачем. Старая колонка `bridges` в БД осталась (миграция не нужна), но больше не читается и не
пишется отсюда.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from core.platform.db.pool import Executor, get_pool, row_to_dict

logger = logging.getLogger(__name__)

_COLS = (
    "vacancy_id, groups, hr_questions, why_company, oral_pitch, "
    "pitch_blocks, jd_brief, generated_at, input_hash"
)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _as_list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


class SavedScreeningQuestions(BaseModel):
    """Сохранённый пакет скрининга под вакансию (кэш последней генерации)."""

    vacancy_id: str
    groups: list[dict[str, Any]] = Field(default_factory=list)
    hr_questions: list[dict[str, Any]] = Field(default_factory=list)
    why_company: str = ""
    oral_pitch: str = ""
    pitch_blocks: list[dict[str, Any]] = Field(default_factory=list)
    jd_brief: dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime | None = None
    input_hash: str = ""


def _from_row(d: dict[str, Any], vacancy_id: str) -> SavedScreeningQuestions:
    jd_brief = d.get("jd_brief")
    return SavedScreeningQuestions(
        vacancy_id=d.get("vacancy_id", vacancy_id),
        groups=_as_list(d.get("groups")),
        hr_questions=_as_list(d.get("hr_questions")),
        why_company=str(d.get("why_company") or ""),
        oral_pitch=str(d.get("oral_pitch") or ""),
        pitch_blocks=_as_list(d.get("pitch_blocks")),
        jd_brief=jd_brief if isinstance(jd_brief, dict) else {},
        generated_at=_aware(d.get("generated_at")),
        input_hash=str(d.get("input_hash") or ""),
    )


async def get_screening_questions(
    vacancy_id: str, *, account_id: int, db: Executor | None = None
) -> SavedScreeningQuestions | None:
    """Прочитать сохранённый пакет. Нет записи/нет PG → None."""
    if not vacancy_id:
        return None
    db = db or get_pool()
    try:
        row = await db.fetchrow(
            f"select {_COLS} from vacancy_screening_questions "
            "where vacancy_id = $1 and account_id = $2",
            vacancy_id,
            account_id,
        )
    except Exception as exc:  # noqa: BLE001 — нет PG / до миграции → None
        logger.debug("screening_questions: чтение недоступно (нет PG?): %s", exc)
        return None
    if row is None:
        return None
    return _from_row(row_to_dict(row), vacancy_id)


async def save_screening_questions(
    vacancy_id: str,
    groups: list[dict[str, Any]],
    *,
    account_id: int,
    hr_questions: list[dict[str, Any]] | None = None,
    why_company: str = "",
    oral_pitch: str = "",
    pitch_blocks: list[dict[str, Any]] | None = None,
    jd_brief: dict[str, Any] | None = None,
    input_hash: str = "",
    db: Executor | None = None,
) -> SavedScreeningQuestions:
    """Перезаписать пакет под вакансию (upsert). Возвращает свежий набор.

    `input_hash` — хэш входа, которым собран этот пакет; по нему `generate_pack`
    решает, можно ли отдать сохранённое вместо повторного вызова LLM.
    """
    if not vacancy_id:
        raise ValueError("vacancy_id required")
    db = db or get_pool()
    hr_v = list(hr_questions or [])
    why_v = why_company or ""
    oral_v = oral_pitch or ""
    pitch_blocks_v = list(pitch_blocks or [])
    jd_brief_v = dict(jd_brief or {})
    row = await db.fetchrow(
        "insert into vacancy_screening_questions "
        "(account_id, vacancy_id, groups, hr_questions, why_company, oral_pitch, "
        "pitch_blocks, jd_brief, generated_at, input_hash) "
        "values ($1, $2, $3, $4, $5, $6, $7, $8, now(), $9) "
        "on conflict (account_id, vacancy_id) do update set "
        "groups = excluded.groups, "
        "hr_questions = excluded.hr_questions, "
        "why_company = excluded.why_company, "
        "oral_pitch = excluded.oral_pitch, "
        "pitch_blocks = excluded.pitch_blocks, "
        "jd_brief = excluded.jd_brief, "
        "generated_at = excluded.generated_at, "
        "input_hash = excluded.input_hash "
        f"returning {_COLS}",
        account_id,
        vacancy_id,
        groups,
        hr_v,
        why_v,
        oral_v,
        pitch_blocks_v,
        jd_brief_v,
        input_hash,
    )
    assert row is not None
    return _from_row(row_to_dict(row), vacancy_id)


async def merge_screening_questions(
    vacancy_id: str,
    *,
    account_id: int,
    hr_questions: list[dict[str, Any]] | None = None,
    groups: list[dict[str, Any]] | None = None,
    db: Executor | None = None,
) -> SavedScreeningQuestions:
    """Дописать вопросы в существующий пакет, не трогая легенду/мосты/`generated_at`."""
    if not vacancy_id:
        raise ValueError("vacancy_id required")
    db = db or get_pool()
    saved = await get_screening_questions(vacancy_id, account_id=account_id, db=db)
    if saved is None:
        raise ValueError("пакет скрининга ещё не собран")
    hr_v = list(hr_questions) if hr_questions is not None else list(saved.hr_questions)
    groups_v = list(groups) if groups is not None else list(saved.groups)
    row = await db.fetchrow(
        "update vacancy_screening_questions set "
        "hr_questions = $2, groups = $3 "
        "where vacancy_id = $1 and account_id = $4 "
        f"returning {_COLS}",
        vacancy_id,
        hr_v,
        groups_v,
        account_id,
    )
    assert row is not None
    return _from_row(row_to_dict(row), vacancy_id)


async def merge_screening_pitch(
    vacancy_id: str,
    *,
    account_id: int,
    oral_pitch: str,
    pitch_blocks: list[dict[str, Any]],
    why_company: str,
    jd_brief: dict[str, Any] | None = None,
    db: Executor | None = None,
) -> SavedScreeningQuestions:
    """Перезаписать только легенду в пакете, вопросы обеих сторон не трогать."""
    if not vacancy_id:
        raise ValueError("vacancy_id required")
    db = db or get_pool()
    saved = await get_screening_questions(vacancy_id, account_id=account_id, db=db)
    if saved is None:
        raise ValueError("пакет скрининга ещё не собран")
    jd_v = dict(jd_brief) if jd_brief is not None else dict(saved.jd_brief)
    row = await db.fetchrow(
        "update vacancy_screening_questions set "
        "oral_pitch = $2, pitch_blocks = $3, why_company = $4, "
        "jd_brief = $5, generated_at = now() "
        "where vacancy_id = $1 and account_id = $6 "
        f"returning {_COLS}",
        vacancy_id,
        oral_pitch or "",
        list(pitch_blocks),
        why_company or "",
        jd_v,
        account_id,
    )
    assert row is not None
    return _from_row(row_to_dict(row), vacancy_id)


__all__ = [
    "SavedScreeningQuestions",
    "get_screening_questions",
    "merge_screening_pitch",
    "merge_screening_questions",
    "save_screening_questions",
]
