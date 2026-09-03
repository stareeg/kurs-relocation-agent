"""SM-4 (plans/heuristics_to_llm.md): postfactum-фильтры scorer.py как safety-net, не заплатка.

Промпт (prompts/opportunities/system.md п.9 + instructions.md) явно запрещает модели генерить
«вилка не указана»/«удалёнка не из РФ» в cons/red_flags. Живая проверка на ~14 реальных
вакансиях (2 раунда, до и после усиления промпта) показала: haiku 4.5 всё равно нарушает правило
в ~35% случаев — промпт-фикс не закрывает случай полностью, регекс остаётся настоящей
страховкой (не мёртвым кодом). Эти тесты фиксируют поведение самой страховки: должна убирать
ровно два класса ложных жалоб и не трогать содержательные пункты с той же лексикой, но с числом
или другой сутью.
"""

from __future__ import annotations

import pytest

from core.domains.opportunities.models import (
    BurnoutRisk,
    GradeMatch,
    RemoteAbroadCompat,
    RoleContentMatch,
    SalaryInfo,
    ScoreResult,
)
from core.domains.opportunities.scorer import (
    _filter_remote_mentions,
    _filter_unspecified_salary_mentions,
    _is_remote_related,
    _is_unspecified_salary_mention,
)


def _make_score(*, cons: list[str], red_flags: list[str]) -> ScoreResult:
    return ScoreResult(
        overall_score=50,
        recommendation="maybe",
        remote_abroad_compat=RemoteAbroadCompat(level="ok", reasoning="r"),
        grade_match=GradeMatch(level="match", reasoning="r"),
        salary=SalaryInfo(meets_min=False, value_or_range="", note=""),
        role_content_match=RoleContentMatch(score=50, matched_niche=[], reasoning="r"),
        burnout_risk=BurnoutRisk(level="low", reasoning="r"),
        company_type="product",
        pros=["ок"],
        cons=cons,
        red_flags=red_flags,
        one_line_verdict="ок",
    )


def test_is_unspecified_salary_mention_matches_pure_complaint():
    assert _is_unspecified_salary_mention("Зарплата не указана в вакансии")
    assert _is_unspecified_salary_mention("Вилка не раскрыта, требует уточнения")


def test_is_unspecified_salary_mention_ignores_when_number_present():
    # Названа конкретная (пусть и низкая) вилка - это уже валидный сигнал, не «не указана».
    text = "Зарплата не указана в вакансии, но по рынку ожидаем около 300k"
    assert not _is_unspecified_salary_mention(text)


def test_is_unspecified_salary_mention_ignores_unrelated_text():
    assert not _is_unspecified_salary_mention("Стек не совпадает с профилем кандидата")


def test_is_remote_related_matches_geo_citizenship_complaints():
    assert _is_remote_related("Удалёнка доступна только при наличии гражданства РФ")
    assert _is_remote_related("Работать можно только из-за рубежа, релокантам")


def test_is_remote_related_ignores_unrelated_text():
    assert not _is_remote_related("Требуется опыт LangGraph от 2 лет")


def test_filter_unspecified_salary_mentions_removes_only_pure_complaints():
    score = _make_score(
        cons=["Зарплата не указана", "Стек классический ML, не LLM"],
        red_flags=["Вилка не раскрыта конкретно"],
    )
    cleaned = _filter_unspecified_salary_mentions(score)
    assert cleaned.cons == ["Стек классический ML, не LLM"]
    assert cleaned.red_flags == []


def test_filter_remote_mentions_removes_only_geo_complaints():
    score = _make_score(
        cons=["Удалёнка только при наличии гражданства РФ", "Грейд middle, ниже целевого"],
        red_flags=["Требуется гражданство РФ"],
    )
    cleaned = _filter_remote_mentions(score)
    assert cleaned.cons == ["Грейд middle, ниже целевого"]
    assert cleaned.red_flags == []


def test_filter_remote_mentions_allows_empty_cons_when_all_stripped():
    """Этап 8 §8.4: раньше пустой cons восстанавливал только что удалённый пункт назад
    (`orig_cons[:1]`) — ровно то, что фильтр признал запрещённой темой. Пустой список —
    честный исход, не баг."""
    score = _make_score(cons=["Удалёнка только из-за рубежа"], red_flags=[])
    cleaned = _filter_remote_mentions(score)
    assert cleaned.cons == []


@pytest.mark.asyncio
async def test_enrich_salary_honest_none_when_no_anchor_no_llm(monkeypatch, tmp_path):
    """Шаг 20: нет зарплаты в резюме + LLM выкл + нет корпуса → estimated_range == \"\"."""
    import json

    from core.config import get_settings
    from core.domains.opportunities.prompt import clear_resume_cache
    from core.domains.opportunities.scorer import _enrich_salary_if_needed

    resume = {
        "personal": {"full_name": "Тест"},
        "position": {"title": "X", "salary_min": 0, "schedule": ["Удалённо"]},
        "search_criteria": {},
        "experience": [{"company": "A", "position": "B", "start": "2020", "current": True}],
    }
    dest = tmp_path / "resume_data.json"
    dest.write_text(json.dumps(resume, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("RESUME_DATA_PATH", str(dest))
    get_settings.cache_clear()
    clear_resume_cache()

    async def _no_prior(*_a, **_k):
        return None

    monkeypatch.setattr(
        "core.domains.opportunities.scorer.segment_salary_estimate", _no_prior
    )

    from core.domains.profile.profile import SearchProfile

    score = _make_score(cons=["ок"], red_flags=[])
    # Нет явной вилки в тексте и в ScoreResult.
    out = await _enrich_salary_if_needed(
        score,
        "Ищем специалиста. Зарплата не указана. Удалённо.",
        use_llm=False,
        profile=SearchProfile(),
        min_salary=0,
        account_id=1,
    )
    assert out.salary.estimated_range == ""
    assert out.salary.estimated_min is None
    assert out.salary.estimated_max is None
    assert out.salary.source == "none"
    assert out.salary.estimate_pending is False


@pytest.mark.asyncio
async def test_enrich_salary_does_not_substitute_anchor_when_llm_off(monkeypatch):
    """2026-08-08: при use_llm=False + непустом якоре резюме вилка НЕ подставляется.
    Раньше _anchor_salary_estimate писал желаемую зарплату из резюме как оценку
    вилки вакансии — все вакансии получали одинаковые вилки, и рыночная аналитика
    (распределение, бенчмарк) становилась бессмысленной."""
    async def _no_prior(*_a, **_k):
        return None

    monkeypatch.setattr(
        "core.domains.opportunities.scorer.segment_salary_estimate", _no_prior
    )
    from core.domains.opportunities.scorer import _enrich_salary_if_needed
    from core.domains.profile.profile import SearchProfile

    profile = SearchProfile(salary_min=300_000, salary_comfortable=400_000)
    assert profile.salary_anchor_base() is not None  # якорь есть

    score = _make_score(cons=["ок"], red_flags=[])
    out = await _enrich_salary_if_needed(
        score,
        "Ищем специалиста. Зарплата не указана. Удалённо.",
        use_llm=False,
        profile=profile,
        min_salary=300_000,
        account_id=1,
    )
    # Якорь не подставлен — честный «нет данных».
    assert out.salary.estimated_range == ""
    assert out.salary.estimated_min is None
    assert out.salary.estimated_max is None
    assert out.salary.source == "none"
    assert out.salary.estimate_pending is False
    from core.domains.opportunities.scorer import _enrich_salary_if_needed

    async def _no_prior(*_a, **_k):
        return None

    monkeypatch.setattr(
        "core.domains.opportunities.scorer.segment_salary_estimate", _no_prior
    )
    from core.domains.profile.profile import SearchProfile

    score = _make_score(cons=["ок"], red_flags=[])
    out = await _enrich_salary_if_needed(
        score,
        "Ищем специалиста. Зарплата не указана. Удалённо.",
        use_llm=True,
        profile=SearchProfile(),
        min_salary=0,
        account_id=1,
    )
    assert out.salary.estimate_pending is True
    assert out.salary.estimated_range == ""
    assert out.salary.source == "none"


@pytest.mark.asyncio
async def test_enrich_explicit_from_page_salary_text_locks():
    from core.domains.opportunities.scorer import _enrich_salary_if_needed, is_salary_locked

    from core.domains.profile.profile import SearchProfile

    score = _make_score(cons=["ок"], red_flags=[])
    out = await _enrich_salary_if_needed(
        score,
        "Текст без цифр зарплаты. Удалённо.",
        use_llm=True,
        salary_text="от 280 000 ₽ на руки",
        profile=SearchProfile(),
        min_salary=0,
        account_id=1,
    )
    assert out.salary.source == "explicit"
    assert out.salary.estimate_pending is False
    assert is_salary_locked(out.salary)
    assert "280" in out.salary.value_or_range


@pytest.mark.asyncio
async def test_enrich_preserves_explicit_on_rescore_without_new_hr():
    from core.domains.opportunities.models import SalaryInfo
    from core.domains.opportunities.scorer import _enrich_salary_if_needed

    locked = SalaryInfo(
        meets_min=True,
        value_or_range="300000–350000",
        note="Вилка со слов HR.",
        source="explicit",
        confidence="high",
    )
    from core.domains.profile.profile import SearchProfile

    score = _make_score(cons=["ок"], red_flags=[])
    out = await _enrich_salary_if_needed(
        score,
        "Текст без цифр. Удалённо.",
        use_llm=True,
        previous_salary=locked,
        profile=SearchProfile(),
        min_salary=0,
        account_id=1,
    )
    assert out.salary.source == "explicit"
    assert out.salary.value_or_range == "300000–350000"
    assert out.salary.estimate_pending is False


@pytest.mark.asyncio
async def test_enrich_hr_salary_updates_explicit_lock():
    from core.domains.pipeline.hr_facts import HRFacts
    from core.domains.opportunities.models import SalaryInfo
    from core.domains.opportunities.scorer import _enrich_salary_if_needed

    locked = SalaryInfo(
        meets_min=False,
        value_or_range="200000",
        note="старое",
        source="explicit",
        confidence="high",
    )
    from core.domains.profile.profile import SearchProfile

    facts = HRFacts(salary="от 450 000 на руки")
    score = _make_score(cons=["ок"], red_flags=[])
    out = await _enrich_salary_if_needed(
        score,
        "Без цифр в JD.",
        use_llm=True,
        hr_facts=facts,
        previous_salary=locked,
        profile=SearchProfile(),
        min_salary=0,
        account_id=1,
    )
    assert out.salary.source == "explicit"
    assert "450" in out.salary.value_or_range
    assert "HR" in out.salary.note
