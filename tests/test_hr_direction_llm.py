"""EXT-H1 (plans/extension_v2.md): DOM-эвристика направления реплики HR-треда
(`extension/src/dom/selectors.ts::_hrMessageDirection`) молча теряет реплику без надёжного
сигнала. `classify_hr_directions_llm` — батч-фолбэк на весь тред; здесь проверяем контракт:
только index'ы с kind=None классифицируются, LLM недоступна/упала → {} (расширение падает на
прежний fallback, не угадывает).

После A-10 модуль ходит в LLM через порт `kernel.ports.LlmPort` — вместо monkeypatch'а
platform-функции тесты передают фейковый порт параметром `llm=`.
"""

from __future__ import annotations

from core.domains.pipeline import hr_direction_llm
from core.domains.pipeline.hr_direction_llm import ThreadMessageIn, classify_hr_directions_llm


def _settings(has_key: bool):
    return type("S", (), {"openrouter_api_key": "test-key" if has_key else ""})()


class _FakeLlm:
    """Порт-заглушка: отдаёт заранее заданные items либо падает."""

    def __init__(self, items: list[dict] | None = None, error: Exception | None = None) -> None:
        self._items = items or []
        self._error = error
        self.calls = 0

    async def complete(self, feature, **kwargs):  # pragma: no cover — не используется
        raise AssertionError("classify_hr_directions_llm ходит только в structured")

    async def structured(self, feature, *, schema, **kwargs):
        self.calls += 1
        if self._error:
            raise self._error
        return schema.model_validate({"items": self._items})

    def stream(self, feature, **kwargs):  # pragma: no cover — не используется
        raise AssertionError("classify_hr_directions_llm не стримит")


class _ForbiddenLlm(_FakeLlm):
    async def structured(self, feature, *, schema, **kwargs):
        raise AssertionError("LLM не должна вызываться, когда нечего классифицировать")


async def test_classify_returns_empty_without_unresolved():
    messages = [ThreadMessageIn(index=0, kind="hr_in", body="Здравствуйте")]
    result = await classify_hr_directions_llm(messages, account_id=1, llm=_ForbiddenLlm())
    assert result == {}


async def test_classify_returns_empty_without_api_key(monkeypatch):
    monkeypatch.setattr(hr_direction_llm, "get_settings", lambda: _settings(False))

    messages = [ThreadMessageIn(index=0, kind=None, body="Непонятно чьё сообщение")]
    result = await classify_hr_directions_llm(messages, account_id=1, llm=_ForbiddenLlm())
    assert result == {}


async def test_classify_resolves_only_unresolved_indices(monkeypatch):
    monkeypatch.setattr(hr_direction_llm, "get_settings", lambda: _settings(True))

    llm = _FakeLlm(
        items=[
            {"index": 1, "kind": "hr_out"},
            {"index": 99, "kind": "hr_in"},  # индекс не запрашивался — должен отсеяться
        ]
    )
    messages = [
        ThreadMessageIn(index=0, kind="hr_in", body="Добрый день, расскажите о вакансии"),
        ThreadMessageIn(index=1, kind=None, body="Здравствуйте, готов ответить"),
    ]
    result = await classify_hr_directions_llm(messages, account_id=1, llm=llm)
    assert result == {1: "hr_out"}
    assert llm.calls == 1


async def test_classify_swallows_llm_error(monkeypatch):
    monkeypatch.setattr(hr_direction_llm, "get_settings", lambda: _settings(True))

    llm = _FakeLlm(error=RuntimeError("upstream network error"))
    messages = [ThreadMessageIn(index=0, kind=None, body="???")]
    result = await classify_hr_directions_llm(messages, account_id=1, llm=llm)
    assert result == {}
