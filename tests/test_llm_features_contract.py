"""A-09: контракт качества LlmFeature (промпт, тир, budget_ms, schema)."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from core.platform.llm.contract import check_all_features_contract, check_feature_contract
from core.platform.llm.openrouter_chat import TIERS
from core.platform.llm.registry import LlmFeature, all_features, ensure_features_loaded

ROOT = Path(__file__).resolve().parents[1]


def test_all_registered_features_satisfy_contract():
    ensure_features_loaded()
    bad = check_all_features_contract(root=ROOT)
    assert not bad, (
        "Нарушения контракта LlmFeature:\n"
        + "\n".join(f"  {name}: {errs}" for name, errs in sorted(bad.items()))
    )


def test_every_feature_has_tier_budget_and_prompt_declaration():
    ensure_features_loaded()
    features = all_features()
    assert len(features) >= 20, f"ожидали реестр не пустой, получили {len(features)}"
    for feat in features:
        assert feat.tier in TIERS
        assert isinstance(feat.budget_ms, int) and feat.budget_ms > 0
        assert isinstance(feat.max_tokens, int) and feat.max_tokens >= 1024
        assert feat.prompt or feat.prompt_in_code
        # L-13: не больше одного ремонтного вызова на сценарий.
        assert feat.retries is None or feat.retries <= 1, (
            f"{feat.name}: retries={feat.retries} — канон ≤1"
        )


def test_structured_features_declare_pydantic_schema():
    """У фич с schema в декларации — настоящий BaseModel."""
    ensure_features_loaded()
    with_schema = [f for f in all_features() if f.schema is not None]
    assert len(with_schema) >= 2, (
        f"ожидали ≥2 фичи со schema в декларации, получили {len(with_schema)}"
    )
    for feat in with_schema:
        assert isinstance(feat.schema, type) and issubclass(feat.schema, BaseModel), (
            f"{feat.name}: schema={feat.schema!r} не BaseModel"
        )


def test_broken_declaration_fails_contract():
    """Намеренно сломанные декларации не проходят check_feature_contract."""
    no_budget = LlmFeature(
        name="broken_no_budget",
        tier="basic",
        max_tokens=1024,
        prompt_in_code=True,
    )
    assert "budget_ms" in " ".join(check_feature_contract(no_budget, root=ROOT))

    no_tokens = LlmFeature(
        name="broken_no_tokens",
        tier="basic",
        budget_ms=10_000,
        prompt_in_code=True,
    )
    assert "max_tokens" in " ".join(check_feature_contract(no_tokens, root=ROOT))

    low_tokens = LlmFeature(
        name="broken_low_tokens",
        tier="basic",
        budget_ms=10_000,
        max_tokens=1024,
        prompt_in_code=True,
    )
    object.__setattr__(low_tokens, "max_tokens", 300)
    assert any("1024" in e for e in check_feature_contract(low_tokens, root=ROOT))

    no_prompt = LlmFeature(
        name="broken_no_prompt",
        tier="basic",
        budget_ms=10_000,
        max_tokens=1024,
    )
    errs = check_feature_contract(no_prompt, root=ROOT)
    assert any("prompt" in e for e in errs)

    bad_schema = LlmFeature(
        name="broken_schema",
        tier="basic",
        budget_ms=10_000,
        max_tokens=1024,
        prompt_in_code=True,
        schema=str,  # type: ignore[arg-type]
    )
    assert any("schema" in e for e in check_feature_contract(bad_schema, root=ROOT))

    missing_file = LlmFeature(
        name="broken_prompt_file",
        tier="basic",
        budget_ms=10_000,
        max_tokens=1024,
        prompt="prompts/__does_not_exist_a09__.md",
    )
    assert any("не найден" in e for e in check_feature_contract(missing_file, root=ROOT))
