"""Тестовые двойники портов.

Обычный модуль, а не `conftest`: импортируется явно там, где нужен, и не влияет на прогон
остальных тестов (`tests/conftest.py` по договорённости держит только UTF-8).

Домены после A-10 зовут LLM через `core.kernel.ports.llm()`, поэтому подмена — это фейковый
порт (параметром `llm=` или через `ports.use_ports(llm=…)`), а не monkeypatch платформенной
функции внутри модуля домена.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ConfigDict, PrivateAttr

from core.kernel import ports
from core.kernel.vacancy import RawVacancy


class ScriptedChatModel(BaseChatModel):
    """Фейк чат-модели для графа агента (A-1): заготовленные сообщения по порядку.

    Отвечает BaseMessage-ами из списка (последний повторяется), имена инструментов
    из `bind_tools` копит в `seen_tools` — так тесты проверяют, какие инструменты
    реально видит модель внутри deepagents. `ls_provider` рапортует «openrouter»,
    чтобы профиль harness deepagents применялся в тестах так же, как в проде.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    responses: list[BaseMessage]
    seen_tools: list[list[str]] = []
    ls_provider_name: str = "openrouter"
    _cursor: Any = PrivateAttr(default=0)

    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedChatModel:
        names: list[str] = []
        for tool in tools:
            if isinstance(tool, dict):
                names.append(str(tool.get("function", {}).get("name", "?")))
            else:
                names.append(str(getattr(tool, "name", "?")))
        self.seen_tools.append(names)
        return self

    @property
    def _llm_type(self) -> str:
        return "scripted-chat"

    def _get_ls_params(self, stop: list[str] | None = None, **kwargs: Any) -> dict[str, Any]:
        return {"ls_provider": self.ls_provider_name, "ls_model_name": "scripted"}

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        _ = messages, stop, run_manager, kwargs
        index = int(self._cursor)
        message = self.responses[index if index < len(self.responses) else -1]
        self._cursor = index + 1
        return ChatResult(generations=[ChatGeneration(message=message)])


class FakeVacancySource:
    """Двойник `VacancySource`: отдаёт заготовленные `RawVacancy` без сети."""

    name = "fake"

    def __init__(
        self,
        vacancies: Sequence[RawVacancy] | None = None,
        *,
        name: str = "fake",
    ) -> None:
        self.name = name
        self._vacancies = list(vacancies or [])

    async def fetch(self, query: str) -> list[RawVacancy]:
        _ = query
        return list(self._vacancies)

    def parse(self, html: str) -> RawVacancy:
        if self._vacancies:
            return self._vacancies[0]
        return RawVacancy(text=html, source=self.name)


class FakeChannel:
    """Двойник `Channel`: только идентичность, без логики."""

    def __init__(self, name: str, *, source_tag: str | None = None) -> None:
        self.name = name
        self.source_tag = source_tag or f"{name}_test"


class FakeLlm:
    """Порт-заглушка: пишет вызовы в `calls`, отдаёт заготовленные ответы.

    `text` / `texts` — ответы `complete` (по очереди, последний повторяется);
    `result` / `results` — ответы `structured`;
    `error` — исключение вместо ответа;
    `on_complete` / `on_structured` — колбэк для нетривиальных случаев (получает feature и kwargs).
    """

    def __init__(
        self,
        *,
        text: str = "",
        texts: Sequence[str] | None = None,
        result: Any = None,
        results: Sequence[Any] | None = None,
        error: Exception | None = None,
        on_complete: Callable[..., Any] | None = None,
        on_structured: Callable[..., Any] | None = None,
    ) -> None:
        self._texts = list(texts) if texts is not None else ([text] if text else [""])
        self._results = list(results) if results is not None else [result]
        self._error = error
        self._on_complete = on_complete
        self._on_structured = on_structured
        self.calls: list[dict[str, Any]] = []

    @property
    def features(self) -> list[str]:
        return [c["feature"] for c in self.calls]

    def _next(self, pool: list[Any]) -> Any:
        return pool.pop(0) if len(pool) > 1 else (pool[0] if pool else None)

    async def complete(self, feature: str, **kwargs: Any) -> str:
        self.calls.append({"feature": feature, **kwargs})
        if self._error:
            raise self._error
        if self._on_complete:
            value = self._on_complete(feature, **kwargs)
            return await value if hasattr(value, "__await__") else value
        return self._next(self._texts)

    async def structured(self, feature: str, *, schema: type, **kwargs: Any) -> Any:
        self.calls.append({"feature": feature, "schema": schema, **kwargs})
        if self._error:
            raise self._error
        if self._on_structured:
            value = self._on_structured(feature, schema=schema, **kwargs)
            return await value if hasattr(value, "__await__") else value
        return self._next(self._results)

    def stream(self, feature: str, **kwargs: Any):
        self.calls.append({"feature": feature, "stream": True, **kwargs})
        chunks = list(self._texts)

        async def _gen():
            if self._error:
                raise self._error
            for chunk in chunks:
                yield chunk

        return _gen()


class RaisingLlm(FakeLlm):
    """Порт, который не должен быть вызван вообще."""

    def __init__(self, message: str = "LLM не должна вызываться") -> None:
        super().__init__()
        self._message = message

    async def complete(self, feature: str, **kwargs: Any) -> str:
        raise AssertionError(f"{self._message} (feature={feature})")

    async def structured(self, feature: str, *, schema: type, **kwargs: Any) -> Any:
        raise AssertionError(f"{self._message} (feature={feature})")


def use_fake_llm(monkeypatch, llm: FakeLlm) -> FakeLlm:
    """Связать фейковый LLM-порт на время теста (снимается финализатором monkeypatch).

    Вариант без `with` — для тестов, где вызов домена идёт несколькими шагами.
    Подменяем снимок портов целиком через monkeypatch: он же вернёт прежний на teardown.
    """
    previous = ports.current()
    monkeypatch.setattr(
        ports,
        "_current",
        ports.Ports(
            llm=llm,
            cache=previous.cache,
            clock=previous.clock,
            events=previous.events,
            notifier=previous.notifier,
            vacancy_sources=dict(previous.vacancy_sources),
            channels=dict(previous.channels),
        ),
    )
    return llm


__all__ = [
    "DEMO_JOBS",
    "DEMO_RESUME",
    "FakeChannel",
    "FakeDemoDb",
    "FakeLlm",
    "FakeVacancySource",
    "RaisingLlm",
    "ScriptedChatModel",
    "use_fake_llm",
]


# ------------------------------------------------------------------ демо-данные (A-2)

_DEMO_V100_TEXT = (
    "Senior LLM Engineer (Agents) в Northwind Labs. Агентные пайплайны на проде, найм через "
    "EOR, оплата в евро. Удалённо из любой точки мира, пересечение с CET не требуется."
)
_DEMO_V102_TEXT = (
    "Applied AI Engineer в Kestrel Analytics. Удалённо из любой точки мира, но нужен ВНЖ ЕС "
    "или право работать в ЕС. Оплата €90 000–110 000 в год, B2B-контракт. Пересечение с "
    "командой CET минимум 4 часа в день."
)
_DEMO_V104_TEXT = (
    "Lead AI Engineer в Brightmoor Health. Хорошие деньги, но гибрид в Амстердаме: "
    "потребуется релокация. Оплата €8 000 в месяц."
)
_DEMO_V106_TEXT = (
    "NLP Engineer в Halden Robotics. Только офис в Осло: блокер для удалёнки, переезд без "
    "помощи компании. Оплата NOK 75 000 в месяц."
)

DEMO_JOBS: list[dict[str, Any]] = [
    {
        "id": 101,
        "vacancy_id": "demo-101",
        "url": "https://example.com/vacancy/demo-101",
        "title": "Senior LLM Engineer (Agents)",
        "company": "Northwind Labs",
        "vacancy_text": _DEMO_V100_TEXT,
        "salary_text": "€6 500–8 000 / мес",
        "area": "Лиссабон, удалённо",
        "work_format": "remote",
        "work_schedule": None,
        "letter_required": None,
        "published_at": None,
        "cover_letter_text": None,
        "cover_letter_lang": None,
        "employer_id": None,
        "skills": ["Python", "LLM", "Agents"],
        "specialization": "ml_engineer",
        "seniority": "senior",
        "source": "hh",
        "is_archived": False,
        "status": "Просмотр",
        "overall_score": 91,
        "recommendation": "strong_apply",
        "score": {
            "one_line_verdict": "Агентные пайплайны на проде, оплата в евро через EOR"
        },
        "skipped": False,
    },
    {
        "id": 102,
        "vacancy_id": "demo-102",
        "url": "https://example.com/vacancy/demo-102",
        "title": "Applied AI Engineer",
        "company": "Kestrel Analytics",
        "vacancy_text": _DEMO_V102_TEXT,
        "salary_text": "€90 000–110 000 / год",
        "area": "Берлин, удалённо в ЕС",
        "work_format": "remote",
        "work_schedule": None,
        "letter_required": None,
        "published_at": None,
        "cover_letter_text": None,
        "cover_letter_lang": None,
        "employer_id": None,
        "skills": ["Python", "LLM", "RAG"],
        "specialization": "ml_engineer",
        "seniority": "middle",
        "source": "hh",
        "is_archived": False,
        "status": "Просмотр",
        "overall_score": 84,
        "recommendation": "apply",
        "score": {"one_line_verdict": "Ловушка: нужен ВНЖ ЕС"},
        "skipped": False,
    },
    {
        "id": 103,
        "vacancy_id": "demo-103",
        "url": "https://example.com/vacancy/demo-103",
        "title": "ML Platform Engineer",
        "company": "Tallgrass Fintech OÜ",
        "vacancy_text": (
            "ML Platform Engineer в Tallgrass Fintech OÜ. Платформа моделей для финтеха, "
            "валютная удалёнка через эстонское юрлицо."
        ),
        "salary_text": "$5 000–6 500 / мес",
        "area": "Таллин, удалённо",
        "work_format": "remote",
        "work_schedule": None,
        "letter_required": None,
        "published_at": None,
        "cover_letter_text": None,
        "cover_letter_lang": None,
        "employer_id": None,
        "skills": ["Python", "MLOps"],
        "specialization": "ml_engineer",
        "seniority": "senior",
        "source": "getmatch",
        "is_archived": False,
        "status": "Просмотр",
        "overall_score": 78,
        "recommendation": "apply",
        "score": {"one_line_verdict": "Платформа моделей, оплата в долларах"},
        "skipped": False,
    },
    {
        "id": 104,
        "vacancy_id": "demo-104",
        "url": "https://example.com/vacancy/demo-104",
        "title": "Lead AI Engineer",
        "company": "Brightmoor Health",
        "vacancy_text": _DEMO_V104_TEXT,
        "salary_text": "€8 000 / мес",
        "area": "Амстердам, гибрид",
        "work_format": "hybrid",
        "work_schedule": None,
        "letter_required": None,
        "published_at": None,
        "cover_letter_text": None,
        "cover_letter_lang": None,
        "employer_id": None,
        "skills": ["LLM", "Team Lead"],
        "specialization": "ml_engineer",
        "seniority": "lead",
        "source": "hh",
        "is_archived": False,
        "status": "Просмотр",
        "overall_score": 72,
        "recommendation": "maybe",
        "score": {"one_line_verdict": "Гибрид в Амстердаме: нужна релокация"},
        "skipped": False,
    },
    {
        "id": 105,
        "vacancy_id": "demo-105",
        "url": "https://example.com/vacancy/demo-105",
        "title": "Senior Python Developer (AI)",
        "company": "Quayside Software",
        "vacancy_text": (
            "Senior Python Developer (AI) в Quayside Software. Оплата в долларах, но роль "
            "больше бэкенд, чем агенты."
        ),
        "salary_text": "$4 200 / мес",
        "area": "Белград, удалённо",
        "work_format": "remote",
        "work_schedule": None,
        "letter_required": None,
        "published_at": None,
        "cover_letter_text": None,
        "cover_letter_lang": None,
        "employer_id": None,
        "skills": ["Python", "FastAPI"],
        "specialization": "backend",
        "seniority": "senior",
        "source": "hh",
        "is_archived": False,
        "status": "Просмотр",
        "overall_score": 66,
        "recommendation": "maybe",
        "score": {"one_line_verdict": "Бэкенд с элементами AI, вилка ниже минимума"},
        "skipped": False,
    },
    {
        "id": 106,
        "vacancy_id": "demo-106",
        "url": "https://example.com/vacancy/demo-106",
        "title": "NLP Engineer",
        "company": "Halden Robotics",
        "vacancy_text": _DEMO_V106_TEXT,
        "salary_text": "NOK 75 000 / мес",
        "area": "Осло, офис",
        "work_format": "office",
        "work_schedule": None,
        "letter_required": None,
        "published_at": None,
        "cover_letter_text": None,
        "cover_letter_lang": None,
        "employer_id": None,
        "skills": ["NLP", "Python"],
        "specialization": "ml_engineer",
        "seniority": "middle",
        "source": "hh",
        "is_archived": False,
        "status": "Просмотр",
        "overall_score": 54,
        "recommendation": "skip",
        "score": {"one_line_verdict": "Только офис в Осло: блокер"},
        "skipped": False,
    },
    {
        "id": 107,
        "vacancy_id": "demo-107",
        "url": "https://example.com/vacancy/demo-107",
        "title": "Data Scientist",
        "company": "Ромашка Ритейл",
        "vacancy_text": (
            "Data Scientist в Ромашка Ритейл. Рублёвая удалёнка по РФ, не ваш трек."
        ),
        "salary_text": "350 000 ₽",
        "area": "Москва, удалённо",
        "work_format": "remote",
        "work_schedule": None,
        "letter_required": None,
        "published_at": None,
        "cover_letter_text": None,
        "cover_letter_lang": None,
        "employer_id": None,
        "skills": ["Python", "SQL"],
        "specialization": "analyst",
        "seniority": "middle",
        "source": "hh",
        "is_archived": False,
        "status": "Просмотр",
        "overall_score": 38,
        "recommendation": "skip",
        "score": {"one_line_verdict": "Рублёвая удалёнка по РФ"},
        "skipped": False,
    },
]

#: Резюме демо-аккаунта (вкладка «Резюме», форма `demo-101…` локального стека).
DEMO_RESUME: dict[str, Any] = {
    "personal": {
        "full_name": "Демо Кандидат",
        "city": "Москва",
        "relocation": "Не готов",
    },
    "position": {
        "title": "Backend-разработчик",
        "salary_min": 5000,
        "salary_currency": "EUR",
        "salary_basis": "На руки",
        "schedule": ["Удалённо"],
        "grade": ["Senior"],
    },
    "search_criteria": {
        "niches": ["LLM-агенты", "RAG"],
        "market_scope": "Международный",
    },
    "key_skills": ["Python", "LLM", "RAG", "Agents"],
    "languages": [
        {"name": "Русский", "level": "Родной"},
        {"name": "English", "level": "C1"},
    ],
}


class FakeDemoDb:
    """Двойник `Executor` на демо-данных: `/api/jobs` → 8 строк, резюме, пустой кэш условий.

    SQL-маршрутизация по подстрокам — как в `_FakeJobsPool` и других двойниках репо:
    тесту важен контракт вызова (fetch/fetchrow/execute), а не SQL-движок.
    """

    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    async def fetch(self, sql: str, *args: Any) -> Any:  # noqa: ARG002
        if "from jobs" in sql:
            return [dict(row) for row in DEMO_JOBS]
        return []

    async def fetchrow(self, sql: str, *args: Any) -> Any:
        if "from resumes" in sql:
            return {"data": DEMO_RESUME}
        if "from jobs" in sql:
            for arg in args:
                if isinstance(arg, str) and arg.startswith("demo-"):
                    row = next((r for r in DEMO_JOBS if r["vacancy_id"] == arg), None)
                    return dict(row) if row else None
                if isinstance(arg, int):
                    row = next((r for r in DEMO_JOBS if r["id"] == arg), None)
                    return dict(row) if row else None
            return None
        return None

    async def fetchval(self, sql: str, *args: Any) -> Any:  # noqa: ARG002
        return None

    async def execute(self, sql: str, *args: Any) -> Any:
        self.executed.append((sql, args))
        return "OK"

    async def executemany(self, sql: str, *args: Any) -> Any:
        self.executed.append((sql, args))
        return "OK"
