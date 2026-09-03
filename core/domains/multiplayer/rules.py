"""Rule engine «Хрюши и Волки»: чистая логика фаз/победы без I/O и LLM.

`start_match(seed)` → `apply(state, intent)` → `is_terminal` / `winners`.
Секреты ролей живут в `MatchState`; клиенту потом отдаётся public-проекция (Э5).
"""

from __future__ import annotations

import random
from typing import Any

from core.domains.multiplayer.deck import (
    CARD_BY_ID,
    QUESTION_CHIPS,
    apply_event_to_bulletin,
    build_candidate_seats,
    card_tags,
    clamp_wolf_count,
    deal_hand,
    empty_candidate_seat,
    pick_bulletin,
    pick_event,
    pick_ghost_slots,
    pick_role_composition,
    shuffled_deck,
)
from core.domains.multiplayer.models import (
    AckBulletin,
    AdvancePhase,
    AnswerLine,
    AskQuestion,
    BeginNextSlot,
    Faction,
    FocusCandidate,
    IllegalMove,
    MarkDiscrepancy,
    MatchConfig,
    MatchState,
    MidJoin,
    Phase,
    PlayCards,
    PublicStatus,
    ResolveJudge,
    RuleEvent,
    Seat,
    SeatKind,
    Stamp,
    StampCandidate,
    SubRole,
    TimeoutPhase,
    Winner,
)

HR_SEAT_ID = "hr"

# Газетная строка после Reveal (§4.4) — без LLM.
WINNER_HEADLINES: dict[Winner, str] = {
    Winner.WOLVES: "Волки в штате. Бюджет ушёл в пасть.",
    Winner.HUMANS: "Стая отсеяна. Найм жив.",
    Winner.FREEZE: "Бюджет сгорел. Рынок победил всех.",
}


def winner_headline(winner: Winner) -> str:
    return WINNER_HEADLINES[winner]


def start_match(
    seed: int,
    *,
    config: MatchConfig | None = None,
    leave_seat_empty: str | None = None,
) -> MatchState:
    """Новая партия: роли, руки, бюллетень слота 0.

    `leave_seat_empty` — id кандидата без игрока (для тестов mid-join), напр. ``c3``.
    Состав ролей (Э12) берётся из пула по seed; `config.wolf_count` форсит число волков.
    """
    cfg = config or MatchConfig()
    if cfg.candidate_count < 2:
        raise ValueError("нужно ≥2 кандидатов")

    rng = random.Random(seed)
    composition = pick_role_composition(rng)
    if cfg.wolf_count is None:
        wolf_count = clamp_wolf_count(composition.wolf_count, cfg.candidate_count)
    else:
        wolf_count = cfg.wolf_count
    if wolf_count < 1 or wolf_count >= cfg.candidate_count:
        raise ValueError("волков должно быть от 1 до candidate_count-1")

    deck = shuffled_deck(rng)
    seats = build_candidate_seats(
        rng,
        candidate_count=cfg.candidate_count,
        wolf_count=wolf_count,
        hand_size=cfg.hand_size,
        deck=deck,
        composition=composition,
    )
    if leave_seat_empty is not None:
        if leave_seat_empty not in seats:
            raise ValueError(f"нет места {leave_seat_empty}")
        # Нельзя оставлять пустым единственного волка — перекинем фракцию.
        empty = seats[leave_seat_empty]
        if empty.faction == Faction.WOLF:
            human = next(s for s in seats.values() if s.faction == Faction.HUMAN and s.filled)
            human.faction = Faction.WOLF
            human.fraud_pair = empty.fraud_pair
            human.is_strong = False
        seats[leave_seat_empty] = empty_candidate_seat(leave_seat_empty)

    seats[HR_SEAT_ID] = Seat(id=HR_SEAT_ID, kind=SeatKind.HR, is_bot=False, filled=True)
    ghosts = pick_ghost_slots(rng, cfg.slot_count)

    state = MatchState(
        seed=seed,
        config=cfg,
        phase=Phase.BULLETIN,
        slot_index=0,
        seats=seats,
        deck_order=deck,
        card_by_id=dict(CARD_BY_ID),
        hr_energy=cfg.hr_energy_max,
        ghost_slot_indices=ghosts,
        lifetime_stamps={cid: [] for cid in seats if seats[cid].kind == SeatKind.CANDIDATE},
        composition_id=composition.id,
    )
    return _open_slot(state, rng)


def apply(state: MatchState, intent: Any) -> tuple[MatchState, list[RuleEvent]]:
    """Применить интент; вернуть новый state + события. Не мутирует вход."""
    if is_terminal(state) and state.phase == Phase.ENDED:
        raise IllegalMove("партия уже закончена")

    t = getattr(intent, "type", None)
    handlers = {
        "ack_bulletin": _ack_bulletin,
        "play_cards": _play_cards,
        "focus_candidate": _focus_candidate,
        "mark_discrepancy": _mark_discrepancy,
        "advance_phase": _advance_phase,
        "ask_question": _ask_question,
        "answer_line": _answer_line,
        "stamp_candidate": _stamp_candidate,
        "resolve_judge": _resolve_judge,
        "timeout_phase": _timeout_phase,
        "mid_join": _mid_join,
        "begin_next_slot": _begin_next_slot,
    }
    if t not in handlers:
        raise IllegalMove(f"неизвестный интент {t!r}")
    new_state, events = handlers[t](state.model_copy(deep=True), intent)
    return new_state, events


def is_terminal(state: MatchState) -> bool:
    return state.phase in (Phase.REVEAL, Phase.ENDED) or state.winner is not None


def winners(state: MatchState) -> Winner | None:
    """Текущий победитель (после подсчёта) или None, если партия ещё идёт."""
    return state.winner


def compute_winner(state: MatchState) -> Winner:
    """Подсчёт по §4.4 плана (после всех слотов или досрочных выговоров)."""
    if state.citations >= state.config.citations_limit:
        return Winner.WOLVES

    candidates = [
        s
        for s in state.seats.values()
        if s.kind == SeatKind.CANDIDATE and s.filled and s.faction is not None
    ]
    wolves = [s for s in candidates if s.faction == Faction.WOLF]
    humans = [s for s in candidates if s.faction == Faction.HUMAN]

    def _ever(seat: Seat, stamp: Stamp) -> bool:
        return stamp in state.lifetime_stamps.get(seat.id, [])

    wolf_offer = any(_ever(w, Stamp.OFFER) for w in wolves)
    if wolf_offer:
        return Winner.WOLVES

    wolves_interview_alive = [
        w
        for w in wolves
        if _ever(w, Stamp.INTERVIEW) and not w.revealed_as_wolf and not _ever(w, Stamp.REJECT)
    ]
    if len(wolves_interview_alive) >= 2:
        return Winner.WOLVES

    all_wolves_stopped = all(_ever(w, Stamp.REJECT) or w.revealed_as_wolf for w in wolves)
    human_hire = any(_ever(h, Stamp.OFFER) or _ever(h, Stamp.INTERVIEW) for h in humans)
    if all_wolves_stopped and human_hire and not wolf_offer:
        return Winner.HUMANS

    return Winner.FREEZE


# --- внутренности ---------------------------------------------------------------


def _rng(state: MatchState) -> random.Random:
    # Слот+фаза в сиде — чтобы mid-join/добор не совпадали с стартовым deal.
    return random.Random(f"{state.seed}:{state.slot_index}:{state.phase}")


def _open_slot(state: MatchState, rng: random.Random) -> MatchState:
    bulletin = pick_bulletin(rng, state.slot_index)
    event = pick_event(rng, bulletin)
    bulletin = apply_event_to_bulletin(bulletin, event)
    state.bulletin = bulletin
    state.event = event
    state.phase = Phase.BULLETIN
    state.focus_candidate_id = None
    state.discrepancy_marks = []
    state.pending_judge = False
    state.question_chip = None
    state.answers = {}
    state.stamps_this_slot = {}
    state.judge_line = None
    state.judge_marker = None
    state.slot_ticker = None
    state.slot_brief = None
    state.stamp_reactions = {}
    for seat in state.seats.values():
        if seat.kind == SeatKind.CANDIDATE and seat.filled:
            seat.played = []
            # Между слотами статусы сбрасываем к waiting, кроме финальных.
            if seat.public_status not in (PublicStatus.REJECTED, PublicStatus.OFFER) and (
                state.slot_index == 0
                or seat.public_status
                in (PublicStatus.WAITING, PublicStatus.INTERVIEW, PublicStatus.GHOSTED)
            ):
                seat.public_status = PublicStatus.WAITING
            # Добор руки до hand_size.
            need = state.config.hand_size - len(seat.hand)
            if need > 0:
                seat.hand.extend(deal_hand(rng, state.deck_order, n=need))
    return state


def _candidates(state: MatchState, *, filled_only: bool = True) -> list[Seat]:
    out = [
        s
        for s in state.seats.values()
        if s.kind == SeatKind.CANDIDATE and (s.filled if filled_only else True)
    ]
    return sorted(out, key=lambda s: s.id)


def _require_phase(state: MatchState, *phases: Phase) -> None:
    if state.phase not in phases:
        raise IllegalMove(f"фаза {state.phase}, ожидали {[p.value for p in phases]}")


def _require_hr(actor: str) -> None:
    if actor != HR_SEAT_ID:
        raise IllegalMove("только хрюша")


def _ack_bulletin(state: MatchState, intent: AckBulletin) -> tuple[MatchState, list[RuleEvent]]:
    _require_phase(state, Phase.BULLETIN)
    _require_hr(intent.actor_seat_id)
    state.phase = Phase.PLAY
    return state, [RuleEvent(type="phase", detail="play")]


def _play_cards(state: MatchState, intent: PlayCards) -> tuple[MatchState, list[RuleEvent]]:
    _require_phase(state, Phase.PLAY)
    seat = state.seats.get(intent.actor_seat_id)
    if seat is None or seat.kind != SeatKind.CANDIDATE or not seat.filled:
        raise IllegalMove("нет такого кандидата")
    if seat.played:
        raise IllegalMove("карты уже выложены")
    bulletin = state.bulletin
    if bulletin is None:
        raise IllegalMove("нет бюллетеня")
    need = bulletin.cards_to_play
    if len(intent.card_ids) != need:
        raise IllegalMove(f"нужно ровно {need} карт")
    if len(set(intent.card_ids)) != len(intent.card_ids):
        raise IllegalMove("дубликаты карт")
    for cid in intent.card_ids:
        if cid not in seat.hand:
            raise IllegalMove(f"карты {cid} нет в руке")
    for cid in intent.card_ids:
        seat.hand.remove(cid)
    seat.played = list(intent.card_ids)
    events = [RuleEvent(type="cards_played", detail=seat.id)]

    # Все заполненные кандидаты выложили?
    pending = [s for s in _candidates(state) if not s.played]
    if not pending:
        state, more = _resolve_ats_and_to_inspect(state)
        events.extend(more)
    return state, events


def _resolve_ats_and_to_inspect(state: MatchState) -> tuple[MatchState, list[RuleEvent]]:
    events: list[RuleEvent] = []
    bulletin = state.bulletin
    assert bulletin is not None
    req = bulletin.required_tag
    for seat in _candidates(state):
        tags = card_tags(seat.played)
        if req is not None and req not in tags:
            seat.public_status = PublicStatus.REJECTED
            state.stamps_this_slot[seat.id] = Stamp.REJECT
            state.lifetime_stamps.setdefault(seat.id, []).append(Stamp.REJECT)
            events.append(RuleEvent(type="ats_knockout", detail=seat.id))
    state.phase = Phase.INSPECT
    # Фокус — первый не отсеянный.
    alive = [s for s in _candidates(state) if s.id not in state.stamps_this_slot]
    state.focus_candidate_id = alive[0].id if alive else None
    events.append(RuleEvent(type="phase", detail="inspect"))
    return state, events


def _focus_candidate(
    state: MatchState, intent: FocusCandidate
) -> tuple[MatchState, list[RuleEvent]]:
    _require_phase(state, Phase.INSPECT, Phase.LINES, Phase.STAMP)
    _require_hr(intent.actor_seat_id)
    seat = state.seats.get(intent.candidate_id)
    if seat is None or seat.kind != SeatKind.CANDIDATE or not seat.filled:
        raise IllegalMove("кандидат не найден")
    if intent.candidate_id in state.stamps_this_slot:
        raise IllegalMove("кандидат уже закрыт в этом слоте")
    state.focus_candidate_id = intent.candidate_id
    state.discrepancy_marks = []
    return state, [RuleEvent(type="focus", detail=intent.candidate_id)]


def _mark_discrepancy(
    state: MatchState, intent: MarkDiscrepancy
) -> tuple[MatchState, list[RuleEvent]]:
    _require_phase(state, Phase.INSPECT)
    _require_hr(intent.actor_seat_id)
    if state.hr_energy <= 0:
        raise IllegalMove("нет энергии")
    if len(intent.markers) != 2 or len(set(intent.markers)) != 2:
        raise IllegalMove("нужно ровно 2 разных маркера")
    if not state.focus_candidate_id:
        raise IllegalMove("сначала выберите кандидата")
    state.hr_energy -= 1
    state.discrepancy_marks = list(intent.markers)
    state.pending_judge = True
    return state, [RuleEvent(type="discrepancy_filed", detail=",".join(intent.markers))]


def _advance_phase(state: MatchState, intent: AdvancePhase) -> tuple[MatchState, list[RuleEvent]]:
    _require_hr(intent.actor_seat_id)
    if state.phase == Phase.INSPECT:
        if state.pending_judge:
            state.phase = Phase.JUDGE
            return state, [RuleEvent(type="phase", detail="judge")]
        state.phase = Phase.LINES
        return state, [RuleEvent(type="phase", detail="lines")]
    if state.phase == Phase.LINES:
        state.phase = Phase.STAMP
        return state, [RuleEvent(type="phase", detail="stamp")]
    if state.phase == Phase.RESULT:
        return _finish_result(state)
    raise IllegalMove(f"advance из фазы {state.phase} нельзя")


def _ask_question(state: MatchState, intent: AskQuestion) -> tuple[MatchState, list[RuleEvent]]:
    _require_phase(state, Phase.LINES)
    _require_hr(intent.actor_seat_id)
    if intent.chip_id not in QUESTION_CHIPS:
        raise IllegalMove("неизвестный вопрос-чип")
    state.question_chip = intent.chip_id
    state.answers = {}
    return state, [RuleEvent(type="question", detail=intent.chip_id)]


def _answer_line(state: MatchState, intent: AnswerLine) -> tuple[MatchState, list[RuleEvent]]:
    _require_phase(state, Phase.LINES)
    if not state.question_chip:
        raise IllegalMove("сначала вопрос хрюши")
    seat = state.seats.get(intent.actor_seat_id)
    if seat is None or seat.kind != SeatKind.CANDIDATE or not seat.filled:
        raise IllegalMove("нет кандидата")
    if seat.id in state.stamps_this_slot:
        raise IllegalMove("кандидат уже закрыт")
    text = intent.text.strip()
    if not text:
        raise IllegalMove("пустой ответ")
    if len(text) > 80:
        raise IllegalMove("ответ >80 символов")
    state.answers[seat.id] = text
    return state, [RuleEvent(type="answer", detail=seat.id)]


def _stamp_candidate(
    state: MatchState, intent: StampCandidate
) -> tuple[MatchState, list[RuleEvent]]:
    _require_phase(state, Phase.STAMP)
    _require_hr(intent.actor_seat_id)
    seat = state.seats.get(intent.candidate_id)
    if seat is None or seat.kind != SeatKind.CANDIDATE or not seat.filled:
        raise IllegalMove("нет кандидата")
    if intent.candidate_id in state.stamps_this_slot:
        raise IllegalMove("уже штампован")
    bulletin = state.bulletin
    assert bulletin is not None

    stamp = intent.stamp
    if stamp == Stamp.OFFER and not bulletin.offer_allowed:
        raise IllegalMove("оффер закрыт бюллетенем/событием")
    if stamp == Stamp.PROBE:
        if state.hr_energy <= 0:
            raise IllegalMove("нет энергии на проверку")
        state.hr_energy -= 1
        # Проверка: если есть fraud_pair — волк/фрод вскрывается.
        if seat.fraud_pair is not None:
            seat.revealed_as_wolf = seat.faction == Faction.WOLF
            stamp = Stamp.REJECT
            events = [RuleEvent(type="probe_caught", detail=seat.id)]
        else:
            # Чисто — дорогая проверка впустую, статус interview-light.
            stamp = Stamp.INTERVIEW
            events = [RuleEvent(type="probe_clean", detail=seat.id)]
        return _record_stamp(state, seat, stamp, events)

    events: list[RuleEvent] = []
    # Ложный отказ сильному человеку.
    if stamp == Stamp.REJECT and seat.is_strong and seat.faction == Faction.HUMAN:
        state.citations += 1
        events.append(RuleEvent(type="citation", detail="false_reject_strong"))

    # Оффер на ghost job.
    if stamp == Stamp.OFFER and state.slot_index in state.ghost_slot_indices:
        state.citations += 1
        events.append(RuleEvent(type="citation", detail="ghost_job_offer"))

    state, more = _record_stamp(state, seat, stamp, events)
    events = more

    if state.citations >= state.config.citations_limit:
        state, end_ev = _end_match(state, Winner.WOLVES)
        return state, events + end_ev

    # Все живые кандидаты получили штамп?
    remaining = [s for s in _candidates(state) if s.id not in state.stamps_this_slot]
    if not remaining:
        state.phase = Phase.RESULT
        events.append(RuleEvent(type="phase", detail="result"))
    return state, events


def _record_stamp(
    state: MatchState,
    seat: Seat,
    stamp: Stamp,
    events: list[RuleEvent],
) -> tuple[MatchState, list[RuleEvent]]:
    state.stamps_this_slot[seat.id] = stamp
    state.lifetime_stamps.setdefault(seat.id, []).append(stamp)
    status = {
        Stamp.INTERVIEW: PublicStatus.INTERVIEW,
        Stamp.REJECT: PublicStatus.REJECTED,
        Stamp.OFFER: PublicStatus.OFFER,
        Stamp.PROBE: PublicStatus.INTERVIEW,
    }[stamp]
    seat.public_status = status
    events.append(RuleEvent(type="stamp", detail=f"{seat.id}:{stamp.value}"))
    return state, events


def claim_is_correct(state: MatchState) -> bool:
    """Попала ли хрюша иском: обе отмеченные улики совпали с подделкой кандидата.

    Вынесено из `_resolve_judge`, потому что тот же факт нужен `wolves_llm`: судья-LLM
    озвучивает вердикт, а не выдумывает его (Э19). Подделка (`Seat.fraud_pair`) модели не
    видна и из улик не выводится — раньше модель угадывала исход, который стоит хрюше
    выговора, а трижды — партии.
    """
    focus = state.focus_candidate_id
    if not focus or len(state.discrepancy_marks) != 2:
        return False
    seat = state.seats.get(focus)
    if seat is None or seat.fraud_pair is None:
        return False
    return tuple(sorted(state.discrepancy_marks)) == tuple(sorted(seat.fraud_pair))


def _resolve_judge(state: MatchState, intent: ResolveJudge) -> tuple[MatchState, list[RuleEvent]]:
    _require_phase(state, Phase.JUDGE)
    _require_hr(intent.actor_seat_id)
    if not state.pending_judge or len(state.discrepancy_marks) != 2:
        raise IllegalMove("нет иска")
    focus = state.focus_candidate_id
    if not focus:
        raise IllegalMove("нет фокуса")
    seat = state.seats[focus]
    correct = claim_is_correct(state)
    events: list[RuleEvent] = []

    if intent.verdict == "confirm":
        if correct:
            if seat.faction == Faction.WOLF:
                seat.revealed_as_wolf = True
            events.append(RuleEvent(type="judge_confirm_ok", detail=focus))
        else:
            state.citations += 1
            events.append(RuleEvent(type="citation", detail="false_confirm"))
    else:  # reject иск
        if correct:
            state.citations += 1
            events.append(RuleEvent(type="citation", detail="missed_fraud"))
        else:
            events.append(RuleEvent(type="judge_reject_ok", detail=focus))

    state.pending_judge = False
    state.discrepancy_marks = []

    if state.citations >= state.config.citations_limit:
        state, more = _end_match(state, Winner.WOLVES)
        events.extend(more)
        return state, events

    state.phase = Phase.LINES
    events.append(RuleEvent(type="phase", detail="lines"))
    return state, events


def _timeout_phase(state: MatchState, intent: TimeoutPhase) -> tuple[MatchState, list[RuleEvent]]:
    del intent  # нет полей
    if state.phase == Phase.BULLETIN:
        state.phase = Phase.PLAY
        return state, [RuleEvent(type="phase", detail="play")]
    if state.phase == Phase.STAMP:
        events: list[RuleEvent] = []
        for seat in _candidates(state):
            if seat.id in state.stamps_this_slot:
                continue
            seat.public_status = PublicStatus.GHOSTED
            # Ghosting: не штамп, но слот закрыт без найма.
            events.append(RuleEvent(type="ghosted", detail=seat.id))
            # Штраф энергии рынку — минус энергия хрюши.
            state.hr_energy = max(0, state.hr_energy - 1)
        state.phase = Phase.RESULT
        events.append(RuleEvent(type="phase", detail="result"))
        return state, events
    if state.phase == Phase.INSPECT:
        # Иск подан — на суд (LLM в Э8); иначе сразу к репликам.
        if state.pending_judge:
            state.phase = Phase.JUDGE
            return state, [RuleEvent(type="phase", detail="judge")]
        state.phase = Phase.LINES
        return state, [RuleEvent(type="phase", detail="lines")]
    if state.phase == Phase.LINES:
        state.phase = Phase.STAMP
        return state, [RuleEvent(type="phase", detail="stamp")]
    if state.phase == Phase.JUDGE:
        # LLM не успел (Э8): «судья молчит» = отклонить иск, не стопать партию.
        return _resolve_judge(state, ResolveJudge(verdict="reject"))
    raise IllegalMove(f"timeout в фазе {state.phase} не обрабатывается")


def _mid_join(state: MatchState, intent: MidJoin) -> tuple[MatchState, list[RuleEvent]]:
    _require_phase(state, Phase.BETWEEN)
    seat = state.seats.get(intent.seat_id)
    if seat is None or seat.kind != SeatKind.CANDIDATE:
        raise IllegalMove("нет слота кандидата")
    if seat.filled:
        raise IllegalMove("слот занят")
    # Антиэксплойт: mid-join только human.
    rng = _rng(state)
    hand = deal_hand(rng, state.deck_order, n=state.config.hand_size)
    seat.filled = True
    seat.faction = Faction.HUMAN
    seat.sub_role = SubRole.NONE
    seat.hand = hand
    seat.played = []
    seat.is_bot = intent.as_bot
    seat.account_id = intent.account_id
    seat.fraud_pair = None
    seat.is_strong = False
    seat.public_status = PublicStatus.WAITING
    seat.revealed_as_wolf = False
    state.lifetime_stamps.setdefault(seat.id, [])
    return state, [RuleEvent(type="mid_join", detail=seat.id)]


def _begin_next_slot(
    state: MatchState, intent: BeginNextSlot
) -> tuple[MatchState, list[RuleEvent]]:
    _require_hr(intent.actor_seat_id)
    _require_phase(state, Phase.BETWEEN)
    rng = random.Random(f"{state.seed}:open:{state.slot_index}")
    state = _open_slot(state, rng)
    return state, [RuleEvent(type="slot_opened", detail=str(state.slot_index))]


def _finish_result(state: MatchState) -> tuple[MatchState, list[RuleEvent]]:
    events: list[RuleEvent] = []
    # Досрочная победа волков по офферу волку.
    for seat in _candidates(state):
        stamps = state.lifetime_stamps.get(seat.id, [])
        if seat.faction == Faction.WOLF and Stamp.OFFER in stamps:
            state, more = _end_match(state, Winner.WOLVES)
            return state, events + more

    next_index = state.slot_index + 1
    if next_index >= state.config.slot_count:
        winner = compute_winner(state)
        state, more = _end_match(state, winner)
        return state, events + more

    state.slot_index = next_index
    state.phase = Phase.BETWEEN
    events.append(RuleEvent(type="phase", detail="between"))
    return state, events


def _end_match(state: MatchState, winner: Winner) -> tuple[MatchState, list[RuleEvent]]:
    state.winner = winner
    state.phase = Phase.REVEAL
    # Газета матча: перекрывает ticker слота на экране Reveal.
    state.slot_ticker = winner_headline(winner)
    return state, [
        RuleEvent(type="reveal", detail=winner.value),
        RuleEvent(type="winner", detail=winner.value),
    ]


def end_reveal(state: MatchState) -> MatchState:
    """Перевести reveal → ended (кнопка «в лобби» / перед рематчем)."""
    if state.phase != Phase.REVEAL:
        raise IllegalMove("не reveal")
    state = state.model_copy(deep=True)
    state.phase = Phase.ENDED
    return state


def vacate_candidate_seat(state: MatchState, seat_id: str) -> MatchState:
    """Освободить слот кандидата; если был волк — перекинуть фракцию на живого human.

    Friends-старт (незанятые) и kick (§4.5 / Э10).
    """
    seat = state.seats.get(seat_id)
    if seat is None or seat.kind != SeatKind.CANDIDATE:
        raise ValueError(f"нет кандидата {seat_id}")
    if seat.faction == Faction.WOLF:
        human = next(
            (
                s
                for s in state.seats.values()
                if s.kind == SeatKind.CANDIDATE
                and s.filled
                and s.id != seat_id
                and s.faction == Faction.HUMAN
            ),
            None,
        )
        if human is not None:
            human.faction = Faction.WOLF
            human.fraud_pair = seat.fraud_pair
            human.is_strong = False
    state.seats[seat_id] = empty_candidate_seat(seat_id)
    state.lifetime_stamps[seat_id] = []
    return state


def vacate_unclaimed_candidates(state: MatchState, claimed_ids: set[str]) -> MatchState:
    """Friends-режим: незанятые кандидаты → пустые слоты под mid-join."""
    for seat in list(state.seats.values()):
        if seat.kind != SeatKind.CANDIDATE:
            continue
        if seat.id in claimed_ids:
            continue
        state = vacate_candidate_seat(state, seat.id)
    return state


__all__ = [
    "HR_SEAT_ID",
    "WINNER_HEADLINES",
    "claim_is_correct",
    "start_match",
    "apply",
    "is_terminal",
    "winners",
    "compute_winner",
    "winner_headline",
    "end_reveal",
    "vacate_candidate_seat",
    "vacate_unclaimed_candidates",
]
