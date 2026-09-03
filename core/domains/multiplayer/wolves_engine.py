"""Адаптер «Хрюши и Волки» под протокол `engine.GameEngine` (Э17).

Здесь собрано всё, что раньше знал про эту игру generic-хаб `session.py`: длительности и
ярлыки фаз, разбор интентов, что делать по таймеру фазы, как боты доигрывают за пустые места,
когда звать LLM (реплики / судья / газета / реакции / сцена слота) и как трогать места на
живом столе.

Содержимого правил не меняем — это обёртка вокруг существующих `rules` / `views` / `deck`.

**Когда какой вызов идёт** (Э19.8/Э20.3/Э20.4) — правило одно: LLM не стоит на критическом
пути фазы.

| что | когда стартует | как доезжает |
| --- | --- | --- |
| сцена слота | вход в BULLETIN | приезжает в тот же слот, фаза не ждёт |
| реплики ботов | вход в LINES | стрим кадрами + применение по одной, параллельно (≤3) |
| судья | **подача иска в INSPECT** | к фазе JUDGE ответ обычно уже готов |
| реакция на штамп | как только штамп поставлен | фоном, применяется в том же слоте |
| газета | вход в RESULT | принимается и в BETWEEN — RESULT короче вызова |
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any, Literal

from pydantic import TypeAdapter

from core.domains.multiplayer import wolves_llm
from core.domains.multiplayer.deck import daily_seed as deck_daily_seed
from core.domains.multiplayer.deck import deal_hand
from core.domains.multiplayer.engine import GameEvent, GameState, MatchRuntime, SeatView
from core.domains.multiplayer.models import (
    AdvancePhase,
    AnswerLine,
    BeginNextSlot,
    Faction,
    IllegalMove,
    Intent,
    MatchConfig,
    MatchState,
    MidJoin,
    Phase,
    PlayCards,
    PublicStatus,
    ResolveJudge,
    Seat,
    SeatKind,
    SubRole,
    TimeoutPhase,
)
from core.domains.multiplayer.rules import (
    HR_SEAT_ID,
    apply,
    claim_is_correct,
    is_terminal,
    start_match,
    vacate_candidate_seat,
)
from core.domains.multiplayer.views import project_private, project_public
from core.platform.observability import event

logger = logging.getLogger(__name__)

_INTENT_ADAPTER: TypeAdapter[Intent] = TypeAdapter(Intent)

# Длительности фаз (сек). Клиент считает от phase_ends_at (абсолютное), не от локального тика.
PHASE_DURATION_S: dict[str, float] = {
    Phase.BULLETIN.value: 8.0,
    Phase.PLAY.value: 35.0,
    Phase.INSPECT.value: 40.0,
    Phase.LINES.value: 30.0,
    Phase.STAMP.value: 35.0,
    Phase.JUDGE.value: 25.0,
    Phase.RESULT.value: 6.0,
    Phase.BETWEEN.value: 20.0,  # Э10: окно mid-join / claim
}

MAX_CANDIDATE_SLOTS = 6

PHASE_LABEL_RU = {
    "lobby": "лобби",
    Phase.BULLETIN.value: "бюллетень",
    Phase.PLAY.value: "подать",
    Phase.INSPECT.value: "осмотр",
    Phase.LINES.value: "реплики",
    Phase.STAMP.value: "штамп",
    Phase.JUDGE.value: "суд",
    Phase.RESULT.value: "итог",
    Phase.BETWEEN.value: "передышка",
    Phase.REVEAL.value: "reveal",
    Phase.ENDED.value: "конец",
}

# Ключи флагов «работа уже запущена» в `MatchRuntime` — против повторного старта LLM
# на ту же фазу (Э8).
FLAG_JUDGE = "judge_llm_inflight"
FLAG_TICKER = "ticker_llm_inflight"
FLAG_LINES = "lines_llm_inflight"
FLAG_BARK = "bark_llm_inflight"
FLAG_BRIEF = "brief_llm_inflight"

# Ключи черновика (`MatchRuntime.memo`) — прогретый судья: задача и хэш улик, под которые
# она запускалась. Хэш нужен, чтобы не подставить в суд текст от другого иска (Э20.4).
MEMO_JUDGE_TASK = "judge_prefetch_task"
MEMO_JUDGE_HASH = "judge_prefetch_hash"

# Потолок одновременных вызовов в одного провайдера. Шесть параллельных запросов ловят
# upstream rate-limit (замер Э19: 429 уже на двух-трёх подряд), и «параллельно» превращается
# в «половина ушла в заглушку». Три — компромисс между кругом за 3-4 с и живым провайдером.
MAX_PARALLEL_LLM = 3


def _seat_view(seat: Seat) -> SeatView:
    return SeatView(
        id=seat.id,
        kind=seat.kind.value,
        filled=seat.filled,
        is_bot=seat.is_bot,
        account_id=seat.account_id,
    )


class WolvesEngine:
    """Реализация `GameEngine` для «Хрюши и Волки»."""

    game_id = "wolves"
    host_seat_id = HR_SEAT_ID
    max_candidate_slots = MAX_CANDIDATE_SLOTS

    # --- жизненный цикл --------------------------------------------------------

    def start(self, seed: int, *, candidate_count: int) -> GameState:
        return start_match(seed, config=MatchConfig(candidate_count=candidate_count))

    def daily_seed(self, day: date) -> int:
        # Соль в хеше — своя на игру: у «стола дня» разных игр не должно совпадать.
        return deck_daily_seed(day=day)

    def seat_id_for_index(self, index: int) -> str:
        """Номер слота из лобби-таблицы → id места в партии."""
        return f"c{index}"

    def index_for_seat_id(self, seat_id: str) -> int | None:
        """Обратно: id места → номер слота (`None`, если это не место кандидата)."""
        if seat_id.startswith("c") and seat_id[1:].isdigit():
            return int(seat_id[1:])
        return None

    def can_restart(self, state: GameState) -> bool:
        # Рематч (§4.5): тот же стол, новый seed — только из reveal/ended.
        return state.phase.value in ("ended", "reveal")

    def is_terminal(self, state: GameState) -> bool:
        return is_terminal(state)

    # --- фазы ------------------------------------------------------------------

    def phase(self, state: GameState) -> str:
        return state.phase.value

    def phase_label(self, phase: str) -> str:
        return PHASE_LABEL_RU.get(phase, phase)

    def phase_duration_s(self, phase: str) -> float | None:
        if phase in (Phase.REVEAL.value, Phase.ENDED.value):
            return None
        return PHASE_DURATION_S.get(phase)

    def on_timeout(self, state: GameState, phase: str) -> GameState:
        """Таймер фазы истёк. Ветвление ровно как было в хабе, поведение не меняется."""
        if phase == Phase.PLAY.value:
            return _force_remaining_plays(state)
        if phase == Phase.RESULT.value:
            new_state, _ = apply(state, AdvancePhase(actor_seat_id=HR_SEAT_ID))
            return new_state
        if phase == Phase.BETWEEN.value:
            new_state, _ = apply(state, BeginNextSlot(actor_seat_id=HR_SEAT_ID))
            return new_state
        new_state, _ = apply(state, TimeoutPhase())
        return new_state

    # --- ходы ------------------------------------------------------------------

    def parse_intent(self, payload: Mapping[str, Any], *, actor_seat_id: str) -> Any:
        data = dict(payload)
        # mid_join / kick — только через claim_seat / host_*, где account_id ставит сервер.
        if data.get("type") in ("mid_join",):
            raise IllegalMove("mid_join только через claim_seat")
        data["actor_seat_id"] = actor_seat_id
        return _INTENT_ADAPTER.validate_python(data)

    def apply(self, state: GameState, intent: Any) -> tuple[GameState, Sequence[GameEvent]]:
        return apply(state, intent)

    # --- проекции --------------------------------------------------------------

    def project_public(self, state: GameState, *, nicks: Mapping[int, str]) -> dict[str, Any]:
        return project_public(state, nicks=dict(nicks))

    def project_private(self, state: GameState, seat_id: str | None) -> dict[str, Any]:
        return project_private(state, seat_id)

    def lobby_state(
        self,
        *,
        account_seats: Mapping[int, str],
        nicks: Mapping[int, str],
    ) -> dict[str, Any]:
        return {
            "phase": "lobby",
            "slot_index": 0,
            "slot_count": MatchConfig().slot_count,
            "seats": [
                {
                    "id": sid,
                    "kind": "hr" if sid == HR_SEAT_ID else "candidate",
                    "account_id": aid,
                    "nick": nicks.get(aid),
                    "filled": True,
                    "is_bot": False,
                    "public_status": "waiting",
                }
                for aid, sid in account_seats.items()
            ],
        }

    # --- места -----------------------------------------------------------------

    def seat(self, state: GameState, seat_id: str) -> SeatView | None:
        seat = state.seats.get(seat_id)
        return _seat_view(seat) if seat is not None else None

    def candidate_seat_ids(self, state: GameState) -> list[str]:
        return sorted(s.id for s in state.seats.values() if s.kind == SeatKind.CANDIDATE)

    def bind_accounts(self, state: GameState, account_seats: Mapping[int, str]) -> None:
        claimed: set[str] = set()
        for aid, sid in account_seats.items():
            seat = state.seats.get(sid)
            if seat is not None:
                seat.account_id = aid
                seat.is_bot = False
                seat.filled = True
                claimed.add(sid)
        # Единый стол: незанятые кандидаты остаются LLM-ботами (друг может сесть).
        for seat in state.seats.values():
            if seat.kind == SeatKind.CANDIDATE and seat.id not in claimed:
                seat.is_bot = True
                seat.filled = True
                seat.account_id = None

    def take_over_seat(self, state: GameState, seat_id: str, account_id: int) -> None:
        seat = state.seats[seat_id]
        seat.account_id = account_id
        seat.is_bot = False
        seat.filled = True

    def ensure_can_join_seat(self, state: GameState) -> None:
        """Guard отдельно от применения: хаб обязан проверить фазу до записи в лобби-таблицу.

        `_mid_join` и сам требует BETWEEN, но его текст («фаза play, ожидали…») — для
        разработчика, игроку нужен человеческий.
        """
        if state.phase != Phase.BETWEEN:
            raise IllegalMove("сесть на пустой слот можно только между слотами")

    def join_seat(
        self, state: GameState, seat_id: str, account_id: int
    ) -> tuple[GameState, Sequence[GameEvent]]:
        return apply(state, MidJoin(seat_id=seat_id, account_id=account_id, as_bot=False))

    def ensure_can_fill_bot(self, state: GameState) -> None:
        """Парный к `ensure_can_join_seat` guard для добора бота хостом."""
        if state.phase != Phase.BETWEEN:
            raise IllegalMove("добор бота только между слотами")

    def fill_seat_with_bot(
        self, state: GameState, seat_id: str
    ) -> tuple[GameState, Sequence[GameEvent]]:
        new_state, events = apply(state, MidJoin(seat_id=seat_id, account_id=None, as_bot=True))
        bot = new_state.seats[seat_id]
        bot.account_id = None
        bot.is_bot = True
        return new_state, events

    def seat_to_bot(self, state: GameState, seat_id: str) -> None:
        seat = state.seats.get(seat_id)
        if seat is None:
            return
        seat.is_bot = True
        seat.account_id = None
        seat.filled = True

    def vacate_seat(self, state: GameState, seat_id: str) -> GameState:
        return vacate_candidate_seat(state, seat_id)

    def can_vacate_seat(self, state: GameState) -> bool:
        # Между слотами слот освобождается насовсем; в партии — только замена ботом,
        # иначе разъедется состав ролей.
        return state.phase == Phase.BETWEEN

    def add_candidate_seat(self, state: GameState, seat_id: str) -> None:
        rng = random.Random(f"{state.seed}:add_slot:{seat_id}")
        hand = deal_hand(rng, state.deck_order, n=state.config.hand_size)
        state.seats[seat_id] = Seat(
            id=seat_id,
            kind=SeatKind.CANDIDATE,
            faction=Faction.HUMAN,
            sub_role=SubRole.NONE,
            hand=hand,
            is_bot=True,
            filled=True,
            public_status=PublicStatus.WAITING,
        )
        state.lifetime_stamps.setdefault(seat_id, [])
        state.config.candidate_count = len(
            [s for s in state.seats.values() if s.kind == SeatKind.CANDIDATE]
        )

    def assign_host_seat(self, state: GameState, account_id: int) -> None:
        hr = state.seats.get(HR_SEAT_ID)
        if hr is None:
            raise IllegalMove("нет места хрюши")
        hr.account_id = account_id
        hr.is_bot = False
        hr.filled = True

    def host_seat_taken_by_other(
        self, state: GameState, account_id: int, host_account_id: int
    ) -> bool:
        """Место ведущего занято живым игроком, который не хост и не претендент."""
        hr = state.seats.get(HR_SEAT_ID)
        if hr is None:
            return False
        return bool(
            hr.filled
            and not hr.is_bot
            and hr.account_id is not None
            and hr.account_id != host_account_id
            and account_id != hr.account_id
        )

    # --- асинхронные шаги ------------------------------------------------------

    async def step(self, runtime: MatchRuntime) -> None:
        # Стол на паузе — ничего не доигрываем и не греем. Долетевшие из-под паузы задачи
        # (стрим реплики, прогрев судьи) применят свой результат сами, но новую работу
        # с паузы не начинаем.
        if runtime.paused:
            return
        # Порядок важен: сначала то, что прогревается заранее (сцена слота, судья), потом
        # то, что идёт по факту фазы. Прогрев не ждём — он живёт своей задачей.
        _warm_judge(runtime)
        await _run_brief(runtime)
        await _auto_bots(runtime)
        await _run_judge(runtime)
        await _run_barks(runtime)
        await _run_ticker(runtime)


# --- внутренности асинхронных шагов -------------------------------------------------
#
# Перенесено из `session.py` без изменения логики: тот же порядок, те же guard-условия,
# те же флаги «уже запущено». Изменился только способ добраться до комнаты — через
# `MatchRuntime` вместо прямого доступа к полям `RoomSession`.


def _force_remaining_plays(state: MatchState) -> MatchState:
    """Таймаут PLAY: кто не выложил — первые карты из руки (бот/AFK)."""
    bulletin = state.bulletin
    if bulletin is None:
        return state
    need = bulletin.cards_to_play
    for seat in list(state.seats.values()):
        if seat.kind != SeatKind.CANDIDATE or not seat.filled or seat.played:
            continue
        cards = seat.hand[:need]
        if len(cards) < need:
            continue
        state, _ = apply(state, PlayCards(actor_seat_id=seat.id, card_ids=list(cards)))
    return state


async def _auto_bots(runtime: MatchRuntime) -> None:
    """Соло/боты: в PLAY сразу кладут карты; в LINES — круг реплик (стрим, параллельно)."""
    play_changed = False
    seat_ids: list[str] = []
    snap: MatchState | None = None

    async with runtime.lock:
        state = runtime.get_state()
        if state is None:
            return
        if state.phase == Phase.PLAY:
            for seat in list(state.seats.values()):
                if not seat.is_bot or not seat.filled or seat.played:
                    continue
                need = state.bulletin.cards_to_play if state.bulletin else 1
                cards = seat.hand[:need]
                if len(cards) < need:
                    continue
                try:
                    state, _ = apply(state, PlayCards(actor_seat_id=seat.id, card_ids=list(cards)))
                    play_changed = True
                except IllegalMove:
                    continue
            runtime.set_state(state)
            if play_changed:
                runtime.rearm_timer()
        elif state.phase == Phase.LINES and state.question_chip and not runtime.flag(FLAG_LINES):
            seat_ids = wolves_llm.bot_seat_ids_needing_line(state)
            if seat_ids:
                runtime.set_flag(FLAG_LINES, True)
                snap = state.model_copy(deep=True)

    if play_changed:
        event(
            logger,
            "ЗАДАЧА",
            "mp_bots_played code=%s phase=play",
            runtime.room_code,
            room_code=runtime.room_code,
        )
        await runtime.broadcast()
        return

    if not seat_ids or snap is None:
        return

    event(
        logger,
        "ЗАДАЧА",
        "mp_bots_lines_round code=%s seats=%d",
        runtime.room_code,
        len(seat_ids),
        room_code=runtime.room_code,
        seats=len(seat_ids),
    )

    # Круг реплик идёт параллельно и с потолком одновременности. Последовательный цикл стоил
    # ~15 с на бота при фазе в 30 с: при трёх ботах двое молчали, при пяти отвечал один —
    # игрок видел не «боты думают», а мёртвый стол (Э20.3).
    sem = asyncio.Semaphore(MAX_PARALLEL_LLM)

    async def _one(seat_id: str) -> None:
        async with sem:
            line = await wolves_llm.stream_bot_line(
                snap,
                seat_id,
                on_delta=_line_delta_sender(runtime, seat_id),
            )
        # Ответ применяем сразу, не дожидаясь остальных: за столом реплики появляются по
        # одной, как в разговоре, а не пачкой в конце круга.
        await _apply_bot_line(runtime, seat_id, line)

    try:
        await asyncio.gather(*(_one(sid) for sid in seat_ids), return_exceptions=True)
    finally:
        async with runtime.lock:
            runtime.set_flag(FLAG_LINES, False)


def _line_delta_sender(runtime: MatchRuntime, seat_id: str) -> wolves_llm.LineDelta:
    """Кадр `line_delta` в комнату: реплика печатается на глазах, а не всплывает готовой."""

    async def _send(text: str) -> None:
        await runtime.send_frame({"type": "line_delta", "seat_id": seat_id, "text": text})

    return _send


async def _apply_bot_line(runtime: MatchRuntime, seat_id: str, line: str) -> None:
    async with runtime.lock:
        state = runtime.get_state()
        if state is None or state.phase != Phase.LINES:
            return
        if seat_id in state.answers or seat_id in state.stamps_this_slot:
            return
        try:
            state, _ = apply(state, AnswerLine(actor_seat_id=seat_id, text=line[:80]))
        except IllegalMove:
            return
        runtime.set_state(state)
    await runtime.broadcast()


def _warm_judge(runtime: MatchRuntime) -> None:
    """Э20.4: иск подан в INSPECT — судью зовём сразу, не дожидаясь фазы JUDGE.

    Всё, что нужно судье, известно в момент `mark_discrepancy`: кандидат, две улики и
    вердикт движка. Раньше вызов стартовал на входе в JUDGE, и все его секунды игрок
    смотрел на статичное «Судья смотрит улики…» (замер: 11.6 с при длине фазы 25 с).
    Теперь ожидание уезжает в осмотр, где игрок и так читает бумаги.
    """
    # Функция синхронная целиком (ни одного await до `create_task`), поэтому читает состояние
    # без блокировки: в кооперативном цикле её никто не может перебить на середине.
    state = runtime.get_state()
    if state is None or state.phase != Phase.INSPECT or not state.pending_judge:
        return
    task = runtime.memo(MEMO_JUDGE_TASK)
    if isinstance(task, asyncio.Task) and not task.done():
        return
    if isinstance(task, asyncio.Task):
        # Прошлый прогрев никому не пригодился — забираем его исключение, иначе asyncio
        # напишет в лог «Task exception was never retrieved» на ровном месте.
        with contextlib.suppress(Exception):
            task.exception()
    snap = state.model_copy(deep=True)
    evidence_hash = wolves_llm.judge_evidence_hash(wolves_llm.build_judge_evidence(snap))
    if task is not None and runtime.memo(MEMO_JUDGE_HASH) == evidence_hash:
        return  # уже прогрет под этот же иск
    runtime.set_memo(MEMO_JUDGE_HASH, evidence_hash)
    runtime.set_memo(MEMO_JUDGE_TASK, asyncio.create_task(wolves_llm.generate_judge(snap)))


async def _take_warm_judge(runtime: MatchRuntime, snap: MatchState) -> wolves_llm.JudgeCall | None:
    """Забрать прогретого судью, если он про этот же иск. Иначе — снять и звать заново."""
    task = runtime.memo(MEMO_JUDGE_TASK)
    if not isinstance(task, asyncio.Task):
        return None
    runtime.set_memo(MEMO_JUDGE_TASK, None)
    wanted = wolves_llm.judge_evidence_hash(wolves_llm.build_judge_evidence(snap))
    if runtime.memo(MEMO_JUDGE_HASH) != wanted:
        task.cancel()
        return None
    try:
        return await task
    except Exception as exc:  # noqa: BLE001 — прогрев не обязан удаться
        event(
            logger,
            "ЗАДАЧА",
            "mp_llm_judge_warm_lost err=%s",
            str(exc),
            room_code=runtime.room_code,
            level=logging.WARNING,
        )
        return None


async def _run_judge(runtime: MatchRuntime) -> None:
    """Э8: авто-суд в JUDGE — без зависания фазы при сбое LLM."""
    async with runtime.lock:
        state = runtime.get_state()
        if state is None:
            return
        if state.phase != Phase.JUDGE or not state.pending_judge:
            return
        if runtime.flag(FLAG_JUDGE):
            return
        runtime.set_flag(FLAG_JUDGE, True)
        snap = state.model_copy(deep=True)

    try:
        try:
            warmed = await _take_warm_judge(runtime, snap)
            call = warmed if warmed is not None else await wolves_llm.generate_judge(snap)
        except Exception as exc:  # noqa: BLE001
            event(
                logger,
                "ЗАДАЧА",
                "mp_llm_judge_crash err=%s",
                str(exc),
                room_code=runtime.room_code,
                level=logging.WARNING,
            )
            # Вердикт считает движок — падение LLM меняет только текст. Раньше здесь стояло
            # «reject», то есть сбой провайдера мог подарить хрюше выговор за пропущенного
            # волка на верном иске.
            verdict: Literal["confirm", "reject"] = (
                "confirm" if claim_is_correct(snap) else "reject"
            )
            call = wolves_llm.JudgeCall(verdict, wolves_llm.FALLBACK_JUDGE_LINE, None)

        async with runtime.lock:
            runtime.set_flag(FLAG_JUDGE, False)
            state = runtime.get_state()
            if state is None or state.phase != Phase.JUDGE:
                return
            if not state.pending_judge:
                return
            try:
                new_state, _ = apply(
                    state,
                    ResolveJudge(actor_seat_id=HR_SEAT_ID, verdict=call.verdict),
                )
                new_state.judge_line = call.line
                new_state.judge_marker = call.marker
                runtime.set_state(new_state)
                runtime.rearm_timer()
                await runtime.note_phase(new_state.phase.value)
                event(
                    logger,
                    "ЗАДАЧА",
                    "mp_judge_resolved code=%s verdict=%s marker=%s → phase=%s",
                    runtime.room_code,
                    call.verdict,
                    call.marker,
                    new_state.phase.value,
                    room_code=runtime.room_code,
                    verdict=call.verdict,
                    phase=new_state.phase.value,
                )
            except IllegalMove as exc:
                event(
                    logger,
                    "ЗАДАЧА",
                    "mp_llm_judge_apply_skip err=%s",
                    str(exc),
                    room_code=runtime.room_code,
                    level=logging.WARNING,
                )
                return
        await runtime.broadcast()
        await _auto_bots(runtime)
    finally:
        async with runtime.lock:
            runtime.set_flag(FLAG_JUDGE, False)


async def _run_ticker(runtime: MatchRuntime) -> None:
    """Э8: газета конца слота в RESULT."""
    async with runtime.lock:
        state = runtime.get_state()
        if state is None:
            return
        if state.phase != Phase.RESULT:
            return
        if state.slot_ticker:
            return
        if runtime.flag(FLAG_TICKER):
            return
        runtime.set_flag(FLAG_TICKER, True)
        snap = state.model_copy(deep=True)

    try:
        try:
            ticker = await wolves_llm.generate_ticker(snap)
        except Exception as exc:  # noqa: BLE001
            event(
                logger,
                "ЗАДАЧА",
                "mp_llm_ticker_crash err=%s",
                str(exc),
                room_code=runtime.room_code,
                level=logging.WARNING,
            )
            ticker = wolves_llm.FALLBACK_TICKER

        async with runtime.lock:
            runtime.set_flag(FLAG_TICKER, False)
            state = runtime.get_state()
            if state is None or state.slot_index != snap.slot_index:
                return
            # RESULT длится 6 с, а газета приезжает позже — раньше её результат просто
            # выбрасывался проверкой фазы, и заголовок не видел никто. Принимаем, пока идёт
            # тот же слот: на экране «Передышки» лента как раз к месту.
            if state.phase not in (Phase.RESULT, Phase.BETWEEN):
                return
            if state.slot_ticker:
                return
            state.slot_ticker = ticker
        await runtime.broadcast()
    finally:
        async with runtime.lock:
            runtime.set_flag(FLAG_TICKER, False)


async def _run_brief(runtime: MatchRuntime) -> None:
    """Сцена слота: режиссёр объявляет день, пока стол читает бюллетень (Э19.8).

    Ни на что не влияет механически, поэтому и ждать её никто не обязан: приезжает —
    показываем, не приезжает — слот идёт как шёл.
    """
    async with runtime.lock:
        state = runtime.get_state()
        if state is None or state.slot_brief:
            return
        if state.phase not in (Phase.BULLETIN, Phase.PLAY):
            return
        if runtime.flag(FLAG_BRIEF):
            return
        runtime.set_flag(FLAG_BRIEF, True)
        snap = state.model_copy(deep=True)

    try:
        brief = await wolves_llm.generate_brief(snap)
        async with runtime.lock:
            state = runtime.get_state()
            if state is None or state.slot_index != snap.slot_index or state.slot_brief:
                return
            state.slot_brief = brief
        await runtime.broadcast()
    finally:
        async with runtime.lock:
            runtime.set_flag(FLAG_BRIEF, False)


async def _run_barks(runtime: MatchRuntime) -> None:
    """Реакция кандидата-бота на свой штамп: живой выдох вместо тишины под печатью."""
    async with runtime.lock:
        state = runtime.get_state()
        if state is None or runtime.flag(FLAG_BARK):
            return
        if state.phase in (Phase.REVEAL, Phase.ENDED):
            return
        seat_ids = wolves_llm.bot_seat_ids_needing_bark(state)
        if not seat_ids:
            return
        runtime.set_flag(FLAG_BARK, True)
        snap = state.model_copy(deep=True)

    sem = asyncio.Semaphore(MAX_PARALLEL_LLM)

    async def _one(seat_id: str) -> None:
        async with sem:
            text = await wolves_llm.generate_bark(snap, seat_id)
        async with runtime.lock:
            state = runtime.get_state()
            if state is None or state.slot_index != snap.slot_index:
                return
            if seat_id in state.stamp_reactions:
                return
            state.stamp_reactions[seat_id] = text
        await runtime.broadcast()

    try:
        await asyncio.gather(*(_one(sid) for sid in seat_ids), return_exceptions=True)
    finally:
        async with runtime.lock:
            runtime.set_flag(FLAG_BARK, False)
