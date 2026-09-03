"""Модели «Хрюши и Волки»: состояние матча, интенты, LLM-схемы.

Чистые данные без I/O. Переходы — в `rules.py`, колоды — в `deck.py`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field

# --- LLM structured -------------------------------------------------------------
#
# Схема здесь ровно одна, и это осознанно (Э19.8). Четыре фичи из пяти отдают **одну короткую
# фразу** — там json_schema берёт лишние токены, добавляет отдельный класс отказов (пустой
# content, обрезанный JSON) и запрещает стрим, ничего не давая взамен: строку не с чем
# сверять. Разбор такого ответа — `wolves_llm.sanitize_utterance`.
#
# Суд — другое дело: у его ответа есть **проверяемое поле**, и врать в нём нельзя.


class WolvesJudgeOut(BaseModel):
    """Оглашение вердикта судьёй: реплика + улика, на которую он ссылается.

    **Вердикта здесь нет намеренно.** Прав ли иск, решает `rules.claim_is_correct`, сравнивая
    отмеченные улики с настоящей подделкой кандидата (`Seat.fraud_pair`) — модели эта подделка
    не видна в принципе, и раньше она угадывала исход, который стоит хрюше выговора, а трижды
    — партии (game_redesign.md §2 «Синдром Бога», Э19).

    А `cited_marker` — ровно то, ради чего structured-выход тут и нужен: судья обязан назвать
    **одну из двух поданных улик**, а не третью выдуманную. Значение сверяется с
    `MatchState.discrepancy_marks` (`wolves_llm._checked_marker`): не совпало — поле гасится и
    уходит WARNING, вместо того чтобы подсветить игроку улику, которой в иске не было.
    """

    line: str = Field(
        ...,
        description=(
            "Оглашение вердикта вслух: одна фраза до 16 слов, с опорой на конкретную улику "
            "(даты, печать, число подчинённых). Сухая ирония, без пафоса и морали."
        ),
    )
    cited_marker: str = Field(
        ...,
        description=(
            "id улики из иска, на которую опирается реплика: ровно одно из двух значений, "
            "перечисленных в блоке ИСК. Выдумывать третье нельзя."
        ),
    )


# --- Игровые enums --------------------------------------------------------------


class Phase(StrEnum):
    """Фазы одного слота + межслотовые / финал."""

    BULLETIN = "bulletin"
    PLAY = "play"
    INSPECT = "inspect"
    LINES = "lines"
    STAMP = "stamp"
    JUDGE = "judge"
    RESULT = "result"
    BETWEEN = "between"
    REVEAL = "reveal"
    ENDED = "ended"


class Stamp(StrEnum):
    INTERVIEW = "interview"  # НА СОБЕС
    REJECT = "reject"
    PROBE = "probe"  # НА ПРОВЕРКУ (тратит энергию)
    OFFER = "offer"


class CardTag(StrEnum):
    OWNERSHIP = "ownership"
    SCALE = "scale"
    INCIDENT = "incident"
    SOFT = "soft"
    STACK = "stack"
    BLUFF = "bluff"
    BATNA = "batna"
    SECOND_JOB = "second_job"


class SeatKind(StrEnum):
    HR = "hr"
    CANDIDATE = "candidate"
    SPECTATOR = "spectator"


class Faction(StrEnum):
    WOLF = "wolf"
    HUMAN = "human"


class SubRole(StrEnum):
    NONE = "none"
    TECH_SNIFF = "tech_sniff"
    REFERRAL = "referral"
    SECOND_SHIFT = "second_shift"


class PublicStatus(StrEnum):
    WAITING = "waiting"
    INTERVIEW = "interview"
    REJECTED = "rejected"
    OFFER = "offer"
    GHOSTED = "ghosted"  # хрюша не успела штамп
    SPECTATING = "spectating"


class Winner(StrEnum):
    WOLVES = "wolves"
    HUMANS = "humans"
    FREEZE = "freeze"  # бюджет сгорел / рынок победил всех


class SlotEventKind(StrEnum):
    ATS_KNOCKOUT = "ats_knockout"
    GHOSTING_WAVE = "ghosting_wave"
    BUDGET_FREEZE = "budget_freeze"
    FOUNDER_JOINS = "founder_joins"
    SECURITY_CHECK = "security_check"
    COUNTER_OFFER = "counter_offer"
    REFERRAL_PRESSURE = "referral_pressure"


# --- Карты / бюллетень / событие -----------------------------------------------


class ExperienceCard(BaseModel):
    """Карта опыта в колоде/руке."""

    id: str
    tag: CardTag
    title: str


class Bulletin(BaseModel):
    """Правила слота (жёлтый бланк)."""

    id: str
    day_label: str
    gates: tuple[str, ...] = ()
    required_tag: CardTag | None = None  # ATS knockout
    cards_to_play: int = 1
    offer_allowed: bool = True
    face_up: bool = True


class SlotEvent(BaseModel):
    id: str
    kind: SlotEventKind
    label: str


# --- Сиденья / матч -------------------------------------------------------------


class Seat(BaseModel):
    id: str
    kind: SeatKind
    faction: Faction | None = None
    sub_role: SubRole = SubRole.NONE
    hand: list[str] = Field(default_factory=list)
    played: list[str] = Field(default_factory=list)
    public_status: PublicStatus = PublicStatus.WAITING
    revealed_as_wolf: bool = False
    is_bot: bool = False
    account_id: int | None = None
    # Пара маркеров «правды» для иска несостыковки; None = чистый кандидат.
    fraud_pair: tuple[str, str] | None = None
    # Сильный живой: ложный отказ → выговор (см. rules).
    is_strong: bool = False
    filled: bool = True  # False = пустой слот под mid-join


class RoleComposition(BaseModel):
    """Фиксированный состав ролей на партию (Э12): волки + подроли."""

    id: str
    label: str
    wolf_count: int = Field(ge=1, le=2)
    sub_roles: tuple[SubRole, ...] = ()


class MatchConfig(BaseModel):
    slot_count: int = 5
    candidate_count: int = 2
    # None = wolf_count из ROLE_COMPOSITIONS по seed (Э12).
    wolf_count: int | None = None
    hr_energy_max: int = 5
    citations_limit: int = 3
    hand_size: int = 5


class MatchState(BaseModel):
    """Полное серверное состояние партии (секреты ролей здесь)."""

    seed: int
    config: MatchConfig
    phase: Phase = Phase.BULLETIN
    slot_index: int = 0
    seats: dict[str, Seat] = Field(default_factory=dict)
    deck_order: list[str] = Field(default_factory=list)
    card_by_id: dict[str, ExperienceCard] = Field(default_factory=dict)
    bulletin: Bulletin | None = None
    event: SlotEvent | None = None
    hr_energy: int = 5
    citations: int = 0
    focus_candidate_id: str | None = None
    discrepancy_marks: list[str] = Field(default_factory=list)
    pending_judge: bool = False
    question_chip: str | None = None
    answers: dict[str, str] = Field(default_factory=dict)
    # Кандидат → штамп в текущем слоте (после фазы stamp / knockout).
    stamps_this_slot: dict[str, Stamp] = Field(default_factory=dict)
    # Стенограмма судьи / газета слота (Э8 LLM; не секрет).
    judge_line: str | None = None
    # Улика из иска, на которую сослался судья (проверена движком, не сырой ответ модели).
    judge_marker: str | None = None
    slot_ticker: str | None = None
    # Э19.8, живость: одна строка «что сегодня за день» от режиссёра (объявляется в bulletin)
    # и реакции кандидатов на свой штамп — «кандидат → что сказал, когда печать упала».
    # Ни то, ни другое не влияет на правила: чистый слой речи поверх посчитанного движком.
    slot_brief: str | None = None
    stamp_reactions: dict[str, str] = Field(default_factory=dict)
    ghost_slot_indices: tuple[int, ...] = ()
    winner: Winner | None = None
    # Накопительная статистика к reveal.
    lifetime_stamps: dict[str, list[Stamp]] = Field(default_factory=dict)
    # Э12: id состава ролей, разданного по seed.
    composition_id: str | None = None


class RuleEvent(BaseModel):
    """Событие движка для лога/WS (без LLM)."""

    type: str
    detail: str = ""


# --- Интенты --------------------------------------------------------------------


class AckBulletin(BaseModel):
    type: Literal["ack_bulletin"] = "ack_bulletin"
    actor_seat_id: str = "hr"


class PlayCards(BaseModel):
    type: Literal["play_cards"] = "play_cards"
    actor_seat_id: str
    card_ids: list[str]


class FocusCandidate(BaseModel):
    type: Literal["focus_candidate"] = "focus_candidate"
    actor_seat_id: str = "hr"
    candidate_id: str


class MarkDiscrepancy(BaseModel):
    type: Literal["mark_discrepancy"] = "mark_discrepancy"
    actor_seat_id: str = "hr"
    markers: list[str]  # ровно 2


class AdvancePhase(BaseModel):
    """Хрюша жмёт «далее» (inspect→lines→stamp) или закрывает result."""

    type: Literal["advance_phase"] = "advance_phase"
    actor_seat_id: str = "hr"


class AskQuestion(BaseModel):
    type: Literal["ask_question"] = "ask_question"
    actor_seat_id: str = "hr"
    chip_id: str


class AnswerLine(BaseModel):
    type: Literal["answer_line"] = "answer_line"
    actor_seat_id: str
    text: str = Field(..., max_length=80)


class StampCandidate(BaseModel):
    type: Literal["stamp_candidate"] = "stamp_candidate"
    actor_seat_id: str = "hr"
    candidate_id: str
    stamp: Stamp


class ResolveJudge(BaseModel):
    """Вердикт суда (в проде — из LLM; в тестах — явный)."""

    type: Literal["resolve_judge"] = "resolve_judge"
    actor_seat_id: str = "hr"
    verdict: Literal["confirm", "reject"]


class TimeoutPhase(BaseModel):
    """Таймер фазы истёк (ghosting на stamp)."""

    type: Literal["timeout_phase"] = "timeout_phase"


class MidJoin(BaseModel):
    type: Literal["mid_join"] = "mid_join"
    seat_id: str
    account_id: int | None = None  # None / omitted = бот-добор
    as_bot: bool = False


class BeginNextSlot(BaseModel):
    type: Literal["begin_next_slot"] = "begin_next_slot"
    actor_seat_id: str = "hr"


Intent = Annotated[
    AckBulletin
    | PlayCards
    | FocusCandidate
    | MarkDiscrepancy
    | AdvancePhase
    | AskQuestion
    | AnswerLine
    | StampCandidate
    | ResolveJudge
    | TimeoutPhase
    | MidJoin
    | BeginNextSlot,
    Field(discriminator="type"),
]


class IllegalMove(ValueError):
    """Интент нельзя применить в текущей фазе/состоянии."""


# --- Лобби столов (Э4 REST) -----------------------------------------------------


class RoomMode(StrEnum):
    SOLO = "solo"
    FRIENDS = "friends"


class RoomStatus(StrEnum):
    OPEN = "open"
    PLAYING = "playing"
    CLOSED = "closed"


class JoinAs(StrEnum):
    PLAYER = "player"
    SPECTATOR = "spectator"


class RoomSettings(BaseModel):
    """Настройки стола в jsonb (кандидаты + число слотов партии)."""

    candidate_slots: int = Field(default=2, ge=2, le=6)
    match_slots: int = Field(default=5, ge=4, le=6)
    # Legacy: UI больше не ставит; список/join публичны для всех аккаунтов.
    friends_only: bool = False
    # Э12: ISO-дата «стола дня» → seed от даты; badge «День #N».
    daily_day: str | None = None
    # Ники за столом: account_id → nick (не ФИО). Ключи — строки.
    nicks: dict[str, str] = Field(default_factory=dict)


class RoomSeatView(BaseModel):
    """Публичное сиденье — без role_secret."""

    id: int
    seat_kind: SeatKind
    seat_index: int
    account_id: int | None = None
    role_public: str = "waiting"
    is_bot: bool = False
    nick: str | None = None


class RoomOut(BaseModel):
    """Стол для клиента (список / create / join)."""

    id: int
    code: str
    name: str
    host_account_id: int
    status: RoomStatus
    mode: RoomMode
    has_pin: bool
    phase_label: str = "лобби"
    seats_total: int
    seats_free: int
    seats_taken: int
    candidate_slots: int
    settings: RoomSettings = Field(default_factory=RoomSettings)
    seats: list[RoomSeatView] = Field(default_factory=list)
    my_seat_id: int | None = None
    my_seat_kind: SeatKind | None = None


__all__ = [
    "WolvesJudgeOut",
    "Phase",
    "Stamp",
    "CardTag",
    "SeatKind",
    "Faction",
    "SubRole",
    "PublicStatus",
    "Winner",
    "SlotEventKind",
    "ExperienceCard",
    "Bulletin",
    "SlotEvent",
    "Seat",
    "RoleComposition",
    "MatchConfig",
    "MatchState",
    "RuleEvent",
    "AckBulletin",
    "PlayCards",
    "FocusCandidate",
    "MarkDiscrepancy",
    "AdvancePhase",
    "AskQuestion",
    "AnswerLine",
    "StampCandidate",
    "ResolveJudge",
    "TimeoutPhase",
    "MidJoin",
    "BeginNextSlot",
    "Intent",
    "IllegalMove",
    "RoomMode",
    "RoomStatus",
    "JoinAs",
    "RoomSettings",
    "RoomSeatView",
    "RoomOut",
]
