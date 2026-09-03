"""FR2-53: скоринг на «только шапке» — to_markdown и сборка промпта без выдуманного опыта."""

from __future__ import annotations

from pathlib import Path

from core.domains.profile.model import (
    Contacts,
    DesiredPosition,
    Personal,
    ResumeData,
    SearchCriteria,
    to_markdown,
)
from core.domains.opportunities.prompt import (
    _ANTI_HALLUCINATION_TOKEN,
    _INSTRUCTIONS_TOKEN,
    _RESUME_TOKEN,
    _SPOTLIGHT_TOKEN,
)


def _header_only_resume() -> ResumeData:
    return ResumeData(
        personal=Personal(full_name="Иван Иванов", city="Москва", work_countries=["Россия"]),
        contacts=Contacts(phone="+79991234567", email="a@b.ru"),
        position=DesiredPosition(
            title="Lead LLM Engineer",
            salary_min=450_000,
            salary_comfortable=550_000,
            schedule=["Удалённо"],
            grade=["Senior", "Lead"],
        ),
        search_criteria=SearchCriteria(
            niches=["LLM / agentic", "RAG"],
            target_companies=["Яндекс"],
            avoid_companies=[],
            dealbreakers=[],
        ),
        experience=[],
        key_skills=[],
        about="",
    )


def test_to_markdown_header_only_does_not_crash_or_invent_experience() -> None:
    md = to_markdown(_header_only_resume())
    assert "Lead LLM Engineer" in md
    assert "450" in md or "450000" in md or "450 000" in md
    assert "Удалённо" in md
    assert "Приоритеты (по убыванию)" in md
    assert "## Опыт работы" not in md
    assert "**Навыки:**" not in md
    assert "## Дополнительная информация" not in md
    # Секция навыков может быть пустой оболочкой под языки — без выдуманных тегов.
    assert "LangGraph" not in md
    assert "Сбер" not in md


def test_system_prompt_assembles_with_partial_resume_and_partial_rule() -> None:
    """Шаблон system.md + частичное резюме → валидная подстановка; есть правило FR2-53."""
    root = Path.cwd()
    template = (root / "prompts/opportunities/system.md").read_text(encoding="utf-8")
    instructions = (root / "prompts/opportunities/instructions.md").read_text(encoding="utf-8")
    resume_md = to_markdown(_header_only_resume())

    assert "{{RESUME}}" in template
    assert "Частично заполненное резюме" in template
    assert "Не додумывай" in template

    assembled = (
        template.replace(_RESUME_TOKEN, resume_md)
        .replace(_INSTRUCTIONS_TOKEN, instructions)
        .replace(_ANTI_HALLUCINATION_TOKEN, "(anti)")
        .replace(_SPOTLIGHT_TOKEN, "(spotlight)")
    )
    assert "{{RESUME}}" not in assembled
    assert "{{INSTRUCTIONS}}" not in assembled
    assert "Lead LLM Engineer" in assembled
    assert "## Опыт работы" not in assembled
    assert "Частично заполненное резюме" in assembled
