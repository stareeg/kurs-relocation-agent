"""Сценарии скрининг-пакета, снятые с роутера.

Пакет = разбор вакансии (бриф) + легенда (рассказ и мосты) + вопросы (что спросят / что спросить).
Всё внутри домена `preparation`: контекст вакансии берём из сохранённой записи скоринга, пишем
в `screening_questions`. Роутер остаётся транспортом — включая NDJSON-кодирование потока.

Поток генерации отдаёт словари-события (`status` / `brief` / `pitch` / `questions` / `part_error`
/ `done`) с накопленным `partial`: при пересборке старые куски держатся на экране, пока не
придёт замена именно той части. Частичная деградация — как и была: упавший шаг шлёт `part_error`
и не рвёт остальные.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any, cast

from core.domains.preparation.interview.records import load_record
from core.domains.preparation.screening import VacancySelfPres, generate_self_pres_pack
from core.domains.preparation.screening.brief import JdBrief, build_jd_brief
from core.domains.preparation.screening.pack import generate_self_pres_pack_events
from core.domains.preparation.screening.pitch import (
    generate_screening_pitch,
    pitch_to_plain_text,
)
from core.domains.preparation.screening.questions import (
    HrQuestion,
    QuestionGroup,
    generate_more_ask_groups,
    generate_more_hr_questions,
)
from core.domains.preparation.screening.store import save_self_pres_pack
from core.domains.preparation.screening.style import PitchBlock
from core.domains.preparation.screening_questions import (
    SavedScreeningQuestions,
    get_screening_questions,
    merge_screening_pitch,
    merge_screening_questions,
)
from core.domains.preparation.vacancy_context import build_score_summary
from core.kernel.errors import InvalidInput, LlmError, StorageUnavailable, UpstreamError
from core.kernel.hashing import input_digest

logger = logging.getLogger(__name__)

NEEDS_PACK = "Сначала собери подготовку кнопкой «Подготовиться»"
_NO_PG = "Postgres недоступен"


async def load_pack(vacancy_id: str, *, account_id: int):
    """Сохранённый пакет под вакансию. Нет записи/нет PG → None (роутер отдаёт пустой ответ)."""
    return await get_screening_questions(vacancy_id, account_id=account_id)


async def generate_pack(
    vacancy_id: str, *, title: str, company: str, vacancy_text: str, account_id: int
) -> VacancySelfPres:
    """Собрать пакет одним проходом (без стрима) — путь бота и клиентов без NDJSON.

    L-19: вход не изменился с последней сборки → отдаём сохранённое, LLM не зовём.
    """
    text, summary = await _context(vacancy_id, vacancy_text, account_id=account_id)
    digest = _pack_input_hash(title, company, text, summary)
    existing = await get_screening_questions(vacancy_id, account_id=account_id)
    if existing is not None and existing.input_hash == digest and _saved_has_content(existing):
        return _to_self_pres(existing)
    try:
        pack = await generate_self_pres_pack(
            account_id=account_id,
            vacancy_id=vacancy_id,
            title=title,
            company=company,
            vacancy_text=text,
            score_summary=summary,
        )
    except ValueError as exc:
        raise InvalidInput(str(exc)) from exc
    pack.input_hash = digest
    return pack


async def persist_pack(vacancy_id: str, pack: VacancySelfPres, *, account_id: int):
    """Записать пакет (upsert). Нет PG → 503: собранный пакет нельзя потерять молча."""
    try:
        return await save_self_pres_pack(vacancy_id, pack, account_id=account_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("screening self_pres: сохранение не удалось (нет PG?): %s", exc)
        raise StorageUnavailable(_NO_PG) from exc


async def stream_pack(
    vacancy_id: str, *, title: str, company: str, vacancy_text: str, account_id: int
) -> AsyncIterator[dict[str, Any]]:
    """Поток сборки пакета: события с накопленным `partial`, в конце `done` с сохранённой записью.

    Ошибку не поднимаем наружу — SSE-соединение уже открыто, клиент ждёт кадр: последним
    уходит `{"type": "error"}` (транспорт A-14 кодирует в `event: error`).

    L-19: вход не изменился с последней сборки → сразу `done` с сохранённым, без LLM-вызовов.
    """
    try:
        text, summary = await _context(vacancy_id, vacancy_text, account_id=account_id)
        existing = await get_screening_questions(vacancy_id, account_id=account_id)
        digest = _pack_input_hash(title, company, text, summary)
        if existing is not None and existing.input_hash == digest and _saved_has_content(existing):
            yield {"type": "done", "saved": existing}
            return
        partial = _partial_from(vacancy_id, existing)
        async for event in generate_self_pres_pack_events(
            account_id=account_id,
            vacancy_id=vacancy_id,
            title=title,
            company=company,
            vacancy_text=text,
            score_summary=summary,
        ):
            etype = event.get("type")
            if etype in ("status", "part_error"):
                yield event
            elif etype == "done":
                pack = cast(VacancySelfPres, event["pack"])
                pack.input_hash = digest
                saved = await persist_pack(vacancy_id, pack, account_id=account_id)
                yield {"type": "done", "saved": saved}
            elif etype in _MERGE_KEYS:
                for key in _MERGE_KEYS[etype]:
                    partial[key] = event.get(key) or _EMPTY[key]
                yield {"type": etype, "partial": dict(partial)}
    except ValueError as exc:
        yield {"type": "error", "detail": str(exc)}
    except LlmError as exc:
        logger.error("screening self_pres OpenRouter error: %s", exc)
        yield {"type": "error", "detail": str(exc)}
    except Exception as exc:  # noqa: BLE001
        logger.error("screening self_pres stream error: %s", exc)
        yield {"type": "error", "detail": "не удалось собрать пакет"}


async def regenerate_pitch(
    vacancy_id: str, *, title: str, company: str, vacancy_text: str, account_id: int
):
    """Пересобрать только легенду (рассказ + мосты), вопросы не трогать."""
    saved = _require_pack(await get_screening_questions(vacancy_id, account_id=account_id))
    text, summary = await _context(vacancy_id, vacancy_text, account_id=account_id)
    brief = await _brief_for(saved, title=title, company=company, text=text, summary=summary)

    try:
        pitch = await generate_screening_pitch(
            account_id=account_id, brief=brief, title=title, company=company, score_summary=summary
        )
    except ValueError as exc:
        raise InvalidInput(str(exc)) from exc

    try:
        return await merge_screening_pitch(
            vacancy_id,
            account_id=account_id,
            oral_pitch=pitch_to_plain_text(pitch.blocks),
            pitch_blocks=[b.model_dump(mode="json") for b in pitch.blocks],
            why_company=pitch.why_company,
            jd_brief=brief.model_dump(mode="json"),
        )
    except ValueError as exc:
        raise InvalidInput(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.error("screening regen-pitch: сохранение не удалось: %s", exc)
        raise StorageUnavailable(_NO_PG) from exc


async def edit_pitch_manual(vacancy_id: str, *, oral_pitch: str, account_id: int):
    """Ручная правка «Рассказа об опыте» (закреплённое сообщение в чате Скринингов).

    Правка всегда схлопывает структурные `pitch_blocks` в плоский `oral_pitch` — после ручного
    редактирования единственный источник правды один текст, как у `vacancy_text` в Чатах.
    """
    saved = _require_pack(await get_screening_questions(vacancy_id, account_id=account_id))
    text = oral_pitch.strip()
    if not text:
        raise InvalidInput("Текст не может быть пустым")
    try:
        return await merge_screening_pitch(
            vacancy_id,
            account_id=account_id,
            oral_pitch=text,
            pitch_blocks=[],
            why_company=saved.why_company,
        )
    except ValueError as exc:
        raise InvalidInput(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.error("screening pitch edit: сохранение не удалось: %s", exc)
        raise StorageUnavailable(_NO_PG) from exc


async def more_questions(
    vacancy_id: str, *, kind: str, title: str, company: str, count: int, account_id: int
):
    """Догенерировать ещё ~count вопросов (`hr` — что спросят, иначе — что спросить) в пакет."""
    saved = _require_pack(await get_screening_questions(vacancy_id, account_id=account_id))
    record = await load_record(vacancy_id, account_id=account_id)
    summary = build_score_summary(record.score) if record else ""
    brief = JdBrief.model_validate(saved.jd_brief) if saved.jd_brief else JdBrief()

    try:
        if kind == "hr":
            merged = await _more_hr(
                saved, brief, title, company, summary, count, account_id=account_id
            )
            return await merge_screening_questions(
                vacancy_id, account_id=account_id, hr_questions=merged
            )
        merged_groups = await _more_ask(
            saved, brief, title, company, summary, count, account_id=account_id
        )
        return await merge_screening_questions(
            vacancy_id, account_id=account_id, groups=merged_groups
        )
    except ValueError as exc:
        raise InvalidInput(str(exc)) from exc
    except (LlmError, UpstreamError):
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("screening more-questions: сохранение не удалось: %s", exc)
        raise StorageUnavailable(_NO_PG) from exc


async def delete_question(vacancy_id: str, *, kind: str, question: str, account_id: int):
    """Удалить один вопрос из пакета (`hr` — из hr_questions, иначе — из groups).

    Сохраняет оставшиеся вопросы, легенду/мосты не трогает. Удаление по тексту вопроса —
    у LLM-пакета нет стабильных id, а вопрос уникален в рамках своей стороны.
    """
    saved = _require_pack(await get_screening_questions(vacancy_id, account_id=account_id))
    target = (question or "").strip()
    if not target:
        raise InvalidInput("Укажите вопрос для удаления")

    if kind == "hr":
        remaining = [
            q
            for q in saved.hr_questions
            if isinstance(q, dict) and str(q.get("question") or "").strip() != target
        ]
        removed = len(saved.hr_questions) - len(remaining)
        if removed == 0:
            raise InvalidInput("Вопрос не найден в пакете")
        return await merge_screening_questions(
            vacancy_id, account_id=account_id, hr_questions=remaining
        )

    remaining_groups: list[Any] = []
    removed = 0
    for group in saved.groups:
        if not isinstance(group, dict):
            remaining_groups.append(group)
            continue
        questions = [
            q
            for q in (group.get("questions") or [])
            if not (isinstance(q, dict) and str(q.get("question") or "").strip() == target)
        ]
        if len(questions) != len(group.get("questions") or []):
            removed += len(group.get("questions") or []) - len(questions)
        clone = dict(group)
        clone["questions"] = questions
        remaining_groups.append(clone)
    if removed == 0:
        raise InvalidInput("Вопрос не найден в пакете")
    return await merge_screening_questions(
        vacancy_id, account_id=account_id, groups=remaining_groups
    )


# --------------------------------------------------------------------------- внутреннее

#: Какие поля накопленного `partial` заменяет каждое событие потока.
_MERGE_KEYS: dict[str, tuple[str, ...]] = {
    "brief": ("jd_brief",),
    "pitch": ("pitch_blocks", "oral_pitch", "why_company"),
    "questions": ("hr_questions", "groups"),
}

#: Пустое значение поля `partial` — тип должен пережить провал шага.
_EMPTY: dict[str, Any] = {
    "jd_brief": {},
    "pitch_blocks": [],
    "oral_pitch": "",
    "why_company": "",
    "hr_questions": [],
    "groups": [],
}


def _pack_input_hash(title: str, company: str, text: str, summary: str) -> str:
    """L-19: хэш входа сборки пакета — совпадение с сохранённым избавляет от LLM-вызовов."""
    return input_digest(title, company, text, summary)


def _saved_has_content(saved: SavedScreeningQuestions) -> bool:
    return bool(
        saved.oral_pitch
        or saved.pitch_blocks
        or saved.hr_questions
        or saved.why_company
        or saved.groups
    )


def _to_self_pres(saved: SavedScreeningQuestions) -> VacancySelfPres:
    """Сохранённый пакет → `VacancySelfPres` (для повторного сохранения без пересборки)."""
    return VacancySelfPres(
        vacancy_id=saved.vacancy_id,
        jd_brief=JdBrief.model_validate(saved.jd_brief) if saved.jd_brief else JdBrief(),
        pitch_blocks=[PitchBlock.model_validate(b) for b in saved.pitch_blocks],
        oral_pitch=saved.oral_pitch,
        why_company=saved.why_company,
        hr_questions=[HrQuestion.model_validate(q) for q in saved.hr_questions],
        groups=[QuestionGroup.model_validate(g) for g in saved.groups],
        input_hash=saved.input_hash,
    )


async def _context(vacancy_id: str, vacancy_text: str, *, account_id: int) -> tuple[str, str]:
    """Текст вакансии и сводка оценки: приоритет у сохранённой записи, фолбэк — тело запроса."""
    record = await load_record(vacancy_id, account_id=account_id)
    text = (record.vacancy_text if record else "") or vacancy_text
    return text, (build_score_summary(record.score) if record else "")


def _partial_from(vacancy_id: str, existing) -> dict[str, Any]:
    """Стартовый `partial`: уже сохранённые куски, чтобы экран не мигал пустотой при пересборке."""
    partial: dict[str, Any] = {"vacancy_id": vacancy_id, **{k: v for k, v in _EMPTY.items()}}
    partial["generated_at"] = None
    if existing is None:
        return partial
    partial.update(
        {
            "pitch_blocks": list(existing.pitch_blocks or []),
            "oral_pitch": existing.oral_pitch or "",
            "why_company": existing.why_company or "",
            "hr_questions": list(existing.hr_questions or []),
            "groups": list(existing.groups or []),
            "jd_brief": dict(existing.jd_brief or {}),
            "generated_at": existing.generated_at.isoformat() if existing.generated_at else None,
        }
    )
    return partial


def _require_pack(saved):
    """Догенерация и пересборка легенды имеют смысл только поверх собранного пакета."""
    if saved is None or not (
        saved.hr_questions or saved.groups or saved.oral_pitch or saved.pitch_blocks
    ):
        raise InvalidInput(NEEDS_PACK)
    return saved


async def _brief_for(saved, *, title: str, company: str, text: str, summary: str) -> JdBrief:
    """Разбор вакансии из пакета; пустой — пробуем собрать заново, но без него тоже пишем рассказ."""
    brief = JdBrief.model_validate(saved.jd_brief) if saved.jd_brief else JdBrief()
    if brief.requirements or brief.role_reality:
        return brief
    try:
        return await build_jd_brief(
            title=title, company=company, vacancy_text=text, score_summary=summary
        )
    except Exception as exc:  # noqa: BLE001 — без разбора всё равно пишем рассказ
        logger.warning("screening regen-pitch: разбор вакансии не удался: %s", exc)
        return JdBrief()


async def _more_hr(saved, brief, title, company, summary, count, *, account_id: int) -> list[dict]:
    existing = [str(q.get("question") or "") for q in saved.hr_questions if isinstance(q, dict)]
    extra = await generate_more_hr_questions(
        account_id=account_id,
        brief=brief,
        title=title,
        company=company,
        score_summary=summary,
        existing=existing,
        count=count,
    )
    if not extra:
        raise UpstreamError("Не удалось получить новые вопросы")
    return list(saved.hr_questions) + [q.model_dump(mode="json") for q in extra]


async def _more_ask(saved, brief, title, company, summary, count, *, account_id: int) -> list[dict]:
    existing: list[str] = []
    for group in saved.groups:
        if not isinstance(group, dict):
            continue
        for q in group.get("questions") or []:
            if isinstance(q, dict) and q.get("question"):
                existing.append(str(q["question"]))
    extra = await generate_more_ask_groups(
        account_id=account_id,
        brief=brief,
        title=title,
        company=company,
        score_summary=summary,
        existing=existing,
        count=count,
    )
    if not extra:
        raise UpstreamError("Не удалось получить новые вопросы")
    return list(saved.groups) + [g.model_dump(mode="json") for g in extra]


__all__ = [
    "NEEDS_PACK",
    "delete_question",
    "generate_pack",
    "load_pack",
    "more_questions",
    "persist_pack",
    "regenerate_pitch",
    "stream_pack",
]
