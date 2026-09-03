"""Порты инфраструктуры: домены зависят от Protocol-ов, а не от `core.platform`.

Зачем: домен, который импортирует `core.platform.llm.*`, тянет за собой langchain, конфиг и
сеть — его нельзя ни собрать в отдельном процессе, ни протестировать без моков httpx. Здесь
описан контракт («что нужно домену»), реализации живут в `core/app/wiring.py` (композиционный
корень) и подставляются на старте `api`/`bot_app`.

Как пользоваться в домене:

```python
from core.kernel import ports

async def assess(text: str, *, llm: ports.LlmPort | None = None) -> Verdict:
    port = llm or ports.llm()          # прод — связанный порт, тест — фейк параметром
    return await port.structured("feature_name", schema=Verdict, user=text)
```

В тестах: `ports.use_ports(llm=FakeLlm())` (контекст-менеджер) либо явный параметр `llm=`.

Модуль без I/O: только stdlib + pydantic (правило слоя `kernel`).
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
import time
from collections.abc import AsyncIterator, Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

from core.kernel.errors import PortNotBoundError
from core.kernel.uow import UnitOfWork
from core.kernel.vacancy import RawVacancy

logger = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)

#: Фабрика нового UoW на каждый сценарий (не синглтон: у каждой записи своя граница).
UowFactory = Callable[[], UnitOfWork]


# --------------------------------------------------------------------------------------
# Контракты
# --------------------------------------------------------------------------------------


@runtime_checkable
class Clock(Protocol):
    """Время как зависимость: тест подменяет `now()` вместо freeze-гимнастики."""

    def now(self) -> datetime: ...

    def monotonic(self) -> float: ...


@runtime_checkable
class CachePort(Protocol):
    """Кэш «ключ → значение» с TTL. Реализация может игнорировать `ttl_s` (см. L-17)."""

    async def get(self, key: str) -> Any | None: ...

    async def set(self, key: str, value: Any, *, ttl_s: float | None = None) -> None: ...

    async def delete(self, key: str) -> None: ...


#: Одна реплика диалога: `{"role": "system"|"user"|"assistant", "content": "…"}`.
Message = Mapping[str, str]


@dataclass(frozen=True, slots=True)
class ImageInput:
    """Картинка для мультимодального вызова.

    sha256 обязателен: он участвует в ключе кэша и single-flight — иначе два
    разных скрина с одинаковой подписью получили бы один ответ из кэша.
    """

    sha256: str
    mime: str
    data: bytes


@runtime_checkable
class LlmPort(Protocol):
    """Вызов LLM-фичи из реестра без знания о провайдере и langchain.

    `feature` — имя `LlmFeature`; тир, промпт, бюджет и схема берутся из декларации домена.

    Сборка запроса:
    - `system=None` → system берётся из `LlmFeature.prompt` реализацией;
    - `prompt_vars` подставляет `{{TOKEN}}`-плейсхолдеры промпта (соглашение `prompts/`);
    - `dynamic_tail` — меняющийся хвост system'а: при `cache_prefix=True` статический префикс
      уходит в prompt cache, а хвост остаётся снаружи кэша;
    - `messages` — готовый диалог (история чата) вместо пары system/user;
    - `tier_override` — ручной выбор тира пользователем (UI чата), а не хардкод модели;
    - `images` — вложения текущей реплики (только текущей — картинки истории уходят в промпт
      текстом).

    Ошибка провайдера, таймаут `budget_ms` и невалидный структурный ответ приходят как
    `core.kernel.errors.LlmError`.
    """

    async def complete(
        self,
        feature: str,
        *,
        user: str | None = None,
        system: str | None = None,
        messages: Sequence[Message] | None = None,
        prompt_vars: Mapping[str, str] | None = None,
        dynamic_tail: str = "",
        temperature: float | None = None,
        max_tokens: int | None = None,
        max_retries: int | None = None,
        tier_override: str | None = None,
        model_override: str | None = None,
        tags: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
        cache_key: str | None = None,
        images: Sequence[ImageInput] = (),
    ) -> str: ...

    async def structured(
        self,
        feature: str,
        *,
        schema: type[ModelT],
        user: str | None = None,
        system: str | None = None,
        messages: Sequence[Message] | None = None,
        prompt_vars: Mapping[str, str] | None = None,
        dynamic_tail: str = "",
        temperature: float | None = None,
        max_tokens: int | None = None,
        max_retries: int | None = None,
        tier_override: str | None = None,
        model_override: str | None = None,
        tags: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
        cache_key: str | None = None,
        images: Sequence[ImageInput] = (),
    ) -> ModelT: ...

    def stream(
        self,
        feature: str,
        *,
        user: str | None = None,
        system: str | None = None,
        messages: Sequence[Message] | None = None,
        prompt_vars: Mapping[str, str] | None = None,
        dynamic_tail: str = "",
        temperature: float | None = None,
        max_tokens: int | None = None,
        tier_override: str | None = None,
        model_override: str | None = None,
        tags: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
        images: Sequence[ImageInput] = (),
    ) -> AsyncIterator[str]: ...


@runtime_checkable
class EventBus(Protocol):
    """Публикация доменных событий: издатель не знает своих подписчиков.

    Два способа опубликовать — потому что эффекты бывают двух родов:
    - `publish` — «сообщил и пошёл дальше» (прогрев кэша, аналитика). Асинхронный подписчик
      уезжает в фоновую задачу;
    - `publish_and_wait` — эффект обязан завершиться до ответа пользователю (так на шину
      переехал прямой вызов домена, который раньше просто ждали).

    В обоих случаях падение подписчика не выходит наружу: событие не должно уметь уронить
    того, кто его опубликовал.
    """

    def publish(self, event: Any) -> None: ...

    async def publish_and_wait(self, event: Any) -> None: ...

    def subscribe(self, event_type: type, handler: Callable[[Any], Any]) -> None: ...


@runtime_checkable
class VacancySource(Protocol):
    """Источник вакансий: hh, getmatch, …. Новый источник = один файл + регистрация.

    `fetch(query)` — поиск/карточка по строке запроса (search-URL, vacancy-URL, id).
    `parse(html)` — одна страница вакансии → `RawVacancy` (без сети).
    """

    name: str

    async def fetch(self, query: str) -> list[RawVacancy]: ...

    def parse(self, html: str) -> RawVacancy: ...


@runtime_checkable
class Notifier(Protocol):
    """Доставка сообщения владельцу (Telegram и т.п.). Реализацию связывает `bot_app`."""

    async def notify(self, text: str, *, channel: str | None = None) -> None: ...


@runtime_checkable
class Channel(Protocol):
    """Поверхность владельца (web / telegram / extension) — A-27.

    Канал — только идентичность: `name` + `source_tag` для меток стадий/аналитики.
    Доменной логики у канала нет: адаптер валидирует вход, зовёт сценарий домена,
    маппит ошибку/формат ответа. Не путать с `Notifier` (исходящий пуш владельцу).
    """

    name: str
    source_tag: str


# --------------------------------------------------------------------------------------
# Реализации по умолчанию (чистые, без I/O)
# --------------------------------------------------------------------------------------


class SystemClock:
    """Системное время (UTC) — дефолт для `clock()`."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()


class MemoryCache:
    """In-process TTL-кэш — дефолт для `cache()` до подключения `platform`.

    Без вытеснения по размеру: держит ровно то, что положили, протухшее чистит на чтении.
    """

    def __init__(self) -> None:
        self._items: dict[str, tuple[Any, float | None]] = {}

    async def get(self, key: str) -> Any | None:
        item = self._items.get(key)
        if item is None:
            return None
        value, expires_at = item
        if expires_at is not None and time.monotonic() >= expires_at:
            self._items.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: Any, *, ttl_s: float | None = None) -> None:
        expires_at = time.monotonic() + ttl_s if ttl_s else None
        self._items[key] = (value, expires_at)

    async def delete(self, key: str) -> None:
        self._items.pop(key, None)


class InProcessEventBus:
    """In-process шина — дефолт для `events()` и рабочая реализация A-11.

    Подписка идёт по типу события и срабатывает по `isinstance`: подписка на `DomainEvent`
    ловит всё (так устроен журнал), подписка на конкретный класс — только его.

    Три инварианта:
    1. падение подписчика не ломает издателя (иначе событие — скрытая жёсткая зависимость);
    2. подписчики независимы: упавший не отменяет остальных;
    3. `subscribe` идемпотентен по паре (тип, обработчик) — повторное связывание портов
       (`api` и `bot` в одном процессе зовут `wire_default_ports`) не задваивает эффект.

    Журнала здесь нет: слой `kernel` не умеет в I/O. Композиционный корень передаёт `journal`
    — колбэк-писатель из `core/platform/events/journal.py`.
    """

    def __init__(self, *, journal: Callable[[Any], Any] | None = None) -> None:
        self._handlers: dict[type, list[Callable[[Any], Any]]] = {}
        self._journal = journal
        # Ссылки на фоновые задачи: без них сборщик мусора вправе убить задачу на полпути.
        self._tasks: set[Any] = set()

    def subscribe(self, event_type: type, handler: Callable[[Any], Any]) -> None:
        handlers = self._handlers.setdefault(event_type, [])
        if handler in handlers:
            return
        handlers.append(handler)

    def handlers_for(self, event: Any) -> list[Callable[[Any], Any]]:
        """Кто получит это событие (для диагностики и тестов)."""
        return [
            handler
            for event_type, handlers in self._handlers.items()
            if isinstance(event, event_type)
            for handler in handlers
        ]

    def publish(self, event: Any) -> None:
        """Опубликовать и не ждать: корутина подписчика уезжает в фоновую задачу."""
        self._write_journal(event)
        for handler in self.handlers_for(event):
            result = self._call(handler, event)
            if inspect.isawaitable(result):
                self._spawn(result, handler, event)

    async def publish_and_wait(self, event: Any) -> None:
        """Опубликовать и дождаться всех подписчиков (эффект нужен до ответа пользователю)."""
        self._write_journal(event)
        for handler in self.handlers_for(event):
            result = self._call(handler, event)
            if inspect.isawaitable(result):
                try:
                    await result
                except Exception as exc:  # noqa: BLE001 — подписчик не валит издателя
                    self._note_failure(handler, event, exc)

    def _call(self, handler: Callable[[Any], Any], event: Any) -> Any:
        try:
            return handler(event)
        except Exception as exc:  # noqa: BLE001 — подписчик не валит издателя
            self._note_failure(handler, event, exc)
            return None

    def _spawn(self, coro: Any, handler: Callable[[Any], Any], event: Any) -> None:
        """Фоновая доставка асинхронному подписчику; вне event loop — событие теряется."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            coro.close()
            logger.warning(
                "подписчик %s асинхронный, но publish вызван вне event loop — событие %s "
                "не доставлено (используй publish_and_wait)",
                getattr(handler, "__name__", handler),
                type(event).__name__,
            )
            return
        task = loop.create_task(self._guarded(coro, handler, event))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _guarded(self, coro: Any, handler: Callable[[Any], Any], event: Any) -> None:
        try:
            await coro
        except Exception as exc:  # noqa: BLE001 — подписчик не валит процесс
            self._note_failure(handler, event, exc)

    def _write_journal(self, event: Any) -> None:
        if self._journal is None:
            return
        try:
            self._journal(event)
        except Exception as exc:  # noqa: BLE001 — витрина не критична для доставки
            logger.debug("журнал события %s не записан: %s", type(event).__name__, exc)

    def _note_failure(self, handler: Callable[[Any], Any], event: Any, exc: Exception) -> None:
        logger.warning(
            "подписчик %s упал на событии %s: %s",
            getattr(handler, "__name__", handler),
            type(event).__name__,
            exc,
        )


class NullNotifier:
    """Молчаливый нотификатор — дефолт, пока `bot_app` не связал настоящий."""

    async def notify(self, text: str, *, channel: str | None = None) -> None:
        logger.debug("notify (порт не связан, канал=%s): %s", channel, text[:200])


# --------------------------------------------------------------------------------------
# Реестр портов
# --------------------------------------------------------------------------------------


@dataclass(slots=True)
class Ports:
    """Текущий набор реализаций. `None` — «не связан», дефолт создаётся аксессором лениво."""

    llm: LlmPort | None = None
    cache: CachePort | None = None
    clock: Clock | None = None
    events: EventBus | None = None
    notifier: Notifier | None = None
    vacancy_sources: dict[str, VacancySource] = field(default_factory=dict)
    channels: dict[str, Channel] = field(default_factory=dict)
    uow_factory: UowFactory | None = None


_current = Ports()

# Композиционный корень импортируется по строке: `kernel` не зависит от `app` статически
# (правила слоёв 2 и 4). Это страховка для CLI/скриптов, которые не позвали
# `wire_default_ports()` явно; `api`/`bot_app` зовут его на старте.
_COMPOSITION_ROOT = "core.app.wiring"
_autowire_tried = False


def _autowire() -> None:
    global _autowire_tried
    if _autowire_tried:
        return
    _autowire_tried = True
    try:
        module = importlib.import_module(_COMPOSITION_ROOT)
    except ImportError as exc:  # pragma: no cover — только в урезанной сборке
        logger.warning("композиционный корень %s недоступен: %s", _COMPOSITION_ROOT, exc)
        return
    wire = getattr(module, "wire_default_ports", None)
    if callable(wire):
        wire()


def current() -> Ports:
    """Текущий набор портов (для диагностики и снапшотов в тестах)."""
    return _current


def bind(
    *,
    llm: LlmPort | None = None,
    cache: CachePort | None = None,
    clock: Clock | None = None,
    events: EventBus | None = None,
    notifier: Notifier | None = None,
    vacancy_sources: Mapping[str, VacancySource] | None = None,
    channels: Mapping[str, Channel] | None = None,
    uow_factory: UowFactory | None = None,
    overwrite: bool = True,
) -> None:
    """Связать реализации. `overwrite=False` — не трогать уже связанное (идемпотентный старт)."""
    if llm is not None and (overwrite or _current.llm is None):
        _current.llm = llm
    if cache is not None and (overwrite or _current.cache is None):
        _current.cache = cache
    if clock is not None and (overwrite or _current.clock is None):
        _current.clock = clock
    if events is not None and (overwrite or _current.events is None):
        _current.events = events
    if notifier is not None and (overwrite or _current.notifier is None):
        _current.notifier = notifier
    if vacancy_sources:
        for name, source in vacancy_sources.items():
            if overwrite or name not in _current.vacancy_sources:
                _current.vacancy_sources[name] = source
    if channels:
        for name, ch in channels.items():
            if overwrite or name not in _current.channels:
                _current.channels[name] = ch
    if uow_factory is not None and (overwrite or _current.uow_factory is None):
        _current.uow_factory = uow_factory


def reset() -> None:
    """Сбросить всё к «не связано» (тесты; прод зовёт `wire_default_ports`)."""
    global _current, _autowire_tried
    _current = Ports()
    _autowire_tried = False


@contextmanager
def use_ports(
    *,
    llm: LlmPort | None = None,
    cache: CachePort | None = None,
    clock: Clock | None = None,
    events: EventBus | None = None,
    notifier: Notifier | None = None,
    vacancy_sources: Mapping[str, VacancySource] | None = None,
    channels: Mapping[str, Channel] | None = None,
    uow_factory: UowFactory | None = None,
) -> Iterator[Ports]:
    """Временно подменить порты (тесты): `with ports.use_ports(llm=FakeLlm()): ...`."""
    global _current
    previous = _current
    _current = Ports(
        llm=llm if llm is not None else previous.llm,
        cache=cache if cache is not None else previous.cache,
        clock=clock if clock is not None else previous.clock,
        events=events if events is not None else previous.events,
        notifier=notifier if notifier is not None else previous.notifier,
        vacancy_sources={**previous.vacancy_sources, **(vacancy_sources or {})},
        channels={**previous.channels, **(channels or {})},
        uow_factory=uow_factory if uow_factory is not None else previous.uow_factory,
    )
    try:
        yield _current
    finally:
        _current = previous


def llm() -> LlmPort:
    """LLM-порт. Без связывания — ошибка (тихого фолбэка на «никакую» модель не бывает)."""
    if _current.llm is None:
        _autowire()
    port = _current.llm
    if port is None:
        raise PortNotBoundError(
            "LLM-порт не связан: позови core.app.wiring.wire_default_ports() "
            "на старте процесса или передай llm= в вызов домена."
        )
    return port


def cache() -> CachePort:
    if _current.cache is None:
        _current.cache = MemoryCache()
    return _current.cache


def clock() -> Clock:
    if _current.clock is None:
        _current.clock = SystemClock()
    return _current.clock


def events() -> EventBus:
    """Шина событий. Автосвязывание — чтобы подписки доменов не потерялись в CLI/скриптах.

    Без корня получится шина без журнала и без подписчиков: события просто никуда не пойдут
    (это законно — публикация не должна падать там, где слушать некому).
    """
    if _current.events is None:
        _autowire()
    if _current.events is None:
        _current.events = InProcessEventBus()
    return _current.events


def notifier() -> Notifier:
    if _current.notifier is None:
        _current.notifier = NullNotifier()
    return _current.notifier


def register_vacancy_source(source: VacancySource) -> None:
    _current.vacancy_sources[source.name] = source


def vacancy_source(name: str) -> VacancySource:
    source = _current.vacancy_sources.get(name)
    if source is None:
        known = ", ".join(sorted(_current.vacancy_sources)) or "(пусто)"
        raise PortNotBoundError(f"источник вакансий {name!r} не связан. Известные: {known}")
    return source


def register_channel(channel: Channel) -> None:
    _current.channels[channel.name] = channel


def channel(name: str) -> Channel:
    ch = _current.channels.get(name)
    if ch is None:
        known = ", ".join(sorted(_current.channels)) or "(пусто)"
        raise PortNotBoundError(f"канал {name!r} не связан. Известные: {known}")
    return ch


def uow() -> UnitOfWork:
    """Новый Unit of Work. Зови как ``async with ports.uow() as uow:``.

    Без связывания — ошибка (тихого «писать без транзакции» не бывает: именно ради
    атомарности A-17 и вводился порт).
    """
    if _current.uow_factory is None:
        _autowire()
    factory = _current.uow_factory
    if factory is None:
        raise PortNotBoundError(
            "UoW-порт не связан: позови core.app.wiring.wire_default_ports() "
            "на старте процесса или передай uow_factory= в ports.use_ports / bind."
        )
    return factory()


__all__ = [
    "CachePort",
    "Channel",
    "Clock",
    "EventBus",
    "ImageInput",
    "InProcessEventBus",
    "LlmPort",
    "MemoryCache",
    "Message",
    "Notifier",
    "NullNotifier",
    "Ports",
    "SystemClock",
    "RawVacancy",
    "UnitOfWork",
    "UowFactory",
    "VacancySource",
    "bind",
    "cache",
    "channel",
    "clock",
    "current",
    "events",
    "llm",
    "notifier",
    "register_channel",
    "register_vacancy_source",
    "reset",
    "uow",
    "use_ports",
    "vacancy_source",
]
