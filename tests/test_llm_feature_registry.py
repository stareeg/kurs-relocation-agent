"""A-06/A-07: реестр LLM-фич — покрытие вызовов из кода + существование prompt-файлов."""

from __future__ import annotations

import re
from pathlib import Path

from core.platform.llm.openrouter_chat import TIERS
from core.platform.llm.registry import all_features, ensure_features_loaded, resolve_tier

ROOT = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = ROOT / "deploy" / ".env.example"

_NON_LLM_AGENT_NAMES = frozenset({"system"})

_RE_AGENT_KW = re.compile(r"""\bagent\s*=\s*["']([^"']+)["']""")
_RE_RUN = re.compile(r"""\brun\s*\(\s*["']([^"']+)["']""")
_RE_PORT_CALL = re.compile(r"""\.(?:complete|structured|stream)\s*\(\s*["']([^"']+)["']""")
_RE_AGENT_CONST = re.compile(
    r"""^[A-Z_][A-Z0-9_]*AGENT\s*=\s*["']([^"']+)["']""",
    re.MULTILINE,
)


def _iter_python_sources(*packages: str) -> list[Path]:
    paths: list[Path] = []
    for package in packages:
        root = ROOT / package
        if not root.is_dir():
            continue
        paths.extend(p for p in root.rglob("*.py") if p.is_file())
    return paths


def _llm_agent_names_from_code() -> set[str]:
    found: set[str] = set()
    for path in _iter_python_sources("core", "bot_app", "api"):
        src = path.read_text(encoding="utf-8")
        found.update(_RE_AGENT_KW.findall(src))
        found.update(_RE_RUN.findall(src))
        found.update(_RE_AGENT_CONST.findall(src))
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith(("core/domains/", "core/app/", "api/", "bot_app/")):
            found.update(_RE_PORT_CALL.findall(src))
    tiers = frozenset(TIERS)
    return {
        name
        for name in found
        if name not in tiers and name not in _NON_LLM_AGENT_NAMES
    }


def test_registry_covers_code_agents():
    ensure_features_loaded()
    registered = {f.name for f in all_features()}
    code_agents = _llm_agent_names_from_code()
    missing = sorted(code_agents - registered)
    assert not missing, (
        "В коде есть LLM agent=/run(\"…\") без LlmFeature в domains/*/llm.py: "
        f"{missing}. Добавь декларацию — иначе resolve_tier упадёт."
    )


def test_registry_tiers_are_known():
    ensure_features_loaded()
    tiers = frozenset(TIERS)
    bad = sorted(f"{f.name}→{f.tier}" for f in all_features() if f.tier not in tiers)
    assert not bad, f"В реестре неизвестные тиры: {bad}"


def test_registry_prompt_files_exist():
    """У каждой фичи с непустым prompt файл лежит в clone."""
    ensure_features_loaded()
    missing: list[str] = []
    with_prompt = 0
    for feature in all_features():
        if not feature.prompt:
            continue
        with_prompt += 1
        path = ROOT / feature.prompt
        if not path.is_file():
            missing.append(f"{feature.name}={feature.prompt!r} → {path}")
    assert not missing, (
        "Битый prompt у LlmFeature (файл не найден):\n" + "\n".join(missing)
    )
    assert with_prompt >= 10, f"ожидали ≥10 фич с prompt-файлом, получили {with_prompt}"


def test_resolve_tier_uses_feature_declaration():
    assert resolve_tier("job_search") == "basic"
    assert resolve_tier("screening_pitch") == "advanced"
    assert resolve_tier("salary_estimate") == "advanced"
    assert resolve_tier("system") == "basic"


def test_env_example_has_overrides_not_map():
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "AGENT_TIER_MAP=" not in text
    assert re.search(r"^AGENT_TIER_OVERRIDES=", text, re.MULTILINE), (
        "В deploy/.env.example нет AGENT_TIER_OVERRIDES="
    )
