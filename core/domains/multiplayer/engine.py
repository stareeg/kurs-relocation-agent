"""Протокол игры и реестр движков (Э17).

`session.py` — generic-хаб столов: коннекты, reconnect по seat_token, таймеры фаз, presence,
рассылка состояния, idle-GC. Он не должен знать, во что играют. Всё, что знает про «Хрюши и
Волки» — фазы, интенты, колоду, роли, ботов, LLM-вставки — живёт за этим интерфейсом
(`wolves_engine.WolvesEngine`).

**Нон-гол (17.5).** Это НЕ общая машина состояний, не общая система карт/колод и не заготовка
под будущее. Здесь ровно те операции, которые хаб уже вызывал у `rules`/`views`/`models`
напрямую, названные обобщённо. Новые методы «на вырост» не добавлять: следующая игра покажет
свою форму сама, и тогда интерфейс можно будет расширить по факту, а не по догадке.

Состояние партии для хаба **непрозрачно** (`GameState = Any`): он его хранит, передаёт обратно
в движок и просит спроецировать — но не читает поля.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol, runtime_checkable

# Ошибка «ход невозможен» — часть контракта хаба: он ловит её и отдаёт клиенту как `error`,
# не зная правил игры. Определение остаётся в models.py (там же, где его кидают правила),
# здесь — точка импорта для generic-слоя, чтобы session.py не тянул Wolves-модели.
from core.domains.multiplayer.models import IllegalMove

__all__ = [
    "GameEngine",
    "GameEvent",
    "GameState",
    "IllegalMove",
    "MatchRuntime",
    "SeatView",
    "get_engine",
    "known_game_ids",
]

#: Состояние партии глазами хаба — чёрный ящик конкретного движка.
GameState = Any


@runtime_checkable
class GameEvent(Protocol):
    """Событие правил, как его пересылает хаб клиентам (`{"type": …, "detail": …}`)."""

    type: str
    detail: str


@dataclass(frozen=True)
class SeatView:
    """Место глазами хаба: только то, что нужно для лобби, presence и хост-панели.

    Игровые поля (рука, фракция, штампы) сюда не попадают — их видит только движок и его
    собственные проекции.
    """

    id: str
    kind: str
    filled: bool
    is_bot: bool
    account_id: int | None


class MatchRuntime(Protocol):
    """Доступ к живой комнате для доигровки за ботов и LLM-фаз.

    Нужен потому, что эти шаги асинхронные и многофазные: часть работы идёт под блокировкой
    комнаты, часть (сетевой вызов LLM) — обязательно вне её, а между ними состояние могло
    уехать. Раньше всё это жило в `session.py` вперемешку с транспортом; теперь хаб отдаёт
    движку узкий доступ к своей комнате, а сам про правила по-прежнему ничего не знает.
    """

    room_code: str

    @property
    def lock(self) -> asyncio.Lock:
        """Блокировка комнаты — одна на все мутации состояния."""
        ...

    def get_state(self) -> GameState | None: ...

    def set_state(self, state: GameState) -> None: ...

    @property
    def paused(self) -> bool:
        """Стол на паузе — движок не доигрывает за ботов и не зовёт LLM (см. `step`)."""
        ...

    def flag(self, name: str) -> bool:
        """Флаг «такая работа уже запущена» — против повторного запуска на ту же фазу."""
        ...

    def set_flag(self, name: str, value: bool) -> None: ...

    def memo(self, name: str) -> Any:
        """Черновик движка на время партии: прогретые задачи и их ключи (Э19.8).

        Отдельно от `flag`, потому что там строго bool. Хаб содержимое не читает —
        только хранит и чистит на рематче.
        """
        ...

    def set_memo(self, name: str, value: Any) -> None: ...

    async def broadcast(self) -> None:
        """Разослать текущее состояние всем за столом."""
        ...

    async def send_frame(self, payload: Mapping[str, Any]) -> None:
        """Разослать лёгкий кадр всем за столом, не гоняя полное состояние.

        Нужен для того, что происходит **между** состояниями: реплика бота печатается по
        мере генерации (`line_delta`), а полный кадр состояния уезжает один раз, когда
        фраза дописана и применена правилами.
        """
        ...

    def rearm_timer(self) -> None:
        """Перевзвести таймер фазы (после смены фазы движком)."""
        ...

    async def note_phase(self, phase: str) -> None:
        """Записать ярлык фазы в лобби-таблицу (её видно в списке столов)."""
        ...


class GameEngine(Protocol):
    """Что хаб умеет спросить у игры. Реализация — одна на игру."""

    game_id: str
    #: Место ведущего (у Wolves — хрюша, `hr`). Хаб раздаёт его хосту и умеет передавать.
    host_seat_id: str
    #: Потолок слотов кандидатов, который стережёт хост-панель.
    max_candidate_slots: int

    # --- жизненный цикл партии -------------------------------------------------

    def start(self, seed: int, *, candidate_count: int) -> GameState: ...

    def daily_seed(self, day: date) -> int:
        """Сид «стола дня» от календарной даты — свой на игру, столы не должны совпадать."""
        ...

    def can_restart(self, state: GameState) -> bool:
        """Можно ли начать новую партию поверх этой (у Wolves — после reveal/ended)."""
        ...

    def is_terminal(self, state: GameState) -> bool: ...

    # --- фазы ------------------------------------------------------------------

    def phase(self, state: GameState) -> str: ...

    def phase_label(self, phase: str) -> str:
        """Человеческий ярлык фазы для списка столов."""
        ...

    def phase_duration_s(self, phase: str) -> float | None:
        """Сколько длится фаза; `None` — фаза без таймера (у Wolves reveal/ended)."""
        ...

    def on_timeout(self, state: GameState, phase: str) -> GameState:
        """Таймер фазы истёк. Движок сам решает, чем это кончается."""
        ...

    # --- ходы ------------------------------------------------------------------

    def parse_intent(self, payload: Mapping[str, Any], *, actor_seat_id: str) -> Any:
        """Разобрать клиентский интент. `actor_seat_id` ставит хаб — античит, не клиент."""
        ...

    def apply(self, state: GameState, intent: Any) -> tuple[GameState, Sequence[GameEvent]]: ...

    # --- проекции --------------------------------------------------------------

    def project_public(self, state: GameState, *, nicks: Mapping[int, str]) -> dict[str, Any]: ...

    def project_private(self, state: GameState, seat_id: str | None) -> dict[str, Any]: ...

    def lobby_state(
        self,
        *,
        account_seats: Mapping[int, str],
        nicks: Mapping[int, str],
    ) -> dict[str, Any]:
        """Состояние до старта партии — стол ещё в лобби, движок не запущен."""
        ...

    # --- места -----------------------------------------------------------------

    def seat(self, state: GameState, seat_id: str) -> SeatView | None: ...

    def candidate_seat_ids(self, state: GameState) -> list[str]: ...

    def seat_id_for_index(self, index: int) -> str:
        """Номер слота в лобби-таблице (`seat_index`) → id места в партии."""
        ...

    def index_for_seat_id(self, seat_id: str) -> int | None:
        """Обратно; `None`, если это не место кандидата (например, место ведущего)."""
        ...

    def bind_accounts(self, state: GameState, account_seats: Mapping[int, str]) -> None:
        """Посадить аккаунты на их места; остальные кандидаты — боты."""
        ...

    def take_over_seat(self, state: GameState, seat_id: str, account_id: int) -> None:
        """Человек садится вместо бота (в любой фазе)."""
        ...

    def ensure_can_join_seat(self, state: GameState) -> None:
        """Бросить `IllegalMove`, если сесть на пустой слот сейчас нельзя.

        Отдельно от `join_seat`, потому что хаб обязан проверить это **до** записи в
        лобби-таблицу: иначе слот окажется занят в БД у хода, который не состоялся.
        """

    def join_seat(
        self, state: GameState, seat_id: str, account_id: int
    ) -> tuple[GameState, Sequence[GameEvent]]:
        """Человек занимает пустой слот (после `ensure_can_join_seat`)."""
        ...

    def ensure_can_fill_bot(self, state: GameState) -> None:
        """Парный guard для добора бота хостом (см. `ensure_can_join_seat`)."""
        ...

    def fill_seat_with_bot(
        self, state: GameState, seat_id: str
    ) -> tuple[GameState, Sequence[GameEvent]]:
        """Хост добирает пустой слот ботом (после `ensure_can_fill_bot`)."""
        ...

    def seat_to_bot(self, state: GameState, seat_id: str) -> None:
        """Игрок ушёл/снят — за место доигрывает бот, партия не стопается."""
        ...

    def vacate_seat(self, state: GameState, seat_id: str) -> GameState:
        """Освободить место полностью (между слотами)."""
        ...

    def can_vacate_seat(self, state: GameState) -> bool:
        """Сейчас место можно освободить, а не только заменить ботом."""
        ...

    def add_candidate_seat(self, state: GameState, seat_id: str) -> None:
        """Хост добавил слот на живом столе."""
        ...

    def assign_host_seat(self, state: GameState, account_id: int) -> None:
        """Передать место ведущего другому аккаунту."""
        ...

    def host_seat_taken_by_other(
        self, state: GameState, account_id: int, host_account_id: int
    ) -> bool:
        """Место ведущего занято живым игроком, у которого его нельзя отобрать молча."""
        ...

    # --- асинхронные шаги (боты, LLM) ------------------------------------------

    async def step(self, runtime: MatchRuntime) -> None:
        """Доиграть за ботов и отработать LLM-фазы, если текущее состояние этого просит.

        Вызывается хабом после каждой мутации. Обязан быть идемпотентным и безопасным при
        параллельных вызовах — состояние между проверкой и применением могло смениться.
        """


# Реестр. Импорт движка ленивый: `engine.py` — generic-слой и не должен тянуть Wolves
# на уровне модуля (это же стережёт `tests/test_multiplayer_engine_boundary.py`).
_ENGINES: dict[str, GameEngine] = {}


def known_game_ids() -> tuple[str, ...]:
    return ("wolves",)


def get_engine(game_id: str) -> GameEngine:
    """Движок по идентификатору игры. Пока игра одна, но точка расширения — здесь."""
    cached = _ENGINES.get(game_id)
    if cached is not None:
        return cached
    if game_id != "wolves":
        raise KeyError(f"неизвестная игра {game_id!r}")
    from core.domains.multiplayer.wolves_engine import WolvesEngine

    engine = WolvesEngine()
    _ENGINES[game_id] = engine
    return engine
