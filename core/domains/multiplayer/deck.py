"""Колоды и сиды «Хрюши и Волки»: карты, бюллетени, события, раздача ролей.

Всё детерминировано от `random.Random` — один `seed` матча → один deal.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Iterable
from datetime import date

from core.domains.multiplayer.models import (
    Bulletin,
    CardTag,
    ExperienceCard,
    Faction,
    PublicStatus,
    RoleComposition,
    Seat,
    SeatKind,
    SlotEvent,
    SlotEventKind,
    SubRole,
)

# ≥30 карт (план Э12 — задел; Э3 уже наполняет пул).
CARD_POOL: tuple[ExperienceCard, ...] = (
    ExperienceCard(id="own_1", tag=CardTag.OWNERSHIP, title="Тащил с нуля, тимлид был в отпуске"),
    ExperienceCard(id="own_2", tag=CardTag.OWNERSHIP, title="Закрыл эпик без менеджера"),
    ExperienceCard(id="own_3", tag=CardTag.OWNERSHIP, title="Единственный oncall три квартала"),
    ExperienceCard(id="scale_1", tag=CardTag.SCALE, title="Нагрузка ×10, никто не умер"),
    ExperienceCard(id="scale_2", tag=CardTag.SCALE, title="Миллион DAU, пэйджинг молчал"),
    ExperienceCard(id="scale_3", tag=CardTag.SCALE, title="Кластер на три ДЦ без даунтайма"),
    ExperienceCard(id="inc_1", tag=CardTag.INCIDENT, title="Роняли прод в пятницу — поднял"),
    ExperienceCard(id="inc_2", tag=CardTag.INCIDENT, title="Откатил кривой релиз за 12 минут"),
    ExperienceCard(id="inc_3", tag=CardTag.INCIDENT, title="Нашёл утечку до клиента"),
    ExperienceCard(id="soft_1", tag=CardTag.SOFT, title="Погасил конфликт без эскалации в Slack"),
    ExperienceCard(id="soft_2", tag=CardTag.SOFT, title="Свёл продукт и бэкенд за один синк"),
    ExperienceCard(id="soft_3", tag=CardTag.SOFT, title="Вытащил джуна из выгорания"),
    ExperienceCard(id="stack_1", tag=CardTag.STACK, title="Точный стек под JD, без воды"),
    ExperienceCard(id="stack_2", tag=CardTag.STACK, title="1С + PostgreSQL как родные"),
    ExperienceCard(id="stack_3", tag=CardTag.STACK, title="Vue 3 / TS — в проде два года"),
    ExperienceCard(id="stack_4", tag=CardTag.STACK, title="Kafka + Go, не «знаком»"),
    ExperienceCard(id="bluff_1", tag=CardTag.BLUFF, title="Звучит идеально — фактов ноль"),
    ExperienceCard(id="bluff_2", tag=CardTag.BLUFF, title="STAR без единой цифры"),
    ExperienceCard(id="bluff_3", tag=CardTag.BLUFF, title="«Мы» вместо «я», и всё"),
    ExperienceCard(id="bluff_4", tag=CardTag.BLUFF, title="Сгенерил резюме за вечер"),
    ExperienceCard(id="batna_1", tag=CardTag.BATNA, title="У меня другой оффер до пятницы"),
    ExperienceCard(id="batna_2", tag=CardTag.BATNA, title="Контр уже на столе — выше вилка"),
    ExperienceCard(id="batna_3", tag=CardTag.BATNA, title="Hold-out: не ниже верхней"),
    ExperienceCard(id="sec_1", tag=CardTag.SECOND_JOB, title="Стендап в 10 и в 19 — совпало"),
    ExperienceCard(id="sec_2", tag=CardTag.SECOND_JOB, title="Календарь орёт на двух работах"),
    ExperienceCard(id="sec_3", tag=CardTag.SECOND_JOB, title="Камера on — а я на другом созвоне"),
    ExperienceCard(id="own_4", tag=CardTag.OWNERSHIP, title="Перевёл легаси без героизма в слаке"),
    ExperienceCard(id="scale_4", tag=CardTag.SCALE, title="Очередь 50k msg/s, лаг в норме"),
    ExperienceCard(id="inc_4", tag=CardTag.INCIDENT, title="Postmortem без поиска виноватых"),
    ExperienceCard(id="soft_4", tag=CardTag.SOFT, title="Уговорил бизнес срезать scope"),
)

CARD_BY_ID: dict[str, ExperienceCard] = {c.id: c for c in CARD_POOL}

BULLETINS: tuple[Bulletin, ...] = (
    Bulletin(
        id="b_moscow",
        day_label="гибрид / Москва",
        gates=("Отсев: только Москва или гибрид",),
        required_tag=CardTag.STACK,
        cards_to_play=1,
        offer_allowed=True,
    ),
    Bulletin(
        id="b_1c",
        day_label="внутренний 1С",
        gates=("Стек без 1С — в архив без хрюши", "Скрытый ключ в требованиях: «наш 1С»"),
        required_tag=CardTag.STACK,
        cards_to_play=1,
    ),
    Bulletin(
        id="b_freeze",
        day_label="бюджет заморожен",
        gates=("Штамп ОФФЕР закрыт до разморозки",),
        required_tag=None,
        offer_allowed=False,
        cards_to_play=1,
    ),
    Bulletin(
        id="b_scale",
        day_label="нужен рост нагрузки",
        gates=("Без опыта с ростом нагрузки — мимо грейда",),
        required_tag=CardTag.SCALE,
        cards_to_play=1,
    ),
    Bulletin(
        id="b_owner",
        day_label="тащил сам или мимо",
        gates=("Ищем тех, кто вёл продукт сам",),
        required_tag=CardTag.OWNERSHIP,
        cards_to_play=1,
    ),
    Bulletin(
        id="b_two",
        day_label="две карты лицом",
        gates=("Кладите две карты опыта", "Обе — лицом вверх"),
        required_tag=None,
        cards_to_play=2,
        face_up=True,
    ),
    Bulletin(
        id="b_soft",
        day_label="мягкие навыки под основателя",
        gates=("Зашёл основатель — нужны мягкие навыки",),
        required_tag=CardTag.SOFT,
        cards_to_play=1,
    ),
    Bulletin(
        id="b_incident",
        day_label="инциденты",
        gates=("Без боя в проде — слабо",),
        required_tag=CardTag.INCIDENT,
        cards_to_play=1,
    ),
    Bulletin(
        id="b_open",
        day_label="открытый найм",
        gates=("Оффер разрешён", "Без отсева по анкете"),
        required_tag=None,
        offer_allowed=True,
        cards_to_play=1,
    ),
    Bulletin(
        id="b_batna",
        day_label="торг вилки",
        gates=("Контр-офферы в ходу",),
        required_tag=CardTag.BATNA,
        cards_to_play=1,
        offer_allowed=True,
    ),
    Bulletin(
        id="b_bluff_hunt",
        day_label="охота на волков",
        gates=("Проверка СБ усилена", "Блеф палится на проверке"),
        required_tag=None,
        cards_to_play=1,
    ),
    Bulletin(
        id="b_second",
        day_label="вторая смена",
        gates=("Смотрим пересечение календарей",),
        required_tag=CardTag.SECOND_JOB,
        cards_to_play=1,
        offer_allowed=False,
    ),
)

EVENTS: tuple[SlotEvent, ...] = (
    SlotEvent(id="e_ats", kind=SlotEventKind.ATS_KNOCKOUT, label="Робот-скринер на максимуме"),
    SlotEvent(id="e_ghost", kind=SlotEventKind.GHOSTING_WAVE, label="Волна тишины"),
    SlotEvent(id="e_budget", kind=SlotEventKind.BUDGET_FREEZE, label="Бюджет заморожен"),
    SlotEvent(id="e_founder", kind=SlotEventKind.FOUNDER_JOINS, label="Зашёл основатель"),
    SlotEvent(id="e_sec", kind=SlotEventKind.SECURITY_CHECK, label="Доп. проверка СБ"),
    SlotEvent(id="e_counter", kind=SlotEventKind.COUNTER_OFFER, label="Контр-оффер на столе"),
    SlotEvent(id="e_ref", kind=SlotEventKind.REFERRAL_PRESSURE, label="Знакомый давит"),
    SlotEvent(id="e_ats2", kind=SlotEventKind.ATS_KNOCKOUT, label="Отсев по городу"),
)

QUESTION_CHIPS: tuple[str, ...] = (
    "q_incident",
    "q_ownership",
    "q_stack",
    "q_why_us",
    "q_salary",
    "q_second_job",
)

# Формулировки для LLM-контекста (UI-ярлыки — в frontend chips.ts).
QUESTION_CHIP_PROMPTS: dict[str, str] = {
    "q_incident": "Расскажи про инцидент: что роняли и кто поднял?",
    "q_ownership": "Где ты отвечал сам, а не «мы командой»?",
    "q_stack": "Какой стек реально в проде, без «видел»?",
    "q_why_us": "Почему эта вакансия, а не соседний оффер?",
    "q_salary": "Вилка и запасной оффер: что на столе до пятницы?",
    "q_second_job": "Стендапы в двух местах — как с календарем?",
}

# Ярлыки категорий опыта на русском (зеркало frontend CardFace.TAG_LABEL) — служебные
# английские слаги CardTag (`ownership`, `scale`…) вслух за столом не звучат.
CARD_TAG_LABELS: dict[CardTag, str] = {
    CardTag.OWNERSHIP: "вёл сам",
    CardTag.SCALE: "рост нагрузки",
    CardTag.INCIDENT: "инцидент в проде",
    CardTag.SOFT: "работа с людьми",
    CardTag.STACK: "стек",
    CardTag.BLUFF: "блеф",
    CardTag.BATNA: "запасной оффер",
    CardTag.SECOND_JOB: "две работы",
}

FRAUD_MARKERS: tuple[str, ...] = (
    "dates_mismatch",
    "ip_surname",
    "stack_lie",
    "team_size",
    "calendar_clash",
    "act_fake",
)

# Подписи улик для судьи (зеркало papers.ts — id = FRAUD_MARKERS).
FRAUD_MARKER_LABELS: dict[str, str] = {
    "dates_mismatch": "Сроки: резюме 2022–2024 без разрывов против требования «от 3 лет, вёл сам»",
    "ip_surname": "Юрлицо/ФИО: акт ИП против договора с тем же ФИО",
    "stack_lie": "Стек: «видел Kafka» против рабочего стека бюллетеня",
    "team_size": "Команда: «вёл 40» против требования 5–8 разработчиков",
    "calendar_clash": "Календарь: стендап 10:00 + синк 19:00 против запрета на две работы",
    "act_fake": "Акт/ИП: размытая печать против оригинала или выписки ЕГРИП",
}

# ≥6 составов ролей (Э12): seed → один состав на партию.
ROLE_COMPOSITIONS: tuple[RoleComposition, ...] = (
    RoleComposition(
        id="rc_classic",
        label="1 волк · sniff+referral",
        wolf_count=1,
        sub_roles=(SubRole.TECH_SNIFF, SubRole.REFERRAL),
    ),
    RoleComposition(
        id="rc_shift",
        label="1 волк · sniff+shift",
        wolf_count=1,
        sub_roles=(SubRole.TECH_SNIFF, SubRole.SECOND_SHIFT),
    ),
    RoleComposition(
        id="rc_ref_shift",
        label="1 волк · referral+shift",
        wolf_count=1,
        sub_roles=(SubRole.REFERRAL, SubRole.SECOND_SHIFT),
    ),
    RoleComposition(
        id="rc_trio",
        label="1 волк · все подроли",
        wolf_count=1,
        sub_roles=(SubRole.TECH_SNIFF, SubRole.REFERRAL, SubRole.SECOND_SHIFT),
    ),
    RoleComposition(
        id="rc_pack",
        label="2 волка · sniff+referral",
        wolf_count=2,
        sub_roles=(SubRole.TECH_SNIFF, SubRole.REFERRAL),
    ),
    RoleComposition(
        id="rc_pack_shift",
        label="2 волка · referral+shift",
        wolf_count=2,
        sub_roles=(SubRole.REFERRAL, SubRole.SECOND_SHIFT),
    ),
    RoleComposition(
        id="rc_pack_trio",
        label="2 волка · все подроли",
        wolf_count=2,
        sub_roles=(SubRole.TECH_SNIFF, SubRole.REFERRAL, SubRole.SECOND_SHIFT),
    ),
    RoleComposition(
        id="rc_lone_sniff",
        label="1 волк · только sniff",
        wolf_count=1,
        sub_roles=(SubRole.TECH_SNIFF,),
    ),
)


def shuffled_deck(rng: random.Random) -> list[str]:
    ids = [c.id for c in CARD_POOL]
    rng.shuffle(ids)
    return ids


def deal_hand(rng: random.Random, deck: list[str], *, n: int) -> list[str]:
    """Снять n карт с верха колоды (мутирует deck)."""
    if len(deck) < n:
        extra = [c.id for c in CARD_POOL]
        rng.shuffle(extra)
        deck.extend(extra)
    hand = deck[:n]
    del deck[:n]
    return hand


def pick_bulletin(rng: random.Random, slot_index: int) -> Bulletin:
    base = BULLETINS[slot_index % len(BULLETINS)]
    if rng.random() < 0.35:
        return rng.choice(list(BULLETINS))
    return base


def pick_event(rng: random.Random, bulletin: Bulletin) -> SlotEvent:
    if not bulletin.offer_allowed:
        frozen = [e for e in EVENTS if e.kind == SlotEventKind.BUDGET_FREEZE]
        if frozen:
            return rng.choice(frozen)
    return rng.choice(list(EVENTS))


def apply_event_to_bulletin(bulletin: Bulletin, event: SlotEvent) -> Bulletin:
    if event.kind == SlotEventKind.BUDGET_FREEZE:
        return bulletin.model_copy(update={"offer_allowed": False})
    if event.kind == SlotEventKind.ATS_KNOCKOUT and bulletin.required_tag is None:
        return bulletin.model_copy(update={"required_tag": CardTag.STACK})
    return bulletin


def daily_seed(*, day: date | None = None) -> int:
    """Детерминированный seed «стола дня» от календарной даты (Э12)."""
    d = day or date.today()
    digest = hashlib.sha256(f"wolves:daily:{d.isoformat()}".encode()).hexdigest()
    return (int(digest[:8], 16) % (2**31 - 2)) + 1


def daily_ordinal(*, day: date | None = None) -> int:
    """Номер дня в году для бейджа «День #N»."""
    d = day or date.today()
    return int(d.timetuple().tm_yday)


def pick_role_composition(rng: random.Random) -> RoleComposition:
    return rng.choice(list(ROLE_COMPOSITIONS))


def clamp_wolf_count(wolf_count: int, candidate_count: int) -> int:
    """Волков от 1 до candidate_count-1."""
    return max(1, min(wolf_count, candidate_count - 1))


def deal_factions(
    rng: random.Random, candidate_ids: list[str], wolf_count: int
) -> dict[str, Faction]:
    if wolf_count < 1 or wolf_count >= len(candidate_ids):
        raise ValueError(f"wolf_count={wolf_count} несовместим с {len(candidate_ids)} кандидатами")
    wolves = set(rng.sample(candidate_ids, wolf_count))
    return {cid: Faction.WOLF if cid in wolves else Faction.HUMAN for cid in candidate_ids}


def deal_sub_roles(
    rng: random.Random,
    candidate_ids: list[str],
    *,
    allowed: tuple[SubRole, ...] | None = None,
) -> dict[str, SubRole]:
    pool = (
        list(allowed)
        if allowed
        else [
            SubRole.TECH_SNIFF,
            SubRole.REFERRAL,
            SubRole.SECOND_SHIFT,
        ]
    )
    pool = [r for r in pool if r != SubRole.NONE]
    if not pool:
        return {cid: SubRole.NONE for cid in candidate_ids}
    rng.shuffle(pool)
    n = min(len(pool), max(1, min(len(pool), len(candidate_ids))))
    chosen = pool[:n]
    targets = list(candidate_ids)
    rng.shuffle(targets)
    out = {cid: SubRole.NONE for cid in candidate_ids}
    for role, cid in zip(chosen, targets, strict=False):
        out[cid] = role
    return out


def pick_ghost_slots(rng: random.Random, slot_count: int) -> tuple[int, ...]:
    if slot_count <= 0:
        return ()
    if rng.random() < 0.55:
        return (rng.randrange(slot_count),)
    return ()


def assign_fraud_and_strength(
    rng: random.Random,
    *,
    factions: dict[str, Faction],
) -> dict[str, tuple[tuple[str, str] | None, bool]]:
    out: dict[str, tuple[tuple[str, str] | None, bool]] = {}
    markers = list(FRAUD_MARKERS)
    for cid, faction in factions.items():
        fraud: tuple[str, str] | None = None
        if faction == Faction.WOLF or rng.random() < 0.2:
            pair = rng.sample(markers, 2)
            fraud = (pair[0], pair[1])
        is_strong = faction == Faction.HUMAN and rng.random() < 0.45
        out[cid] = (fraud, is_strong)
    return out


def build_candidate_seats(
    rng: random.Random,
    *,
    candidate_count: int,
    wolf_count: int,
    hand_size: int,
    deck: list[str],
    composition: RoleComposition | None = None,
) -> dict[str, Seat]:
    ids = [f"c{i}" for i in range(candidate_count)]
    factions = deal_factions(rng, ids, wolf_count)
    allowed = composition.sub_roles if composition is not None else None
    subs = deal_sub_roles(rng, ids, allowed=allowed)
    frauds = assign_fraud_and_strength(rng, factions=factions)
    seats: dict[str, Seat] = {}
    for cid in ids:
        fraud, strong = frauds[cid]
        seats[cid] = Seat(
            id=cid,
            kind=SeatKind.CANDIDATE,
            faction=factions[cid],
            sub_role=subs[cid],
            hand=deal_hand(rng, deck, n=hand_size),
            fraud_pair=fraud,
            is_strong=strong,
            is_bot=True,
            filled=True,
        )
    return seats


def empty_candidate_seat(seat_id: str) -> Seat:
    return Seat(
        id=seat_id,
        kind=SeatKind.CANDIDATE,
        faction=None,
        filled=False,
        public_status=PublicStatus.WAITING,
    )


def card_tags(card_ids: Iterable[str]) -> set[CardTag]:
    tags: set[CardTag] = set()
    for cid in card_ids:
        card = CARD_BY_ID.get(cid)
        if card is not None:
            tags.add(card.tag)
    return tags


__all__ = [
    "CARD_POOL",
    "CARD_BY_ID",
    "BULLETINS",
    "EVENTS",
    "QUESTION_CHIPS",
    "QUESTION_CHIP_PROMPTS",
    "FRAUD_MARKERS",
    "FRAUD_MARKER_LABELS",
    "CARD_TAG_LABELS",
    "ROLE_COMPOSITIONS",
    "daily_seed",
    "daily_ordinal",
    "pick_role_composition",
    "clamp_wolf_count",
    "shuffled_deck",
    "deal_hand",
    "pick_bulletin",
    "pick_event",
    "apply_event_to_bulletin",
    "deal_factions",
    "deal_sub_roles",
    "pick_ghost_slots",
    "assign_fraud_and_strength",
    "build_candidate_seats",
    "empty_candidate_seat",
    "card_tags",
]
