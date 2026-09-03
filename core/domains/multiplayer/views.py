"""Публичная/личная проекция MatchState для WS (секреты ролей не утекают)."""

from __future__ import annotations

from typing import Any

from core.domains.multiplayer.models import Faction, MatchState, Phase, SeatKind
from core.domains.multiplayer.rules import winner_headline


def project_public(
    state: MatchState,
    *,
    nicks: dict[int, str] | None = None,
) -> dict[str, Any]:
    """Состояние для всех за столом (и зрителей). Без faction/hand/fraud_pair.

    `is_ghost_slot` намеренно не отдаём — иначе оффер на ghost job становится
    тривиальным; citation `ghost_job_offer` остаётся серверным сюрпризом.
    """
    nick_map = nicks or {}
    bulletin = None
    if state.bulletin is not None:
        b = state.bulletin
        bulletin = {
            "id": b.id,
            "day_label": b.day_label,
            "gates": list(b.gates),
            "required_tag": b.required_tag.value if b.required_tag else None,
            "cards_to_play": b.cards_to_play,
            "offer_allowed": b.offer_allowed,
            "face_up": b.face_up,
        }
    event = None
    if state.event is not None:
        event = {"id": state.event.id, "kind": state.event.kind.value, "label": state.event.label}

    revealing = state.phase in (Phase.REVEAL, Phase.ENDED)
    seats: list[dict[str, Any]] = []
    for seat in sorted(state.seats.values(), key=lambda s: (s.kind.value, s.id)):
        played: list[dict[str, str]]
        if state.bulletin and state.bulletin.face_up:
            played = []
            for cid in seat.played:
                card = state.card_by_id.get(cid)
                if card is not None:
                    played.append({"id": card.id, "tag": card.tag.value, "title": card.title})
                else:
                    played.append({"id": cid, "tag": "?", "title": cid})
        else:
            # Рубашкой: только число.
            played = [{"id": cid, "tag": "hidden", "title": "•••"} for cid in seat.played]

        nick: str | None = None
        if seat.is_bot:
            nick = "бот"
        elif seat.account_id is not None:
            nick = nick_map.get(int(seat.account_id))

        row: dict[str, Any] = {
            "id": seat.id,
            "kind": seat.kind.value,
            "public_status": seat.public_status.value,
            "filled": seat.filled,
            "is_bot": seat.is_bot,
            "played": played if seat.kind == SeatKind.CANDIDATE else [],
            "account_id": seat.account_id,
            "nick": nick,
        }
        if revealing and seat.faction is not None:
            row["faction"] = seat.faction.value
            row["revealed_as_wolf"] = seat.revealed_as_wolf
            row["lifetime_stamps"] = [s.value for s in state.lifetime_stamps.get(seat.id, [])]
        seats.append(row)

    out: dict[str, Any] = {
        "seed": state.seed,
        "composition_id": state.composition_id,
        "phase": state.phase.value,
        "slot_index": state.slot_index,
        "slot_count": state.config.slot_count,
        "bulletin": bulletin,
        "event": event,
        "hr_energy": state.hr_energy,
        "hr_energy_max": state.config.hr_energy_max,
        "citations": state.citations,
        "citations_limit": state.config.citations_limit,
        "focus_candidate_id": state.focus_candidate_id,
        "discrepancy_marks": list(state.discrepancy_marks),
        "pending_judge": state.pending_judge,
        "question_chip": state.question_chip,
        "answers": dict(state.answers),
        "stamps_this_slot": {k: v.value for k, v in state.stamps_this_slot.items()},
        "judge_line": state.judge_line,
        "judge_marker": state.judge_marker,
        "slot_ticker": state.slot_ticker,
        "slot_brief": state.slot_brief,
        "stamp_reactions": dict(state.stamp_reactions),
        "winner": state.winner.value if state.winner else None,
        "winner_line": (winner_headline(state.winner) if state.winner is not None else None),
        "seats": seats,
    }
    return out


def project_private(state: MatchState, engine_seat_id: str | None) -> dict[str, Any]:
    """Персональный слой: рука и секретная фракция только своего места."""
    if not engine_seat_id:
        return {"engine_seat_id": None, "hand": [], "faction": None, "sub_role": None}
    seat = state.seats.get(engine_seat_id)
    if seat is None:
        return {"engine_seat_id": engine_seat_id, "hand": [], "faction": None, "sub_role": None}

    hand = []
    for cid in seat.hand:
        card = state.card_by_id.get(cid)
        if card is not None:
            hand.append({"id": card.id, "tag": card.tag.value, "title": card.title})

    faction = seat.faction.value if seat.faction is not None else None
    # Волки видят своих (social deduction) — только id других волков, не руки.
    pack_mates: list[str] = []
    if seat.faction == Faction.WOLF:
        pack_mates = [
            s.id
            for s in state.seats.values()
            if s.faction == Faction.WOLF and s.id != seat.id and s.filled
        ]

    return {
        "engine_seat_id": engine_seat_id,
        "hand": hand,
        "faction": faction,
        "sub_role": seat.sub_role.value if seat.sub_role else None,
        "pack_mates": pack_mates,
    }
