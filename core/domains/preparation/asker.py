"""LLM Q&A по вакансии.

Транспорт — порт `kernel.ports.llm().complete(messages=…)` (фича `qa`). Enrichment-bundle — из Postgres
(`core.domains.preparation.interview_stages.load_bundle`); api прокидывает bundle явно,
сентинел `_UNSET` оставляет точку авто-подгрузки из PG для прямых вызовов.
"""

from __future__ import annotations

import logging

from core.config import get_settings
from core.domains.assistant.models import AskMessage
from core.domains.preparation.models import ScoreResult, VacancyRecord
from core.domains.preparation.prompts import build_qa_system_prompt
from core.domains.preparation.vacancy_context import build_first_user_message
from core.kernel import ports
from core.kernel.errors import LlmError

logger = logging.getLogger(__name__)

# Сентинел: bundle не передан → подгружаем из Postgres. Если передан явно (в т.ч. None) —
# используем как есть; так api прокидывает enrichment из PG (S4/S5).
_UNSET = object()


async def _load_pg_bundle(vacancy_id: str, *, account_id: int | None):
    """Best-effort enrichment+этапы из Postgres; None, если PG/account_id недоступен."""
    if account_id is None:
        return None
    try:
        from core.domains.preparation.interview_stages import load_bundle

        return await load_bundle(vacancy_id, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — Q&A работает и без enrichment
        logger.debug("Q&A: bundle из Postgres недоступен (%s): %s", vacancy_id, exc)
        return None


def build_qa_messages(
    record: VacancyRecord,
    question: str,
    history: list[AskMessage],
    bundle=None,
) -> list[dict[str, str]]:
    """История + текущий вопрос без system (system уходит отдельно под cache_prefix)."""
    messages: list[dict[str, str]] = []

    if not history:
        messages.append(
            {
                "role": "user",
                "content": build_first_user_message(record, question, bundle),
            }
        )
        return messages

    first = True
    for msg in history:
        content = msg.content
        if first and msg.role == "user":
            content = build_first_user_message(record, msg.content, bundle)
            first = False
        messages.append({"role": msg.role, "content": content})

    messages.append({"role": "user", "content": question.strip()})
    return messages


async def ask_about_vacancy(
    record: VacancyRecord,
    question: str,
    history: list[AskMessage] | None = None,
    *,
    bundle=_UNSET,
    account_id: int | None = None,
) -> str:
    if not get_settings().openrouter_api_key:
        raise LlmError("OPENROUTER_API_KEY не задан")

    history = history or []
    if bundle is _UNSET:
        vid = record.vacancy_id
        bundle = await _load_pg_bundle(vid, account_id=account_id) if vid else None
    messages = build_qa_messages(record, question, history, bundle)

    answer = await ports.llm().complete(
        "qa",
        system=await build_qa_system_prompt(account_id=account_id),
        messages=messages,
        temperature=0.3,
    )
    return answer.strip()


def record_from_request_fallback(
    vacancy_id: str,
    *,
    vacancy_text: str,
    title: str | None = None,
    company: str | None = None,
    salary_text: str | None = None,
    score: ScoreResult | None = None,
) -> VacancyRecord:
    """Минимальный VacancyRecord из payload extension, если в БД нет записи."""
    if score is None:
        score = ScoreResult.model_validate(
            {
                "overall_score": 0,
                "recommendation": "maybe",
                "remote_abroad_compat": {"level": "risky", "reasoning": "нет оценки"},
                "grade_match": {"level": "match", "reasoning": "нет оценки"},
                "salary": {
                    "meets_min": False,
                    "value_or_range": salary_text or "",
                    "estimated_range": "",
                    "note": "оценка недоступна",
                },
                "role_content_match": {"score": 0, "matched_niche": [], "reasoning": ""},
                "burnout_risk": {"level": "medium", "reasoning": "нет оценки"},
                "company_type": "unknown",
                "pros": ["—"],
                "cons": ["—"],
                "red_flags": [],
                "one_line_verdict": "Оценка недоступна — ответ только по тексту вакансии",
            }
        )

    return VacancyRecord(
        vacancy_id=vacancy_id,
        vacancy_text=vacancy_text,
        title=title,
        company=company,
        salary_text=salary_text,
        score=score,
    )
