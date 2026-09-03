"""Рынок поиска (`search_criteria.market_scope`) и статус занятости из опыта.

Две оси резюме, добавленные вместе с переездом критериев поиска в левую панель:

- «Рынок поиска» — «Только РФ» (дефолт) / «Международный» / «Любой». Пустое значение в
  сохранённых резюме читается как дефолт, а не как «не указано»: гадать за кандидата нечего.
- «Работает сейчас» — не из дат периодов (они свободные строки), а из галочки «по н.в.».

Тесты проверяют именно то, ради чего оси заводились: значение доезжает до промпта скоринга
(`to_markdown`), до профиля (`CandidateProfile`) и до блока ЦЕЛЬ на «Рынке».
"""

from __future__ import annotations

from core.domains.market.situation import _situation_goal_block
from core.domains.profile.model import (
    DesiredPosition,
    Experience,
    Personal,
    ResumeData,
    ResumeDataPatch,
    SearchCriteria,
    is_currently_employed,
    market_scope_label,
    to_markdown,
)
from core.domains.profile.profile import derive_candidate_profile


def _resume(**kwargs) -> ResumeData:
    return ResumeData(**kwargs)


# --- нормализация -----------------------------------------------------------------------


def test_market_scope_label_defaults_to_ru():
    assert market_scope_label("") == "Только РФ"
    assert market_scope_label("   ") == "Только РФ"
    # Мусор из старого/чужого JSON не роняет форму и не выдумывает третьего смысла.
    assert market_scope_label("что-то своё") == "Только РФ"


def test_market_scope_label_keeps_known_values():
    assert market_scope_label("Международный") == "Международный"
    assert market_scope_label("любой") == "Любой"


# --- профиль ----------------------------------------------------------------------------


def test_derive_profile_maps_scope_to_slug():
    profile = derive_candidate_profile(
        _resume(search_criteria=SearchCriteria(market_scope="Международный"))
    )
    assert profile.market_scope == "intl"
    assert profile.market_scope_label == "Международный"


def test_derive_profile_empty_scope_is_ru():
    profile = derive_candidate_profile(_resume())
    assert profile.market_scope == "ru"
    assert profile.market_scope_label == "Только РФ"


# --- статус занятости -------------------------------------------------------------------


def test_currently_employed_none_without_experience():
    assert is_currently_employed(_resume()) is None
    assert derive_candidate_profile(_resume()).currently_employed is None


def test_currently_employed_reads_current_flag():
    working = _resume(experience=[Experience(company="X", position="Инженер", current=True)])
    left = _resume(
        experience=[Experience(company="X", position="Инженер", current=False, end="Май 2026")]
    )
    assert is_currently_employed(working) is True
    assert is_currently_employed(left) is False
    assert derive_candidate_profile(working).currently_employed is True
    assert derive_candidate_profile(left).currently_employed is False


# --- промпт скоринга --------------------------------------------------------------------


def test_markdown_always_prints_market_scope():
    """Дефолт печатается тоже: «Только РФ» — такое же указание кандидата, как и остальные."""
    md = to_markdown(_resume())
    assert "- Рынок поиска: Только РФ" in md

    md_intl = to_markdown(_resume(search_criteria=SearchCriteria(market_scope="Международный")))
    assert "- Рынок поиска: Международный" in md_intl


def test_markdown_renames_countries_to_residence():
    md = to_markdown(_resume(personal=Personal(work_countries=["Россия"])))
    assert "- Страна проживания: Россия" in md
    assert "Страны для работы" not in md


def test_markdown_prints_employment_status():
    md_working = to_markdown(
        _resume(experience=[Experience(company="X", position="Инженер", current=True)])
    )
    assert "- Статус: сейчас работает" in md_working

    md_free = to_markdown(
        _resume(experience=[Experience(company="X", position="Инженер", current=False)])
    )
    assert "- Статус: сейчас без работы" in md_free

    # Опыта нет — статус не выдумываем.
    assert "- Статус:" not in to_markdown(_resume())


# --- автосейв чипа (PATCH /api/resume/data) ---------------------------------------------


def test_patch_round_trip_keeps_neighbours():
    """Тот же merge, что делает `api/routers/profile/resume.py::patch_resume_data`.

    Чип рынка шлёт точечный патч одной оси. Проверяем, что поле доезжает до модели (не
    отбрасывается как неизвестное) и что соседние оси критериев поиска патч не затирает.
    """
    current = ResumeData(search_criteria=SearchCriteria(niches=["LLM"], role_kind="Делаю руками"))
    body = ResumeDataPatch.model_validate({"search_criteria": {"market_scope": "Международный"}})
    assert body.search_criteria is not None
    fields = body.search_criteria.model_dump(exclude_unset=True)
    assert fields == {"market_scope": "Международный"}

    merged = current.model_copy(
        update={"search_criteria": current.search_criteria.model_copy(update=fields)}
    )
    assert merged.search_criteria.market_scope == "Международный"
    assert merged.search_criteria.niches == ["LLM"]
    assert merged.search_criteria.role_kind == "Делаю руками"
    # В jsonb резюме поле уезжает под своим именем — иначе фронт прочитает пустоту.
    assert merged.model_dump(mode="json")["search_criteria"]["market_scope"] == "Международный"


# --- блок ЦЕЛЬ на «Рынке» ---------------------------------------------------------------


def test_situation_goal_block_carries_scope_and_status():
    profile = derive_candidate_profile(
        _resume(
            position=DesiredPosition(title="Инженер", salary_min=300_000),
            search_criteria=SearchCriteria(market_scope="Любой"),
            experience=[Experience(company="X", position="Инженер", current=True)],
        )
    )
    block = _situation_goal_block(profile, horizon_days=60)
    assert "Рынок поиска: Любой." in block
    assert "Сейчас работает" in block


def test_situation_goal_block_stays_honest_on_empty_profile():
    """Пустое резюме — прежний честный отказ, а не «Рынок поиска: Только РФ» в вакууме."""
    block = _situation_goal_block(derive_candidate_profile(_resume()), horizon_days=60)
    assert "не описана" in block
    assert "Рынок поиска" not in block
