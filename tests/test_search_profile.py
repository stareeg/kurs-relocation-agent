"""Шаг 2: SearchProfile — производная от ResumeData для скоринга/аналитики."""

from __future__ import annotations

import json
from pathlib import Path

from core.domains.profile.model import ResumeData, SearchCriteria
from core.domains.profile.profile import (
    GRADE_SCALE,
    derive_search_profile,
    load_search_profile,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name: str) -> ResumeData:
    raw = json.loads((_FIXTURES / name).read_text(encoding="utf-8"))
    return ResumeData.model_validate(raw)


def test_derive_empty_resume_does_not_crash():
    profile = derive_search_profile(ResumeData())
    assert profile.role_kind == "unknown"
    assert profile.salary_basis == "net"
    assert profile.grade_floor_index == -1
    assert profile.grade_ceil_index == -1
    assert profile.priorities == []
    assert profile.is_filled is False
    assert profile.profile_axes_filled is False
    assert profile.identity  # нейтральная заглушка, не пустая


def test_derive_smoke_pm_grades_priorities_and_format():
    data = _load_fixture("resume_smoke_pm.json")
    profile = derive_search_profile(data)

    assert profile.title == "Project Manager"
    assert profile.target_grades == ["Senior", "Lead"]
    assert GRADE_SCALE[profile.grade_floor_index] == "Senior"
    assert GRADE_SCALE[profile.grade_ceil_index] == "Lead"
    assert profile.salary_min == 250_000
    assert profile.salary_comfortable == 320_000
    assert profile.salary_currency == "RUB"
    assert profile.salary_basis == "net"  # «На руки» → net
    assert profile.role_kind == "management"  # «Управляю людьми» (шаг 16)
    assert profile.market_segment == "IT"
    assert profile.profile_axes_filled is True
    assert profile.salary_anchor_base() == (250_000, 320_000)
    assert profile.priorities == [
        "Agile delivery",
        "FinTech product",
        "Cross-functional teams",
    ]
    assert profile.priorities == [
        n for n in data.search_criteria.niches if n.strip()
    ]
    assert profile.allows_office is True
    assert profile.allows_hybrid is True
    assert profile.allows_remote is False
    assert profile.travel_is_dealbreaker is True  # «Частые командировки» в dealbreakers
    assert profile.is_filled is True


def test_derive_smoke_frontend_remote_and_single_grade():
    data = _load_fixture("resume_smoke_frontend.json")
    profile = derive_search_profile(data)

    assert profile.title == "Senior Frontend Developer"
    assert profile.target_grades == ["Senior"]
    assert profile.grade_floor_index == profile.grade_ceil_index == GRADE_SCALE.index("Senior")
    assert profile.salary_min == 280_000
    assert profile.allows_office is False
    assert profile.allows_hybrid is True
    assert profile.allows_remote is True
    # relocation «Не готов…» → travel dealbreaker даже без редфлага в списке
    assert profile.travel_is_dealbreaker is True
    assert profile.priorities == ["Frontend", "Design systems", "E-commerce"]
    assert profile.is_filled is True
    assert profile.role_kind == "unknown"
    assert profile.profile_axes_filled is False


def test_derive_role_kind_and_salary_basis_normalization():
    data = _load_fixture("resume_smoke_pm.json")
    data.search_criteria.role_kind = "Управляю людьми"
    data.search_criteria.market_segment = "Медиа / Продакшн"
    data.position.salary_basis = "До вычета"

    profile = derive_search_profile(data)
    assert profile.role_kind == "management"
    assert profile.market_segment == "Медиа / Продакшн"
    assert profile.profile_axes_filled is True
    assert profile.salary_basis == "gross"

    data.search_criteria.role_kind = "Делаю руками"
    data.position.salary_basis = "На руки"
    profile2 = derive_search_profile(data)
    assert profile2.role_kind == "hands_on"
    assert profile2.salary_basis == "net"

    data.search_criteria.role_kind = "И то, и другое"
    assert derive_search_profile(data).role_kind == "mixed"


def test_profile_axes_filled_requires_both():
    data = ResumeData(
        search_criteria=SearchCriteria(role_kind="Делаю руками", market_segment=""),
    )
    assert derive_search_profile(data).profile_axes_filled is False
    data.search_criteria.market_segment = "IT"
    assert derive_search_profile(data).profile_axes_filled is True


def test_load_search_profile_reads_fixture(tmp_path, monkeypatch):
    src = _FIXTURES / "resume_smoke_pm.json"
    dest = tmp_path / "resume_data.json"
    dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("RESUME_DATA_PATH", str(dest))
    from core.config import get_settings
    from core.domains.profile.profile import clear_search_profile_cache

    get_settings.cache_clear()
    clear_search_profile_cache()

    profile = load_search_profile()
    assert profile.title == "Project Manager"
    assert profile.is_filled is True


def test_clear_resume_cache_refreshes_search_profile(tmp_path, monkeypatch):
    """Тот же путь JSON, новое содержимое: без clear_resume_cache профиль остаётся старым.

    Критерий шага 3: load → смена резюме → clear_resume_cache → профиль обновился.
    Кэш keyed по пути, поэтому переписываем файл на месте (как save из вкладки «Резюме»).
    """
    dest = tmp_path / "resume_data.json"
    dest.write_text(
        (_FIXTURES / "resume_smoke_pm.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    monkeypatch.setenv("RESUME_DATA_PATH", str(dest))

    from core.config import get_settings
    from core.domains.opportunities.prompt import clear_resume_cache

    get_settings.cache_clear()
    clear_resume_cache()

    first = load_search_profile()
    assert first.title == "Project Manager"

    dest.write_text(
        (_FIXTURES / "resume_smoke_frontend.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    # get_settings тот же путь — без clear отдаст закэшированный PM-профиль.
    stale = load_search_profile()
    assert stale.title == "Project Manager"

    clear_resume_cache()
    fresh = load_search_profile()
    assert fresh.title == "Senior Frontend Developer"
    assert fresh.allows_remote is True
    assert fresh.priorities == ["Frontend", "Design systems", "E-commerce"]
