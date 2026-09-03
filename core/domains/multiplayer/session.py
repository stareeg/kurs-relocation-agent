"""In-memory сессии столов: таймеры фаз, intents → rules.apply, presence.

Один процесс API = один хаб. Reconnect по seat_token (Э5); слот держим 60 с после обрыва.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from core.domains.multiplayer import repo
from core.domains.multiplayer.engine import (
    GameEngine,
    GameState,
    IllegalMove,
    get_engine,
)
from core.platform.observability import event

logger = logging.getLogger(__name__)

DISCONNECT_HOLD_S = 60.0
#: Пока игра одна; поле на сессии заведено, чтобы вторая подключалась через реестр движков.
DEFAULT_GAME_ID = "wolves"

#: Окно склейки кадров состояния (Э20.2). Один клик игрока рождает каскад из 2–3 полных
#: state за миллисекунды («интент применён → боты походили → LLM-фаза объявилась»); клиент
#: мигал промежуточными состояниями и делал лишние рендеры. Копим кадры это время и шлём
#: последний. Значение в плановом диапазоне 16–30 мс: длиннее — заметная задержка отклика,
#: короче — не перекрывает каскад. Стриму реплик ботов не мешает: его кадры идут секундами
#: врозь и под склейку не попадают.
BROADCAST_COALESCE_S = 0.02

#: Отсчёт после «Продолжить» — как в Dota: игроки успевают вернуть руки на клавиатуру.
RESUME_COUNTDOWN_S = 3.0


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


@dataclass
class Conn:
    ws: Any  # starlette WebSocket
    account_id: int
    engine_seat_id: str | None
    seat_token: str
    is_spectator: bool = False


@dataclass
class RoomSession:
    """Живая комната. Правил игры не знает — всё через `self.engine` (Э17).

    Заодно реализует `engine.MatchRuntime`: движку нужен узкий доступ к этой же комнате,
    чтобы доигрывать за ботов и звать LLM, не таща сюда свою логику обратно.
    """

    room_code: str
    room_id: int
    host_account_id: int
    # Лобби-словарь (`RoomMode`), хабу важна только строка — тип держим generic, чтобы
    # session.py не тянул игровые модели.
    mode: str
    candidate_slots: int
    game_id: str = DEFAULT_GAME_ID
    # Э12: ISO-дата стола дня → seed на первом старте; rematch — случайный.
    daily_day: str | None = None
    # account_id → nick за столом (не ФИО)
    nicks: dict[int, str] = field(default_factory=dict)
    match: GameState | None = None
    phase_ends_at: datetime | None = None
    connections: dict[int, Conn] = field(default_factory=dict)  # id(ws) → Conn
    # engine_seat_id → seat_token (переподключение)
    seat_tokens: dict[str, str] = field(default_factory=dict)
    # account → engine seat (hr / c0…)
    account_seats: dict[int, str] = field(default_factory=dict)
    # account → monotonic deadline удержания слота после disconnect
    disconnect_hold_until: dict[int, float] = field(default_factory=dict)
    # account → task истечения hold → LLM-бот (§4.5)
    _hold_tasks: dict[int, asyncio.Task] = field(default_factory=dict)
    _conn_seq: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _timer_task: asyncio.Task | None = None
    # Флаги «такая работа уже запущена» — смысл ключей знает движок (Э8: LLM судьи/тикера
    # не должен стартовать повторно на ту же фазу).
    _engine_flags: dict[str, bool] = field(default_factory=dict)
    # Черновик движка: прогретые LLM-задачи и ключи, по которым их можно опознать (Э19.8).
    # Хаб в содержимое не заглядывает — только хранит и снимает задачи на рематче.
    _engine_memo: dict[str, Any] = field(default_factory=dict)
    # Э20.1/20.2/20.6: склейка кадров состояния. `_state_rev` — монотонный номер конверта
    # (клиент отбрасывает кадр не новее применённого); `_broadcast_pending` — «есть что
    # разослать»; `_broadcast_task` — единственная задача-склейка на сессию.
    _state_rev: int = 0
    _broadcast_pending: bool = False
    _broadcast_task: asyncio.Task | None = None
    # Пауза (Dota-стиль, по запросу владельца 2026-08-28). Ставит любой участник, держится
    # бессрочно; «Продолжить» запускает 3-сек отсчёт и возвращает таймер фазы с остатком.
    # `paused_at` = None → не на паузе. `resume_at` != None → идёт отсчёт продолжения.
    paused_at: datetime | None = None
    paused_by_label: str = ""
    paused_phase_left_s: float | None = None
    resume_at: datetime | None = None
    _resume_task: asyncio.Task | None = None

    @property
    def paused(self) -> bool:
        """MatchRuntime: движок не доигрывает за ботов и не зовёт LLM, пока стол на паузе."""
        return self.paused_at is not None

    def next_conn_id(self) -> int:
        self._conn_seq += 1
        return self._conn_seq

    @property
    def engine(self) -> GameEngine:
        return get_engine(self.game_id)

    # --- engine.MatchRuntime -------------------------------------------------------

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    def get_state(self) -> GameState | None:
        return self.match

    def set_state(self, state: GameState) -> None:
        self.match = state

    def flag(self, name: str) -> bool:
        return self._engine_flags.get(name, False)

    def set_flag(self, name: str, value: bool) -> None:
        self._engine_flags[name] = value

    def memo(self, name: str) -> Any:
        return self._engine_memo.get(name)

    def set_memo(self, name: str, value: Any) -> None:
        self._engine_memo[name] = value

    async def broadcast(self) -> None:
        await broadcast_state(self)

    async def send_frame(self, payload: Mapping[str, Any]) -> None:
        await send_frame(self, dict(payload))

    def rearm_timer(self) -> None:
        _arm_phase_timer(self)

    async def note_phase(self, phase: str) -> None:
        await repo.update_phase_label(self.room_id, self.engine.phase_label(phase))


def _phase_of(session: RoomSession) -> str:
    """Ярлык фазы для логов; до старта партии — «lobby»."""
    return session.engine.phase(session.match) if session.match is not None else "lobby"


def _cancel_hold_task(session: RoomSession, account_id: int) -> None:
    task = session._hold_tasks.pop(account_id, None)
    if task is not None and not task.done():
        task.cancel()


class RoomHub:
    """Глобальный реестр живых столов в процессе."""

    def __init__(self) -> None:
        self._rooms: dict[str, RoomSession] = {}
        self._lock = asyncio.Lock()

    async def get_or_load(self, room_code: str) -> RoomSession | None:
        code = room_code.upper().strip()
        async with self._lock:
            if code in self._rooms:
                return self._rooms[code]
        room = await repo.get_room_by_code(code)
        if room is None:
            return None
        if room.get("status") == "closed":
            return None
        settings = repo.settings_from_json(room.get("settings"))
        nicks: dict[int, str] = {}
        for k, v in (settings.nicks or {}).items():
            try:
                nicks[int(k)] = str(v)
            except (TypeError, ValueError):
                continue
        session = RoomSession(
            room_code=code,
            room_id=int(room["id"]),
            host_account_id=int(room["host_account_id"]),
            mode=str(room["mode"]),
            candidate_slots=settings.candidate_slots,
            daily_day=settings.daily_day,
            nicks=nicks,
        )
        engine = session.engine
        seats = await repo.list_seats(session.room_id)
        for s in seats:
            aid = s.get("account_id")
            if aid is None:
                continue
            kind = s["seat_kind"]
            if kind == "hr":
                session.account_seats[int(aid)] = engine.host_seat_id
            elif kind == "candidate":
                session.account_seats[int(aid)] = engine.seat_id_for_index(int(s["seat_index"]))
            # spectator — без engine seat
        async with self._lock:
            # гонка: другой коннект мог уже создать
            existing = self._rooms.get(code)
            if existing is not None:
                return existing
            self._rooms[code] = session
            return session

    def get(self, room_code: str) -> RoomSession | None:
        return self._rooms.get(room_code.upper().strip())

    def room_codes(self) -> list[str]:
        """Коды живых сессий (для idle GC / sweep)."""
        return list(self._rooms.keys())

    async def drop_if_empty(self, room_code: str) -> None:
        code = room_code.upper().strip()
        close_room_id: int | None = None
        async with self._lock:
            session = self._rooms.get(code)
            if session is None:
                return
            if session.connections:
                return
            # Не дропаем сразу — hold disconnect; чистим только без матча и без hold.
            now = time.monotonic()
            if session.disconnect_hold_until and any(
                t > now for t in session.disconnect_hold_until.values()
            ):
                return
            # Партия ещё идёт (не reveal/ended).
            if session.match is not None and not session.engine.can_restart(session.match):
                if session.account_seats:
                    # Живой игрок ещё за столом (сейчас офлайн, hold истёк бы выше). Ждём.
                    return
                # За столом не осталось ни одного живого — играть некому, ботам между
                # собой смысла нет. Закрываем стол по-настоящему (в БД тоже), а не держим
                # до idle-GC на 2 часа.
                close_room_id = session.room_id
                event(
                    logger,
                    "ЗАДАЧА",
                    "mp_ws_room_abandoned code=%s phase=%s — все живые ушли, закрываю стол",
                    code,
                    _phase_of(session),
                    room_code=code,
                    phase=_phase_of(session),
                )
            if session._timer_task and not session._timer_task.done():
                session._timer_task.cancel()
            _cancel_engine_tasks(session)
            _cancel_pending_broadcast(session)
            _clear_pause(session)
            self._rooms.pop(code, None)
        if close_room_id is not None:
            with contextlib.suppress(Exception):
                await repo.close_room(close_room_id)

    async def force_close(self, room_code: str, *, detail: str = "Стол закрыт") -> None:
        """Хост завершил стол: уведомить WS-клиентов и выкинуть сессию из хаба."""
        code = room_code.upper().strip()
        async with self._lock:
            session = self._rooms.pop(code, None)
        if session is None:
            return
        if session._timer_task and not session._timer_task.done():
            session._timer_task.cancel()
        _cancel_engine_tasks(session)
        _cancel_pending_broadcast(session)
        _clear_pause(session)
        for conn in list(session.connections.values()):
            with contextlib.suppress(Exception):
                await conn.ws.send_json({"type": "error", "detail": detail})
            with contextlib.suppress(Exception):
                await conn.ws.close(code=4001)
        session.connections.clear()


_HUB = RoomHub()


def hub() -> RoomHub:
    return _HUB


def reset_hub_for_tests() -> None:
    """Сброс синглтона между тестами."""
    global _HUB
    _HUB = RoomHub()


async def issue_or_reuse_token(session: RoomSession, engine_seat_id: str | None) -> str:
    if engine_seat_id and engine_seat_id in session.seat_tokens:
        return session.seat_tokens[engine_seat_id]
    token = secrets.token_urlsafe(24)
    if engine_seat_id:
        session.seat_tokens[engine_seat_id] = token
    return token


async def bind_connection(
    session: RoomSession,
    *,
    ws: Any,
    account_id: int,
    seat_token: str | None,
) -> Conn:
    """Привязать WS к месту. seat_token — reconnect; иначе seat из лобби."""
    async with session._lock:
        engine_seat_id = session.account_seats.get(account_id)
        is_spectator = engine_seat_id is None

        if seat_token:
            # Reconnect: токен должен совпадать с известным для seat этого аккаунта
            # или найти seat по токену.
            for sid, tok in session.seat_tokens.items():
                if secrets.compare_digest(tok, seat_token):
                    # Слот мог быть у другого account только если hold истёк — не отдаём чужой.
                    owners = [a for a, es in session.account_seats.items() if es == sid]
                    if owners and owners[0] != account_id:
                        raise PermissionError("seat_token чужого места")
                    engine_seat_id = sid
                    is_spectator = False
                    session.account_seats[account_id] = sid
                    break

        token = await issue_or_reuse_token(session, engine_seat_id)
        session.disconnect_hold_until.pop(account_id, None)
        _cancel_hold_task(session, account_id)

        # Вытеснить старое соединение того же аккаунта
        for cid, old in list(session.connections.items()):
            if old.account_id == account_id:
                with contextlib.suppress(Exception):
                    await old.ws.close(code=4000)
                session.connections.pop(cid, None)

        conn = Conn(
            ws=ws,
            account_id=account_id,
            engine_seat_id=engine_seat_id,
            seat_token=token,
            is_spectator=is_spectator,
        )
        session.connections[id(ws)] = conn
        event(
            logger,
            "ЗАДАЧА",
            "mp_ws_join code=%s seat=%s",
            session.room_code,
            engine_seat_id or "spectator",
            room_code=session.room_code,
            account_id=account_id,
            phase=_phase_of(session),
        )
        return conn


async def unbind_connection(session: RoomSession, ws: Any) -> None:
    engine_seat_id: str | None = None
    account_id: int | None = None
    async with session._lock:
        conn = session.connections.pop(id(ws), None)
        if conn is None:
            return
        account_id = conn.account_id
        engine_seat_id = conn.engine_seat_id
        # Зрители без места — hold не нужен.
        if engine_seat_id is None:
            event(
                logger,
                "ЗАДАЧА",
                "mp_ws_leave code=%s seat=spectator",
                session.room_code,
                room_code=session.room_code,
                account_id=account_id,
                phase=_phase_of(session),
            )
            return
        session.disconnect_hold_until[account_id] = time.monotonic() + DISCONNECT_HOLD_S
        event(
            logger,
            "ЗАДАЧА",
            "mp_ws_leave code=%s seat=%s hold=%ss",
            session.room_code,
            engine_seat_id,
            int(DISCONNECT_HOLD_S),
            room_code=session.room_code,
            account_id=account_id,
            phase=_phase_of(session),
        )
        _cancel_hold_task(session, account_id)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        session._hold_tasks[account_id] = loop.create_task(
            _hold_expire_to_bot(session, account_id, engine_seat_id)
        )


async def _hold_expire_to_bot(session: RoomSession, account_id: int, engine_seat_id: str) -> None:
    """§4.5: после 60 с без reconnect — LLM-заместитель с пометкой «бот»."""
    try:
        await asyncio.sleep(DISCONNECT_HOLD_S)
    except asyncio.CancelledError:
        return
    async with session._lock:
        deadline = session.disconnect_hold_until.get(account_id)
        if deadline is None or time.monotonic() < deadline - 0.5:
            return
        # Кто-то ещё держит WS этого аккаунта — не трогаем.
        if any(c.account_id == account_id for c in session.connections.values()):
            session.disconnect_hold_until.pop(account_id, None)
            return
        session.disconnect_hold_until.pop(account_id, None)
        session._hold_tasks.pop(account_id, None)
        session.account_seats.pop(account_id, None)
        session.seat_tokens.pop(engine_seat_id, None)
        if session.match is not None:
            session.engine.seat_to_bot(session.match, engine_seat_id)
        with contextlib.suppress(Exception):
            await repo.mark_account_seat_bot(session.room_id, account_id)
        humans_left = len(session.account_seats)
        event(
            logger,
            "ЗАДАЧА",
            "mp_ws_hold_bot code=%s seat=%s humans_left=%d",
            session.room_code,
            engine_seat_id,
            humans_left,
            room_code=session.room_code,
            account_id=account_id,
            phase=_phase_of(session),
            humans_left=humans_left,
        )
    await broadcast_state(session)
    await session.engine.step(session)
    # Если это был последний живой за столом — закрыть, а не оставлять ботов друг с другом.
    await hub().drop_if_empty(session.room_code)


async def broadcast_state(session: RoomSession) -> None:
    """Запросить рассылку состояния всем за столом.

    Кадры, родившиеся в пределах `BROADCAST_COALESCE_S` (каскад «интент применён → боты
    походили → LLM-фаза объявилась»), склеиваются в один конверт `{type:"state", …}` —
    Э20.1/20.2. Публичное и приватное состояние теперь едут вместе: раньше это были два
    отдельных `send_json` и два коммита React на каждое изменение.
    """
    if not session.connections:
        return
    session._broadcast_pending = True
    task = session._broadcast_task
    if task is not None and not task.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Без событийного цикла (в проде не бывает, редкий синхронный тест) — шлём сразу.
        await _broadcast_now(session)
        return
    session._broadcast_task = loop.create_task(_coalesced_broadcast(session))


async def _coalesced_broadcast(session: RoomSession) -> None:
    """Задача-склейка: подождать окно, разослать последнее состояние, повторить, если за
    время рассылки прилетел ещё запрос (докатывающийся каскад)."""
    try:
        while True:
            await asyncio.sleep(BROADCAST_COALESCE_S)
            if not session._broadcast_pending:
                return
            await _broadcast_now(session)
    except asyncio.CancelledError:
        return


async def _broadcast_now(session: RoomSession) -> None:
    """Собственно рассылка: один конверт на клиента, `private` подставляется по его месту."""
    session._broadcast_pending = False
    session._state_rev += 1
    base = _state_envelope(session, rev=session._state_rev)
    running = session.match is not None
    dead: list[Any] = []
    for conn in list(session.connections.values()):
        frame = base
        if running:
            frame = {
                **base,
                "private": session.engine.project_private(session.match, conn.engine_seat_id),
            }
        try:
            await conn.ws.send_json(frame)
        except Exception:  # noqa: BLE001
            dead.append(conn.ws)
    for ws in dead:
        session.connections.pop(id(ws), None)


def _cancel_pending_broadcast(session: RoomSession) -> None:
    """Снять задачу-склейку (комнату закрывают/выбрасывают) — иначе она отправит кадр в
    уже мёртвые соединения и повиснет пустой задачей."""
    task = session._broadcast_task
    if task is not None and not task.done():
        task.cancel()
    session._broadcast_task = None
    session._broadcast_pending = False


async def send_frame(session: RoomSession, payload: dict[str, Any]) -> None:
    """Лёгкий кадр всем за столом (не состояние): стрим реплики, будущие «живые» события."""
    dead: list[Any] = []
    for conn in list(session.connections.values()):
        try:
            await conn.ws.send_json(payload)
        except Exception:  # noqa: BLE001
            dead.append(conn.ws)
    for ws in dead:
        session.connections.pop(id(ws), None)


def _cancel_engine_tasks(session: RoomSession) -> None:
    """Снять прогретые LLM-задачи прошлой партии — иначе рематч ловит чужой текст/утечку."""
    for value in session._engine_memo.values():
        if isinstance(value, asyncio.Task) and not value.done():
            value.cancel()
    session._engine_memo.clear()


def _pause_envelope(session: RoomSession) -> dict[str, Any]:
    """Состояние паузы для клиента: заморожен ли стол и идёт ли отсчёт продолжения."""
    if session.paused_at is None:
        return {"paused": False}
    return {
        "paused": True,
        "by": session.paused_by_label,
        "resuming_at": _iso(session.resume_at),
    }


def _state_envelope(session: RoomSession, *, rev: int) -> dict[str, Any]:
    """Публичная половина конверта состояния + метаданные. `private` добавляет `_broadcast_now`
    на каждого клиента отдельно (по его месту). `rev` — монотонный номер кадра (Э20.6)."""
    now = _utc_now()
    if session.match is None:
        return {
            "type": "state",
            "rev": rev,
            "server_now": _iso(now),
            "phase_ends_at": None,
            "lobby": True,
            "pause": {"paused": False},
            "public": session.engine.lobby_state(
                account_seats=session.account_seats,
                nicks=session.nicks,
            ),
        }
    return {
        "type": "state",
        "rev": rev,
        "server_now": _iso(now),
        "phase_ends_at": _iso(session.phase_ends_at),
        "lobby": False,
        "pause": _pause_envelope(session),
        "public": session.engine.project_public(session.match, nicks=session.nicks),
    }


async def start_match_for_room(session: RoomSession, *, by_account_id: int) -> None:
    """Старт или «Ещё раунд» (тот же стол, новый seed) после Reveal/Ended."""
    if by_account_id != session.host_account_id:
        raise PermissionError("только хост запускает партию")
    engine = session.engine
    async with session._lock:
        # Рематч (§4.5): room тот же, match новый — только из терминальной фазы.
        if session.match is not None and not engine.can_restart(session.match):
            raise IllegalMove("партия уже идёт")
        # Э12: первый старт стола дня — seed от даты; rematch — случайный.
        is_rematch = session.match is not None
        if session.daily_day and not is_rematch:
            seed = engine.daily_seed(date.fromisoformat(session.daily_day))
        else:
            seed = secrets.randbelow(2**31 - 1) + 1
        state = engine.start(seed, candidate_count=session.candidate_slots)
        engine.bind_accounts(state, session.account_seats)
        session.match = state
        session._engine_flags.clear()
        _cancel_engine_tasks(session)
        _clear_pause(session)  # рематч поверх паузы — начинаем с чистого стола
        _arm_phase_timer(session)
        phase = engine.phase(state)
        await repo.update_room_playing(
            session.room_id,
            phase_label=engine.phase_label(phase),
        )
        event(
            logger,
            "ЗАДАЧА",
            "mp_ws_match_start code=%s seed=%s",
            session.room_code,
            seed,
            room_code=session.room_code,
            account_id=by_account_id,
            phase=phase,
        )
    await broadcast_state(session)
    await engine.step(session)


async def apply_client_intent(
    session: RoomSession,
    *,
    account_id: int,
    payload: dict[str, Any],
) -> None:
    """Клиентский intent: подставить actor_seat_id с сервера (античит)."""
    async with session._lock:
        if session.match is None:
            raise IllegalMove("партия ещё не начата")
        if session.paused:
            raise IllegalMove("стол на паузе")
        engine_seat = session.account_seats.get(account_id)
        if engine_seat is None:
            raise IllegalMove("зритель не ходит")
        engine = session.engine
        intent = engine.parse_intent(payload, actor_seat_id=engine_seat)
        new_state, events = engine.apply(session.match, intent)
        session.match = new_state
        _arm_phase_timer(session)
        phase = engine.phase(new_state)
        await repo.update_phase_label(session.room_id, engine.phase_label(phase))
        event(
            logger,
            "ЗАДАЧА",
            "mp_ws_intent code=%s type=%s phase=%s",
            session.room_code,
            payload.get("type"),
            phase,
            room_code=session.room_code,
            account_id=account_id,
            phase=phase,
        )
    await broadcast_state(session)
    for conn in list(session.connections.values()):
        with contextlib.suppress(Exception):
            await conn.ws.send_json(
                {"type": "events", "events": [{"type": e.type, "detail": e.detail} for e in events]}
            )
    await session.engine.step(session)


async def claim_seat(
    session: RoomSession,
    *,
    account_id: int,
    seat_id: str,
) -> None:
    """Сесть на пустой слот или заменить LLM-бота (BETWEEN или mid-match)."""
    async with session._lock:
        if session.match is None:
            raise IllegalMove("партия ещё не начата")
        if account_id in session.account_seats:
            raise IllegalMove("уже за столом")
        engine = session.engine
        idx = engine.index_for_seat_id(seat_id)
        if idx is None:
            raise IllegalMove("неверный seat_id")
        seat = engine.seat(session.match, seat_id)
        if seat is None or seat.kind != "candidate":
            raise IllegalMove("слот недоступен")
        # Пустой → join; бот → takeover. Живой игрок — нельзя.
        if seat.filled and not seat.is_bot:
            raise IllegalMove("слот занят")
        if seat.filled and seat.is_bot:
            # Замена бота человеком в любой фазе.
            claimed = await repo.claim_candidate_by_index(session.room_id, idx, account_id)
            if claimed is None:
                raise IllegalMove("слот занят в лобби")
            await repo.delete_spectator_for_account(session.room_id, account_id)
            engine.take_over_seat(session.match, seat_id, account_id)
            events = []
        else:
            # Порядок важен: фазу проверяем до записи в лобби-таблицу, иначе слот
            # окажется занят в БД у хода, который не состоялся.
            engine.ensure_can_join_seat(session.match)
            claimed = await repo.claim_candidate_by_index(session.room_id, idx, account_id)
            if claimed is None:
                raise IllegalMove("слот занят в лобби")
            await repo.delete_spectator_for_account(session.room_id, account_id)
            session.match, events = engine.join_seat(session.match, seat_id, account_id)

        session.account_seats[account_id] = seat_id
        token = await issue_or_reuse_token(session, seat_id)
        for conn in session.connections.values():
            if conn.account_id == account_id:
                conn.engine_seat_id = seat_id
                conn.is_spectator = False
                conn.seat_token = token
                with contextlib.suppress(Exception):
                    await conn.ws.send_json(
                        {
                            "type": "seat_assigned",
                            "engine_seat_id": seat_id,
                            "seat_token": token,
                            "is_spectator": False,
                        }
                    )
        event(
            logger,
            "ЗАДАЧА",
            "mp_ws_claim_seat code=%s seat=%s",
            session.room_code,
            seat_id,
            room_code=session.room_code,
            account_id=account_id,
            phase=_phase_of(session),
        )
    await broadcast_state(session)
    if events:
        for conn in list(session.connections.values()):
            with contextlib.suppress(Exception):
                await conn.ws.send_json(
                    {
                        "type": "events",
                        "events": [{"type": e.type, "detail": e.detail} for e in events],
                    }
                )


async def apply_human_takeover(
    session: RoomSession,
    *,
    account_id: int,
    seat_index: int,
) -> None:
    """REST join занял слот — синхронизировать живую партию (бот → человек)."""
    engine = session.engine
    seat_id = engine.seat_id_for_index(seat_index)
    async with session._lock:
        session.account_seats[account_id] = seat_id
        if session.match is None:
            return
        seat = engine.seat(session.match, seat_id)
        if seat is None:
            return
        if seat.filled and not seat.is_bot and seat.account_id not in (None, account_id):
            return
        if not seat.filled:
            session.match, _ = engine.join_seat(session.match, seat_id, account_id)
        else:
            engine.take_over_seat(session.match, seat_id, account_id)
        for conn in session.connections.values():
            if conn.account_id == account_id:
                conn.engine_seat_id = seat_id
                conn.is_spectator = False
    await broadcast_state(session)


async def host_action(
    session: RoomSession,
    *,
    by_account_id: int,
    action: str,
    seat_id: str | None = None,
    account_id: int | None = None,
) -> None:
    """Хост-панель: kick / fill_bot / assign_hr / add_slot."""
    if by_account_id != session.host_account_id:
        raise PermissionError("только хост")
    if action == "kick":
        await _host_kick(session, seat_id=seat_id)
    elif action == "fill_bot":
        await _host_fill_bot(session, seat_id=seat_id)
    elif action == "assign_hr":
        if account_id is None:
            raise IllegalMove("нужен account_id")
        await _host_assign_hr(session, to_account_id=account_id)
    elif action == "add_slot":
        await _host_add_slot(session)
    else:
        raise IllegalMove(f"неизвестное host action {action!r}")


async def _host_add_slot(session: RoomSession) -> None:
    """Добавить слот кандидата (макс. 6), сразу LLM-бот."""
    engine = session.engine
    async with session._lock:
        if session.candidate_slots >= engine.max_candidate_slots:
            raise IllegalMove(f"максимум {engine.max_candidate_slots} слотов кандидатов")
        new_idx = session.candidate_slots
        seat_id = engine.seat_id_for_index(new_idx)
        session.candidate_slots += 1
        settings = repo.settings_from_json(
            (await repo.get_room_by_id(session.room_id) or {}).get("settings")
        )
        settings.candidate_slots = session.candidate_slots
        await repo.update_room_settings(session.room_id, settings)
        await repo.insert_seat(
            room_id=session.room_id,
            account_id=None,
            seat_kind="candidate",
            seat_index=new_idx,
            is_bot=True,
        )
        if session.match is not None:
            engine.add_candidate_seat(session.match, seat_id)
        event(
            logger,
            "ЗАДАЧА",
            "mp_ws_add_slot code=%s seat=%s",
            session.room_code,
            seat_id,
            room_code=session.room_code,
            account_id=session.host_account_id,
        )
    await broadcast_state(session)
    await engine.step(session)


async def _host_kick(session: RoomSession, *, seat_id: str | None) -> None:
    engine = session.engine
    if not seat_id or seat_id == engine.host_seat_id:
        raise IllegalMove("кик только кандидата")
    idx = engine.index_for_seat_id(seat_id)
    if idx is None:
        raise IllegalMove("неверный seat_id")
    async with session._lock:
        if session.match is None:
            raise IllegalMove("партия ещё не начата")
        seat = engine.seat(session.match, seat_id)
        if seat is None or seat.kind != "candidate" or not seat.filled:
            raise IllegalMove("некого кикать")
        kicked_aid = seat.account_id
        # Между слотами слот освобождается насовсем; в партии — бот-заместитель,
        # чтобы состав ролей не разъехался и партия не встала.
        if engine.can_vacate_seat(session.match):
            session.match = engine.vacate_seat(session.match, seat_id)
            await repo.clear_candidate_to_empty(session.room_id, idx)
        else:
            engine.seat_to_bot(session.match, seat_id)
            await repo.set_candidate_bot(session.room_id, idx)
        if kicked_aid is not None:
            session.account_seats.pop(kicked_aid, None)
            session.seat_tokens.pop(seat_id, None)
            _cancel_hold_task(session, kicked_aid)
            session.disconnect_hold_until.pop(kicked_aid, None)
            for conn in session.connections.values():
                if conn.account_id == kicked_aid:
                    conn.engine_seat_id = None
                    conn.is_spectator = True
                    with contextlib.suppress(Exception):
                        await conn.ws.send_json(
                            {
                                "type": "seat_assigned",
                                "engine_seat_id": None,
                                "seat_token": conn.seat_token,
                                "is_spectator": True,
                            }
                        )
                        await conn.ws.send_json(
                            {"type": "error", "detail": "Хост снял вас со слота — вы зритель"}
                        )
        event(
            logger,
            "ЗАДАЧА",
            "mp_ws_kick code=%s seat=%s",
            session.room_code,
            seat_id,
            room_code=session.room_code,
            account_id=session.host_account_id,
            phase=_phase_of(session),
        )
    await broadcast_state(session)
    await engine.step(session)


async def _host_fill_bot(session: RoomSession, *, seat_id: str | None) -> None:
    engine = session.engine
    if not seat_id:
        raise IllegalMove("нужен seat_id")
    idx = engine.index_for_seat_id(seat_id)
    if idx is None:
        raise IllegalMove("неверный seat_id")
    async with session._lock:
        if session.match is None:
            raise IllegalMove("партия ещё не начата")
        engine.ensure_can_fill_bot(session.match)
        seat = engine.seat(session.match, seat_id)
        if seat is None or seat.kind != "candidate":
            raise IllegalMove("нет слота")
        if seat.filled:
            raise IllegalMove("слот занят")
        session.match, _ = engine.fill_seat_with_bot(session.match, seat_id)
        await repo.set_candidate_bot(session.room_id, idx)
        event(
            logger,
            "ЗАДАЧА",
            "mp_ws_fill_bot code=%s seat=%s",
            session.room_code,
            seat_id,
            room_code=session.room_code,
            account_id=session.host_account_id,
            phase=_phase_of(session),
        )
    await broadcast_state(session)
    await engine.step(session)


async def _host_assign_hr(session: RoomSession, *, to_account_id: int) -> None:
    """Назначить хрюшу зрителю/себе (если слот hr пуст/бот или хост передаёт)."""
    engine = session.engine
    host_seat = engine.host_seat_id
    async with session._lock:
        occupied = session.account_seats.get(to_account_id)
        if occupied is not None and occupied != host_seat:
            raise IllegalMove("сначала освободите слот кандидата")
        old_hr_aid = next(
            (a for a, s in session.account_seats.items() if s == host_seat),
            None,
        )
        if session.match is not None:
            # Место ведущего у живого игрока (не хоста) — забрать можно только через kick/hold.
            if engine.host_seat_taken_by_other(
                session.match, to_account_id, session.host_account_id
            ):
                raise IllegalMove("хрюша занята — сначала kick/hold")
            engine.assign_host_seat(session.match, to_account_id)
        if old_hr_aid is not None and old_hr_aid != to_account_id:
            session.account_seats.pop(old_hr_aid, None)
        session.account_seats[to_account_id] = host_seat
        token = await issue_or_reuse_token(session, host_seat)
        await repo.transfer_hr_seat(
            session.room_id,
            to_account_id=to_account_id,
            from_account_id=old_hr_aid,
        )
        for conn in session.connections.values():
            if conn.account_id == to_account_id:
                conn.engine_seat_id = host_seat
                conn.is_spectator = False
                conn.seat_token = token
                with contextlib.suppress(Exception):
                    await conn.ws.send_json(
                        {
                            "type": "seat_assigned",
                            "engine_seat_id": host_seat,
                            "seat_token": token,
                            "is_spectator": False,
                        }
                    )
            elif old_hr_aid is not None and conn.account_id == old_hr_aid:
                conn.engine_seat_id = None
                conn.is_spectator = True
                with contextlib.suppress(Exception):
                    await conn.ws.send_json(
                        {
                            "type": "seat_assigned",
                            "engine_seat_id": None,
                            "seat_token": conn.seat_token,
                            "is_spectator": True,
                        }
                    )
        event(
            logger,
            "ЗАДАЧА",
            "mp_ws_assign_hr code=%s to=%s",
            session.room_code,
            to_account_id,
            room_code=session.room_code,
            account_id=session.host_account_id,
            phase=_phase_of(session),
        )
    await broadcast_state(session)


def _arm_phase_timer(session: RoomSession, *, resume_seconds: float | None = None) -> None:
    # Снимаем прежний таймер — но НЕ тот, из которого нас же и позвали. `_phase_timer`,
    # доведя фазу до следующей, взводит таймер сам, и `session._timer_task` в этот момент
    # всё ещё он сам: `cancel()` на текущей задаче доставляет CancelledError на ближайшем
    # `await` — то есть до `broadcast_state`. Партия при этом идёт дальше (состояние-то
    # сменилось), а клиентам об этом никто не говорит: экран замирает на прошлой фазе, и
    # следующий клик получает «не та фаза». Заодно терялся лог `mp_ws_timeout` и `step()`
    # (боты/судья/газета). Дефект Д1, plans/wolves_game_deep_polish_2026_08_26.md.
    #
    # `resume_seconds` — путь «Продолжить» после паузы: взвести на ОСТАТОК фазы, а не на её
    # полную длину.
    prev = session._timer_task
    if prev is not None and not prev.done() and prev is not asyncio.current_task():
        prev.cancel()
    if session.match is None:
        session.phase_ends_at = None
        return
    phase = session.engine.phase(session.match)
    dur = session.engine.phase_duration_s(phase)
    if dur is None:
        # Фаза без таймера (у Wolves — reveal/ended): ждём действия людей, не часов.
        session.phase_ends_at = None
        return
    if session.paused and resume_seconds is None:
        # Стол на паузе — таймер не тикает. Запоминаем остаток по новой фазе (её мог
        # довести до конца долетевший из-под паузы LLM-шаг) и держим экран замороженным.
        session.paused_phase_left_s = dur
        session.phase_ends_at = None
        return
    dur = resume_seconds if resume_seconds is not None else dur
    session.phase_ends_at = _utc_now() + timedelta(seconds=dur)
    # asyncio.create_task from running loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    session._timer_task = loop.create_task(_phase_timer(session, phase, dur))


async def _phase_timer(session: RoomSession, phase_when_armed: str, delay: float) -> None:
    try:
        await asyncio.sleep(delay)
    except asyncio.CancelledError:
        return
    if session.paused:
        # Пауза дошла до нас между sleep и локом — фазу не двигаем (защита; обычно
        # `pause_match` уже снял эту задачу).
        return
    engine = session.engine
    async with session._lock:
        if session.match is None or engine.phase(session.match) != phase_when_armed:
            return
        try:
            session.match = engine.on_timeout(session.match, phase_when_armed)
        except IllegalMove as exc:
            event(
                logger,
                "ЗАДАЧА",
                "mp_ws_timeout_skip code=%s phase=%s err=%s",
                session.room_code,
                phase_when_armed,
                str(exc),
                room_code=session.room_code,
                phase=phase_when_armed,
                level=logging.WARNING,
            )
            return
        _arm_phase_timer(session)
        phase = engine.phase(session.match)
        await repo.update_phase_label(session.room_id, engine.phase_label(phase))
        event(
            logger,
            "ЗАДАЧА",
            "mp_ws_timeout code=%s → %s",
            session.room_code,
            phase,
            room_code=session.room_code,
            phase=phase,
        )
    await broadcast_state(session)
    await engine.step(session)


# --- Пауза (Dota-стиль, по запросу владельца 2026-08-28) ------------------------------


def _cancel_resume_countdown(session: RoomSession) -> None:
    # `task is not current` — как в `_arm_phase_timer`: `_finish_resume` вызывает `_clear_pause`
    # из самой задачи отсчёта, `cancel()` на себе оборвал бы `broadcast_state`/`step` следом.
    task = session._resume_task
    if task is not None and not task.done() and task is not asyncio.current_task():
        task.cancel()
    session._resume_task = None
    session.resume_at = None


def _clear_pause(session: RoomSession) -> None:
    """Полностью снять паузу (закрытие стола, рематч, продолжение)."""
    _cancel_resume_countdown(session)
    session.paused_at = None
    session.paused_by_label = ""
    session.paused_phase_left_s = None


async def pause_match(session: RoomSession, *, account_id: int, by_label: str) -> None:
    """Любой участник ставит стол на паузу — держится бессрочно, до «Продолжить»."""
    async with session._lock:
        if session.match is None:
            raise IllegalMove("партия ещё не начата")
        if session.engine.can_restart(session.match):
            raise IllegalMove("партия уже окончена")
        was_resuming = session.resume_at is not None
        _cancel_resume_countdown(session)  # нажали паузу во время отсчёта — отменяем его
        if session.paused_at is None:
            left: float | None = None
            if session.phase_ends_at is not None:
                left = max(0.0, (session.phase_ends_at - _utc_now()).total_seconds())
            session.paused_phase_left_s = left
            session.paused_at = _utc_now()
            session.paused_by_label = by_label or "кто-то"
            prev = session._timer_task
            if prev is not None and not prev.done():
                prev.cancel()
            session._timer_task = None
            session.phase_ends_at = None
        event(
            logger,
            "ЗАДАЧА",
            "mp_ws_pause code=%s by=%s phase=%s left=%.1fs resume_cancelled=%s",
            session.room_code,
            session.paused_by_label,
            _phase_of(session),
            session.paused_phase_left_s or 0.0,
            was_resuming,
            room_code=session.room_code,
            account_id=account_id,
            phase=_phase_of(session),
        )
    await broadcast_state(session)


async def resume_match(session: RoomSession, *, account_id: int, by_label: str) -> None:
    """Любой участник снимает паузу — игра пойдёт через RESUME_COUNTDOWN_S с таймером."""
    task: asyncio.Task | None = None
    async with session._lock:
        if session.paused_at is None or session.resume_at is not None:
            return  # не на паузе / отсчёт уже идёт — no-op, не ошибка
        session.resume_at = _utc_now() + timedelta(seconds=RESUME_COUNTDOWN_S)
        event(
            logger,
            "ЗАДАЧА",
            "mp_ws_resume_countdown code=%s by=%s in=%.0fs",
            session.room_code,
            by_label or "кто-то",
            RESUME_COUNTDOWN_S,
            room_code=session.room_code,
            account_id=account_id,
            phase=_phase_of(session),
        )
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            task = loop.create_task(_resume_after_countdown(session))
            session._resume_task = task
    await broadcast_state(session)
    if task is None:
        # Без событийного цикла (редкий синхронный тест) — продолжаем сразу.
        await _finish_resume(session)


async def _resume_after_countdown(session: RoomSession) -> None:
    try:
        await asyncio.sleep(RESUME_COUNTDOWN_S)
    except asyncio.CancelledError:
        return
    await _finish_resume(session)


async def _finish_resume(session: RoomSession) -> None:
    async with session._lock:
        if session.paused_at is None:
            return
        left = session.paused_phase_left_s
        _clear_pause(session)
        if session.match is not None and left is not None and left > 0:
            _arm_phase_timer(session, resume_seconds=left)
        else:
            _arm_phase_timer(session)
        event(
            logger,
            "ЗАДАЧА",
            "mp_ws_resumed code=%s phase=%s left=%.1fs",
            session.room_code,
            _phase_of(session),
            left or 0.0,
            room_code=session.room_code,
            phase=_phase_of(session),
        )
    await broadcast_state(session)
    if session.match is not None:
        await session.engine.step(session)
