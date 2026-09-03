"""Контракт качества LlmFeature (+ L-13).

Каждая фича: тир, budget_ms > 0, max_tokens > 0, промпт (файл или `prompt_in_code`).
Если объявлена schema — это Pydantic BaseModel.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from core.platform.llm.openrouter_chat import TIERS
from core.platform.llm.registry import LlmFeature, all_features

_ROOT = Path(__file__).resolve().parents[3]


def check_feature_contract(
    feature: LlmFeature,
    *,
    root: Path | None = None,
) -> list[str]:
    """Вернуть список нарушений контракта (пустой = ок)."""
    errors: list[str] = []
    base = root or _ROOT

    if feature.tier not in TIERS:
        errors.append(f"неизвестный tier={feature.tier!r}")

    if feature.budget_ms is None:
        errors.append("нет budget_ms")
    elif not isinstance(feature.budget_ms, int) or feature.budget_ms <= 0:
        errors.append(f"budget_ms должен быть > 0, сейчас {feature.budget_ms!r}")

    if feature.max_tokens is None:
        errors.append("нет max_tokens")
    elif not isinstance(feature.max_tokens, int) or feature.max_tokens < 1024:
        # L-13: потолок выхода <1024 режет JSON/короткие structured-ответы и бесит в UI.
        errors.append(f"max_tokens должен быть ≥ 1024, сейчас {feature.max_tokens!r}")

    prompt = (feature.prompt or "").strip()
    has_prompt = bool(prompt)
    if has_prompt and feature.prompt_in_code:
        errors.append("prompt и prompt_in_code взаимоисключающи")
    elif not has_prompt and not feature.prompt_in_code:
        errors.append("нет prompt (файла) и не стоит prompt_in_code=True")
    elif has_prompt:
        path = Path(prompt) if Path(prompt).is_absolute() else base / prompt
        if not path.is_file():
            errors.append(f"prompt-файл не найден: {feature.prompt}")

    if feature.schema is not None and not (
        isinstance(feature.schema, type) and issubclass(feature.schema, BaseModel)
    ):
        errors.append(f"schema должна быть subclass BaseModel, сейчас {feature.schema!r}")

    return errors


def check_all_features_contract(*, root: Path | None = None) -> dict[str, list[str]]:
    """Имя фичи → нарушения. Пустой dict = все зелёные."""
    bad: dict[str, list[str]] = {}
    for feature in all_features():
        errs = check_feature_contract(feature, root=root)
        if errs:
            bad[feature.name] = errs
    return bad


__all__ = ["check_feature_contract", "check_all_features_contract"]
