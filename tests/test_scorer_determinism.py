"""Этап 8 §8.2 (plans/scoring_precision_2026_08_17.md): базовая линия детерминизма скоринга.

Прод-находка (§1.11): одна и та же вакансия под двумя `vacancy_id` — 50 и 69 баллов (Δ19),
и теста, который бы это ловил, не было. Здесь — реальный (платный) прогон одного и того же
текста три раза подряд: `overall_score` должен укладываться в разброс ±5, `recommendation` —
совпадать.

Замер 2026-08-18 (баллы вакансии из этого файла, тир `basic`, temperature=0.3, 5 прогонов вместо
трёх — для более честной оценки хвоста): 81/83/83/84/83, разброс 3, `recommendation` не менялся
ни разу. Похоже, что прод-разъезд 50/69 из §1.11 — не сама LLM-стохастика (она укладывается в
единицы баллов), а дрейф весов рубрики между двумя моментами скоринга (D7/§1.5, уже закрыт
Этапом 5 — версионирование весов). Порог ниже (±5) оставлен с запасом над измеренным разбросом.

Живой только сам LLM-вызов; резюме и ручные company-правила аккаунта замоканы (structured_store
читает Postgres, здесь не нужен) — маркер только `llm`, не `db`. Зарплата — по explicit-пути
(`salary_text` с цифрами), чтобы разброс не размывался вторым, независимым источником
неопределённости (фоновая LLM-оценка вилки).

**Кэш результатов обязательно обходить.** `call.run` кэширует по `feature:prompt_version:
input_hash` (TTL 7д) — три вызова с ОДИНАКОВЫМ текстом внутри одного процесса без этого всегда
дают разброс 0: второй и третий прогон бьют в `llm_result_cache`/in-process кэш, а не в модель,
и тест перестаёт что-либо проверять. `_FreshCacheLlm` форсирует уникальный `cache_key` на
каждый вызов (Protocol `LlmPort.structured` несёт этот параметр явно — `platform.llm` домену
импортировать не нужно).

Запуск: `uv run pytest -m llm tests/test_scorer_determinism.py` (нужен `OPENROUTER_API_KEY`).
Если разброс не проходит — снижать температуру фичи `job_search` (`core/domains/opportunities/
llm.py`) или усиливать формулировки уровней в `prompts/opportunities/instructions.md`
(см. план §8.2), не поднимать порог тут.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from core.domains.opportunities.scorer import score_vacancy
from core.domains.profile.model import ResumeData
from core.kernel import ports
from core.kernel.ports import LlmPort

pytestmark = pytest.mark.llm

# Тот же генерик-фикстур-резюме (не владелец), что FR-34 (test_smoke_other_specialty.py).
_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "resume_smoke_frontend.json"

# Умеренное, не крайнее совпадение (не гейт, не потолок 100) — там, где у оси «Содержание роли»
# реально есть простор для субъективной оценки модели от вызова к вызову.
_VACANCY_TEXT = (
    "Ищем Middle+/Senior Frontend Developer во внутреннюю CRM-систему логистической компании.\n"
    "Стек: Vue 3, немного React на легаси-модулях, TypeScript частично (часть кодовой базы "
    "ещё на чистом JS), Vuex, Webpack.\n"
    "Задачи: доработка форм и таблиц внутреннего интерфейса, немного вёрстки по готовому "
    "дизайну (design system не используется), поддержка легаси-модулей.\n"
    "Формат: гибрид 3 дня в офисе (Санкт-Петербург), 2 дня из дома.\n"
    "Зарплата: 285 000 - 300 000 ₽ на руки, обсуждается по итогам собеседования."
)
_SALARY_TEXT = "285 000 - 300 000 ₽ на руки"

# Допустимый разброс `overall_score` между прогонами одного и того же текста (замерено 3, см. выше).
_MAX_SPREAD = 5
_RUNS = 3


class _FreshCacheLlm:
    """Обёртка над реальным LLM-портом, форсирующая уникальный `cache_key` на каждый вызов."""

    def __init__(self, inner: LlmPort) -> None:
        self._inner = inner

    async def complete(self, feature: str, **kwargs: Any) -> str:
        kwargs["cache_key"] = str(uuid.uuid4())
        return await self._inner.complete(feature, **kwargs)

    async def structured(self, feature: str, *, schema: Any, **kwargs: Any) -> Any:
        kwargs["cache_key"] = str(uuid.uuid4())
        return await self._inner.structured(feature, schema=schema, **kwargs)

    def stream(self, feature: str, **kwargs: Any):
        return self._inner.stream(feature, **kwargs)


def _resume() -> ResumeData:
    return ResumeData.model_validate(json.loads(_FIXTURE.read_text(encoding="utf-8")))


@pytest.fixture(autouse=True)
def _patch_account_io(monkeypatch: pytest.MonkeyPatch) -> None:
    """Резюме и ручные company-правила — из фикстуры/пусто, а не из Postgres (маркер только
    llm, не db). `load_list_company_adjustments` НЕ трогаем — чистая функция от резюме."""
    resume = _resume()

    async def fake_resume(_account_id: int, db: object | None = None) -> ResumeData:
        return resume

    async def fake_manual_rules(_account_id: int) -> list:
        return []

    monkeypatch.setattr(
        "core.domains.profile.structured_store.read_resume_data_for_account", fake_resume
    )
    monkeypatch.setattr(
        "core.domains.opportunities.scorer.load_manual_company_adjustments", fake_manual_rules
    )


async def test_same_vacancy_scored_three_times_stays_within_spread() -> None:
    llm = _FreshCacheLlm(ports.llm())
    results = [
        await score_vacancy(
            _VACANCY_TEXT,
            account_id=1,
            salary_use_llm=False,
            salary_text=_SALARY_TEXT,
            company="Ozon",
            llm=llm,
        )
        for _ in range(_RUNS)
    ]
    scores = [r.overall_score for r in results]
    recommendations = {r.recommendation for r in results}

    spread = max(scores) - min(scores)
    assert spread <= _MAX_SPREAD, f"разброс {spread} > {_MAX_SPREAD}: баллы {scores}"
    assert len(recommendations) == 1, f"recommendation разъехались: {recommendations} ({scores})"
