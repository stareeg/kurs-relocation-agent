"""Э19: `{{include: путь}}` в файлах `prompts/` — общий кусок промпта без копипасты.

Заведено под multiplayer: у трёх фич (реплика/судья/газета) общий канон — мир игры, тон,
бан-лист, few-shot-якоря. До этого канон лежал отдельным файлом с пометкой «копируется в
line/judge/ticker вручную», то есть по факту не применялся нигде, а каждый промпт нёс свой
огрызок правил.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.platform.llm import call as call_mod

ROOT = Path(__file__).resolve().parent.parent


def _load(path: str) -> str:
    call_mod._load_prompt_template.cache_clear()
    try:
        return call_mod._load_prompt_template(path)
    finally:
        call_mod._load_prompt_template.cache_clear()


def test_include_pastes_the_shared_canon() -> None:
    canon = (ROOT / "prompts" / "multiplayer" / "wolves_system.md").read_text(encoding="utf-8")
    marker = "Железное правило: ты играешь, но не судишь"
    assert marker in canon

    for feature_prompt in (
        "prompts/multiplayer/wolves_line.md",
        "prompts/multiplayer/wolves_judge.md",
        "prompts/multiplayer/wolves_ticker.md",
    ):
        text = _load(feature_prompt)
        assert marker in text, f"{feature_prompt}: канон не подставился"
        assert "{{include:" not in text, f"{feature_prompt}: остался нераскрытый include"


def test_prompt_version_follows_the_included_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Правка канона обязана инвалидировать кэш результатов включающих его фич.

    Иначе после смены тона игра ещё неделю отвечает старыми репликами из `llm_result_cache`.
    """
    from core.platform.llm.registry import LlmFeature

    feature = LlmFeature(
        name="_include_probe",
        tier="basic",
        prompt="prompts/multiplayer/wolves_ticker.md",
        prompt_in_code=False,
        max_tokens=1024,
        budget_ms=10_000,
    )
    call_mod._load_prompt_template.cache_clear()
    before = call_mod._prompt_version(feature)

    canon = ROOT / "prompts" / "multiplayer" / "wolves_system.md"
    original = canon.read_text(encoding="utf-8")
    try:
        canon.write_text(original + "\nПравка ради теста.\n", encoding="utf-8")
        call_mod._load_prompt_template.cache_clear()
        after = call_mod._prompt_version(feature)
    finally:
        canon.write_text(original, encoding="utf-8")
        call_mod._load_prompt_template.cache_clear()

    assert before != after, "хэш промпта не заметил правку включённого файла"


def test_missing_include_is_loud() -> None:
    probe = ROOT / "prompts" / "multiplayer" / "_include_probe.md"
    probe.write_text("{{include: prompts/multiplayer/нет-такого.md}}\n", encoding="utf-8")
    try:
        with pytest.raises(FileNotFoundError):
            _load("prompts/multiplayer/_include_probe.md")
    finally:
        probe.unlink(missing_ok=True)


def test_include_cycle_is_caught() -> None:
    probe = ROOT / "prompts" / "multiplayer" / "_include_cycle.md"
    probe.write_text("{{include: prompts/multiplayer/_include_cycle.md}}\n", encoding="utf-8")
    try:
        with pytest.raises(RecursionError):
            _load("prompts/multiplayer/_include_cycle.md")
    finally:
        probe.unlink(missing_ok=True)
