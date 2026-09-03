"""Реестр wolves_* + модели раздела (без платного вызова)."""

from __future__ import annotations

from core.domains.multiplayer import llm as mp_llm
from core.domains.multiplayer.models import WolvesJudgeOut
from core.platform.config.base import normalize_openrouter_model
from core.platform.config.llm import LlmSettings
from core.platform.llm.registry import all_features, ensure_features_loaded, get_feature

GAME_FEATURES = ("wolves_line", "wolves_judge", "wolves_ticker", "wolves_bark", "wolves_brief")


def test_wolves_features_registered() -> None:
    ensure_features_loaded()
    names = {f.name for f in all_features()}
    assert set(GAME_FEATURES) <= names
    for name in GAME_FEATURES:
        feat = get_feature(name)
        assert feat is not None
        assert feat.budget_ms and feat.budget_ms > 0
        assert feat.max_tokens and feat.max_tokens >= 1024


def test_schema_only_where_there_is_something_to_check() -> None:
    """Э19.8: structured у судьи (`cited_marker` сверяется с иском), у остальных — голый текст.

    Схема на фичах, отдающих одну фразу, стоила бы лишних токенов, дала бы свой класс отказов
    (пустой content, обрезанный JSON) и запретила бы стрим реплик, ничего не давая взамен.
    """
    with_schema = {f.name for f in mp_llm.FEATURES if f.schema is not None}
    assert with_schema == {"wolves_judge"}
    assert get_feature("wolves_judge").schema is WolvesJudgeOut  # type: ignore[union-attr]
    # Вердикт остаётся за движком: схема физически не даёт модели его переписать.
    assert set(WolvesJudgeOut.model_fields) == {"line", "cited_marker"}


def test_arbiter_feature_does_not_force_thinking_off() -> None:
    """Арбитр — модель с обязательным reasoning: `"none"` там стоит лишнего круга 400 → повтор.

    Плюс потолок токенов выше: при включённом thinking скрытые токены съедают `max_tokens`,
    и при json_schema ответ приходит пустым — фича молча падает в заглушку.
    """
    judge = get_feature("wolves_judge")
    assert judge is not None
    assert judge.reasoning_effort is None
    assert judge.max_tokens and judge.max_tokens >= 2048
    for name in ("wolves_line", "wolves_bark", "wolves_ticker", "wolves_brief"):
        feat = get_feature(name)
        assert feat is not None and feat.reasoning_effort == "none"


def test_every_feature_has_a_role_and_a_prompt() -> None:
    """Роль решает, какая модель играет фичу; без записи в таблице она уедет к режиссёру молча."""
    assert {f.name for f in mp_llm.FEATURES} == set(GAME_FEATURES)
    known_roles = (mp_llm.ROLE_ACTOR, mp_llm.ROLE_DIRECTOR, mp_llm.ROLE_ARBITER)
    for feat in mp_llm.FEATURES:
        assert feat.name in mp_llm.FEATURE_ROLE, f"{feat.name} без роли в FEATURE_ROLE"
        assert mp_llm.FEATURE_ROLE[feat.name] in known_roles
        assert feat.prompt and feat.prompt in mp_llm.PROMPT_PATHS.values()


def test_roles_split_speech_world_and_protocol() -> None:
    """Прямая речь — актёру, мир вокруг стола — режиссёру, строгий JSON — арбитру."""
    by_role: dict[str, set[str]] = {}
    for name, role in mp_llm.FEATURE_ROLE.items():
        by_role.setdefault(role, set()).add(name)
    assert by_role[mp_llm.ROLE_ACTOR] == {"wolves_line", "wolves_bark"}
    assert by_role[mp_llm.ROLE_DIRECTOR] == {"wolves_ticker", "wolves_brief"}
    assert by_role[mp_llm.ROLE_ARBITER] == {"wolves_judge"}


def test_extra_roles_fall_back_to_director() -> None:
    """Одна модель в `.env` должна продолжать работать: пустые актёр/арбитр = режиссёр."""
    only_director = LlmSettings(model_multiplayer="vendor/director")
    assert only_director.multiplayer_actor_model() == "vendor/director"
    assert only_director.multiplayer_arbiter_model() == "vendor/director"

    full = LlmSettings(
        model_multiplayer="vendor/director",
        model_multiplayer_actor="vendor/actor",
        model_multiplayer_arbiter="vendor/arbiter",
    )
    assert full.multiplayer_model() == "vendor/director"
    assert full.multiplayer_actor_model() == "vendor/actor"
    assert full.multiplayer_arbiter_model() == "vendor/arbiter"

    empty = LlmSettings()
    assert empty.multiplayer_model() == ""
    assert empty.multiplayer_actor_model() == ""
    assert empty.multiplayer_arbiter_model() == ""


def test_model_slugs_are_normalized() -> None:
    """Алиасы из старых `.env` чинятся в одном месте — все роли ходят через нормализацию."""
    alias = "deepseek/deepseek-v4-flash-latest"
    assert normalize_openrouter_model(alias) == "~deepseek/deepseek-v4-flash-latest"
    settings = LlmSettings(
        model_multiplayer=alias, model_multiplayer_actor=alias, model_multiplayer_arbiter=alias
    )
    assert settings.multiplayer_model() == "~deepseek/deepseek-v4-flash-latest"
    assert settings.multiplayer_actor_model() == "~deepseek/deepseek-v4-flash-latest"
    assert settings.multiplayer_arbiter_model() == "~deepseek/deepseek-v4-flash-latest"


def test_no_model_slug_hardcoded_in_python() -> None:
    """Модель меняется одной строкой `.env`; в коде домена живут только имена ролей."""
    from pathlib import Path

    domain = Path(__file__).resolve().parents[1] / "core" / "domains" / "multiplayer"
    for path in domain.glob("*.py"):
        body = path.read_text(encoding="utf-8")
        for vendor in ("qwen/", "tencent/", "deepseek/", "openai/", "google/", "anthropic/"):
            assert vendor not in body, f"{path.name}: slug {vendor!r} в Python — место ему в .env"
