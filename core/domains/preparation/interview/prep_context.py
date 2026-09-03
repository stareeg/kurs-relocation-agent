"""RD-21: контекст-сборщик подготовки — главный рычаг против «общих вопросов».

Один сборщик, блоки контекста (каждый — отдельная секция, пустые пропускаются), который
кормит ВСЕ промпты `core.domains.preparation.interview.prep` (`generate_prep_questions`, `answer_prep_chat`,
`build_sobes_context`) и `core.domains.preparation.interview.prep_pack.generate_prep_pack`. Раньше каждый потребитель
собирал часть этих данных сам (или не видел их вовсе) — теперь один сбор, один источник истины.

Блоки и приоритет усечения (если промпт когда-нибудь придётся резать) — 1 > 6 > 3 > 5 > 2 > 4 > 7 > 8:
1. Следующий этап из цепочки (`interview_stages`, RD-19/20) — формат+дата+слова HR.
2. Факты со слов HR — последняя `hr_confirmed`-ревизия скоринга
   (`core.domains.opportunities.score_revision`), БЕЗ нового LLM-вызова: переиспользуем уже
   извлечённые `rescore_from_hr_facts` факты.
3. Слабые темы — из дебрифов ЭТОЙ вакансии (все этапы) + дебрифов ЭТОГО формата (другие вакансии).
4. Сильные ответы — козыри кандидата из дебрифов этой вакансии, не тратить на них вопросы.
5. Фидбек рекрутёров по этой вакансии (`stage_outcomes`).
6. Уже спрошенное — вопросы прошлых дебрифов этой вакансии, с пометкой сильно/слабо отвечено.
7. Прошлые prep-сессии этого же этапа — не повторять вопросы дословно.
8. Долгая память (`career_facts`) — факты из прошлых разборов/заметок, глобально.

Каждый блок собирается best-effort: нет Postgres/данных → пустая строка, остальные блоки не
затронуты (тот же принцип, что `core.domains.preparation.interview.prep_pack` — подготовка не должна падать из-за
одного недоступного источника).
"""

from __future__ import annotations

import logging
from collections.abc import Coroutine
from typing import Any

from pydantic import BaseModel

from core.domains.opportunities.score_revision import load_score_revisions
from core.domains.pipeline.stage_outcome import load_stage_outcome_history
from core.domains.preparation.debrief import load_debrief_history
from core.domains.preparation.interview_stages import load_stages
from core.domains.preparation.models import STAGE_LABELS, STAGE_TYPE_LABELS
from core.domains.preparation.prep import load_prep_history
from core.platform.db.pool import Executor, get_pool

logger = logging.getLogger(__name__)

# PrepStage-значения, буквально совпадающие с interview_stages.stage_type (канон) — только
# для них есть смысл искать этап в цепочке. У screening/hr_final/other своей цепочки нет.
_CHAIN_STAGES = frozenset({"theory", "system_design", "live_coding", "business_case", "final"})

_DEBRIEF_HISTORY_LIMIT = 30
_WEAK_TOPICS_LIMIT = 15
_STRONG_ANSWERS_LIMIT = 8
_RECRUITER_FEEDBACK_LIMIT = 10
_ASKED_QUESTIONS_LIMIT = 20
_PAST_SESSIONS_LIMIT = 15


class PrepContext(BaseModel):
    """Блоки контекста подготовки. Пустая строка — блок пропускается при рендере."""

    next_stage: str = ""
    hr_facts: str = ""
    weak_topics: str = ""
    strong_answers: str = ""
    recruiter_feedback: str = ""
    asked_questions: str = ""
    past_sessions: str = ""
    # A-28: долгая память кандидата (career_facts) — глобально, не только эта вакансия.
    career_facts: str = ""

    def render(self) -> str:
        """Непустые блоки в промпт-секции. Порядок = приоритет усечения 1>6>3>5>2>4>7>8."""
        sections = [
            ("Следующий этап из цепочки собеса", self.next_stage),
            ("Уже спрошенное на прошлых этапах этой вакансии", self.asked_questions),
            ("Слабые темы (из прошлых разборов собесов)", self.weak_topics),
            ("Фидбек рекрутёров по этой вакансии", self.recruiter_feedback),
            ("Факты со слов HR", self.hr_facts),
            ("Сильные ответы кандидата (козыри)", self.strong_answers),
            ("Прошлые подготовки этого же этапа", self.past_sessions),
            ("Долгая память кандидата (career_facts)", self.career_facts),
        ]
        parts = [f"\n## {title}\n\n{body.strip()}\n" for title, body in sections if body.strip()]
        return "".join(parts)


def _format_dt(dt: Any) -> str:
    if dt is None:
        return "дата не назначена"
    return dt.strftime("%d.%m %H:%M МСК")


async def _next_stage_block(vacancy_id: str, stage: str, account_id: int, db: Executor) -> str:
    if stage not in _CHAIN_STAGES:
        return ""
    stages = await load_stages(vacancy_id, account_id=account_id, db=db)
    target = next((s for s in stages if s.stage_type == stage and s.status == "scheduled"), None)
    if target is None:
        return ""
    label = STAGE_TYPE_LABELS.get(target.stage_type, target.stage_type)
    lines = [f"Формат: {label}. {_format_dt(target.scheduled_at)}."]
    notes = target.notes.strip()
    if notes:
        lines.append(f"Слова HR: {notes}")
    lines.append(
        "Готовь ровно под этот формат. Если HR назвал детали (число задач, время, инструменты, "
        "тема) - используй их дословно, не выдумывай другое."
    )
    return "\n".join(lines)


async def _hr_facts_block(vacancy_id: str, account_id: int, db: Executor) -> str:
    from core.domains.pipeline.hr_facts import HRFacts

    revisions = await load_score_revisions(vacancy_id, limit=50, account_id=account_id, db=db)
    latest = next((r for r in revisions if r.basis == "hr_confirmed" and r.facts), None)
    if latest is None:
        return ""
    facts = HRFacts(**latest.facts)
    if not facts.is_meaningful():
        return ""
    return facts.to_prompt_block()


_LEVEL_LABEL = {"weak": "слабо", "medium": "средне"}


async def _weak_topics_block(vacancy_id: str, stage: str, account_id: int, db: Executor) -> str:
    """Слабые темы — из леджера компетенций, а не из сырых `topics_to_study` дебрифов.

    Источник — `competency_ledger.load_latest_topic_levels`: СВЕЖИЙ уровень каждой темы-канона,
    не вся история провалов скопом. Тема, ставшая `confident` в новом дебрифе, перестаёт быть
    weak/medium в леджере и САМА выпадает из фокуса — без ручной чистки. Леджер копится по
    аккаунту целиком (тема неспецифична вакансии), поэтому `vacancy_id`/`stage` здесь не
    фильтруют выборку, только оставлены для единообразия сигнатуры блоков.
    """
    from core.domains.preparation.competency import load_latest_topic_levels

    latest = await load_latest_topic_levels(account_id=account_id, db=db)
    weak = [t for t in latest if t.level in _LEVEL_LABEL]
    if not weak:
        return ""
    weak.sort(key=lambda t: (t.level != "weak", -t.created_at.timestamp()))
    lines = [
        f"- {t.topic_canon} (уровень: {_LEVEL_LABEL[t.level]})" for t in weak[:_WEAK_TOPICS_LIMIT]
    ]
    return "\n".join(lines)


async def _strong_answers_block(vacancy_id: str, account_id: int, db: Executor) -> str:
    records = await load_debrief_history(
        vacancy_id, limit=_DEBRIEF_HISTORY_LIMIT, account_id=account_id, db=db
    )
    answers: list[str] = []
    for record in records:
        for a in (record.analysis or {}).get("strong_answers") or []:
            a = str(a).strip()
            if a and a not in answers:
                answers.append(a)
    if not answers:
        return ""
    lines = "\n".join(f"- {a}" for a in answers[:_STRONG_ANSWERS_LIMIT])
    return f"{lines}\n\nЭто козыри кандидата - НЕ трать на них вопросы генерации, держи их в виду."


async def _recruiter_feedback_block(vacancy_id: str, account_id: int, db: Executor) -> str:
    records = await load_stage_outcome_history(
        vacancy_id, limit=_RECRUITER_FEEDBACK_LIMIT, account_id=account_id, db=db
    )
    lines: list[str] = []
    for r in records:
        feedback = (r.recruiter_feedback or "").strip()
        notes = (r.next_stage_notes or "").strip()
        if not feedback and not notes:
            continue
        parts = [p for p in (feedback, notes) if p]
        lines.append(f"- этап «{STAGE_LABELS.get(r.stage, r.stage)}»: " + "; ".join(parts))
    return "\n".join(lines)


async def _asked_questions_block(vacancy_id: str, account_id: int, db: Executor) -> str:
    """Уже заданное на прошлых этапах ЭТОЙ вакансии, с пометкой сильно/слабо.

    RD-24: слабые вопросы несут дословный `how_to_improve` дебрифа (не общая пометка) — это и есть
    материал для секции «Не повторить» в шпаргалках sobes.tech/prep-pack, без нового LLM-вызова.
    """
    records = await load_debrief_history(
        vacancy_id, limit=_DEBRIEF_HISTORY_LIMIT, account_id=account_id, db=db
    )
    lines: list[str] = []
    seen: set[str] = set()
    for record in records:
        analysis = record.analysis or {}
        weak_by_question = {
            str(w.get("question", "")).strip(): w
            for w in (analysis.get("weak_answers") or [])
            if str(w.get("question", "")).strip()
        }
        for q in analysis.get("questions_asked") or []:
            q = str(q).strip()
            if not q or q in seen:
                continue
            seen.add(q)
            weak = weak_by_question.get(q)
            if weak is not None:
                improve = str(weak.get("how_to_improve", "")).strip()
                tag = (
                    f"было слабо - {improve}" if improve else "было слабо - зайди с другой стороны"
                )
            else:
                tag = "ответил уверенно, не повторяй"
            lines.append(f"- {q} ({tag})")
            if len(lines) >= _ASKED_QUESTIONS_LIMIT:
                break
        if len(lines) >= _ASKED_QUESTIONS_LIMIT:
            break
    return "\n".join(lines)


async def _career_facts_block(account_id: int, db: Executor) -> str:
    """A-28: активные факты из `career_facts` (в т.ч. извлечённые из прошлых разборов)."""
    from core.domains.career.facts import load_facts_context_block

    return await load_facts_context_block(account_id=account_id, db=db)


async def _past_sessions_block(vacancy_id: str, stage: str, account_id: int, db: Executor) -> str:
    """Прошлые prep-сессии этапа — с поправкой на RD-22 (выпал/не выпал).

    `unused` (заготовлен, но на прошлом этапе не пригодился) сюда не попадает вовсе - таскать в
    следующую генерацию вопрос, который уже проверен как нерелевантный, только шумит промпт
    (дословный запрос владельца). `asked` остаётся с пометкой - если ответ на него был
    слабым (есть в `weak_answers` дебрифов вакансии), явный приоритет "жди снова, готовь глубже".
    Ещё не сматченные (этап не пройден/не разобран) идут как раньше, без пометки.
    """
    sessions = await load_prep_history(vacancy_id, limit=20, account_id=account_id, db=db)

    weak_texts: set[str] = set()
    for record in await load_debrief_history(
        vacancy_id, limit=_DEBRIEF_HISTORY_LIMIT, account_id=account_id, db=db
    ):
        for w in (record.analysis or {}).get("weak_answers") or []:
            q = str((w or {}).get("question", "")).strip()
            if q:
                weak_texts.add(q)

    lines: list[str] = []
    seen: set[str] = set()
    for s in sessions:
        if s.stage != stage:
            continue
        for q in s.questions:
            if not isinstance(q, dict):
                continue
            text = str(q.get("text", "")).strip()
            outcome = q.get("outcome")
            if not text or text in seen or outcome == "unused":
                continue
            seen.add(text)
            if outcome == "asked":
                tag = (
                    "выпал, ответ был слабым - жди снова, готовь глубже"
                    if text in weak_texts
                    else "уже выпадал"
                )
                lines.append(f"- {text} ({tag})")
            else:
                lines.append(f"- {text}")
    if not lines:
        return ""
    body = "\n".join(lines[:_PAST_SESSIONS_LIMIT])
    return f"{body}\n\nНе повторяй эти вопросы дословно - давай новые углы на те же темы."


async def _safe(coro: Coroutine[Any, Any, str], label: str) -> str:
    try:
        return await coro
    except Exception as exc:  # noqa: BLE001 — блок best-effort, не валит остальной контекст
        logger.debug("prep_context: блок %s недоступен: %s", label, exc)
        return ""


async def gather_prep_context(
    vacancy_id: str, stage: str, *, account_id: int, db: Executor | None = None
) -> PrepContext:
    """Собрать блоки контекста подготовки под (vacancy_id, stage).

    Нет vacancy_id (например запрос без сохранённой вакансии) → пустой контекст, не ошибка.
    Блоки независимы и необязательны — A-13 Pipeline гоняет их параллельно; упавший
    блок даёт пустую строку (как прежний `_safe`).
    """
    from core.app.pipeline import Pipeline, Step

    if not vacancy_id:
        return PrepContext()
    db = db or get_pool()

    steps = [
        Step(
            "next_stage",
            lambda _c: _safe(_next_stage_block(vacancy_id, stage, account_id, db), "next_stage"),
            required=False,
            default_factory=str,
        ),
        Step(
            "hr_facts",
            lambda _c: _safe(_hr_facts_block(vacancy_id, account_id, db), "hr_facts"),
            required=False,
            default_factory=str,
        ),
        Step(
            "weak_topics",
            lambda _c: _safe(_weak_topics_block(vacancy_id, stage, account_id, db), "weak_topics"),
            required=False,
            default_factory=str,
        ),
        Step(
            "strong_answers",
            lambda _c: _safe(_strong_answers_block(vacancy_id, account_id, db), "strong_answers"),
            required=False,
            default_factory=str,
        ),
        Step(
            "recruiter_feedback",
            lambda _c: _safe(
                _recruiter_feedback_block(vacancy_id, account_id, db), "recruiter_feedback"
            ),
            required=False,
            default_factory=str,
        ),
        Step(
            "asked_questions",
            lambda _c: _safe(_asked_questions_block(vacancy_id, account_id, db), "asked_questions"),
            required=False,
            default_factory=str,
        ),
        Step(
            "past_sessions",
            lambda _c: _safe(
                _past_sessions_block(vacancy_id, stage, account_id, db), "past_sessions"
            ),
            required=False,
            default_factory=str,
        ),
        Step(
            "career_facts",
            lambda _c: _safe(_career_facts_block(account_id, db), "career_facts"),
            required=False,
            default_factory=str,
        ),
    ]
    results = await Pipeline(steps, name="prep_context").run()
    return PrepContext(
        next_stage=results.get("next_stage") or "",
        hr_facts=results.get("hr_facts") or "",
        weak_topics=results.get("weak_topics") or "",
        strong_answers=results.get("strong_answers") or "",
        recruiter_feedback=results.get("recruiter_feedback") or "",
        asked_questions=results.get("asked_questions") or "",
        past_sessions=results.get("past_sessions") or "",
        career_facts=results.get("career_facts") or "",
    )


__all__ = ["PrepContext", "gather_prep_context"]
