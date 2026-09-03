"""FR2-32/33/37: постпроцессинг ats-fit без живых LLM-вызовов."""

from __future__ import annotations

import pytest

from unittest.mock import AsyncMock

from core.domains.profile.ats_fit import (
    SKIP_REASON_ABOUT_NO_BODY,
    SKIP_REASON_EXPERIENCE_EMPTY,
    AtsFitAboutPatch,
    AtsFitExperiencePatch,
    assemble_ats_fit_result,
    build_ats_fit_context,
    has_substantive_resume_body,
    is_block_too_thin,
    iter_ats_fit_events,
    skip_about_if_no_body,
    skip_experience_if_thin,
    strengthen_experience_block,
)
from core.domains.profile.context import StrengthenContext
from core.domains.profile.model import DesiredPosition, Experience, ResumeData
from core.domains.profile.skill_suggest import SkillSnapshot, SkillSuggestionRow


def test_assemble_keeps_partial_blocks_when_one_failed() -> None:
    """FR2-38: упавший блок не затирает остальные в сборке — остальные применимы."""
    result = assemble_ats_fit_result(
        experience=[
            AtsFitExperiencePatch(
                index=0,
                company="A",
                position="Lead",
                original="длинный текст опыта про LLM и агентов здесь есть",
                proposed="переписано",
                status="ok",
            ),
            AtsFitExperiencePatch(
                index=1,
                company="B",
                position="Dev",
                original="ещё один блок",
                status="error",
                error="timeout",
            ),
            AtsFitExperiencePatch(
                index=2,
                company="C",
                position="Intern",
                original="",
                status="skipped",
                skip_reason=SKIP_REASON_EXPERIENCE_EMPTY,
            ),
        ],
        about=AtsFitAboutPatch(original="", proposed="я lead llm", status="ok"),
        missing_concepts=["LangGraph", "RAG"],
        top_jobs_count=3,
        has_market=True,
    )
    assert len(result.experience) == 3
    assert result.experience[0].status == "ok"
    assert result.experience[1].status == "error"
    assert result.experience[2].status == "skipped"
    assert result.about.proposed == "я lead llm"
    assert result.missing_concepts == ["LangGraph", "RAG"]
    assert result.top_jobs_count == 3
    assert result.has_market is True


def test_is_block_too_thin_empty_and_placeholders() -> None:
    assert is_block_too_thin("")
    assert is_block_too_thin("   ")
    assert is_block_too_thin("коротко")
    assert is_block_too_thin("...")
    assert is_block_too_thin("— — —")
    assert is_block_too_thin("описание")
    assert not is_block_too_thin(
        "Собрал multi-agent пайплайн под RAG и выкатил в ПРОМ"
    )


def test_skip_experience_if_thin_returns_canonical_reason() -> None:
    skipped = skip_experience_if_thin(0, "Сбер", "Lead", "")
    assert skipped is not None
    assert skipped.status == "skipped"
    assert skipped.skip_reason == SKIP_REASON_EXPERIENCE_EMPTY
    assert skipped.proposed == ""
    assert skipped.company == "Сбер"

    almost = skip_experience_if_thin(1, "A", "B", "tba")
    assert almost is not None
    assert almost.skip_reason == SKIP_REASON_EXPERIENCE_EMPTY

    filled = "Собрал multi-agent пайплайн под RAG и выкатил в ПРОМ"
    assert skip_experience_if_thin(2, "A", "B", filled) is None


def test_header_only_resume_skips_about() -> None:
    """Новый пользователь заполнил только шапку — не выдумываем опыт/био."""
    data = ResumeData(
        position=DesiredPosition(title="Lead LLM Engineer", salary_min=450_000),
        experience=[Experience(company="Сбер", position="Lead", description="")],
        key_skills=[],
        about="",
    )
    assert has_substantive_resume_body(data) is False

    about = skip_about_if_no_body("", data)
    assert about is not None
    assert about.status == "skipped"
    assert about.skip_reason == SKIP_REASON_ABOUT_NO_BODY

    exp = skip_experience_if_thin(0, "Сбер", "Lead", "")
    assert exp is not None
    assert exp.skip_reason == SKIP_REASON_EXPERIENCE_EMPTY


def test_resume_with_experience_body_is_not_skipped() -> None:
    data = ResumeData(
        position=DesiredPosition(title="Lead LLM Engineer"),
        experience=[
            Experience(
                company="Сбер",
                position="Lead",
                description="Собрал multi-agent пайплайн под RAG и выкатил в ПРОМ",
            )
        ],
        key_skills=[],
    )
    assert has_substantive_resume_body(data) is True
    assert skip_about_if_no_body("", data) is None


def test_resume_with_skills_only_allows_about() -> None:
    data = ResumeData(
        position=DesiredPosition(title="Lead LLM Engineer"),
        experience=[],
        key_skills=["Python", "RAG"],
    )
    assert has_substantive_resume_body(data) is True
    assert skip_about_if_no_body("", data) is None


@pytest.mark.asyncio
async def test_build_context_without_market_is_text_only() -> None:
    """FR2-37: нет снимка и топ-вакансий → has_market=False, без рыночного текста в ctx."""
    data = ResumeData(
        position=DesiredPosition(title="Lead LLM Engineer"),
        experience=[
            Experience(
                company="Сбер",
                position="Lead",
                description="Собрал multi-agent пайплайн под RAG и выкатил в ПРОМ",
            )
        ],
        key_skills=["Python"],
    )
    ctx, gaps, top_n, has_market = await build_ats_fit_context(
        account_id=1,
        data=data,
        snapshot=None,
        top_jobs_texts=[],
    )
    assert has_market is False
    assert gaps == []
    assert top_n == 0
    assert ctx.has_gap is False
    assert ctx.has_top_vacancies is False
    assert "разрывы по требованиям выборки" not in ctx.text.casefold()
    assert "фрагменты топ" not in ctx.text.casefold()
    assert "рынок покрыт" not in ctx.text.casefold()


@pytest.mark.asyncio
async def test_build_context_with_top_jobs_sets_has_market() -> None:
    data = ResumeData(position=DesiredPosition(title="Lead LLM Engineer"))
    ctx, _gaps, top_n, has_market = await build_ats_fit_context(
        account_id=1,
        data=data,
        snapshot=None,
        top_jobs_texts=["Нужен опыт LangGraph и RAG в проде"],
    )
    assert has_market is True
    assert top_n == 1
    assert ctx.has_top_vacancies is True
    assert "langgraph" in ctx.text.casefold()


@pytest.mark.asyncio
async def test_build_context_uses_snapshot_gaps_not_ngram_noise() -> None:
    """S-06: разрывы идут из снимка навыков (state=add), а не из n-граммного gap-отчёта."""
    data = ResumeData(position=DesiredPosition(title="Lead LLM Engineer"), key_skills=["Python"])
    snapshot = SkillSnapshot(
        corpus_size=43,
        rows=[
            SkillSuggestionRow(
                skill="Python", state="have", demand_count=20, demand_total=43
            ),
            SkillSuggestionRow(
                skill="vLLM", state="add", demand_count=18, demand_total=43
            ),
            SkillSuggestionRow(
                skill="Apache Spark", state="drop", demand_count=0, demand_total=43
            ),
        ],
    )
    ctx, gaps, _top_n, has_market = await build_ats_fit_context(
        account_id=1,
        data=data,
        snapshot=snapshot,
        top_jobs_texts=[],
    )
    assert gaps == ["vLLM"]
    assert has_market is True
    assert "vllm" in ctx.text.casefold()
    assert "локация" not in ctx.text.casefold()
    assert "apache spark" not in ctx.text.casefold()


@pytest.mark.asyncio
async def test_iter_ats_fit_events_progress_and_partial_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR2-38: стрим start→progress×K→result; один блок error — остальные в result."""
    data = ResumeData(
        position=DesiredPosition(title="Lead LLM Engineer"),
        experience=[
            Experience(
                company="Сбер",
                position="Lead",
                description="Собрал multi-agent пайплайн под RAG и выкатил в ПРОМ",
            ),
            Experience(
                company="Яндекс",
                position="Dev",
                description="Ещё один полноценный блок опыта про агентов и RAG",
            ),
        ],
        key_skills=["Python"],
        about="Коротко про опыт",
    )
    monkeypatch.setattr("core.domains.profile.ats_fit.get_settings", lambda: type("S", (), {"openrouter_api_key": "x"})())

    async def _fake_read_resume_data(account_id, *, db=None):
        return data

    monkeypatch.setattr(
        "core.domains.profile.ats_fit.read_resume_data_for_account", _fake_read_resume_data
    )
    empty_ctx = StrengthenContext(text="", has_gap=False, has_funnel=False, has_top_vacancies=False)
    monkeypatch.setattr(
        "core.domains.profile.ats_fit.build_ats_fit_context",
        AsyncMock(return_value=(empty_ctx, [], 0, False)),
    )

    async def fake_exp(index, company, position, original, **_kw):
        if index == 1:
            return AtsFitExperiencePatch(
                index=1,
                company=company,
                position=position,
                original=original,
                status="error",
                error="timeout",
            )
        return AtsFitExperiencePatch(
            index=index,
            company=company,
            position=position,
            original=original,
            proposed="ок",
            status="ok",
        )

    async def fake_about(*_a, **_k):
        return AtsFitAboutPatch(original="", proposed="био", status="ok")

    monkeypatch.setattr("core.domains.profile.ats_fit._rewrite_experience", fake_exp)
    monkeypatch.setattr("core.domains.profile.ats_fit._rewrite_about", fake_about)

    events = [ev async for ev in iter_ats_fit_events(account_id=1)]
    assert events[0]["type"] == "start"
    assert events[0]["total"] == 3  # about + 2 experience
    progress = [e for e in events if e["type"] == "progress"]
    assert len(progress) == 3
    assert progress[-1]["done"] == 3
    result_ev = events[-1]
    assert result_ev["type"] == "result"
    result = result_ev["data"]
    assert result["experience"][0]["status"] == "ok"
    assert result["experience"][1]["status"] == "error"
    assert result["about"]["status"] == "ok"


@pytest.mark.asyncio
async def test_strengthen_experience_block_rewrites_one_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Кнопка «Подогнать под ATS» у одного блока: собирает контекст и переписывает лишь его."""
    data = ResumeData(
        position=DesiredPosition(title="Lead LLM Engineer", salary_min=450_000),
        experience=[
            Experience(
                company="Сбер",
                position="Lead",
                description="Собрал multi-agent пайплайн под RAG и выкатил в ПРОМ",
            ),
            Experience(
                company="Яндекс",
                position="Dev",
                description="Ещё один полноценный блок опыта про агентов и RAG",
            ),
        ],
        key_skills=["Python", "LangGraph"],
    )
    monkeypatch.setattr(
        "core.domains.profile.ats_fit.get_settings",
        lambda: type("S", (), {"openrouter_api_key": "x"})(),
    )

    async def _fake_read_resume_data(account_id, *, db=None):
        return data

    monkeypatch.setattr(
        "core.domains.profile.ats_fit.read_resume_data_for_account", _fake_read_resume_data
    )
    empty_ctx = StrengthenContext(text="", has_gap=False, has_funnel=False, has_top_vacancies=False)
    monkeypatch.setattr(
        "core.domains.profile.ats_fit.build_ats_fit_context",
        AsyncMock(return_value=(empty_ctx, [], 0, False)),
    )

    async def fake_exp(index, company, position, original, **_kw):
        return AtsFitExperiencePatch(
            index=index,
            company=company,
            position=position,
            original=original,
            proposed=f"переписано-{index}",
            status="ok",
        )

    monkeypatch.setattr("core.domains.profile.ats_fit._rewrite_experience", fake_exp)

    patch = await strengthen_experience_block(index=1, account_id=1)
    assert patch.index == 1
    assert patch.company == "Яндекс"
    assert patch.proposed == "переписано-1"
    assert patch.status == "ok"


@pytest.mark.asyncio
async def test_strengthen_experience_block_bad_index_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = ResumeData(
        position=DesiredPosition(title="Lead"),
        experience=[
            Experience(company="Сбер", position="Lead", description="полноценный блок опыта"),
        ],
        key_skills=[],
    )
    monkeypatch.setattr(
        "core.domains.profile.ats_fit.get_settings",
        lambda: type("S", (), {"openrouter_api_key": "x"})(),
    )

    async def _fake_read_resume_data(account_id, *, db=None):
        return data

    monkeypatch.setattr(
        "core.domains.profile.ats_fit.read_resume_data_for_account", _fake_read_resume_data
    )
    with pytest.raises(ValueError):
        await strengthen_experience_block(index=5, account_id=1)
