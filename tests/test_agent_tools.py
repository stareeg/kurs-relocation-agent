"""Инструменты агента поверх продукта (A-2) на демо-данных.

Демо-данные — те же `demo-101…` (аккаунт 1, владелец), что заливаются в локальный
стек (`deck/src/tools/seed_jobs.py`): форма строк — как в ответе `/api/jobs`. БД и
LLM-порт подменены двойниками (`FakeDemoDb`, `FakeLlm`), поэтому тесты живут в CI без
сети и живого Postgres: проверяется, что инструмент правильно ходит в домен и возвращает
компактный ответ, а ошибки домена приходят как данные.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

import pytest

from core.app.agent.contracts import ToolCall, ToolContext
from core.app.agent.toolkit import execute_tool
from core.app.agent.tools import MAX_RESULT_ITEMS, TOOLS, ensure_tools_registered
from core.domains.opportunities.models import (
    BurnoutRisk,
    GradeMatch,
    RemoteAbroadCompat,
    RoleContentMatch,
    SalaryInfo,
    ScoreResult,
    TermEvidence,
    VacancyWorkTerms,
)
from core.platform.db.pool import Executor
from tests.fakes import DEMO_JOBS, FakeDemoDb, FakeLlm, use_fake_llm

ensure_tools_registered()


@pytest.fixture(autouse=True)
def _resume_cache_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Кэш резюме в `structured_store` — глобальный LRU; тесты не делят записи."""
    monkeypatch.setattr("core.domains.profile.structured_store._cache", OrderedDict())


def call(name: str, args: dict[str, Any], call_id: str = "c1") -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=args)


def sample_score() -> ScoreResult:
    return ScoreResult(
        overall_score=85,
        recommendation="apply",
        remote_abroad_compat=RemoteAbroadCompat(level="ideal", reasoning="оплата в евро"),
        grade_match=GradeMatch(level="match", reasoning="Senior"),
        salary=SalaryInfo(meets_min=True, value_or_range="€6 500–8 000 / мес", note=""),
        role_content_match=RoleContentMatch(score=70, matched_niche=[], reasoning="r"),
        burnout_risk=BurnoutRisk(level="low", reasoning="r"),
        company_type="product",
        pros=["стек совпадает"],
        cons=["пояс UTC+1"],
        red_flags=[],
        one_line_verdict="Агентные пайплайны, оплата в евро",
    )


def sample_terms() -> VacancyWorkTerms:
    return VacancyWorkTerms(
        engagement="b2b",
        geo_scope="region",
        residency_required=True,
        currency="EUR",
        rate_period="year",
        rate_min=90_000,
        rate_max=110_000,
        overlap_hours_required=4,
        evidence=[
            TermEvidence(field="engagement", quote="B2B-контракт"),
            TermEvidence(field="residency_required", quote="нужен ВНЖ ЕС"),
            TermEvidence(field="currency", quote="Оплата €90 000–110 000 в год"),
            TermEvidence(field="rate_period", quote="Оплата €90 000–110 000 в год"),
            TermEvidence(field="rate_min", quote="Оплата €90 000–110 000 в год"),
            TermEvidence(field="rate_max", quote="Оплата €90 000–110 000 в год"),
            TermEvidence(field="overlap_hours_required", quote="минимум 4 часа в день"),
        ],
    )


@pytest.fixture
def db() -> FakeDemoDb:
    return FakeDemoDb()


def ctx_with(db: FakeDemoDb, **overrides: Any) -> ToolContext:
    return ToolContext(account_id=1, db=db, **overrides)


# ------------------------------------------------------------------- read_profile


async def test_read_profile_returns_international_readiness(db: FakeDemoDb) -> None:
    result, error, _ = await execute_tool(call("read_profile", {}), ctx_with(db))

    assert error is None
    assert result["position"] == "Backend-разработчик"
    assert result["salary_min"] == 5000
    assert result["market_scope"] == "Международный"
    assert result["key_skills"][:2] == ["Python", "LLM"]
    assert result["home_timezone"], "часовой пояс выведен из города"
    assert "hint" not in result


async def test_read_profile_empty_resume_gets_hint() -> None:
    class EmptyResumeDb(FakeDemoDb):
        async def fetchrow(self, sql: str, *args: Any) -> Any:
            if "from resumes" in sql:
                return None
            return await super().fetchrow(sql, *args)

    result, error, _ = await execute_tool(call("read_profile", {}), ctx_with(EmptyResumeDb()))
    assert error is None
    assert "профиль пуст" in result["hint"]


# ------------------------------------------------------------------- search_vacancies


async def test_search_returns_all_demo_jobs_capped(db: FakeDemoDb) -> None:
    result, error, _ = await execute_tool(call("search_vacancies", {}), ctx_with(db))

    assert error is None
    assert result["total"] == len(DEMO_JOBS)
    assert result["shown"] == MAX_RESULT_ITEMS
    assert len(result["items"]) == MAX_RESULT_ITEMS
    assert f"показано {MAX_RESULT_ITEMS} из {len(DEMO_JOBS)}" in result["hint"]
    first = result["items"][0]
    assert first["id"].startswith("demo-")
    assert first["title"] and first["salary_text"]


async def test_search_filters_by_query_and_format(db: FakeDemoDb) -> None:
    result, error, _ = await execute_tool(
        call("search_vacancies", {"query": "kestrel"}), ctx_with(db)
    )
    assert error is None
    assert result["total"] == 1
    assert result["items"][0]["id"] == "demo-102"

    remote, _, _ = await execute_tool(
        call("search_vacancies", {"work_format": "remote"}), ctx_with(db)
    )
    assert remote["total"] == 5
    assert all(item["work_format"] == "remote" for item in remote["items"])

    office, _, _ = await execute_tool(
        call("search_vacancies", {"work_format": "office"}), ctx_with(db)
    )
    assert office["total"] == 1
    assert office["items"][0]["id"] == "demo-106"


async def test_search_min_score_and_empty_result_hint(db: FakeDemoDb) -> None:
    result, error, _ = await execute_tool(
        call("search_vacancies", {"min_overall_score": 80}), ctx_with(db)
    )
    assert error is None
    assert result["total"] == 2

    empty, _, _ = await execute_tool(
        call("search_vacancies", {"query": "unsplittable-token-xyz"}), ctx_with(db)
    )
    assert error is None
    assert empty["items"] == []
    assert "ослабьте фильтры" in empty["hint"]


async def test_search_skips_archived(db: FakeDemoDb) -> None:
    class WithArchivedDb(FakeDemoDb):
        async def fetch(self, sql: str, *args: Any) -> Any:
            rows = await super().fetch(sql, *args)
            for row in rows:
                if row["vacancy_id"] == "demo-107":
                    row["is_archived"] = True
            return rows

    result, _, _ = await execute_tool(call("search_vacancies", {}), ctx_with(WithArchivedDb()))
    assert result["total"] == len(DEMO_JOBS) - 1
    assert all(item["id"] != "demo-107" for item in result["items"])


# ------------------------------------------------------------------- read_work_terms


async def test_work_terms_extracted_with_quotes(
    db: FakeDemoDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    llm = use_fake_llm(monkeypatch, FakeLlm(result=sample_terms()))
    result, error, _ = await execute_tool(
        call("read_work_terms", {"vacancy_id": "demo-102"}), ctx_with(db)
    )

    assert error is None
    assert result["engagement"] == "b2b"
    assert result["residency_required"] is True
    assert result["currency"] == "EUR"
    assert result["rate_min"] == 90_000
    assert result["overlap_hours_required"] == 4
    assert any(item["field"] == "residency_required" for item in result["evidence"])
    assert llm.features == ["vacancy_work_terms"]


async def test_work_terms_unknown_vacancy_is_not_found(db: FakeDemoDb) -> None:
    result, error, _ = await execute_tool(
        call("read_work_terms", {"vacancy_id": "demo-999"}), ctx_with(db)
    )
    assert error is not None
    assert error.type == "not_found"
    assert "search_vacancies" in error.hint


# ------------------------------------------------------------------- score_vacancy


async def test_score_uses_job_from_db_and_llm_port(
    db: FakeDemoDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    llm = use_fake_llm(monkeypatch, FakeLlm(result=sample_score()))
    result, error, _ = await execute_tool(
        call("score_vacancy", {"vacancy_id": "demo-101"}), ctx_with(db)
    )

    assert error is None
    assert result["vacancy_id"] == "demo-101"
    assert isinstance(result["overall_score"], int)
    assert 0 <= result["overall_score"] <= 100
    assert result["one_line_verdict"]
    assert "salary" in result and "remote_abroad_compat" in result
    assert llm.features == ["job_search"], "один structured-вызов скоринга"


async def test_score_error_of_llm_comes_back_as_data(
    db: FakeDemoDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_fake_llm(monkeypatch, FakeLlm(error=RuntimeError("модель недоступна")))
    result, error, _ = await execute_tool(
        call("score_vacancy", {"vacancy_id": "demo-101"}), ctx_with(db)
    )
    assert error is not None
    assert error.type == "unavailable"
    assert result["error"]["hint"]


# ------------------------------------------------------------------- write_cover_letter


async def test_cover_letter_generated_and_saved(
    db: FakeDemoDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    llm = use_fake_llm(monkeypatch, FakeLlm(text="Здравствуйте! Готов обсудить роль и условия."))
    # Сценарий письма пишет в `jobs` через глобальный пул (db у сценария нет) — подменяем.
    monkeypatch.setattr("core.domains.opportunities.jobs.get_pool", lambda: db)
    result, error, _ = await execute_tool(
        call("write_cover_letter", {"vacancy_id": "demo-101", "lang": "ru"}), ctx_with(db)
    )

    assert error is None
    assert result["vacancy_id"] == "demo-101"
    assert result["lang"] == "ru"
    assert result["saved"] is True
    assert result["letter"].startswith("Здравствуйте")
    assert llm.calls, "письмо собрано через LLM-порт"
    # Сценарий письма пишет текст в карточку вакансии.
    assert any("update jobs" in sql for sql, _args in db.executed)


# ------------------------------------------------------------------- queue_application


async def test_queue_application_requires_confirmation(db: FakeDemoDb) -> None:
    context = ctx_with(db, confirm=lambda card: False)
    result, error, confirmed_by = await execute_tool(
        call(
            "queue_application",
            {"vacancy_id": "demo-101", "cover_note": "Здравствуйте! Меня заинтересовала позиция."},
        ),
        context,
    )
    assert error is None
    assert confirmed_by is None
    assert result["cancelled"] is True
    assert db.executed == [], "без «да» человека ничего не пишется в базу"


async def test_queue_application_after_confirmation_queues_and_persists(db: FakeDemoDb) -> None:
    context = ctx_with(db, confirm=lambda card: True)
    args = {"vacancy_id": "demo-101", "cover_note": "Здравствуйте! Готов обсудить позицию backend."}

    first, error, confirmed_by = await execute_tool(call("queue_application", args), context)
    second, error2, _ = await execute_tool(call("queue_application", args), context)

    assert error is None and error2 is None
    assert confirmed_by == "1"
    assert first["queued"] is True
    assert first["queue_bucket"] == "auto"
    assert second["idempotent_replay"] is True
    assert second["submission_id"] == first["submission_id"]
    writes = [sql for sql, _ in db.executed]
    assert any("update jobs" in sql for sql in writes), "текст письма уходит в карточку"
    assert any("auto_apply_queue_overrides" in sql for sql in writes), "вакансия в очереди"


async def test_queue_application_rejects_short_note(db: FakeDemoDb) -> None:
    result, error, _ = await execute_tool(
        call("queue_application", {"vacancy_id": "demo-101", "cover_note": "привет"}), ctx_with(db)
    )
    assert error is not None
    assert error.type == "validation"


async def test_queue_application_unknown_vacancy_is_not_found(db: FakeDemoDb) -> None:
    # Подтверждение есть («да» человека), но вакансии нет — not_found вместо записи в базу.
    result, error, _ = await execute_tool(
        call(
            "queue_application",
            {
                "vacancy_id": "demo-999",
                "cover_note": "Здравствуйте! Готов обсудить позицию senior backend.",
            },
        ),
        ctx_with(db, confirm=lambda card: True),
    )
    assert error is not None
    assert error.type == "not_found"
    assert db.executed == []


# ------------------------------------------------------------------- контракт инструмента


def test_every_tool_has_schema_and_demo_card() -> None:
    """Контракт A-2: у каждого инструмента схема аргументов и описание простыми словами."""
    assert {tool.name for tool in TOOLS} == {
        "read_profile",
        "search_vacancies",
        "read_work_terms",
        "score_vacancy",
        "write_cover_letter",
        "queue_application",
    }
    for tool in TOOLS:
        schema = tool.schema()
        assert schema["function"]["description"], tool.name
        parameters = schema["function"]["parameters"]
        assert parameters.get("additionalProperties") is False
    actions = [tool for tool in TOOLS if tool.kind == "action"]
    assert [tool.name for tool in actions] == ["queue_application"], "одно действие, с «да» человека"


def test_executor_protocol_satisfied_by_fake() -> None:
    """FakeDemoDb удовлетворяет структурному Protocol Executor (типовая страховка)."""
    executor: Executor = FakeDemoDb()  # type: ignore[assignment]
    assert executor is not None
