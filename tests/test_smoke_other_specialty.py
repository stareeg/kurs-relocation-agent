"""FR-34: смоук-тест «другая специальность» — frontend, не ML/LLM.

Проверяем собранные system-промпты (то, что реально ушло бы в LLM): скоринг, подготовка к
собесу, профили компаний. Старый хардкод владельца (Lead LLM / ex-Сбер / ML/LLM как ниша
кандидата) не должен проступать, когда резюме — Senior Frontend Developer.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from core.config import get_settings
from core.domains.preparation.interview.company_profiles import match_company_profile
from core.domains.preparation.interview.prep import _build_prep_system_parts
from core.domains.preparation.interview.prep_pack import _build_system_prompt as build_prep_pack_system_prompt
from core.domains.profile.model import ResumeData
from core.domains.profile.structured_store import save_resume_data
from core.domains.preparation.models import VacancyRecord
from core.domains.opportunities.models import (
    BurnoutRisk,
    GradeMatch,
    RemoteAbroadCompat,
    RoleContentMatch,
    SalaryInfo,
    ScoreResult,
)
from core.domains.opportunities.prompt import (
    CANDIDATE_IDENTITY_TOKEN,
    build_system_prompt_text,
    load_candidate_identity,
    load_candidate_specialization,
)
from core.domains.preparation.screening.questions import _load_groups_prompt as _load_screening_groups_prompt
from core.domains.preparation.screening.questions import _load_hr_questions_prompt as _load_screening_hr_prompt

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "resume_smoke_frontend.json"

# Следы старого хардкода под Lead LLM Engineer / ex-Сбер — не должны быть в промптах
# frontend-кандидата. «Сбер» как название компании в профилях допустим.
FORBIDDEN_IN_PROMPTS = (
    "Lead LLM Engineer",
    "ex-Сбер",
    "{{CANDIDATE_IDENTITY}}",
    "{{SPECIALIZATION}}",
    "ML/LLM",
    "GraphRAG",
    "agentic",
    "трансформеры, attention, метрики качества LLM",
    "проектирование LLM-системы",
)

EXPECTED_IDENTITY_FRAGMENT = "Senior Frontend Developer"
EXPECTED_SPECIALIZATION_FRAGMENTS = ("Frontend", "Design systems", "E-commerce")
EXPECTED_RESUME_MARKERS = ("React", "TypeScript", "Критерии поиска", "Авито")


def _minimal_score() -> ScoreResult:
    return ScoreResult(
        overall_score=70,
        recommendation="apply",
        remote_abroad_compat=RemoteAbroadCompat(level="ok", reasoning="удалёнка"),
        grade_match=GradeMatch(level="match", reasoning="senior"),
        salary=SalaryInfo(meets_min=True, value_or_range="300k", note=""),
        role_content_match=RoleContentMatch(
            score=75,
            matched_niche=["Frontend"],
            reasoning="react/typescript",
        ),
        burnout_risk=BurnoutRisk(level="low", reasoning="ok"),
        company_type="product",
        pros=["стек совпадает"],
        cons=["—"],
        red_flags=[],
        one_line_verdict="подходит",
    )


SAMPLE_VACANCIES: tuple[VacancyRecord, ...] = (
    VacancyRecord(
        score=_minimal_score(),
        vacancy_id="smoke_fe_1",
        title="Senior Frontend Developer (React)",
        company="Ozon",
        salary_text="от 300 000 ₽ на руки",
        work_schedule="Удалённо",
        vacancy_text=(
            "Ищем Senior Frontend Developer в продуктовую команду маркетплейса.\n"
            "Стек: React 18, TypeScript, Next.js, Module Federation, Playwright.\n"
            "Задачи: развитие витрины, design system, E2E-тесты, code review.\n"
            "Формат: полная удалёнка по РФ."
        ),
    ),
    VacancyRecord(
        score=_minimal_score(),
        vacancy_id="smoke_qa_1",
        title="QA Automation Engineer",
        company="Авито",
        salary_text="280 000 - 350 000 ₽",
        work_schedule="Гибрид",
        vacancy_text=(
            "QA Automation Engineer в команду classified.\n"
            "Python, Pytest, Playwright, CI/CD, тестирование API и UI.\n"
            "Нужен опыт автотестов в продуктовой разработке, не ручное тестирование 100%."
        ),
    ),
)


def _load_chat_system_prompt() -> str:
    from core.domains.assistant.llm import CHAT_SYSTEM

    path = Path(CHAT_SYSTEM)
    template = path.read_text(encoding="utf-8").strip()
    return template.replace(CANDIDATE_IDENTITY_TOKEN, load_candidate_identity())


@pytest.fixture
def frontend_resume_env(tmp_path, monkeypatch):
    """Копирует FR-34 fixture в temp resume_data.json и сбрасывает кэш настроек."""
    dest = tmp_path / "resume_data.json"
    shutil.copy(FIXTURE, dest)
    monkeypatch.setenv("RESUME_DATA_PATH", str(dest))
    get_settings.cache_clear()
    from core.domains.opportunities.prompt import clear_resume_cache

    clear_resume_cache()
    yield dest
    get_settings.cache_clear()


def _assert_no_owner_hardcode(text: str, *, label: str) -> None:
    lowered = text.lower()
    for needle in FORBIDDEN_IN_PROMPTS:
        assert needle.lower() not in lowered, f"{label}: найден запрещённый фрагмент «{needle}»"


async def _collect_prompt_texts(vacancy: VacancyRecord) -> dict[str, str]:
    """`account_id=None` — те же файловые/bootstrap семантики, что и остальной тест (нет
    аккаунтов, резюме из `RESUME_DATA_PATH`); продовый путь всегда получает реальный account_id
    (см. `core.domains.pipeline.cover_letter`, тот же класс бага)."""
    profile = await match_company_profile(vacancy.company, vacancy.vacancy_text or "", account_id=None)
    assert profile is not None, "профиль компании должен матчиться для smoke-вакансии"

    scoring = build_system_prompt_text()
    prep_static, prep_dyn = await _build_prep_system_parts("tech", profile, account_id=None)
    prep = f"{prep_static}\n\n{prep_dyn}"
    prep_pack = await build_prep_pack_system_prompt(
        stage="tech",
        profile=profile,
        weak_topics_block="",
        recruiter_feedback_block="",
        legend_content="",
        strong_answers_block="",
        asked_questions_block="",
        account_id=None,
    )
    screening_hr = await _load_screening_hr_prompt(account_id=None)
    screening_groups = await _load_screening_groups_prompt(account_id=None)
    chat = _load_chat_system_prompt()

    company_blob = "\n".join(
        [
            profile.summary,
            *profile.stage_notes.values(),
            *(tip for tips in profile.stage_tips.values() for tip in tips),
        ]
    )

    return {
        "scoring": scoring,
        "prep": prep,
        "prep_pack": prep_pack,
        "screening_hr": screening_hr,
        "screening_groups": screening_groups,
        "chat": chat,
        "company_profile": company_blob,
    }


def test_fixture_is_frontend_not_llm():
    data = ResumeData.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    niches = " ".join(data.search_criteria.niches).lower()
    skills = " ".join(data.key_skills).lower()
    assert "llm" not in niches
    assert "rag" not in niches
    assert "react" in skills
    assert data.position.title == "Senior Frontend Developer"


def test_identity_and_specialization_from_resume(frontend_resume_env):
    identity = load_candidate_identity()
    specialization = load_candidate_specialization()

    assert EXPECTED_IDENTITY_FRAGMENT in identity
    assert "Сбер" not in identity
    assert "LLM" not in identity

    for part in EXPECTED_SPECIALIZATION_FRAGMENTS:
        assert part in specialization


def test_scoring_prompt_reflects_frontend_resume(frontend_resume_env):
    prompt = build_system_prompt_text()
    _assert_no_owner_hardcode(prompt, label="scoring")

    for marker in EXPECTED_RESUME_MARKERS:
        assert marker in prompt

    assert "## Критерии поиска" in prompt
    assert "Senior Frontend Developer" in prompt


@pytest.mark.parametrize("vacancy", SAMPLE_VACANCIES)
async def test_assembled_prompts_no_llm_owner_hardcode(frontend_resume_env, vacancy: VacancyRecord):
    prompts = await _collect_prompt_texts(vacancy)

    for name, text in prompts.items():
        _assert_no_owner_hardcode(text, label=f"{name} ({vacancy.company})")

    for part in EXPECTED_SPECIALIZATION_FRAGMENTS:
        assert part in prompts["company_profile"], (
            f"ниша кандидата должна подставиться в профиль компании ({vacancy.company})"
        )

    assert EXPECTED_IDENTITY_FRAGMENT in prompts["prep"]
    assert EXPECTED_IDENTITY_FRAGMENT in prompts["prep_pack"]
    assert "React" in prompts["prep"] or "TypeScript" in prompts["prep"]


async def test_save_resume_roundtrip_keeps_frontend_prompts_clean(tmp_path, monkeypatch):
    """Проверка цепочки save → clear cache → свежий промпт (как в проде после правки резюме)."""
    dest = tmp_path / "resume_data.json"
    monkeypatch.setenv("RESUME_DATA_PATH", str(dest))
    get_settings.cache_clear()

    payload = ResumeData.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    payload.search_criteria.niches = ["Frontend", "Mobile Web"]
    await save_resume_data(payload)

    prompt = build_system_prompt_text()
    _assert_no_owner_hardcode(prompt, label="scoring after save")
    assert "Mobile Web" in prompt


def test_frontend_international_derivation_does_not_crash():
    data = ResumeData.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    from core.domains.profile.international import derive_international_readiness

    ready = derive_international_readiness(data)
    assert ready.readiness == "unknown"  # рынок по умолчанию — Только РФ
    data.search_criteria.market_scope = "Международный"
    intl = derive_international_readiness(data)
    assert intl.english_level == "B2"
    assert intl.home_timezone == "Europe/Moscow"
