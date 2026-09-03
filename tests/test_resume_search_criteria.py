"""FR-18: сохранение search_criteria → сброс кэша скоринга → свежий промпт.

Цепочка: PUT /api/resume/data → save_resume_data → clear_resume_cache → to_markdown
включает «Критерии поиска» в {{RESUME}} без рестарта сервера.
"""

from __future__ import annotations

import json
from pathlib import Path

from core.config import get_settings
from core.domains.profile.model import DesiredPosition, ResumeData, SearchCriteria, to_markdown
from core.domains.profile.structured_store import read_resume_data_from_file, save_resume_data
from core.domains.opportunities.prompt import load_candidate_specialization, load_resume

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _use_temp_resume(tmp_path, monkeypatch):
    path = tmp_path / "resume_data.json"
    monkeypatch.setenv("RESUME_DATA_PATH", str(path))
    get_settings.cache_clear()
    return path


def test_to_markdown_includes_search_criteria():
    data = ResumeData(
        search_criteria=SearchCriteria(
            niches=["LLM / RAG", "Agentic"],
            target_companies=["Яндекс", "Ozon"],
            avoid_companies=["аутсорс"],
            dealbreakers=["Офис без удалёнки", "Только ГПХ / ИП"],
            notes="Полная удалёнка, гражданство РФ.",
        )
    )
    md = to_markdown(data)
    assert "## Критерии поиска" in md
    assert "Приоритеты (по убыванию):" in md
    assert "Приоритетные ниши" not in md
    assert "LLM / RAG" in md
    assert "Яндекс" in md
    assert "аутсорс" in md
    assert "Офис без удалёнки" in md
    assert "Полная удалёнка, гражданство РФ." in md


def test_to_markdown_omits_red_flags_when_dealbreakers_empty():
    """Пустые ред флаги - нормальное состояние, секция не появляется и ничего не ломает."""
    data = ResumeData(
        search_criteria=SearchCriteria(
            niches=["LLM"],
            dealbreakers=[],
            notes="",
        )
    )
    md = to_markdown(data)
    assert "Ред флаги" not in md
    assert "LLM" in md


def test_to_markdown_profile_axes_and_salary_basis():
    """Новые оси профиля и базис зарплаты печатаются только когда заполнены (базис - суффикс)."""
    filled = ResumeData(
        position=DesiredPosition(
            salary_min=250_000,
            salary_currency="RUB",
            salary_basis="На руки",
        ),
        search_criteria=SearchCriteria(
            role_kind="Управляю людьми",
            market_segment="Медиа / Продакшн",
            niches=["Agile delivery"],
        ),
    )
    md = to_markdown(filled)
    assert "Желаемая зарплата: от 250 000 ₽ на руки." in md
    assert "- Тип роли: Управляю людьми" in md
    assert "- Рынок / отрасль: Медиа / Продакшн" in md
    assert "Приоритеты (по убыванию): Agile delivery" in md
    assert "Приоритетные ниши" not in md

    empty_axes = ResumeData(
        position=DesiredPosition(salary_min=200_000),
        search_criteria=SearchCriteria(),
    )
    md_empty = to_markdown(empty_axes)
    # Пустой salary_basis = исторический дефолт «на руки».
    assert "Желаемая зарплата: от 200 000 ₽ на руки." in md_empty
    assert "Тип роли:" not in md_empty
    assert "Рынок / отрасль:" not in md_empty
    assert "Приоритеты" not in md_empty


def test_to_markdown_salary_basis_gross():
    data = ResumeData(
        position=DesiredPosition(
            salary_min=300_000,
            salary_comfortable=400_000,
            salary_basis="До вычета",
        )
    )
    md = to_markdown(data)
    assert "Желаемая зарплата: от 300 000 до 400 000 ₽ до вычета." in md


def test_legacy_resume_json_loads_without_new_keys(tmp_path, monkeypatch):
    """Старый resume_data.json без salary_basis/role_kind/market_segment грузится с дефолтами."""
    _use_temp_resume(tmp_path, monkeypatch)
    path = tmp_path / "resume_data.json"
    path.write_text(
        json.dumps(
            {
                "position": {"title": "PM", "salary_min": 200000},
                "search_criteria": {"niches": ["Delivery"]},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    get_settings.cache_clear()
    loaded = read_resume_data_from_file()
    assert loaded.position.salary_basis == ""
    assert loaded.search_criteria.role_kind == ""
    assert loaded.search_criteria.market_segment == ""
    assert loaded.search_criteria.niches == ["Delivery"]


def test_to_markdown_smoke_pm_fixture_priorities_label():
    raw = json.loads((_FIXTURES / "resume_smoke_pm.json").read_text(encoding="utf-8"))
    data = ResumeData.model_validate(raw)
    md = to_markdown(data)
    assert "Приоритеты (по убыванию):" in md
    assert "Приоритетные ниши" not in md
    assert "Agile delivery" in md
    # Фикстура уже заполняет оси профиля поиска.
    assert "- Тип роли: Управляю людьми" in md
    assert "- Рынок / отрасль: IT" in md
    assert "на руки" in md


def test_to_markdown_smoke_pm_with_profile_axes_filled():
    raw = json.loads((_FIXTURES / "resume_smoke_pm.json").read_text(encoding="utf-8"))
    raw["position"]["salary_basis"] = "На руки"
    raw["search_criteria"]["role_kind"] = "Управляю людьми"
    raw["search_criteria"]["market_segment"] = "IT"
    md = to_markdown(ResumeData.model_validate(raw))
    assert "- Тип роли: Управляю людьми" in md
    assert "- Рынок / отрасль: IT" in md
    assert "на руки" in md


async def test_save_resume_data_persists_search_criteria(tmp_path, monkeypatch):
    _use_temp_resume(tmp_path, monkeypatch)
    payload = ResumeData(
        search_criteria=SearchCriteria(
            niches=["FinTech"],
            role_kind="Делаю руками",
            market_segment="Финансы",
            target_companies=["Тинькофф"],
            dealbreakers=["без вилки"],
            notes="Ищу продукт.",
        )
    )
    await save_resume_data(payload)
    loaded = read_resume_data_from_file()
    assert loaded.search_criteria.niches == ["FinTech"]
    assert loaded.search_criteria.role_kind == "Делаю руками"
    assert loaded.search_criteria.market_segment == "Финансы"
    assert loaded.search_criteria.target_companies == ["Тинькофф"]
    assert loaded.search_criteria.dealbreakers == ["без вилки"]
    assert loaded.search_criteria.notes == "Ищу продукт."


async def test_save_resume_data_refreshes_scoring_prompt_cache(tmp_path, monkeypatch):
    """Без clear_resume_cache() в save_resume_data второй save оставил бы старые ниши в промпте."""
    _use_temp_resume(tmp_path, monkeypatch)

    await save_resume_data(ResumeData(search_criteria=SearchCriteria(niches=["Alpha"])))
    first = load_resume()
    assert "Alpha" in first
    assert "Beta" not in first

    await save_resume_data(ResumeData(search_criteria=SearchCriteria(niches=["Beta"])))
    second = load_resume()
    assert "Beta" in second
    assert "Alpha" not in second

    assert load_candidate_specialization() == "Beta"


async def test_roundtrip_preserves_empty_search_criteria(tmp_path, monkeypatch):
    _use_temp_resume(tmp_path, monkeypatch)
    await save_resume_data(ResumeData())
    loaded = read_resume_data_from_file()
    assert loaded.search_criteria.niches == []
    assert loaded.search_criteria.role_kind == ""
    assert loaded.search_criteria.market_segment == ""
    assert loaded.search_criteria.notes == ""
    assert loaded.position.salary_basis == ""
