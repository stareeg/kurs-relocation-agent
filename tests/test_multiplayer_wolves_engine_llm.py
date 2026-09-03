"""Асинхронные шаги движка: круг реплик, прогрев судьи, газета, реакции, сцена слота.

Проверяем не тексты (это `test_multiplayer_wolves_llm.py`), а расписание вызовов: что LLM не
стоит на критическом пути фазы, что параллельность ограничена и что сбой модели не меняет
исход партии.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from core.domains.multiplayer import wolves_engine, wolves_llm
from core.domains.multiplayer.models import MatchConfig, MatchState, Phase, Stamp
from core.domains.multiplayer.rules import start_match


class FakeRuntime:
    """`MatchRuntime` без сокетов и БД: считает кадры и рассылки."""

    room_code = "TEST01"

    def __init__(self, state: MatchState) -> None:
        self._state: MatchState | None = state
        self._lock = asyncio.Lock()
        self._flags: dict[str, bool] = {}
        self._memo: dict[str, Any] = {}
        self.frames: list[dict[str, Any]] = []
        self.broadcasts = 0
        self.rearmed = 0
        self.phases: list[str] = []
        self.paused = False

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    def get_state(self) -> MatchState | None:
        return self._state

    def set_state(self, state: MatchState) -> None:
        self._state = state

    def flag(self, name: str) -> bool:
        return self._flags.get(name, False)

    def set_flag(self, name: str, value: bool) -> None:
        self._flags[name] = value

    def memo(self, name: str) -> Any:
        return self._memo.get(name)

    def set_memo(self, name: str, value: Any) -> None:
        self._memo[name] = value

    async def broadcast(self) -> None:
        self.broadcasts += 1

    async def send_frame(self, payload: Any) -> None:
        self.frames.append(dict(payload))

    def rearm_timer(self) -> None:
        self.rearmed += 1

    async def note_phase(self, phase: str) -> None:
        self.phases.append(phase)


def _table(seed: int = 5, *, candidates: int = 4) -> MatchState:
    state = start_match(seed, config=MatchConfig(candidate_count=candidates))
    for seat in state.seats.values():
        if seat.kind.value == "candidate":
            seat.is_bot = True
    return state


def _lines_table(seed: int = 5, *, candidates: int = 4) -> MatchState:
    state = _table(seed, candidates=candidates)
    state.phase = Phase.LINES
    state.question_chip = "q_stack"
    return state


@pytest.mark.asyncio
async def test_bot_round_runs_in_parallel_under_a_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Последовательный круг не помещался в фазу: 15 с на бота при `lines` в 30 с (Э20.3).

    Заодно стережём потолок одновременности: шесть параллельных запросов в одного провайдера
    ловят upstream 429, и «параллельно» превращается в «половина ушла в заглушку».
    """
    state = _lines_table(candidates=5)
    runtime = FakeRuntime(state)
    live = 0
    peak = 0

    async def fake_stream(snap, seat_id, *, on_delta=None, llm=None):  # noqa: ANN001
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        try:
            if on_delta is not None:
                await on_delta(f"{seat_id} гово")
                await on_delta(f"{seat_id} говорит по делу")
            await asyncio.sleep(0)
            return f"{seat_id} говорит по делу"
        finally:
            live -= 1

    monkeypatch.setattr(wolves_llm, "stream_bot_line", fake_stream)

    await wolves_engine._auto_bots(runtime)

    answered = runtime.get_state().answers
    assert set(answered) == {"c0", "c1", "c2", "c3", "c4"}
    assert peak > 1, "круг снова последовательный — фаза его не переживёт"
    assert peak <= wolves_engine.MAX_PARALLEL_LLM
    deltas = [f for f in runtime.frames if f["type"] == "line_delta"]
    assert {f["seat_id"] for f in deltas} == set(answered), "стрим доехал не до всех мест"


@pytest.mark.asyncio
async def test_bot_lines_land_one_by_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ответ применяется сразу, а не пачкой в конце круга: за столом говорят по очереди."""
    state = _lines_table(candidates=3)
    runtime = FakeRuntime(state)
    seen: list[int] = []

    async def fake_stream(snap, seat_id, *, on_delta=None, llm=None):  # noqa: ANN001
        await asyncio.sleep(0.01 * (1 + int(seat_id[1:])))
        seen.append(len(runtime.get_state().answers))
        return f"реплика {seat_id}"

    monkeypatch.setattr(wolves_llm, "stream_bot_line", fake_stream)
    await wolves_engine._auto_bots(runtime)

    assert seen == sorted(seen), "ответы должны появляться по мере готовности"
    assert runtime.broadcasts >= 3, "каждая реплика — своя рассылка, иначе стол молчит до конца"


@pytest.mark.asyncio
async def test_judge_is_warmed_on_claim_and_reused_in_judge_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Э20.4: судью зовём в момент иска (INSPECT), а не на входе в JUDGE."""
    state = _table(6)
    state.phase = Phase.INSPECT
    state.focus_candidate_id = "c0"
    state.discrepancy_marks = ["act_fake", "ip_surname"]
    state.seats["c0"].fraud_pair = ("act_fake", "ip_surname")
    state.pending_judge = True
    runtime = FakeRuntime(state)
    calls = 0

    async def fake_judge(snap, *, llm=None):  # noqa: ANN001
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return wolves_llm.JudgeCall("confirm", "Печать плывёт. Вскрыт.", "act_fake")

    monkeypatch.setattr(wolves_llm, "generate_judge", fake_judge)

    wolves_engine._warm_judge(runtime)
    assert isinstance(runtime.memo(wolves_engine.MEMO_JUDGE_TASK), asyncio.Task)

    # Фаза сменилась — суд забирает уже готовый ответ, второго вызова быть не должно.
    state.phase = Phase.JUDGE
    await wolves_engine._run_judge(runtime)

    assert calls == 1, "судью позвали дважды — прогрев не сработал"
    assert runtime.get_state().judge_line == "Печать плывёт. Вскрыт."
    assert runtime.get_state().judge_marker == "act_fake", "улику показываем игроку в кабинке"
    assert runtime.get_state().phase == Phase.LINES


@pytest.mark.asyncio
async def test_warm_judge_from_another_claim_is_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Хрюша передумала и подала иск заново — чужой прогретый текст в суд попасть не должен."""
    state = _table(7)
    state.phase = Phase.INSPECT
    state.focus_candidate_id = "c0"
    state.discrepancy_marks = ["act_fake", "ip_surname"]
    state.pending_judge = True
    runtime = FakeRuntime(state)

    async def fake_judge(snap, *, llm=None):  # noqa: ANN001
        return wolves_llm.JudgeCall("reject", f"иск по {'+'.join(snap.discrepancy_marks)}", None)

    monkeypatch.setattr(wolves_llm, "generate_judge", fake_judge)
    wolves_engine._warm_judge(runtime)

    state.discrepancy_marks = ["dates_mismatch", "team_size"]
    state.phase = Phase.JUDGE
    await wolves_engine._run_judge(runtime)

    assert runtime.get_state().judge_line == "иск по dates_mismatch+team_size"


@pytest.mark.asyncio
async def test_judge_crash_keeps_the_engine_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    """Сбой LLM не имеет права подарить хрюше выговор за пропущенного волка.

    Раньше здесь стоял жёсткий `verdict = "reject"`: на верном иске это ровно выговор
    «missed_fraud», то есть шаг к проигрышу партии из-за упавшего провайдера.
    """
    state = _table(8)
    state.phase = Phase.JUDGE
    state.focus_candidate_id = "c0"
    state.discrepancy_marks = ["act_fake", "ip_surname"]
    state.seats["c0"].fraud_pair = ("ip_surname", "act_fake")
    state.pending_judge = True
    runtime = FakeRuntime(state)
    citations_before = state.citations

    async def boom(snap, *, llm=None):  # noqa: ANN001
        raise RuntimeError("провайдер лёг")

    monkeypatch.setattr(wolves_llm, "generate_judge", boom)
    await wolves_engine._run_judge(runtime)

    after = runtime.get_state()
    assert after.judge_line == wolves_llm.FALLBACK_JUDGE_LINE
    assert after.citations == citations_before, "верный иск не может стоить выговора"


@pytest.mark.asyncio
async def test_ticker_is_accepted_after_result_phase_ends(monkeypatch: pytest.MonkeyPatch) -> None:
    """RESULT длится 6 с, газета приезжает позже — раньше её просто выбрасывали."""
    state = _table(9)
    state.phase = Phase.RESULT
    runtime = FakeRuntime(state)

    async def slow_ticker(snap, *, llm=None):  # noqa: ANN001
        # Пока модель думает, стол ушёл на передышку.
        runtime.get_state().phase = Phase.BETWEEN
        return "Четыре отказа за день. Рынок стабилен."

    monkeypatch.setattr(wolves_llm, "generate_ticker", slow_ticker)
    await wolves_engine._run_ticker(runtime)

    assert runtime.get_state().slot_ticker == "Четыре отказа за день. Рынок стабилен."


@pytest.mark.asyncio
async def test_ticker_from_previous_slot_is_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _table(10)
    state.phase = Phase.RESULT
    runtime = FakeRuntime(state)

    async def slow_ticker(snap, *, llm=None):  # noqa: ANN001
        runtime.get_state().slot_index += 1
        return "Заголовок из прошлого слота"

    monkeypatch.setattr(wolves_llm, "generate_ticker", slow_ticker)
    await wolves_engine._run_ticker(runtime)

    assert runtime.get_state().slot_ticker is None


@pytest.mark.asyncio
async def test_barks_fill_reactions_for_stamped_bots(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _table(11)
    state.phase = Phase.STAMP
    state.stamps_this_slot = {"c0": Stamp.REJECT, "c1": Stamp.OFFER}
    runtime = FakeRuntime(state)

    async def fake_bark(snap, seat_id, *, llm=None):  # noqa: ANN001
        return f"{seat_id}: ну и ладно"

    monkeypatch.setattr(wolves_llm, "generate_bark", fake_bark)
    await wolves_engine._run_barks(runtime)

    assert set(runtime.get_state().stamp_reactions) == {"c0", "c1"}


@pytest.mark.asyncio
async def test_brief_announces_the_slot_without_blocking(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _table(12)
    state.phase = Phase.BULLETIN
    runtime = FakeRuntime(state)

    async def fake_brief(snap, *, llm=None):  # noqa: ANN001
        return "ATS рубит всех без стека. Разговоров сегодня будет мало."

    monkeypatch.setattr(wolves_llm, "generate_brief", fake_brief)
    await wolves_engine._run_brief(runtime)

    assert runtime.get_state().slot_brief is not None
    # Сцена — украшение: повторный шаг не переспрашивает модель.
    await wolves_engine._run_brief(runtime)
    assert runtime.broadcasts == 1
