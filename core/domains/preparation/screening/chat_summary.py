"""Саммари чата подготовки (Скрининги) — под кнопку «В Telegram» в чат-панели: короткое резюме
переписки, чтобы продолжить разговор про вакансию в боте, не пересказывая её с нуля.
"""

from __future__ import annotations

from pathlib import Path

from core.domains.opportunities.prompt import CANDIDATE_IDENTITY_TOKEN, load_candidate_identity
from core.domains.preparation.llm import SCREENING_CHAT_SUMMARY
from core.kernel import ports

_PROMPT = Path(SCREENING_CHAT_SUMMARY)
_NO_CONTENT = "Предметного разговора пока не было."

_ROLE_LABEL = {"user": "Кандидат", "assistant": "Агент"}


def _format_history(messages: list[tuple[str, str]]) -> str:
    lines = []
    for role, content in messages:
        text = content.strip()
        if not text:
            continue
        lines.append(f"{_ROLE_LABEL.get(role, role)}: {text}")
    return "\n\n".join(lines)


async def _load_system_prompt(*, account_id: int) -> str:
    from core.domains.profile.structured_store import read_resume_data_for_account

    resume_data = await read_resume_data_for_account(account_id)
    raw = _PROMPT.read_text(encoding="utf-8")
    return raw.replace(CANDIDATE_IDENTITY_TOKEN, load_candidate_identity(data=resume_data))


async def summarize_screening_chat(
    messages: list[tuple[str, str]], *, account_id: int, title: str = "", company: str = ""
) -> str:
    """Короткое резюме переписки «Агент»-чата Скринингов. Пустая/служебная переписка → заглушка
    без LLM-вызова — нечего сжимать."""
    history_text = _format_history(messages)
    if not history_text:
        return _NO_CONTENT

    vacancy = " — ".join(p for p in (company, title) if p) or "вакансия без названия"
    user = f"## Вакансия\n\n{vacancy}\n\n## Переписка\n\n{history_text}"
    raw = await ports.llm().complete(
        "screening_chat_summary", system=await _load_system_prompt(account_id=account_id), user=user
    )
    return raw.strip() or _NO_CONTENT


__all__ = ["summarize_screening_chat"]
