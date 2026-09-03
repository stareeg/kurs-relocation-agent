"""FR3-56 / план 2026-07-23 шаги 4/6/7/8 + доп. усиление надёжности: промпты/схема пакета
скрининга - четыре промпта (разбор вакансии, рассказ, вопросы HR часть A, вопросы к HR часть B)
объявляют те же ключи, что модели, и `core.domains.preparation.screening.pack.VacancySelfPres` собирает их в один
канонический пакет. Части A/B вопросов разведены по отдельным промптам/вызовам (см. докстринг
`core/screening/questions.py`) - живая проверка шага 16 поймала случай, когда объединённая схема
роняла обязательное поле `question` во всех группах части B."""

from __future__ import annotations

from pathlib import Path

from core.domains.preparation.screening.pack import VacancySelfPres

_JD_BRIEF_PROMPT = Path("prompts/preparation/screening/jd_brief.md")
_PITCH_PROMPT = Path("prompts/preparation/screening/pitch.md")
_HR_QUESTIONS_PROMPT = Path("prompts/preparation/screening/hr_questions.md")
_GROUPS_PROMPT = Path("prompts/preparation/screening/questions.md")

_JD_BRIEF_KEYS = (
    "role_reality",
    "product_context",
    "requirements",
    "unknowns",
    "hooks",
    "jargon",
)
_PITCH_KEYS = ("blocks", "why_company")
_HR_QUESTIONS_KEYS = ("hr_questions", "requirement")
_GROUPS_KEYS = ("groups",)

# Зашитый список рубрик из старого self_pres.md - в новом questions.md их быть не должно
# (план 2026-07-23, шаг 7: модель придумывает рубрики под вакансию сама).
_HARDCODED_RUBRICS = (
    "Роль и задачи",
    "Команда и процессы",
    "Технологии и качество",
    "Удалёнка и формат",
    "Деньги и рост",
    "Красные флаги",
)


def test_jd_brief_prompt_declares_schema() -> None:
    text = _JD_BRIEF_PROMPT.read_text(encoding="utf-8")
    assert text.strip(), "промпт jd_brief пуст"
    for key in _JD_BRIEF_KEYS:
        assert f'"{key}"' in text, f"в промпте нет ключа JSON {key!r}"


def test_pitch_prompt_declares_schema() -> None:
    text = _PITCH_PROMPT.read_text(encoding="utf-8")
    assert text.strip(), "промпт pitch пуст"
    for key in _PITCH_KEYS:
        assert f'"{key}"' in text, f"в промпте нет ключа JSON {key!r}"


def test_hr_questions_prompt_declares_schema() -> None:
    text = _HR_QUESTIONS_PROMPT.read_text(encoding="utf-8")
    assert text.strip(), "промпт hr_questions пуст"
    for key in _HR_QUESTIONS_KEYS:
        assert f'"{key}"' in text, f"в промпте нет ключа JSON {key!r}"


def test_hr_questions_prompt_uses_oral_style_token() -> None:
    """draft_answer читают вслух - должен применяться тот же словарь устного стиля, что у
    легенды (`prompts/preparation/screening/oral_style.md`), а не только собственные словесные правила."""
    text = _HR_QUESTIONS_PROMPT.read_text(encoding="utf-8")
    assert "{{ORAL_STYLE}}" in text


def test_groups_prompt_declares_schema() -> None:
    text = _GROUPS_PROMPT.read_text(encoding="utf-8")
    assert text.strip(), "промпт questions (часть B) пуст"
    for key in _GROUPS_KEYS:
        assert f'"{key}"' in text, f"в промпте нет ключа JSON {key!r}"
    # Часть B обязана требовать поле question явно - живая проверка шага 16 поймала его пропажу.
    assert "question - сама формулировка вопроса" in text


def test_questions_prompts_have_no_hardcoded_rubrics() -> None:
    for path in (_HR_QUESTIONS_PROMPT, _GROUPS_PROMPT):
        text = path.read_text(encoding="utf-8")
        for rubric in _HARDCODED_RUBRICS:
            assert rubric not in text, f"зашитая рубрика {rubric!r} не должна быть в {path}"


def test_vacancy_self_pres_model_fields_match_pack_contract() -> None:
    fields = set(VacancySelfPres.model_fields)
    for key in (
        "vacancy_id",
        "jd_brief",
        "pitch_blocks",
        "oral_pitch",
        "why_company",
        "hr_questions",
        "groups",
    ):
        assert key in fields, f"VacancySelfPres без поля {key!r}"
