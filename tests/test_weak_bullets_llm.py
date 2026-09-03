"""SM-5 (plans/heuristics_to_llm.md): find_weak_bullets — digit-or-verb эвристика ошибается в обе
стороны (буллет с цифрой не про результат проходит как сильный; содержательный буллет без цифры
и без стема из ACTION_VERB_STEMS ложно считается слабым). Проверяем: (1) регекс-баг документирован
напрямую, (2) батч-LLM-путь чинит оба случая одним вызовом на все буллеты, (3) откат на regex при
недоступности/сбое LLM.
"""

from __future__ import annotations

from core.domains.profile import weak_bullets_llm as weak_bullets_llm_module
from core.domains.profile.gap import (
    WeakBullet,
    _all_bullet_records,
    _bullets,
    count_bullets,
    find_weak_bullets,
    find_weak_bullets_llm,
)
from core.domains.profile.model import Experience, ResumeData
from core.domains.profile.weak_bullets_llm import resolve_weak_bullets_llm
from core.kernel.errors import LlmError

# Цифра есть, но она про состав команды, не про результат — regex ложно считает буллет сильным.
BULLET_DIGIT_NOT_RESULT = "работал с командой из 5 человек"
# Ни цифры, ни стема из ACTION_VERB_STEMS, но буллет содержательный — regex ложно считает слабым.
BULLET_CONTENT_NO_DIGIT_NO_VERB = (
    "разобрал зависший процесс ревью, договорился с командой об SLA на ответ"
)

_DATA = ResumeData(
    experience=[
        Experience(
            company="Acme",
            position="Lead LLM Engineer",
            description=f"- {BULLET_DIGIT_NOT_RESULT}\n- {BULLET_CONTENT_NO_DIGIT_NO_VERB}",
        )
    ]
)


def test_regex_fallback_mislabels_digit_and_verbless_bullets():
    """Документирует баг, который чинит SM-5."""
    weak_texts = {w.text for w in find_weak_bullets(_DATA)}
    assert BULLET_DIGIT_NOT_RESULT not in weak_texts  # ложно НЕ слабый (спасла случайная цифра)
    assert BULLET_CONTENT_NO_DIGIT_NO_VERB in weak_texts  # ложно слабый (нет цифры/глагола)


async def test_find_weak_bullets_llm_fixes_both_cases(monkeypatch):
    async def fake_resolve(bullets, **_kw):
        out = []
        for section, ref, index, text in bullets:
            if text == BULLET_DIGIT_NOT_RESULT:
                out.append(
                    WeakBullet(
                        section=section,
                        ref=ref,
                        index=index,
                        text=text,
                        reason="цифра про состав команды, не про результат",
                    )
                )
        return out

    monkeypatch.setattr(weak_bullets_llm_module, "resolve_weak_bullets_llm", fake_resolve)

    weak = await find_weak_bullets_llm(_DATA)
    weak_texts = {w.text for w in weak}
    assert BULLET_DIGIT_NOT_RESULT in weak_texts
    assert BULLET_CONTENT_NO_DIGIT_NO_VERB not in weak_texts


async def test_find_weak_bullets_llm_falls_back_to_regex_when_unavailable(monkeypatch):
    async def fake_resolve_none(bullets):
        return None

    monkeypatch.setattr(weak_bullets_llm_module, "resolve_weak_bullets_llm", fake_resolve_none)

    weak = await find_weak_bullets_llm(_DATA)
    weak_texts = {w.text for w in weak}
    assert weak_texts == {BULLET_CONTENT_NO_DIGIT_NO_VERB}  # ровно regex-путь, баг ещё жив


async def test_find_weak_bullets_llm_no_bullets_skips_llm_call(monkeypatch):
    async def fail_if_called(bullets):
        raise AssertionError("resolve_weak_bullets_llm must not be called without bullets")

    monkeypatch.setattr(weak_bullets_llm_module, "resolve_weak_bullets_llm", fail_if_called)

    weak = await find_weak_bullets_llm(ResumeData())
    assert weak == []


class _FakeLlm:
    """Порт-заглушка вместо monkeypatch'а platform-функции."""

    def __init__(self, text: str) -> None:
        self._text = text
        self.features: list[str] = []

    async def complete(self, feature, **kwargs):
        self.features.append(feature)
        return self._text

    async def structured(self, feature, *, schema, **kwargs):  # pragma: no cover
        raise AssertionError("weak_bullets ходит текстом, не structured")

    def stream(self, feature, **kwargs):  # pragma: no cover
        raise AssertionError("weak_bullets не стримит")


async def test_resolve_weak_bullets_llm_parses_batch_response(monkeypatch):
    llm = _FakeLlm(
        '{"verdicts": ['
        '{"i": 1, "weak": false, "reason": "есть эффект"},'
        '{"i": 2, "weak": true, "reason": "нет результата"}'
        "]}"
    )
    monkeypatch.setattr(
        weak_bullets_llm_module,
        "get_settings",
        lambda: type("S", (), {"openrouter_api_key": "test-key"})(),
    )

    bullets = [
        ("experience", "Acme — Lead", 0, "поднял latency-дашборд, сократил p95 вдвое"),
        ("experience", "Acme — Lead", 0, "занимался развитием продукта"),
    ]
    result = await resolve_weak_bullets_llm(bullets, llm=llm)
    assert llm.features == ["weak_bullets"]
    assert result == [
        WeakBullet(
            section="experience",
            ref="Acme — Lead",
            index=0,
            text="занимался развитием продукта",
                reason="добавьте результат",
        )
    ]


class _FlakyLlm:
    """Порт-заглушка §13: первые `fail_times` вызовов виснут (LlmError), затем отвечает."""

    def __init__(self, text: str, *, fail_times: int) -> None:
        self._text = text
        self._fail_times = fail_times
        self.calls = 0

    async def complete(self, feature, **kwargs):
        self.calls += 1
        if self.calls <= self._fail_times:
            raise LlmError(f"фича {feature!r}: таймаут budget_ms")
        return self._text

    async def structured(self, feature, *, schema, **kwargs):  # pragma: no cover
        raise AssertionError("weak_bullets ходит текстом, не structured")

    def stream(self, feature, **kwargs):  # pragma: no cover
        raise AssertionError("weak_bullets не стримит")


async def test_resolve_weak_bullets_llm_retries_once_after_llm_error(monkeypatch):
    """§13: первая попытка виснет/падает по budget_ms — вторая короткая попытка спасает результат."""
    monkeypatch.setattr(
        weak_bullets_llm_module,
        "get_settings",
        lambda: type("S", (), {"openrouter_api_key": "test-key"})(),
    )
    llm = _FlakyLlm(
        '{"verdicts": [{"i": 1, "weak": true, "reason": "нет результата"}]}',
        fail_times=1,
    )
    bullets = [("about", "Обо мне", None, "занимался развитием продукта")]

    result = await resolve_weak_bullets_llm(bullets, llm=llm)

    assert llm.calls == 2  # первая попытка сгорела, вторая — короткая, но успела
    assert result == [
        WeakBullet(
            section="about", ref="Обо мне", index=None, text=bullets[0][3], reason="добавьте результат"
        )
    ]


async def test_resolve_weak_bullets_llm_falls_back_after_two_failed_attempts(monkeypatch):
    """§13: обе короткие попытки виснут — не третья попытка, честный fallback на regex."""
    monkeypatch.setattr(
        weak_bullets_llm_module,
        "get_settings",
        lambda: type("S", (), {"openrouter_api_key": "test-key"})(),
    )
    llm = _FlakyLlm("не важно — не дойдёт до parse", fail_times=99)

    result = await resolve_weak_bullets_llm([("about", "Обо мне", None, "текст")], llm=llm)

    assert result is None
    assert llm.calls == 2  # ровно две попытки, не бесконечный ретрай


async def test_resolve_weak_bullets_llm_returns_none_without_api_key(monkeypatch):
    monkeypatch.setattr(
        weak_bullets_llm_module,
        "get_settings",
        lambda: type("S", (), {"openrouter_api_key": ""})(),
    )
    result = await resolve_weak_bullets_llm([("about", "Обо мне", None, "текст")])
    assert result is None


async def test_resolve_weak_bullets_llm_returns_none_on_invalid_json(monkeypatch):
    monkeypatch.setattr(
        weak_bullets_llm_module,
        "get_settings",
        lambda: type("S", (), {"openrouter_api_key": "test-key"})(),
    )

    result = await resolve_weak_bullets_llm(
        [("about", "Обо мне", None, "текст")], llm=_FakeLlm("не json вообще")
    )
    assert result is None


async def test_resolve_weak_bullets_llm_returns_empty_list_without_bullets():
    result = await resolve_weak_bullets_llm([])
    assert result == []


# --- Нумерованные списки (правка «Подогнать под ATS» / чат с Агентом) -----------------------

_NUMBERED = ResumeData(
    experience=[
        Experience(
            company="Сбер",
            position="Lead LLM Engineer",
            description=(
                "Архитектор multi-agent платформы:\n\n"
                "1. Спроектировал архитектуру Supervisor-Worker на LangGraph.\n"
                "2. Внедрил reasoning-пайплайны с Tool Calling.\n"
                "3. Настроил Self-correction, 78% авто-исправлений."
            ),
        )
    ],
    about=(
        "Фокусируюсь на:\n\n"
        "1. Multi-Agent платформах на LangGraph.\n"
        "2. Alignment & Safety: SFT/DPO, guardrails.\n"
        "3. Advanced RAG на Qdrant и Neo4j."
    ),
)


def test_bullets_recognizes_numbered_lists():
    """Нумерованные списки («1.», «2)») должны парситься как буллеты (раньше только «- »)."""
    assert len(_bullets(_NUMBERED.experience[0].description)) == 3
    assert len(_bullets(_NUMBERED.about)) == 3


def test_count_bullets_counts_numbered_lists():
    """count_bullets = 6 (3 в опыте + 3 в «Обо мне») — иначе фактор «Формулировки» обнулялся."""
    assert count_bullets(_NUMBERED) == 6


def test_all_bullet_records_covers_numbered_lists():
    records = _all_bullet_records(_NUMBERED)
    assert len(records) == 6
    # section/ref/index пробрасываются для опыта, «Обо мне» — index=None.
    exp_records = [r for r in records if r[0] == "experience"]
    about_records = [r for r in records if r[0] == "about"]
    assert len(exp_records) == 3 and all(r[2] == 0 for r in exp_records)
    assert len(about_records) == 3 and all(r[2] is None for r in about_records)


def test_mixed_dash_and_numbered_bullets():
    """Смесь «- » и «1. » в одном описании — обе формы считаются."""
    data = ResumeData(
        experience=[
            Experience(
                company="Acme",
                position="Lead",
                description="- Разобрал зависший ревью\n1. Поднял faithfulness до 0.9",
            )
        ]
    )
    assert count_bullets(data) == 2


def test_bullet_surrounded_by_prose_not_matched():
    """Обычные строки текста без маркеров не должны считаться буллетами."""
    data = ResumeData(about="Просто абзац текста без маркеров и цифр.")
    assert _bullets(data.about) == []
    assert count_bullets(data) == 0
