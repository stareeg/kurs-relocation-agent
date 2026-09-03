"""OF-15 (plans/offer_awareness_and_final_prep.md): «Рынок» видит офферы в руках.

Чистые проверки форматирования блока АКТИВНЫЕ ОФФЕРЫ в user-промпте `build_situation_user_prompt`
и расчёта `days_until_deadline` в `_offer_brief` — без БД, конструируем `SituationFacts`/`Offer`
напрямую.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from core.domains.market.situation import (
    SituationFacts,
    SituationOfferBrief,
    _offer_brief,
    _situation_goal_block,
    build_situation_user_prompt,
)
from core.domains.offers.store import Offer
from core.domains.profile.profile import SearchProfile


def test_no_active_offers_omits_section_and_goal_note() -> None:
    prompt = build_situation_user_prompt(
        SituationFacts(),
        profile=SearchProfile(),
        target_companies=[],
    )
    assert "АКТИВНЫЕ ОФФЕРЫ" not in prompt
    assert "оффер(а) в руках" not in prompt
    assert "Цель поиска в резюме не описана" in prompt


def test_search_track_label_sits_next_to_search_mode() -> None:
    prompt = build_situation_user_prompt(
        SituationFacts(
            search_mode_label="Активно ищу",
            search_track_label="Основная, Дополнительная",
        ),
        profile=SearchProfile(),
        target_companies=[],
    )
    assert "Режим поиска: Активно ищу." in prompt
    assert "Треки поиска: Основная, Дополнительная." in prompt


def test_prompt_omits_removed_b09_blocks() -> None:
    """B-09: SKIP_BREAKDOWN / MARKET_SUPPLY убраны; источники и цитаты HR остаются."""
    prompt = build_situation_user_prompt(
        SituationFacts(),
        profile=SearchProfile(),
        target_companies=[],
    )
    assert "SKIP_BREAKDOWN" not in prompt
    assert "MARKET_SUPPLY" not in prompt
    assert "ИСТОЧНИКИ" in prompt
    assert "MARKET_GRID_JSON" in prompt
    assert "OFFER_CHANCE" in prompt
    assert "TOP_JOBS" in prompt
    assert "TOP_COMPANIES" in prompt
    assert "ПЕРИОД" in prompt
    assert "Цитаты фидбека рекрутёров" in prompt


def test_active_offer_adds_section_and_goal_note() -> None:
    offer = SituationOfferBrief(
        company="POSCREDIT",
        position="ML-инженер",
        base_salary=450_000,
        base_salary_currency="RUB",
        base_salary_period="month",
        work_format="hybrid",
        office_days_per_week=3,
        status="active",
        deadline=datetime.now(UTC) + timedelta(days=2),
        days_until_deadline=2,
    )
    prompt = build_situation_user_prompt(
        SituationFacts(active_offers=[offer]),
        profile=SearchProfile(),
        target_companies=[],
    )

    assert "АКТИВНЫЕ ОФФЕРЫ" in prompt
    assert "POSCREDIT" in prompt
    assert "450 000 RUB/мес" in prompt
    assert "3 дн. в офисе" in prompt
    assert "осталось 2 дн." in prompt
    assert "1 оффер(а) в руках" in prompt


def test_expired_deadline_reported_as_passed() -> None:
    offer = SituationOfferBrief(
        company="Acme",
        status="active",
        deadline=datetime.now(UTC) - timedelta(days=1),
        days_until_deadline=-1,
    )
    prompt = build_situation_user_prompt(
        SituationFacts(active_offers=[offer]),
        profile=SearchProfile(),
        target_companies=[],
    )
    assert "дедлайн прошёл" in prompt


def test_situation_goal_block_from_filled_profile() -> None:
    profile = SearchProfile(
        title="Project Manager",
        salary_min=250_000,
        salary_currency="RUB",
        salary_basis="net",
        market_segment="Медиа / Продакшн",
        allows_hybrid=True,
        allows_office=True,
    )
    goal = _situation_goal_block(profile, horizon_days=45, target_companies=["Авито"])
    assert "Project Manager" in goal
    assert "гибрид" in goal
    assert "офис" in goal
    assert "250 000" in goal
    assert "на руки" in goal
    assert "Медиа / Продакшн" in goal
    assert "Авито" in goal
    assert "бигтех" not in goal.casefold()
    assert "450 000" not in goal
    assert "полной удалёнке" not in goal.casefold()


def test_offer_brief_computes_days_until_deadline() -> None:
    offer = Offer(
        vacancy_id="v1",
        company="POSCREDIT",
        deadline=datetime.now(UTC) + timedelta(days=3, hours=1),
    )
    brief = _offer_brief(offer)
    assert brief.days_until_deadline == 3


def test_offer_brief_no_deadline_is_none() -> None:
    offer = Offer(vacancy_id="v1", company="POSCREDIT")
    brief = _offer_brief(offer)
    assert brief.days_until_deadline is None


def test_schema_version_is_seven() -> None:
    from core.domains.market.situation import SCHEMA_VERSION

    assert SCHEMA_VERSION == 7


def test_legacy_schema_v6_cache_rejected() -> None:
    """Кэш прошлой версии → None → GET отдаёт LEGACY_CACHE_NOTE, не пустые блоки."""
    from core.domains.market.situation import (
        LEGACY_CACHE_NOTE,
        SituationNarrative,
        SituationStep,
        SituationTarget,
        narrative_to_storage,
        normalize_narrative,
        parse_stored_narrative,
    )

    assert "Разобрать ситуацию" in LEGACY_CACHE_NOTE
    assert parse_stored_narrative({"summary": "старое"}, db_schema_version=6) is None
    assert parse_stored_narrative({"schema_version": 6, "summary": "старое"}) is None

    n = normalize_narrative(
        SituationNarrative(
            conclusion="ок",
            steps=[SituationStep(text="написать HR", target=SituationTarget(section="jobs"))],
        )
    )
    stored = narrative_to_storage(n)
    assert stored["schema_version"] == 7
    assert "funnel_diagnosis" not in stored
    assert "likely_salary" not in stored
    assert parse_stored_narrative(stored, db_schema_version=7) is not None
