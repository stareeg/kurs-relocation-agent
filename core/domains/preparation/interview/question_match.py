"""RD-22/RD-23: жизненный цикл вопросов подготовки (выпал/не выпал) и канонизация тем компетенций.

RD-22. Запрос владельца дословно: «после прошедшего собеса не имеет смысла тащить в следующий этап
теоретические вопросы, которые не выпали». Вопросы prep-сессии до этой задачи были мёртвым jsonb —
сессия завершалась, связь с реальным собесом не устанавливалась.

Механика. После сохранения дебрифа этапа X (`api/routers/debrief.py`, рядом с авто-прогрессом
цепочки RD-19) — best-effort LLM-матчинг: список А = вопросы prep-сессий ЭТОЙ вакансии и ЭТОГО
этапа, ещё не размеченные (`outcome is None`), список Б = `questions_asked` дебрифа (реально
заданные, слова интервьюера). Дешёвый structured-вызов (haiku, тир `extract`) сопоставляет их
семантически (перефразировка — не строковое совпадение) и возвращает индексы вопросов из списка А,
которые реально прозвучали. Остальные помечаются `unused`.

Хранение — прямо в `prep_sessions.questions` (поле `outcome` на элементе, RD-22 сознательно не
заводит отдельную таблицу — тот же принцип, что и остальной jsonb в этом репозитории).

Cost-гард — естественный, без regex-предфильтра (в отличие от RD-15/20, где триггер — любое
входящее HR-сообщение, здесь триггер — осознанное действие владельца «разобрать собес», в неделю
несколько раз): LLM не дёргается, если нет несматченных вопросов ИЛИ дебриф не назвал ни одного
реально заданного вопроса.

RD-23. `competency_map` каждого дебрифа называет темы своими словами («eval для RAG» /
«RAG evaluation» — одна и та же тема) — без канонизации леджер (`core.domains.preparation.competency`) рассыпался
бы на дубли и траекторию было бы не построить. `canonicalize_topics` — та же задача, что RD-22-
матчинг (семантическое сопоставление haiku'ой), поэтому один модуль: для каждой новой темы дебрифа
ищем среди уже принятых канонов совпадение по смыслу, иначе тема становится новым каноном сама
(первое упоминание задаёт написание). `record_competency_ledger_safe` — best-effort хук рядом с
`match_session_questions_safe` в write-path дебрифа: канонизирует `competency_map` и дописывает
леджер.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from core.domains.preparation.competency import (
    CompetencyEntry,
    load_distinct_canon_topics,
    save_competency_entries,
)
from core.domains.preparation.models import MockCompetency, QuestionMastery
from core.domains.preparation.prep import (
    PrepSession,
    load_prep_history,
    update_prep_session_questions,
)
from core.kernel import ports
from core.platform.db.pool import Executor, get_pool
from core.platform.observability import event

logger = logging.getLogger(__name__)

_SYSTEM = """\
Ты сверяешь подготовку кандидата к собеседованию с тем, что реально спрашивали на прошедшем этапе.

Список А — вопросы, которые кандидат заготовил заранее (пронумерованы).
Список Б — вопросы, которые реально прозвучали на собеседовании (по памяти кандидата, своими \
словами, не обязательно дословно).

Для каждого вопроса из списка А определи, задавали ли его на собесе — по смыслу, не по точному \
совпадению текста («как работает attention» и «объясни механизм внимания в трансформере» — один \
и тот же вопрос). Разные темы, даже близкие, не считаются совпадением («RAG» и «fine-tuning» — \
разные вопросы).

Верни пары "candidate" (индекс вопроса из списка А) → "asked" (индекс вопроса из списка Б), для \
каждого вопроса из списка А, который точно прозвучал. Если сомневаешься — не включай пару \
(лучше пропустить реально заданный, чем ложно засчитать незаданный). Один вопрос из списка А \
может соответствовать только одному вопросу из списка Б; если кандидат объединил два вопроса в \
один ответ — сопоставь с первым по смыслу.
"""


class _MatchItem(BaseModel):
    candidate: int
    asked: int


class _MatchResult(BaseModel):
    matches: list[_MatchItem] = Field(default_factory=list)


def _normalize_question(text: str) -> str:
    """Вопрос → сравнимая форма (регистр/пробелы) для поиска уровня ответа из дебрифа."""
    return " ".join(str(text or "").strip().casefold().split())


def _with_mastery(item: dict[str, Any], outcome: str, mastery: str | None) -> dict[str, Any]:
    """Вопрос prep-сессии + outcome/mastery из матчинга (RD-22b); mastery None → поле не трогаем,
    чтобы фронт честно показал «Под вопросом», а не выдуманную оценку."""
    patched = {**item, "outcome": outcome}
    if mastery is not None:
        patched["mastery"] = mastery
    return patched


def _build_user_prompt(candidates: list[str], asked: list[str]) -> str:
    list_a = "\n".join(f"{i}. {text}" for i, text in enumerate(candidates))
    list_b = "\n".join(f"{i}. {text}" for i, text in enumerate(asked))
    return f"Список А (заготовлено):\n{list_a}\n\nСписок Б (реально спрашивали):\n{list_b}"


async def _call_llm(candidates: list[str], asked: list[str]) -> dict[int, int]:
    """candidate-индекс → asked-индекс для пар, которые LLM признала совпавшими."""
    result = await ports.llm().structured(
        "question_match",
        system=_SYSTEM,
        user=_build_user_prompt(candidates, asked),
        schema=_MatchResult,
        temperature=0.0,
    )
    valid_c = set(range(len(candidates)))
    valid_a = set(range(len(asked)))
    out: dict[int, int] = {}
    for m in result.matches:
        if m.candidate in valid_c and m.asked in valid_a and m.candidate not in out:
            out[m.candidate] = m.asked
    return out


def _unresolved_candidates(
    sessions: list[PrepSession], stage: str
) -> list[tuple[PrepSession, int, str]]:
    """(сессия, индекс вопроса в сессии, текст) для вопросов этого этапа без `outcome`."""
    out: list[tuple[PrepSession, int, str]] = []
    for session in sessions:
        if session.stage != stage:
            continue
        for idx, q in enumerate(session.questions):
            if not isinstance(q, dict):
                continue
            text = str(q.get("text", "")).strip()
            if text and q.get("outcome") is None:
                out.append((session, idx, text))
    return out


async def match_session_questions(
    vacancy_id: str,
    stage: str,
    questions_asked: list[str],
    *,
    account_id: int,
    db: Executor | None = None,
    question_mastery: list[QuestionMastery] | None = None,
) -> int:
    """Сматчить несматченные вопросы prep-сессий (vacancy_id, stage) с реально заданными.

    Возвращает число вопросов, помеченных `asked`. Нет кандидатов/нет заданных вопросов → 0,
    без LLM-вызова (естественный cost-гард).

    `question_mastery` — оценка ответа по каждому реально заданному вопросу из дебрифа: уровень
    переносится на сматченный вопрос подготовки, чтобы фронт показал «Сильно/Средне/Слабо».
    """
    asked = [q.strip() for q in questions_asked if q and q.strip()]
    if not vacancy_id or not stage or not asked:
        return 0
    db = db or get_pool()

    # Нормализованный вопрос → уровень ответа (RD-22b); вопросы без ответа в списке отсутствуют.
    mastery_by_question: dict[str, str] = {}
    for m in question_mastery or []:
        if m.question.strip():
            mastery_by_question[_normalize_question(m.question)] = m.level

    sessions = await load_prep_history(vacancy_id, limit=20, account_id=account_id, db=db)
    candidates = _unresolved_candidates(sessions, stage)
    if not candidates:
        return 0

    texts = [text for _, _, text in candidates]
    asked_idx = await _call_llm(texts, asked)

    by_session: dict[int, list[dict[str, Any]]] = {}
    for pos, (session, q_idx, _text) in enumerate(candidates):
        if session.id is None:
            continue
        questions = by_session.setdefault(session.id, list(session.questions))
        if pos in asked_idx:
            asked_position = asked_idx[pos]
            matched_question = asked[asked_position] if asked_position < len(asked) else ""
            mastery = mastery_by_question.get(_normalize_question(matched_question))
            questions[q_idx] = _with_mastery(questions[q_idx], "asked", mastery)
        else:
            questions[q_idx] = {**questions[q_idx], "outcome": "unused"}

    for session_id, questions in by_session.items():
        await update_prep_session_questions(session_id, questions, account_id=account_id, db=db)

    event(
        logger,
        "LLM",
        "question_match: сопоставлено %d из %d",
        len(asked_idx),
        len(candidates),
        vacancy_id=vacancy_id,
        stage=stage,
        candidates=len(candidates),
        matched=len(asked_idx),
    )
    return len(asked_idx)


async def match_session_questions_safe(
    vacancy_id: str,
    stage: str,
    questions_asked: list[str],
    *,
    account_id: int,
    db: Executor | None = None,
    question_mastery: list[QuestionMastery] | None = None,
) -> None:
    """Best-effort обёртка для write-path дебрифа: исключения не валят сохранение разбора."""
    try:
        await match_session_questions(
            vacancy_id,
            stage,
            questions_asked,
            account_id=account_id,
            db=db,
            question_mastery=question_mastery,
        )
    except Exception as exc:  # noqa: BLE001 — фоновый best-effort
        logger.warning("question_match: vacancy_id=%s упал (best-effort): %s", vacancy_id, exc)


_CANON_SYSTEM = """\
Ты приводишь темы карты компетенций кандидата к единому канону, чтобы одна и та же тема,
названная разными словами в разных разборах собеса, не считалась разными темами.

Список А — уже принятые названия тем (канон), пронумерован.
Список Б — новые темы из свежего разбора, которые нужно сопоставить с каноном, пронумерован.

Для каждой темы из списка Б определи, есть ли в списке А та же тема другими словами («eval для
RAG» и «RAG evaluation» — одна тема; «attention» и «трансформеры» — разные, не путай смежные темы).
Если совпадение есть — верни номер темы из списка А. Если темы в каноне ещё нет — верни -1.
"""


class _CanonResult(BaseModel):
    canon_indices: list[int] = Field(default_factory=list)


def _build_canon_prompt(new_topics: list[str], existing_canon: list[str]) -> str:
    list_a = "\n".join(f"{i}. {text}" for i, text in enumerate(existing_canon))
    list_b = "\n".join(f"{i}. {text}" for i, text in enumerate(new_topics))
    return f"Список А (канон):\n{list_a}\n\nСписок Б (новые темы):\n{list_b}"


async def canonicalize_topics(new_topics: list[str], existing_canon: list[str]) -> list[str]:
    """Свести новые темы к уже принятому канону (1:1 с `new_topics`).

    Пустой `existing_canon` (первый дебриф вообще) — канонизировать не с чем, темы становятся
    каноном сами собой, без LLM-вызова (естественный cost-гард).
    """
    cleaned = [t.strip() for t in new_topics if t.strip()]
    if not cleaned:
        return []
    if not existing_canon:
        return cleaned

    result = await ports.llm().structured(
        "competency_canon",
        system=_CANON_SYSTEM,
        user=_build_canon_prompt(cleaned, existing_canon),
        schema=_CanonResult,
        temperature=0.0,
    )
    indices = result.canon_indices
    out: list[str] = []
    for i, topic in enumerate(cleaned):
        idx = indices[i] if i < len(indices) else -1
        out.append(existing_canon[idx] if 0 <= idx < len(existing_canon) else topic)
    return out


async def record_competency_ledger(
    vacancy_id: str,
    stage: str,
    debrief_id: int | None,
    competency_map: list[MockCompetency],
    *,
    account_id: int,
    db: Executor | None = None,
) -> int:
    """Канонизировать `competency_map` дебрифа и дописать леджер. Возвращает число строк.

    Нет вакансии/строк карты/debrief_id (не сохранился разбор - нет PG) → 0, без LLM-вызова.
    """
    if not vacancy_id or not competency_map or debrief_id is None:
        return 0
    db = db or get_pool()

    existing_canon = await load_distinct_canon_topics(account_id=account_id, db=db)
    raw_topics = [c.topic.strip() for c in competency_map if c.topic.strip()]
    canon_topics = await canonicalize_topics(raw_topics, existing_canon)

    entries = [
        CompetencyEntry(
            topic_canon=canon,
            level=c.level,
            evidence=c.evidence.strip(),
            vacancy_id=vacancy_id,
            stage=stage,
            debrief_id=debrief_id,
        )
        for c, canon in zip(
            (c for c in competency_map if c.topic.strip()), canon_topics, strict=True
        )
    ]
    await save_competency_entries(entries, account_id=account_id, db=db)
    logger.info(
        "competency_ledger: vacancy_id=%s stage=%s debrief_id=%s topics=%d",
        vacancy_id,
        stage,
        debrief_id,
        len(entries),
    )
    return len(entries)


async def record_competency_ledger_safe(
    vacancy_id: str,
    stage: str,
    debrief_id: int | None,
    competency_map: list[MockCompetency],
    *,
    account_id: int,
    db: Executor | None = None,
) -> None:
    """Best-effort обёртка для write-path дебрифа: исключения не валят сохранение разбора."""
    try:
        await record_competency_ledger(
            vacancy_id, stage, debrief_id, competency_map, account_id=account_id, db=db
        )
    except Exception as exc:  # noqa: BLE001 — фоновый best-effort
        logger.warning("competency_ledger: vacancy_id=%s упал (best-effort): %s", vacancy_id, exc)


__all__ = [
    "match_session_questions",
    "match_session_questions_safe",
    "canonicalize_topics",
    "record_competency_ledger",
    "record_competency_ledger_safe",
]
