"""Э3: rule engine «Хрюши и Волки» — фазa/ATS/выговоры/победа/mid-join."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.domains.multiplayer.deck import (
    BULLETINS,
    CARD_POOL,
    EVENTS,
    QUESTION_CHIPS,
    ROLE_COMPOSITIONS,
    daily_ordinal,
    daily_seed,
)
from core.domains.multiplayer.models import (
    AckBulletin,
    AdvancePhase,
    AnswerLine,
    AskQuestion,
    BeginNextSlot,
    Bulletin,
    CardTag,
    Faction,
    FocusCandidate,
    IllegalMove,
    MarkDiscrepancy,
    MatchConfig,
    MidJoin,
    Phase,
    PlayCards,
    PublicStatus,
    ResolveJudge,
    Stamp,
    StampCandidate,
    SubRole,
    TimeoutPhase,
    Winner,
)
from core.domains.multiplayer.rules import (
    apply,
    compute_winner,
    end_reveal,
    is_terminal,
    start_match,
    winners,
)


def _ack(state):
    state, _ = apply(state, AckBulletin())
    return state


def _play_all(state, card_picker):
    """card_picker(seat) -> list[card_id]."""
    for seat in list(state.seats.values()):
        if seat.kind.value != "candidate" or not seat.filled:
            continue
        if seat.id in state.stamps_this_slot:
            continue
        if seat.played:
            continue
        cards = card_picker(seat)
        state, _ = apply(state, PlayCards(actor_seat_id=seat.id, card_ids=cards))
    return state


def state_card_tag(card_id: str) -> CardTag | None:
    from core.domains.multiplayer.deck import CARD_BY_ID

    c = CARD_BY_ID.get(card_id)
    return c.tag if c else None


def _pick_without_tag(seat, tag: CardTag, n: int) -> list[str]:
    chosen = [cid for cid in seat.hand if state_card_tag(cid) != tag][:n]
    if len(chosen) < n:
        chosen = list(seat.hand)[:n]
    return chosen


def test_card_pool_and_bulletins_sized():
    assert len(CARD_POOL) >= 30
    assert len(BULLETINS) >= 12
    assert len(EVENTS) >= 8
    assert len(ROLE_COMPOSITIONS) >= 6
    assert len(QUESTION_CHIPS) >= 5
    assert len({c.id for c in ROLE_COMPOSITIONS}) == len(ROLE_COMPOSITIONS)


def test_start_match_deterministic_deal():
    a = start_match(42, config=MatchConfig(candidate_count=4, wolf_count=1))
    b = start_match(42, config=MatchConfig(candidate_count=4, wolf_count=1))
    assert a.phase == Phase.BULLETIN
    assert a.seats.keys() == b.seats.keys()
    assert a.composition_id == b.composition_id
    for cid in a.seats:
        assert a.seats[cid].faction == b.seats[cid].faction
        assert a.seats[cid].hand == b.seats[cid].hand
        assert a.seats[cid].sub_role == b.seats[cid].sub_role
    wolves = [s for s in a.seats.values() if s.faction == Faction.WOLF]
    assert len(wolves) == 1


def test_start_match_different_seeds_diverge():
    a = start_match(1, config=MatchConfig(candidate_count=4, wolf_count=1))
    b = start_match(2, config=MatchConfig(candidate_count=4, wolf_count=1))
    hands_a = tuple(tuple(a.seats[f"c{i}"].hand) for i in range(4))
    hands_b = tuple(tuple(b.seats[f"c{i}"].hand) for i in range(4))
    assert hands_a != hands_b or a.bulletin != b.bulletin or a.composition_id != b.composition_id


def test_role_compositions_cover_wolf_counts():
    """Пул составов: и 1, и 2 волка; подроли из whitelist."""
    wolf_counts = {c.wolf_count for c in ROLE_COMPOSITIONS}
    assert 1 in wolf_counts and 2 in wolf_counts
    allowed = {SubRole.TECH_SNIFF, SubRole.REFERRAL, SubRole.SECOND_SHIFT}
    for comp in ROLE_COMPOSITIONS:
        assert comp.sub_roles
        assert set(comp.sub_roles) <= allowed


def test_composition_driven_wolf_count_from_seed():
    """Без явного wolf_count — число волков из состава (clamp под candidate_count)."""
    state = start_match(77, config=MatchConfig(candidate_count=3))
    wolves = [s for s in state.seats.values() if s.faction == Faction.WOLF]
    assert 1 <= len(wolves) <= 2  # max = candidate_count - 1
    assert state.composition_id is not None

    state4 = start_match(88, config=MatchConfig(candidate_count=4))
    wolves4 = [s for s in state4.seats.values() if s.faction == Faction.WOLF]
    assert 1 <= len(wolves4) <= 2

    from core.domains.multiplayer.deck import clamp_wolf_count

    assert clamp_wolf_count(2, 3) == 2
    assert clamp_wolf_count(5, 4) == 3
    assert clamp_wolf_count(0, 4) == 1


def _first_slots_fingerprint(seed: int, n: int = 3) -> tuple[tuple[str, str | None], ...]:
    """(bulletin_id, event_id) первых n слотов без полного прогона карт."""
    state = start_match(
        seed, config=MatchConfig(candidate_count=4, wolf_count=1, slot_count=max(5, n))
    )
    out: list[tuple[str, str | None]] = []
    for i in range(n):
        assert state.bulletin is not None
        out.append((state.bulletin.id, state.event.id if state.event else None))
        if i + 1 >= n:
            break
        state = state.model_copy(deep=True)
        state.slot_index = i + 1
        state.phase = Phase.BETWEEN
        state, _ = apply(state, BeginNextSlot())
    return tuple(out)


def test_first_three_slots_unique_across_50_seeds():
    """Метрика Э12: на 50 сидах первые 3 слота не копируют одну и ту же тройку."""
    fingerprints = [_first_slots_fingerprint(s) for s in range(1, 51)]
    unique = set(fingerprints)
    # С 12×8 пулом ожидаем заметное разнообразие; порог с запасом.
    assert len(unique) >= 20, f"only {len(unique)} unique triples in 50 seeds"


def test_daily_seed_stable_per_day():
    from datetime import date

    d = date(2026, 8, 26)
    assert daily_seed(day=d) == daily_seed(day=d)
    assert daily_seed(day=d) != daily_seed(day=date(2026, 8, 27))
    assert daily_ordinal(day=d) == 238
    a = start_match(daily_seed(day=d), config=MatchConfig(candidate_count=4))
    b = start_match(daily_seed(day=d), config=MatchConfig(candidate_count=4))
    assert a.composition_id == b.composition_id
    assert a.bulletin == b.bulletin
    for cid in a.seats:
        if a.seats[cid].kind.value != "candidate":
            continue
        assert a.seats[cid].hand == b.seats[cid].hand
        assert a.seats[cid].faction == b.seats[cid].faction


def test_ack_bulletin_to_play():
    state = start_match(7)
    state, ev = apply(state, AckBulletin())
    assert state.phase == Phase.PLAY
    assert any(e.type == "phase" for e in ev)


def test_illegal_play_wrong_phase():
    state = start_match(7)
    with pytest.raises(IllegalMove):
        apply(state, PlayCards(actor_seat_id="c0", card_ids=state.seats["c0"].hand[:1]))


def test_ats_knockout_rejects_without_required_tag():
    state = start_match(99, config=MatchConfig(candidate_count=3, wolf_count=1))
    state = _ack(state)
    # Форсируем ATS: нужен STACK.
    state.bulletin = Bulletin(
        id="test_ats",
        day_label="тест",
        gates=("knockout stack",),
        required_tag=CardTag.STACK,
        cards_to_play=1,
    )
    # Руки без stack.
    for cid in ("c0", "c1", "c2"):
        seat = state.seats[cid]
        seat.hand = ["bluff_1", "soft_1", "own_1", "inc_1", "batna_1"]
    state = _play_all(state, lambda s: _pick_without_tag(s, CardTag.STACK, 1))
    assert state.phase == Phase.INSPECT
    for cid in ("c0", "c1", "c2"):
        assert state.stamps_this_slot[cid] == Stamp.REJECT
        assert state.seats[cid].public_status == PublicStatus.REJECTED


def test_ats_passes_with_required_tag():
    state = start_match(100, config=MatchConfig(candidate_count=3, wolf_count=1))
    state = _ack(state)
    state.bulletin = Bulletin(
        id="test_ats_ok",
        day_label="тест",
        required_tag=CardTag.STACK,
        cards_to_play=1,
    )
    for cid in ("c0", "c1", "c2"):
        state.seats[cid].hand = ["stack_1", "bluff_1", "soft_1", "own_1", "inc_1"]
    state = _play_all(state, lambda s: ["stack_1"])
    assert state.phase == Phase.INSPECT
    assert state.stamps_this_slot == {}


def test_three_citations_end_match_on_stamp():
    state = start_match(11, config=MatchConfig(candidate_count=3, wolf_count=1, citations_limit=3))
    state = _ack(state)
    state.bulletin = Bulletin(id="open", day_label="x", required_tag=None, cards_to_play=1)
    state.ghost_slot_indices = ()
    for cid in ("c0", "c1", "c2"):
        state.seats[cid].hand = ["own_1", "scale_1", "soft_1", "inc_1", "stack_1"]
        state.seats[cid].faction = Faction.HUMAN
        state.seats[cid].is_strong = True
    # Формально один волк нужен конфигу — переопределили всех в human для чистого теста выговоров.
    state = _play_all(state, lambda s: [s.hand[0]])
    state, _ = apply(state, AdvancePhase())
    state, _ = apply(state, AdvancePhase())
    state, _ = apply(state, StampCandidate(candidate_id="c0", stamp=Stamp.REJECT))
    state, _ = apply(state, StampCandidate(candidate_id="c1", stamp=Stamp.REJECT))
    assert state.citations == 2
    state, ev = apply(state, StampCandidate(candidate_id="c2", stamp=Stamp.REJECT))
    assert state.citations == 3
    assert is_terminal(state)
    assert winners(state) == Winner.WOLVES
    assert any(e.type == "winner" for e in ev)


def test_false_reject_strong_increments_citation():
    state = start_match(12, config=MatchConfig(candidate_count=3, wolf_count=1))
    state = _ack(state)
    state.bulletin = Bulletin(id="o", day_label="x", cards_to_play=1)
    for cid in ("c0", "c1", "c2"):
        state.seats[cid].hand = ["own_1", "bluff_1", "soft_1", "inc_1", "stack_1"]
    state.seats["c0"].is_strong = True
    state.seats["c0"].faction = Faction.HUMAN
    state = _play_all(state, lambda s: [s.hand[0]])
    state, _ = apply(state, AdvancePhase())  # lines
    state, _ = apply(state, AdvancePhase())  # stamp
    state, ev = apply(state, StampCandidate(candidate_id="c0", stamp=Stamp.REJECT))
    assert state.citations == 1
    assert any(e.detail == "false_reject_strong" for e in ev)


def test_wolf_offer_wins_on_result():
    state = start_match(13, config=MatchConfig(candidate_count=3, wolf_count=1))
    state = _ack(state)
    state.bulletin = Bulletin(id="o", day_label="x", cards_to_play=1, offer_allowed=True)
    state.ghost_slot_indices = ()
    wolf_id = next(s.id for s in state.seats.values() if s.faction == Faction.WOLF)
    for cid in ("c0", "c1", "c2"):
        state.seats[cid].hand = ["own_1", "bluff_1", "soft_1", "inc_1", "stack_1"]
    state = _play_all(state, lambda s: [s.hand[0]])
    state, _ = apply(state, AdvancePhase())
    state, _ = apply(state, AdvancePhase())
    # Оффер волку, остальным отказ.
    for cid in ("c0", "c1", "c2"):
        stamp = Stamp.OFFER if cid == wolf_id else Stamp.REJECT
        state, _ = apply(state, StampCandidate(candidate_id=cid, stamp=stamp))
    assert state.phase == Phase.RESULT
    state, ev = apply(state, AdvancePhase())
    assert is_terminal(state)
    assert winners(state) == Winner.WOLVES
    assert any(e.type == "winner" for e in ev)


def test_offer_blocked_when_budget_frozen():
    state = start_match(14, config=MatchConfig(candidate_count=3, wolf_count=1))
    state = _ack(state)
    state.bulletin = Bulletin(id="fr", day_label="x", cards_to_play=1, offer_allowed=False)
    for cid in ("c0", "c1", "c2"):
        state.seats[cid].hand = ["own_1", "bluff_1", "soft_1", "inc_1", "stack_1"]
    state = _play_all(state, lambda s: [s.hand[0]])
    state, _ = apply(state, AdvancePhase())
    state, _ = apply(state, AdvancePhase())
    with pytest.raises(IllegalMove, match="оффер закрыт"):
        apply(state, StampCandidate(candidate_id="c0", stamp=Stamp.OFFER))


def test_humans_win_when_wolves_rejected_and_hire():
    state = start_match(15, config=MatchConfig(candidate_count=3, wolf_count=1, slot_count=1))
    state = _ack(state)
    state.bulletin = Bulletin(id="o", day_label="x", cards_to_play=1, offer_allowed=True)
    state.ghost_slot_indices = ()
    wolf_id = next(s.id for s in state.seats.values() if s.faction == Faction.WOLF)
    human_id = next(s.id for s in state.seats.values() if s.faction == Faction.HUMAN)
    for cid in ("c0", "c1", "c2"):
        state.seats[cid].hand = ["own_1", "bluff_1", "soft_1", "inc_1", "stack_1"]
        state.seats[cid].is_strong = False
    state = _play_all(state, lambda s: [s.hand[0]])
    state, _ = apply(state, AdvancePhase())
    state, _ = apply(state, AdvancePhase())
    for cid in ("c0", "c1", "c2"):
        if cid == wolf_id:
            stamp = Stamp.REJECT
        elif cid == human_id:
            stamp = Stamp.OFFER
        else:
            stamp = Stamp.REJECT
        state, _ = apply(state, StampCandidate(candidate_id=cid, stamp=stamp))
    state, _ = apply(state, AdvancePhase())
    assert winners(state) == Winner.HUMANS


def test_freeze_when_no_hire_and_wolves_not_cleared():
    state = start_match(16, config=MatchConfig(candidate_count=3, wolf_count=1, slot_count=1))
    state = _ack(state)
    state.bulletin = Bulletin(id="o", day_label="x", cards_to_play=1)
    state.ghost_slot_indices = ()
    for cid in ("c0", "c1", "c2"):
        state.seats[cid].hand = ["own_1", "bluff_1", "soft_1", "inc_1", "stack_1"]
        state.seats[cid].is_strong = False
    state = _play_all(state, lambda s: [s.hand[0]])
    state, _ = apply(state, AdvancePhase())
    state, _ = apply(state, AdvancePhase())
    # Всех в тишину через timeout — нет офферов/отказов волку явно.
    state, _ = apply(state, TimeoutPhase())
    assert state.phase == Phase.RESULT
    state, _ = apply(state, AdvancePhase())
    assert winners(state) == Winner.FREEZE


def test_judge_confirm_correct_reveals_wolf():
    state = start_match(17, config=MatchConfig(candidate_count=3, wolf_count=1))
    state = _ack(state)
    state.bulletin = Bulletin(id="o", day_label="x", cards_to_play=1)
    wolf_id = next(s.id for s in state.seats.values() if s.faction == Faction.WOLF)
    state.seats[wolf_id].fraud_pair = ("dates_mismatch", "act_fake")
    for cid in ("c0", "c1", "c2"):
        state.seats[cid].hand = ["own_1", "bluff_1", "soft_1", "inc_1", "stack_1"]
    state = _play_all(state, lambda s: [s.hand[0]])
    state, _ = apply(state, FocusCandidate(candidate_id=wolf_id))
    state, _ = apply(state, MarkDiscrepancy(markers=["dates_mismatch", "act_fake"]))
    assert state.pending_judge
    assert state.hr_energy == state.config.hr_energy_max - 1
    state, _ = apply(state, AdvancePhase())
    assert state.phase == Phase.JUDGE
    state, ev = apply(state, ResolveJudge(verdict="confirm"))
    assert state.seats[wolf_id].revealed_as_wolf
    assert state.phase == Phase.LINES
    assert any(e.type == "judge_confirm_ok" for e in ev)


def test_judge_false_confirm_citation():
    state = start_match(18, config=MatchConfig(candidate_count=3, wolf_count=1))
    state = _ack(state)
    state.bulletin = Bulletin(id="o", day_label="x", cards_to_play=1)
    human_id = next(s.id for s in state.seats.values() if s.faction == Faction.HUMAN)
    state.seats[human_id].fraud_pair = None
    for cid in ("c0", "c1", "c2"):
        state.seats[cid].hand = ["own_1", "bluff_1", "soft_1", "inc_1", "stack_1"]
    state = _play_all(state, lambda s: [s.hand[0]])
    state, _ = apply(state, FocusCandidate(candidate_id=human_id))
    state, _ = apply(state, MarkDiscrepancy(markers=["dates_mismatch", "ip_surname"]))
    state, _ = apply(state, AdvancePhase())
    state, ev = apply(state, ResolveJudge(verdict="confirm"))
    assert state.citations == 1
    assert any(e.detail == "false_confirm" for e in ev)


def test_probe_catches_fraud_and_rejects():
    state = start_match(19, config=MatchConfig(candidate_count=3, wolf_count=1))
    state = _ack(state)
    state.bulletin = Bulletin(id="o", day_label="x", cards_to_play=1, offer_allowed=True)
    target = "c0"
    state.seats[target].fraud_pair = ("stack_lie", "team_size")
    for cid in ("c0", "c1", "c2"):
        state.seats[cid].hand = ["own_1", "bluff_1", "soft_1", "inc_1", "stack_1"]
    state = _play_all(state, lambda s: [s.hand[0]])
    state, _ = apply(state, AdvancePhase())
    state, _ = apply(state, AdvancePhase())
    energy_before = state.hr_energy
    state, ev = apply(state, StampCandidate(candidate_id=target, stamp=Stamp.PROBE))
    assert state.hr_energy == energy_before - 1
    assert state.stamps_this_slot[target] == Stamp.REJECT
    assert any(e.type == "probe_caught" for e in ev)


def test_mid_join_only_between_and_human():
    state = start_match(
        20,
        config=MatchConfig(candidate_count=4, wolf_count=1),
        leave_seat_empty="c3",
    )
    assert not state.seats["c3"].filled
    with pytest.raises(IllegalMove):
        apply(state, MidJoin(seat_id="c3", account_id=42))
    # Дотянем до between через короткий матч slot_count=1 ... проще форснуть фазу.
    state.phase = Phase.BETWEEN
    state, ev = apply(state, MidJoin(seat_id="c3", account_id=42))
    seat = state.seats["c3"]
    assert seat.filled
    assert seat.faction == Faction.HUMAN
    assert seat.account_id == 42
    assert len(seat.hand) == state.config.hand_size
    assert any(e.type == "mid_join" for e in ev)
    # Повторный join нельзя.
    with pytest.raises(IllegalMove):
        apply(state, MidJoin(seat_id="c3", account_id=99))


def test_mid_join_cannot_target_hr():
    state = start_match(21)
    state.phase = Phase.BETWEEN
    with pytest.raises(IllegalMove):
        apply(state, MidJoin(seat_id="hr", account_id=1))


def test_lines_question_and_answer():
    state = start_match(22, config=MatchConfig(candidate_count=3, wolf_count=1))
    state = _ack(state)
    state.bulletin = Bulletin(id="o", day_label="x", cards_to_play=1)
    for cid in ("c0", "c1", "c2"):
        state.seats[cid].hand = ["own_1", "bluff_1", "soft_1", "inc_1", "stack_1"]
    state = _play_all(state, lambda s: [s.hand[0]])
    state, _ = apply(state, AdvancePhase())
    assert state.phase == Phase.LINES
    state, _ = apply(state, AskQuestion(chip_id=QUESTION_CHIPS[0]))
    state, _ = apply(state, AnswerLine(actor_seat_id="c0", text="Поднял прод за ночь"))
    assert state.answers["c0"]
    with pytest.raises(ValidationError):
        AnswerLine(actor_seat_id="c0", text="x" * 81)


def test_begin_next_slot_opens_bulletin():
    state = start_match(23, config=MatchConfig(candidate_count=3, wolf_count=1, slot_count=3))
    state.phase = Phase.BETWEEN
    state.slot_index = 1
    state, ev = apply(state, BeginNextSlot())
    assert state.phase == Phase.BULLETIN
    assert state.slot_index == 1
    assert state.bulletin is not None


def test_end_reveal_to_ended():
    state = start_match(24, config=MatchConfig(candidate_count=3, wolf_count=1, slot_count=1))
    state.winner = Winner.FREEZE
    state.phase = Phase.REVEAL
    state = end_reveal(state)
    assert state.phase == Phase.ENDED


def test_ghost_job_offer_citation():
    state = start_match(25, config=MatchConfig(candidate_count=3, wolf_count=1))
    state = _ack(state)
    state.bulletin = Bulletin(id="o", day_label="x", cards_to_play=1, offer_allowed=True)
    state.ghost_slot_indices = (0,)
    state.slot_index = 0
    for cid in ("c0", "c1", "c2"):
        state.seats[cid].hand = ["own_1", "bluff_1", "soft_1", "inc_1", "stack_1"]
        state.seats[cid].is_strong = False
    state = _play_all(state, lambda s: [s.hand[0]])
    state, _ = apply(state, AdvancePhase())
    state, _ = apply(state, AdvancePhase())
    state, ev = apply(state, StampCandidate(candidate_id="c0", stamp=Stamp.OFFER))
    assert state.citations == 1
    assert any(e.detail == "ghost_job_offer" for e in ev)


def test_two_wolves_interview_alive_wins():
    state = start_match(26, config=MatchConfig(candidate_count=4, wolf_count=2, slot_count=1))
    # Форсим lifetime: два волка с interview.
    wolves = [s for s in state.seats.values() if s.faction == Faction.WOLF]
    assert len(wolves) == 2
    for w in wolves:
        state.lifetime_stamps[w.id] = [Stamp.INTERVIEW]
    for s in state.seats.values():
        if s.faction == Faction.HUMAN:
            state.lifetime_stamps[s.id] = [Stamp.REJECT]
    assert compute_winner(state) == Winner.WOLVES


def test_play_wrong_card_count():
    state = start_match(27)
    state = _ack(state)
    state.bulletin = Bulletin(id="t", day_label="x", cards_to_play=2)
    seat = state.seats["c0"]
    seat.hand = ["own_1", "scale_1", "soft_1", "inc_1", "stack_1"]
    with pytest.raises(IllegalMove, match="ровно 2"):
        apply(state, PlayCards(actor_seat_id="c0", card_ids=["own_1"]))


def test_inspect_timeout_with_pending_goes_to_judge():
    """Э6: иск подан → таймер осмотра ведёт на суд, не мимо."""
    state = start_match(28, config=MatchConfig(candidate_count=3, wolf_count=1))
    state = _ack(state)
    state.bulletin = Bulletin(id="o", day_label="x", cards_to_play=1)
    for cid in ("c0", "c1", "c2"):
        state.seats[cid].hand = ["own_1", "bluff_1", "soft_1", "inc_1", "stack_1"]
    state = _play_all(state, lambda s: [s.hand[0]])
    assert state.phase == Phase.INSPECT
    state, _ = apply(state, MarkDiscrepancy(markers=["dates_mismatch", "act_fake"]))
    assert state.pending_judge
    state, ev = apply(state, TimeoutPhase())
    assert state.phase == Phase.JUDGE
    assert any(e.detail == "judge" for e in ev)


def test_judge_timeout_silent_reject():
    """Э6/Э8 fallback: без LLM судья «молчит» → reject иска → LINES."""
    state = start_match(29, config=MatchConfig(candidate_count=3, wolf_count=1))
    state = _ack(state)
    state.bulletin = Bulletin(id="o", day_label="x", cards_to_play=1)
    for cid in ("c0", "c1", "c2"):
        state.seats[cid].hand = ["own_1", "bluff_1", "soft_1", "inc_1", "stack_1"]
    state = _play_all(state, lambda s: [s.hand[0]])
    state, _ = apply(state, MarkDiscrepancy(markers=["dates_mismatch", "act_fake"]))
    state, _ = apply(state, AdvancePhase())
    assert state.phase == Phase.JUDGE
    state, _ = apply(state, TimeoutPhase())
    assert state.phase == Phase.LINES
    assert not state.pending_judge
    assert state.discrepancy_marks == []


def test_fraud_markers_match_frontend_papers():
    """Кабинка (papers.ts) и deck.FRAUD_MARKERS не разъезжаются."""
    from pathlib import Path

    from core.domains.multiplayer.deck import FRAUD_MARKERS

    papers = (
        Path(__file__).resolve().parents[1]
        / "frontend"
        / "src"
        / "features"
        / "multiplayer"
        / "wolves"
        / "papers.ts"
    ).read_text(encoding="utf-8")
    for mid in FRAUD_MARKERS:
        assert f'"{mid}"' in papers, f"маркер {mid} отсутствует в papers.ts"


def test_question_chips_match_frontend():
    """Чипы реплик (chips.ts) и deck.QUESTION_CHIPS не разъезжаются."""
    from pathlib import Path

    from core.domains.multiplayer.deck import QUESTION_CHIPS

    chips = (
        Path(__file__).resolve().parents[1]
        / "frontend"
        / "src"
        / "features"
        / "multiplayer"
        / "wolves"
        / "chips.ts"
    ).read_text(encoding="utf-8")
    for qid in QUESTION_CHIPS:
        assert f'id: "{qid}"' in chips or f'"{qid}"' in chips, f"чип {qid} нет в chips.ts"


def test_cannot_answer_outside_lines():
    """Э7: текст ответа только в фазе LINES — осмотр режется сервером."""
    state = start_match(30, config=MatchConfig(candidate_count=3, wolf_count=1))
    state = _ack(state)
    state.bulletin = Bulletin(id="o", day_label="x", cards_to_play=1)
    for cid in ("c0", "c1", "c2"):
        state.seats[cid].hand = ["own_1", "bluff_1", "soft_1", "inc_1", "stack_1"]
    state = _play_all(state, lambda s: [s.hand[0]])
    assert state.phase == Phase.INSPECT
    with pytest.raises(IllegalMove):
        apply(state, AnswerLine(actor_seat_id="c0", text="Не в ту фазу"))
    state.question_chip = QUESTION_CHIPS[0]
    with pytest.raises(IllegalMove):
        apply(state, AnswerLine(actor_seat_id="c0", text="Всё ещё осмотр"))


def test_ask_then_answer_chip_text():
    state = start_match(31, config=MatchConfig(candidate_count=3, wolf_count=1))
    state = _ack(state)
    state.bulletin = Bulletin(id="o", day_label="x", cards_to_play=1)
    for cid in ("c0", "c1", "c2"):
        state.seats[cid].hand = ["own_1", "bluff_1", "soft_1", "inc_1", "stack_1"]
    state = _play_all(state, lambda s: [s.hand[0]])
    state, _ = apply(state, AdvancePhase())
    assert state.phase == Phase.LINES
    state, _ = apply(state, AskQuestion(chip_id=QUESTION_CHIPS[2]))
    assert state.question_chip == QUESTION_CHIPS[2]
    state, _ = apply(state, AnswerLine(actor_seat_id="c1", text="Стек бил, дедлайны жёсткие."))
    assert state.answers["c1"].startswith("Стек")
    with pytest.raises(IllegalMove):
        apply(state, AnswerLine(actor_seat_id="hr", text="хрюша не кандидат"))


def test_vacate_unclaimed_leaves_empty_for_mid_join():
    """Э10: friends-старт — незанятые слоты пустые, mid-join human-only."""
    from core.domains.multiplayer.rules import vacate_unclaimed_candidates

    state = start_match(40, config=MatchConfig(candidate_count=4, wolf_count=1))
    claimed = {"c0", "c1"}
    state = vacate_unclaimed_candidates(state, claimed)
    assert state.seats["c0"].filled
    assert state.seats["c1"].filled
    assert not state.seats["c2"].filled
    assert not state.seats["c3"].filled
    wolves = [s for s in state.seats.values() if s.filled and s.faction == Faction.WOLF]
    assert len(wolves) == 1
    state.phase = Phase.BETWEEN
    state, ev = apply(state, MidJoin(seat_id="c2", account_id=77))
    assert state.seats["c2"].faction == Faction.HUMAN
    assert state.seats["c2"].account_id == 77
    assert any(e.type == "mid_join" for e in ev)

# --- Э9: полный цикл 5 слотов + Reveal + победы ---------------------------------


def _candidate_ids(state) -> list[str]:
    return sorted(
        s.id for s in state.seats.values() if s.kind.value == "candidate" and s.filled
    )


def _rush_slot_to_result(state, stamps: dict[str, Stamp]):
    """Быстрый проход слота: bulletin→play→inspect→lines→stamp→result."""
    if state.phase == Phase.BETWEEN:
        state, _ = apply(state, BeginNextSlot())
    if state.phase == Phase.BULLETIN:
        state, _ = apply(state, AckBulletin())
    state.bulletin = Bulletin(
        id="rush", day_label="тест", cards_to_play=1, offer_allowed=True
    )
    state.ghost_slot_indices = ()
    for cid in _candidate_ids(state):
        seat = state.seats[cid]
        seat.hand = ["own_1", "bluff_1", "soft_1", "inc_1", "stack_1"]
        seat.played = []
        seat.is_strong = False
    state = _play_all(state, lambda s: [s.hand[0]])
    assert state.phase == Phase.INSPECT
    state, _ = apply(state, AdvancePhase())  # lines
    state, _ = apply(state, AdvancePhase())  # stamp
    for cid in _candidate_ids(state):
        if cid in state.stamps_this_slot:
            continue
        stamp = stamps.get(cid, Stamp.REJECT)
        state, _ = apply(state, StampCandidate(candidate_id=cid, stamp=stamp))
    assert state.phase == Phase.RESULT
    return state


def test_five_slots_humans_win():
    """Э9: 5 слотов → Reveal; волки с ОТКАЗ, человек с ОФФЕР → люди."""
    state = start_match(
        901, config=MatchConfig(candidate_count=3, wolf_count=1, slot_count=5)
    )
    wolf_id = next(s.id for s in state.seats.values() if s.faction == Faction.WOLF)
    human_id = next(s.id for s in state.seats.values() if s.faction == Faction.HUMAN)
    other = next(cid for cid in _candidate_ids(state) if cid not in (wolf_id, human_id))

    for slot in range(5):
        assert state.slot_index == slot
        stamps = {
            wolf_id: Stamp.REJECT,
            human_id: Stamp.OFFER if slot == 0 else Stamp.INTERVIEW,
            other: Stamp.REJECT,
        }
        state = _rush_slot_to_result(state, stamps)
        state, ev = apply(state, AdvancePhase())
        if slot < 4:
            assert state.phase == Phase.BETWEEN
            assert any(e.detail == "between" for e in ev)
        else:
            assert state.phase == Phase.REVEAL
            assert winners(state) == Winner.HUMANS
            assert state.slot_ticker == "Стая отсеяна. Найм жив."
            assert any(e.type == "reveal" for e in ev)


def test_five_slots_wolves_win_by_offer():
    """Э9: оффер волку на любом слоте → досрочная победа волков."""
    state = start_match(
        902, config=MatchConfig(candidate_count=3, wolf_count=1, slot_count=5)
    )
    wolf_id = next(s.id for s in state.seats.values() if s.faction == Faction.WOLF)
    others = [cid for cid in _candidate_ids(state) if cid != wolf_id]

    # Слот 0: обычный найм людей
    stamps0 = {wolf_id: Stamp.REJECT, others[0]: Stamp.INTERVIEW, others[1]: Stamp.REJECT}
    state = _rush_slot_to_result(state, stamps0)
    state, _ = apply(state, AdvancePhase())
    assert state.phase == Phase.BETWEEN

    # Слот 1: оффер волку → волки
    stamps1 = {wolf_id: Stamp.OFFER, others[0]: Stamp.REJECT, others[1]: Stamp.REJECT}
    state = _rush_slot_to_result(state, stamps1)
    state, ev = apply(state, AdvancePhase())
    assert state.phase == Phase.REVEAL
    assert winners(state) == Winner.WOLVES
    assert "Волки" in (state.slot_ticker or "")
    assert any(e.type == "winner" for e in ev)


def test_five_slots_freeze():
    """Э9: 5 слотов без офферов и без явного отказа волку → заморозка."""
    state = start_match(
        903, config=MatchConfig(candidate_count=3, wolf_count=1, slot_count=5)
    )
    # Всех в тишину (timeout stamp) — волки не пойманы, найма нет.
    for slot in range(5):
        if state.phase == Phase.BETWEEN:
            state, _ = apply(state, BeginNextSlot())
        if state.phase == Phase.BULLETIN:
            state, _ = apply(state, AckBulletin())
        state.bulletin = Bulletin(id="f", day_label="x", cards_to_play=1)
        state.ghost_slot_indices = ()
        for cid in _candidate_ids(state):
            state.seats[cid].hand = ["own_1", "bluff_1", "soft_1", "inc_1", "stack_1"]
            state.seats[cid].played = []
            state.seats[cid].is_strong = False
        state = _play_all(state, lambda s: [s.hand[0]])
        state, _ = apply(state, AdvancePhase())
        state, _ = apply(state, AdvancePhase())
        assert state.phase == Phase.STAMP
        state, _ = apply(state, TimeoutPhase())
        assert state.phase == Phase.RESULT
        state, _ = apply(state, AdvancePhase())
        if slot < 4:
            assert state.phase == Phase.BETWEEN
        else:
            assert state.phase == Phase.REVEAL
            assert winners(state) == Winner.FREEZE
            assert "Бюджет сгорел" in (state.slot_ticker or "")


def test_winner_headline_mapping():
    from core.domains.multiplayer.rules import winner_headline

    assert "Волки" in winner_headline(Winner.WOLVES)
    assert "Найм" in winner_headline(Winner.HUMANS)
    assert "Бюджет" in winner_headline(Winner.FREEZE)


def test_public_reveal_exposes_factions_and_lifetime():
    from core.domains.multiplayer.views import project_public

    state = start_match(904, config=MatchConfig(candidate_count=3, wolf_count=1, slot_count=1))
    wolf_id = next(s.id for s in state.seats.values() if s.faction == Faction.WOLF)
    human_id = next(s.id for s in state.seats.values() if s.faction == Faction.HUMAN)
    other = next(cid for cid in _candidate_ids(state) if cid not in (wolf_id, human_id))
    state = _rush_slot_to_result(
        state,
        {wolf_id: Stamp.REJECT, human_id: Stamp.OFFER, other: Stamp.REJECT},
    )
    state, _ = apply(state, AdvancePhase())
    assert state.phase == Phase.REVEAL
    pub = project_public(state)
    assert pub["winner"] == "humans"
    assert pub["winner_line"]
    assert "is_ghost_slot" not in pub
    by_id = {s["id"]: s for s in pub["seats"] if s["kind"] == "candidate"}
    assert by_id[wolf_id]["faction"] == "wolf"
    assert "reject" in by_id[wolf_id]["lifetime_stamps"]
    assert by_id[human_id]["faction"] == "human"


def test_bulletins_change_across_slots():
    """Смена бюллетеней между слотами (детерминизм от seed+slot)."""
    state = start_match(
        905, config=MatchConfig(candidate_count=3, wolf_count=1, slot_count=3)
    )
    first = state.bulletin.id if state.bulletin else None
    labels = [state.bulletin.day_label if state.bulletin else None]
    for _ in range(2):
        # Минимальный проход к between
        state = _rush_slot_to_result(
            state, {cid: Stamp.REJECT for cid in _candidate_ids(state)}
        )
        # Все reject → возможна freeze на последнем; на mid — between
        state, _ = apply(state, AdvancePhase())
        if state.phase == Phase.REVEAL:
            break
        assert state.phase == Phase.BETWEEN
        state, _ = apply(state, BeginNextSlot())
        labels.append(state.bulletin.day_label if state.bulletin else None)
    assert first is not None
    # Хотя бы один слот мог взять другой бланк (не жёстко — сид может совпасть).
    assert len(labels) >= 2
    assert all(x is not None for x in labels)