"""Существование путей: промпты из деклараций доменов + LlmFeature.prompt + *_path в CoreSettings.

R-40/A-06: `*_prompt_path` убраны из CoreSettings — пути в `domains/*/llm.PROMPT_PATHS` и
`LlmFeature.prompt`. Ловит переименование/перенос промпта без обновления декларации.
Секреты (`secrets/*`) опциональны: на машине друга файлов может не быть.
"""

from __future__ import annotations

from pathlib import Path

from core.config import CoreSettings, get_settings
from core.domains.assistant.llm import PROMPT_PATHS as ASSISTANT_PROMPTS
from core.domains.market.llm import PROMPT_PATHS as MARKET_PROMPTS
from core.domains.multiplayer.llm import PROMPT_PATHS as MULTIPLAYER_PROMPTS
from core.domains.offers.llm import PROMPT_PATHS as OFFERS_PROMPTS
from core.domains.opportunities.llm import PROMPT_PATHS as OPPORTUNITIES_PROMPTS
from core.domains.preparation.llm import PROMPT_PATHS as PREPARATION_PROMPTS
from core.domains.profile.llm import PROMPT_PATHS as PROFILE_PROMPTS
from core.platform.llm.registry import all_features, ensure_features_loaded

ROOT = Path(__file__).resolve().parents[1]

_OPTIONAL_SECRET_PATH_FIELDS = frozenset(
    {
        "langsmith_api_key_path",
    }
)

_DOMAIN_PROMPT_MAPS: tuple[dict[str, str], ...] = (
    OPPORTUNITIES_PROMPTS,
    PREPARATION_PROMPTS,
    ASSISTANT_PROMPTS,
    PROFILE_PROMPTS,
    MARKET_PROMPTS,
    OFFERS_PROMPTS,
    MULTIPLAYER_PROMPTS,
)


def _path_fields() -> list[str]:
    return sorted(
        name
        for name in CoreSettings.model_fields
        if name.endswith("_path") and name not in _OPTIONAL_SECRET_PATH_FIELDS
    )


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else (ROOT / path)


def test_domain_prompt_paths_exist_in_repo():
    """Все пути из `domains/*/llm.PROMPT_PATHS` — файлы в clone."""
    missing: list[str] = []
    seen: set[str] = set()
    for mapping in _DOMAIN_PROMPT_MAPS:
        for key, raw in mapping.items():
            if raw in seen:
                continue
            seen.add(raw)
            path = _resolve(raw)
            if not path.is_file():
                missing.append(f"{key}={raw!r} → {path}")
    assert not missing, (
        "Битый путь в domains/*/llm.PROMPT_PATHS (файл не найден). "
        "Переименовали промпт и забыли обновить декларацию?\n" + "\n".join(missing)
    )
    assert len(seen) >= 20, f"ожидали ≥20 промптов в декларациях, получили {len(seen)}"


def test_llm_feature_prompt_paths_exist():
    """A-06: каждый LlmFeature.prompt указывает на существующий файл."""
    ensure_features_loaded()
    missing: list[str] = []
    for feature in all_features():
        if not feature.prompt:
            continue
        path = _resolve(feature.prompt)
        if not path.is_file():
            missing.append(f"{feature.name}={feature.prompt!r} → {path}")
    assert not missing, (
        "Битый LlmFeature.prompt (файл не найден).\n" + "\n".join(missing)
    )


def test_settings_path_fields_point_to_existing_files():
    """Оставшиеся *_path в CoreSettings (resume, secrets, benchmarks) — файлы или пусто."""
    settings = get_settings()
    missing: list[str] = []
    for name in _path_fields():
        raw = str(getattr(settings, name) or "").strip()
        if not raw:
            continue
        path = _resolve(raw)
        if not path.is_file():
            missing.append(f"{name}={raw!r} → {path}")
    assert not missing, (
        "Битые *_path в CoreSettings (файл не найден).\n" + "\n".join(missing)
    )


def test_settings_default_resume_path_has_example():
    """Дефолт resume_data_path — в git не идёт; в clone должен быть пример установщика."""
    default = CoreSettings.model_fields["resume_data_path"].default
    assert isinstance(default, str) and default.strip()
    example = ROOT / "deploy" / "resume_data.example.json"
    assert example.is_file(), f"нет {example} под дефолт resume_data_path={default!r}"


def test_no_prompt_path_fields_in_core_settings():
    """R-40: промпты не живут в CoreSettings."""
    names = set(_path_fields())
    leaked = sorted(n for n in names if "prompt" in n or n == "instructions_path")
    assert not leaked, f"остались prompt-поля в CoreSettings: {leaked}"
    assert "resume_data_path" in names
