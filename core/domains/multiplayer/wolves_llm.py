"""Вызовы игровых LLM-фич «Хрюш и Волков» через ports + модели раздела.

Что здесь важно и почему так:

- **Три модели, три роли** (Э19.8). `wolves_line` / `wolves_bark` — «актёр»
  (`MODEL_MULTIPLAYER_ACTOR`), прямая речь персонажей. `wolves_ticker` / `wolves_brief` —
  «режиссёр» (`MODEL_MULTIPLAYER`), мир вокруг стола. `wolves_judge` — «арбитр»
  (`MODEL_MULTIPLAYER_ARBITER`), строгий JSON под сверку с движком. Разбор ролей — в `llm.py`;
  slug'ов в Python нет, только имена ролей.
- **Голый текст там, где сверять нечего.** Четыре фичи отдают одну короткую фразу: json_schema
  за неё дороже, добавляет свой класс отказов и запрещает стрим. Разбор — `sanitize_utterance`
  (обрезка по словам, бан-лист §5.2, снятие случайной JSON-обёртки/кавычек).
- **Structured там, где есть что проверить.** У судьи в ответе `cited_marker` — id улики,
  который обязан совпасть с поданным иском (`_checked_marker`). Это единственное поле во всём
  разделе, где галлюцинация видна машине, а не только на глаз.
- **Реплика кандидата стримится** — `stream_bot_line`: фраза печатается за столом по мере
  генерации, а не появляется целиком через N секунд.
- **Партия не стопается никогда.** Любой сбой провайдера → заглушка `FALLBACK_*` и WARNING в
  журнал; исход иска считает движок (`rules.claim_is_correct`), а не модель.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any, Literal

from core.config import get_settings
from core.domains.multiplayer import llm as mp_llm
from core.domains.multiplayer.deck import (
    CARD_TAG_LABELS,
    FRAUD_MARKER_LABELS,
    QUESTION_CHIP_PROMPTS,
)
from core.domains.multiplayer.models import (
    Faction,
    MatchState,
    SeatKind,
    Stamp,
    SubRole,
    WolvesJudgeOut,
)
from core.domains.multiplayer.rules import claim_is_correct
from core.kernel import ports
from core.platform.observability import event

logger = logging.getLogger(__name__)

LINE_MAX_WORDS = 16
TICKER_MAX_WORDS = 12
BARK_MAX_WORDS = 12
BRIEF_MAX_WORDS = 18

FALLBACK_BOT_LINE = "Стек бил, дедлайны жёсткие."
FALLBACK_JUDGE_LINE = "Судья молчит. Идём дальше."
FALLBACK_TICKER = "Слот закрыт. Тишина в чате."
FALLBACK_BARK = "Понял. Пойду дальше по списку."
FALLBACK_BRIEF = "Обычный день кабинета: бумаги, гейты, очередь."

#: Пауза между кадрами стрима одной реплики. Чаще — пустая нагрузка на сокет: глазу хватает
#: ~8 обновлений в секунду, чтобы текст читался как печатающийся.
STREAM_MIN_INTERVAL_S = 0.12

#: Ниже этого реплика перестаёт быть репликой («Да.»), и обрубок по словам честнее.
MIN_SENTENCE_WORDS = 3

#: Что делать с куском реплики по ходу генерации (кадр в комнату).
LineDelta = Callable[[str], Awaitable[None]]

# Бан-лист §5.2 (нижний регистр) — совпадение → fallback / вырезка.
_SLOP_PHRASES: tuple[str, ...] = (
    "динамично развивающаяся команда",
    "динамично развивающейся команды",
    "динамичная команда",
    "проактивность",
    "синергия",
    "спасибо за ваш отклик",
    "мы свяжемся",
    "лучшие практики",
    "в рамках синергии",
    "взаимовыгодное сотрудничество",
    "амбициозные задачи",
    "молодой коллектив",
)

# Корпоративный английский, от которого реплики звучат как перевод с LinkedIn. НЕ роняем
# в fallback: заглушка скучнее живой фразы с одним лишним словом, а вырезать слово из
# середины — портить синтаксис. Только считаем, чтобы видеть, работает ли бан-лист в
# промпте (`prompts/multiplayer/wolves_system.md`). Э19.
_ANGLICISMS: tuple[str, ...] = (
    "ownership",
    "scale",
    "performance",
    "alignment",
    "background",
    "expertise",
    "challenge",
    "commitment",
    "mindset",
    "work-life",
    "soft skills",
    "hard skills",
    "asap",
    "follow-up",
    "knockout",
    "batna",
    "hiring manager",
    "candidate experience",
)

# Ярлыки движка → то, как это называют вслух за столом.
_STAMP_RU: dict[str, str] = {
    "interview": "НА СОБЕС",
    "reject": "ОТКАЗ",
    "probe": "НА ПРОВЕРКУ",
    "offer": "ОФФЕР",
}
_STATUS_RU: dict[str, str] = {
    "waiting": "ждёшь штампа",
    "interview": "отправлен на собес",
    "rejected": "уже отказ в этом слоте",
    "offer": "получил оффер",
    "ghosted": "хрюша не успела — тишина",
    "spectating": "смотришь со стороны",
}
# Что штамп значит для того, кому его поставили: реакция должна быть на смысл, а не на слово.
_STAMP_MEANING: dict[str, str] = {
    "interview": "тебя позвали дальше — но это ещё не деньги",
    "reject": "тебе отказали прямо здесь, при всех",
    "probe": "тебя отправили на проверку: бумаги смотрят под лупой",
    "offer": "тебе дали оффер — прямо сейчас, при всём столе",
}

# Подроли движком пока не отыгрываются механически (`deck.deal_sub_roles` их раздаёт, правила
# не читают) — но кандидату они дают то, чего не даёт ни одна карта: причину вести себя именно
# так. Поэтому живут они здесь, в слое речи, а не в rules.
_SUB_ROLE_HINTS: dict[str, str] = {
    SubRole.TECH_SNIFF.value: (
        "У тебя нюх на технику: слышишь, где собеседник плавает, и не упускаешь случая "
        "уточнить деталь, от которой другому неуютно."
    ),
    SubRole.REFERRAL.value: (
        "Тебя привёл человек изнутри. Ты держишься чуть увереннее, чем позволяет опыт, "
        "и знаешь, чьё имя можно уронить в разговор."
    ),
    SubRole.SECOND_SHIFT.value: (
        "Ты уже где-то работаешь и уходить оттуда не планируешь. Вопросы про календарь и "
        "занятость — по тебе, и ты это чувствуешь."
    ),
}

# Амплуа кандидата: голос, который держится всю партию (детерминирован от seed+места).
# Без этого все боты за столом отвечают одинаково — одна модель, один промпт, один тон.
# game_redesign.md §5: у каждого персонажа свой лексикон и своя температура.
_PERSONAS: tuple[tuple[str, str, float], ...] = (
    (
        "уставший циник",
        "Говоришь ровно и негромко, энтузиазм кончился два места назад. "
        "Шутишь так, что не сразу понятно, шутка ли.",
        0.75,
    ),
    (
        "бодрый продажник",
        "Продаёшь себя громко, любишь круглые числа и превосходную степень. "
        "Цифры называешь уверенно, даже когда они ничего не значат.",
        0.95,
    ),
    (
        "технарь-буквоед",
        "Отвечаешь конкретикой: версии, сроки, названия. Светские формулировки тебя "
        "раздражают, и это слышно.",
        0.7,
    ),
    (
        "вежливый уклонист",
        "Отвечаешь безупречно вежливо и мимо сути. Ни одного прямого «да» или «нет».",
        0.85,
    ),
    (
        "выгоревший ветеран",
        "Двадцать лет в отрасли, терять нечего. Говоришь то, что думаешь, коротко и "
        "с усталой прямотой.",
        0.8,
    ),
    (
        "джун с завышенной планкой",
        "Опыта мало, амбиций много. Искренне не понимаешь, почему тебе не дают сеньора.",
        0.9,
    ),
)


@dataclass(frozen=True, slots=True)
class Persona:
    """Амплуа кандидата на всю партию."""

    label: str
    hint: str
    temperature: float


@dataclass(frozen=True, slots=True)
class JudgeCall:
    """Что вернул суд: исход движка + озвучка + проверенная улика (или `None`)."""

    verdict: Literal["confirm", "reject"]
    line: str
    marker: str | None = None


def persona_for(state: MatchState, seat_id: str) -> Persona:
    """Стабильное амплуа места: один seed матча → один и тот же голос до конца партии."""
    digest = hashlib.sha256(f"{state.seed}:{seat_id}".encode()).hexdigest()
    label, hint, temp = _PERSONAS[int(digest[:8], 16) % len(_PERSONAS)]
    return Persona(label=label, hint=hint, temperature=temp)


def word_count(text: str) -> int:
    return len([w for w in text.split() if w])


def truncate_words(text: str, max_words: int) -> str:
    """Жёсткий потолок слов; хвост обрезаем без многоточия (стенограмма, не чат)."""
    words = [w for w in text.split() if w]
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words])


def contains_slop(text: str) -> bool:
    lowered = text.casefold()
    return any(phrase in lowered for phrase in _SLOP_PHRASES)


def anglicisms_in(text: str) -> list[str]:
    """Корпоративный английский в реплике — метрика качества промпта, не повод для fallback."""
    lowered = text.casefold()
    return [word for word in _ANGLICISMS if word in lowered]


# Служебная обёртка вокруг фразы: остаток привычки моделей отвечать JSON'ом плюс ярлык
# «Реплика:», который иногда приклеивается спереди. Раньше это ловил json_schema; теперь
# ловим здесь — дешевле и без отдельного класса отказов (Э19.8).
_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")
_LABEL_RE = re.compile(
    r"^(реплика|ответ|фраза|заголовок|судья|кандидат|вердикт)\s*[:—-]\s*", re.IGNORECASE
)


def unwrap_model_text(text: str) -> str:
    """Снять с ответа модели служебную обёртку: ```-забор, JSON-объект, ярлык, кавычки."""
    cleaned = _FENCE_RE.sub("", (text or "").strip()).strip()
    if cleaned.startswith("{"):
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            # Оборванный JSON (например, обрезали по max_tokens) — вытащим первую строку.
            match = re.search(r'"\s*:\s*"(?P<val>[^"]+)', cleaned)
            cleaned = match.group("val") if match else cleaned
        else:
            if isinstance(data, dict):
                value = next(
                    (v for v in data.values() if isinstance(v, str) and v.strip()),
                    "",
                )
                cleaned = value or cleaned
    cleaned = _LABEL_RE.sub("", cleaned).strip()
    if len(cleaned) >= 2 and cleaned[0] in "«\"'“" and cleaned[-1] in "»\"'”":
        cleaned = cleaned[1:-1].strip()
    return cleaned


def trim_to_sentence(text: str, *, min_words: int) -> str:
    """Отрезать хвост после последней законченной фразы, если от реплики что-то останется.

    Жёсткая обрезка по словам ловится глазом мгновенно: «Робот отсёк — без стека. Зато вилку
    я всё равно» читается как сбой, а не как реплика (живой прогон 2026-08-27). Если внутри
    потолка есть точка — режем по ней; если законченной фразы нет вовсе или она короче
    `min_words` («Да.»), оставляем обрубок: он всё равно информативнее.
    """
    cut = max(text.rfind(ch) for ch in ".!?…")
    if cut < 0:
        return text
    head = text[: cut + 1].strip()
    return head if word_count(head) >= min_words else text


def sanitize_utterance(text: str, *, max_words: int, fallback: str) -> str:
    """Снять обёртку + truncate + anti-slop. Пустое/slop → fallback (тоже truncate)."""
    cleaned = re.sub(r"\s+", " ", unwrap_model_text(text))
    if not cleaned or contains_slop(cleaned):
        cleaned = fallback
    raw_words = word_count(cleaned)
    out = truncate_words(cleaned, max_words)
    if raw_words > max_words:
        out = trim_to_sentence(out, min_words=MIN_SENTENCE_WORDS)
    if not out:
        out = truncate_words(fallback, max_words)
    if raw_words > max_words:
        event(
            logger,
            "ЗАДАЧА",
            "mp_llm_truncate words=%s→%s",
            raw_words,
            max_words,
            level=logging.WARNING,
        )
    found = anglicisms_in(out)
    if found:
        event(
            logger,
            "ЗАДАЧА",
            "mp_llm_anglicism words=%s",
            ",".join(found),
            level=logging.WARNING,
            anglicisms=found,
        )
    return out


def _model_for(feature: str) -> str:
    """Slug модели по роли фичи. Роль — в `llm.FEATURE_ROLE`, slug — только в `.env`."""
    settings = get_settings()
    role = mp_llm.FEATURE_ROLE.get(feature)
    if role == mp_llm.ROLE_ACTOR:
        return settings.multiplayer_actor_model()
    if role == mp_llm.ROLE_ARBITER:
        return settings.multiplayer_arbiter_model()
    return settings.multiplayer_model()


def _llm_ready() -> bool:
    settings = get_settings()
    return bool(settings.openrouter_api_key.strip() and settings.multiplayer_model())


def _budget_s(feature: str) -> float:
    """Потолок ожидания стрима: у нестримовых вызовов его держит сама платформа."""
    feat = next((f for f in mp_llm.FEATURES if f.name == feature), None)
    return (feat.budget_ms or 20_000) / 1000.0 if feat else 20.0


def _card_titles(state: MatchState, card_ids: Iterable[str]) -> list[str]:
    """Названия карт как их произносят, без служебных тегов движка."""
    out: list[str] = []
    for cid in card_ids:
        card = state.card_by_id.get(cid)
        out.append(f"«{card.title}»" if card is not None else cid)
    return out


def _scene_block(state: MatchState) -> list[str]:
    """Общая шапка сцены: что за слот, что требует бюллетень, чем рискует хрюша.

    Раньше в промпт уезжал только `day_label`, поэтому модель не знала ни гейтов, ни
    требования ATS, ни ставок — и отвечала «вообще про найм», а не про этот стол.
    """
    bulletin = state.bulletin
    lines = [
        "# СЦЕНА (факты движка — обыграй их, не меняй)",
        "",
        f"Слот {state.slot_index + 1} из {state.config.slot_count}. "
        f"Бюллетень: «{bulletin.day_label if bulletin else '—'}».",
    ]
    if state.event is not None:
        lines.append(f"Событие дня: «{state.event.label}».")
    if bulletin is not None:
        if bulletin.gates:
            lines.append(f"Гейты слота: {'; '.join(bulletin.gates)}.")
        if bulletin.required_tag is not None:
            tag_ru = CARD_TAG_LABELS.get(bulletin.required_tag, bulletin.required_tag.value)
            lines.append(
                f"Робот-скринер сегодня рубит всех без опыта «{tag_ru}» "
                "— без такой карты кандидата срезает без разговора."
            )
        if not bulletin.offer_allowed:
            lines.append("Оффер в этом слоте запрещён — максимум собес.")
    lines.append(
        f"Выговоры хрюши: {state.citations} из {state.config.citations_limit} "
        "(на третьем волки побеждают)."
    )
    # Последний слот меняет цену любой реплики: тянуть время больше некуда.
    if state.slot_index + 1 == state.config.slot_count:
        lines.append("Это последний слот партии — после него считают итог.")
    if state.slot_brief:
        lines.append(f"Сегодняшняя сводка кабинета: «{state.slot_brief}»")
    return lines


def _match_memory(state: MatchState, seat_id: str | None = None) -> list[str]:
    """Короткая память партии: чем кончались прошлые слоты у этого места.

    Жёстко ограничена по объёму (game_redesign.md §7, «Ожирение токенов»): не история
    реплик, а несколько фактов-флагов, из которых модель сама достраивает бэкграунд.
    """
    if state.slot_index == 0 and not state.judge_line:
        return []
    lines = ["# ЧТО БЫЛО РАНЬШЕ", ""]
    if seat_id is not None:
        stamps = [_STAMP_RU.get(s.value, s.value) for s in state.lifetime_stamps.get(seat_id, [])]
        if stamps:
            lines.append(f"Тебе в этой партии уже ставили: {', '.join(stamps[-4:])}.")
        else:
            lines.append("Тебе в этой партии ещё ни разу ничего не ставили.")
    if state.judge_line:
        lines.append(f"Последнее слово судьи: «{state.judge_line}»")
    if state.slot_ticker:
        lines.append(f"Газета о прошлом слоте: «{state.slot_ticker}»")
    return lines


def _self_block(state: MatchState, seat_id: str) -> list[str]:
    """Кто ты за этим столом: амплуа, фракция, подроль, карты, статус.

    Подроль и стая волков сюда доехали в Э19.8: до этого модель знала про место ровно две
    вещи (волк/человек и что выложено), поэтому все шесть амплуа тянули одну и ту же ноту.
    """
    seat = state.seats[seat_id]
    persona = persona_for(state, seat_id)
    lines = [
        "# ТЫ",
        "",
        f"Место за столом: {seat_id}. Амплуа: {persona.label}. {persona.hint}",
    ]
    if seat.faction is not None and seat.faction.value == "wolf":
        lines.append(
            "Ты волк: опыт дорисован, и ты знаешь, где у тебя тонко. Держись уверенно, "
            "отвечай по существу и ни словом, ни намёком не выдай, что ты волк."
        )
        pack = sorted(
            s.id
            for s in state.seats.values()
            if s.faction == Faction.WOLF and s.id != seat_id and s.filled
        )
        if pack:
            lines.append(
                f"За столом ты не один: {', '.join(pack)} — тоже волк. Вы не сговаривались "
                "вслух и не выгораживаете друг друга в открытую."
            )
    else:
        lines.append("Ты человек: за словами есть реальный опыт, скрывать нечего.")
        if seat.is_strong:
            lines.append(
                "Опыт у тебя сильный, и ты это знаешь: отказ тебе — ошибка кабинета, "
                "а не твоя. Держись соответственно."
            )
    hint = _SUB_ROLE_HINTS.get(seat.sub_role.value if seat.sub_role else "")
    if hint:
        lines.append(hint)
    cards = _card_titles(state, seat.played)
    lines.append(f"Твои карты на столе: {'; '.join(cards) if cards else '(ничего не выложил)'}.")
    status = seat.public_status.value
    lines.append(f"Твой статус: {_STATUS_RU.get(status, status)}.")
    return lines


def build_line_context(state: MatchState, seat_id: str) -> str:
    """Динамический хвост system'а для реплики кандидата.

    Уезжает в `dynamic_tail`, а не в `{{context}}` внутри промпта: при `cache_prefix=True`
    подстановка в тело промпта делает «статический префикс» разным на каждый вызов, и
    prompt cache не срабатывает ни разу — то есть платим полным TTFT каждую реплику.
    """
    chip = state.question_chip or ""
    question = QUESTION_CHIP_PROMPTS.get(chip, chip)

    lines = _scene_block(state)
    lines += ["", *_self_block(state, seat_id)]

    memory = _match_memory(state, seat_id)
    if memory:
        lines += ["", *memory]

    lines += ["", "# ВОПРОС ХРЮШИ ВСЕМУ СТОЛУ", "", f"«{question}»"]

    # Кто уже успел ответить в этом кругу. При параллельной генерации (Э20.3) здесь обычно
    # только живые игроки: боты стартуют одновременно и друг друга не слышат — осознанный
    # размен ради того, чтобы круг умещался в фазу.
    said = [f"{sid}: «{text}»" for sid, text in state.answers.items() if sid != seat_id and text]
    if said:
        lines += ["", "# УЖЕ ОТВЕТИЛИ", "", *said[-3:]]

    lines += ["", f"Ответь одной фразой в образе, максимум {LINE_MAX_WORDS} слов."]
    return "\n".join(lines)


def build_judge_evidence(state: MatchState) -> str:
    """Динамический хвост system'а для судьи — вместе с ВЕРДИКТОМ движка.

    Вердикт здесь не для того, чтобы модель его «учла», а потому что решает его движок:
    совпадение улик с `Seat.fraud_pair` из улик не выводится, и раньше модель угадывала
    исход, который стоит хрюше выговора (game_redesign.md §2).
    """
    focus = state.focus_candidate_id or "?"
    seat = state.seats.get(focus)
    cards = _card_titles(state, seat.played) if seat is not None else []
    correct = claim_is_correct(state)

    lines = _scene_block(state)
    lines += ["", "# ИСК", "", f"Хрюша обвиняет место {focus} в двух несостыковках:"]
    # id рядом с подписью: судья возвращает его в `cited_marker`, и это единственное поле
    # раздела, которое движок умеет сверить с фактом (`_checked_marker`).
    lines += [
        f'  {i}. id="{marker}" — {FRAUD_MARKER_LABELS.get(marker, marker)}'
        for i, marker in enumerate(state.discrepancy_marks, start=1)
    ]
    lines.append(f"Карты этого кандидата на столе: {'; '.join(cards) if cards else '(нет)'}.")
    if seat is not None and state.answers.get(focus):
        # Судья слышал, что кандидат говорил вслух, — с этим приятно срифмовать вердикт.
        lines.append(f"Вслух этот кандидат сказал: «{state.answers[focus]}»")
    lines += [
        "",
        "# ВЕРДИКТ ДВИЖКА — ФАКТ, НЕ МНЕНИЕ",
        "",
    ]
    if correct:
        lines += [
            "ИСК ВЕРНЫЙ. Обе улики указывают ровно на то, что кандидат подделал — он вскрыт.",
            "Огласи подтверждение, опираясь на конкретную улику из списка.",
        ]
    else:
        lines += [
            "ИСК МИМО. В этих двух местах бумаги чистые, кандидат по ним не подделывал ничего.",
            "Сними обвинение. Не намекай, что кандидат всё равно подозрителен.",
        ]
    return "\n".join(lines)


def judge_evidence_hash(evidence: str) -> str:
    return hashlib.sha256(evidence.encode("utf-8")).hexdigest()[:32]


def build_slot_result(state: MatchState) -> str:
    """Динамический хвост system'а для газеты: сводка закрытого слота."""
    stamps = [
        f"{sid} — {_STAMP_RU.get(stamp.value, stamp.value)}"
        for sid, stamp in sorted(state.stamps_this_slot.items())
    ]
    lines = _scene_block(state)
    lines += [
        "",
        "# ЧЕМ КОНЧИЛСЯ СЛОТ",
        "",
        f"Штампы хрюши: {', '.join(stamps) if stamps else 'ни одного'}.",
    ]
    if state.judge_line:
        lines.append(f"Судья в этом слоте сказал: «{state.judge_line}»")
    loud = [f"{sid}: «{text}»" for sid, text in list(state.answers.items())[:2] if text]
    if loud:
        lines.append(f"Из стенограммы реплик: {'; '.join(loud)}")
    lines += [
        "",
        f"Выбери самую громкую деталь и сделай заголовок, максимум {TICKER_MAX_WORDS} слов.",
    ]
    return "\n".join(lines)


def build_bark_context(state: MatchState, seat_id: str) -> str:
    """Хвост для реакции на штамп: что именно упало на этого кандидата и что это значит."""
    stamp = state.stamps_this_slot.get(seat_id)
    stamp_ru = _STAMP_RU.get(stamp.value, stamp.value) if stamp is not None else "—"
    meaning = _STAMP_MEANING.get(stamp.value, "") if stamp is not None else ""

    lines = _scene_block(state)
    lines += ["", *_self_block(state, seat_id)]
    lines += [
        "",
        "# ЧТО ТОЛЬКО ЧТО ПРОИЗОШЛО",
        "",
        f"Хрюша поставила тебе штамп: {stamp_ru}. {meaning}.",
    ]
    if state.answers.get(seat_id):
        lines.append(f"Перед этим ты сказал: «{state.answers[seat_id]}»")
    if stamp is Stamp.REJECT and state.bulletin and state.bulletin.required_tag is not None:
        lines.append(
            "Возможно, тебя срезал ATS по требованию слота — до разговора дело так и не дошло."
        )
    lines += [
        "",
        f"Брось одну реплику вслед печати, максимум {BARK_MAX_WORDS} слов. Не проси "
        "пересмотреть решение и не устраивай сцену — это выдох, а не спор.",
    ]
    return "\n".join(lines)


def build_brief_context(state: MatchState) -> str:
    """Хвост для сцены слота: режиссёр объявляет, что сегодня за день в кабинете."""
    lines = _scene_block(state)
    seats = [s for s in state.seats.values() if s.kind == SeatKind.CANDIDATE and s.filled]
    lines += [
        "",
        "# КТО В ОЧЕРЕДИ",
        "",
        f"Кандидатов на сегодня: {len(seats)}.",
    ]
    memory = _match_memory(state)
    if memory:
        lines += ["", *memory]
    lines += [
        "",
        f"Объяви этот день одной фразой, максимум {BRIEF_MAX_WORDS} слов.",
    ]
    return "\n".join(lines)


# --- вызовы -------------------------------------------------------------------------


def _log_ok(feature: str, model: str, **fields: Any) -> None:
    event(
        logger,
        "ЗАДАЧА",
        "mp_llm_%s model=%s",
        feature.removeprefix("wolves_"),
        model,
        feature=feature,
        model=model,
        **fields,
    )


def _log_fallback(feature: str, model: str, exc: Exception, **fields: Any) -> None:
    event(
        logger,
        "ЗАДАЧА",
        "mp_llm_%s_fallback err=%s",
        feature.removeprefix("wolves_"),
        str(exc),
        feature=feature,
        model=model,
        level=logging.WARNING,
        **fields,
    )


async def _say(
    feature: str,
    *,
    tail: str,
    cue: str,
    max_words: int,
    fallback: str,
    temperature: float | None = None,
    cache_key: str | None = None,
    metadata: dict[str, object] | None = None,
    llm: ports.LlmPort | None = None,
) -> str:
    """Один короткий текст от модели роли `feature`. Любой сбой → `fallback`.

    Общая обвязка всех игровых фич: выбор модели по роли, сцена в `dynamic_tail` (чтобы
    статический префикс попадал в prompt cache), санитайзер и лог. Исключения ловим все:
    у стола нет ни одной причины падать из-за провайдера.
    """
    model = _model_for(feature)
    if not _llm_ready():
        return sanitize_utterance(fallback, max_words=max_words, fallback=fallback)
    port = llm or ports.llm()
    try:
        raw = await port.complete(
            feature,
            user=cue,
            dynamic_tail=tail,
            temperature=temperature,
            model_override=model,
            tags=("multiplayer", feature),
            cache_key=cache_key,
            metadata=metadata or {},
        )
    except Exception as exc:  # noqa: BLE001 — партия не стопается ни на чём
        _log_fallback(feature, model, exc)
        return sanitize_utterance(fallback, max_words=max_words, fallback=fallback)
    _log_ok(feature, model)
    return sanitize_utterance(raw, max_words=max_words, fallback=fallback)


def _checked_marker(raw: str | None, state: MatchState) -> str | None:
    """Улика из ответа судьи, сверенная с иском. Чужое/выдуманное → None + WARNING.

    Ровно ради этой проверки у судьи и есть schema: строку сверить не с чем, а id улики —
    можно. Модель, назвавшая третий маркер, не должна подсветить игроку бумагу, которой в
    иске не было: это выглядело бы как решение движка, а не как оговорка модели.
    """
    value = (raw or "").strip()
    if value and value in state.discrepancy_marks:
        return value
    if value:
        event(
            logger,
            "ЗАДАЧА",
            "mp_llm_judge_marker_off marker=%s claim=%s",
            value,
            ",".join(state.discrepancy_marks),
            level=logging.WARNING,
            feature="wolves_judge",
            marker=value,
        )
    return None


async def stream_bot_line(
    state: MatchState,
    seat_id: str,
    *,
    on_delta: LineDelta | None = None,
    llm: ports.LlmPort | None = None,
) -> str:
    """Реплика бота-кандидата со стримом: `on_delta` получает текст по мере генерации.

    Стрим здесь не про экономию, а про ощущение стола: игрок видит, что персонаж говорит,
    через полторы секунды после вопроса, а не через пятнадцать. Ошибка/нет модели →
    `FALLBACK_BOT_LINE`, и это неотличимо от обычной реплики для правил.
    """
    model = _model_for("wolves_line")
    if not _llm_ready():
        return sanitize_utterance(
            FALLBACK_BOT_LINE, max_words=LINE_MAX_WORDS, fallback=FALLBACK_BOT_LINE
        )
    port = llm or ports.llm()
    persona = persona_for(state, seat_id)
    tail = build_line_context(state, seat_id)
    chunks: list[str] = []
    last_sent = 0.0
    try:
        async with asyncio.timeout(_budget_s("wolves_line")):
            stream = port.stream(
                "wolves_line",
                user="Твоя реплика:",
                dynamic_tail=tail,
                temperature=persona.temperature,
                model_override=model,
                tags=("multiplayer", "wolves_line"),
                metadata={"room_seed": state.seed, "seat": seat_id, "persona": persona.label},
            )
            async for piece in stream:
                chunks.append(piece)
                if on_delta is None:
                    continue
                now = time.monotonic()
                if now - last_sent < STREAM_MIN_INTERVAL_S:
                    continue
                last_sent = now
                # Кадр — накопленный текст целиком, а не приращение: клиент, пропустивший
                # кадр (реконнект, свёрнутая вкладка), сам себя чинит следующим же.
                so_far = truncate_words(unwrap_model_text("".join(chunks)), LINE_MAX_WORDS)
                with contextlib.suppress(Exception):
                    await on_delta(so_far)
    except Exception as exc:  # noqa: BLE001
        if not chunks:
            _log_fallback("wolves_line", model, exc, seat=seat_id)
            return sanitize_utterance(
                FALLBACK_BOT_LINE, max_words=LINE_MAX_WORDS, fallback=FALLBACK_BOT_LINE
            )
        # Оборвались на середине — уже сказанное лучше заглушки.
        _log_fallback("wolves_line", model, exc, seat=seat_id, partial=True)
    line = sanitize_utterance("".join(chunks), max_words=LINE_MAX_WORDS, fallback=FALLBACK_BOT_LINE)
    _log_ok("wolves_line", model, seat=seat_id, persona=persona.label)
    return line


async def generate_bot_line(
    state: MatchState,
    seat_id: str,
    *,
    llm: ports.LlmPort | None = None,
) -> str:
    """Реплика бота-кандидата без стрима (тесты и вызовы, которым кадры не нужны)."""
    persona = persona_for(state, seat_id)
    return await _say(
        "wolves_line",
        tail=build_line_context(state, seat_id),
        cue="Твоя реплика:",
        max_words=LINE_MAX_WORDS,
        fallback=FALLBACK_BOT_LINE,
        temperature=persona.temperature,
        # Реплики не кэшируем (temperature↑) — уникальный ключ.
        cache_key=f"line:{uuid.uuid4().hex}",
        metadata={"room_seed": state.seed, "seat": seat_id, "persona": persona.label},
        llm=llm,
    )


async def generate_judge(
    state: MatchState,
    *,
    llm: ports.LlmPort | None = None,
) -> JudgeCall:
    """Оглашение вердикта судьёй. Вердикт считает движок, LLM озвучивает и ссылается на улику.

    Раньше вердикт возвращала модель — а совпадение улик с `Seat.fraud_pair` из улик не
    выводится в принципе, модели подделка не видна. То есть исход, который стоит хрюше
    выговора (а на третьем — партии), решался фактически броском монеты. Теперь вердикт
    берётся из `rules.claim_is_correct`, и сбой LLM меняет только текст реплики, но не
    ход партии (game_redesign.md §2).

    Единственная фича раздела со structured-выходом: `cited_marker` сверяется с иском
    (`_checked_marker`), поэтому судья не может сослаться на улику, которой не подавали.
    """
    verdict: Literal["confirm", "reject"] = "confirm" if claim_is_correct(state) else "reject"
    evidence = build_judge_evidence(state)
    model = _model_for("wolves_judge")
    if not _llm_ready():
        return JudgeCall(verdict, FALLBACK_JUDGE_LINE, None)
    port = llm or ports.llm()
    try:
        raw = await port.structured(
            "wolves_judge",
            schema=WolvesJudgeOut,
            user="Оглашай решение:",
            dynamic_tail=evidence,
            model_override=model,
            tags=("multiplayer", "wolves_judge"),
            # Хэш улик уже включает вердикт (он часть evidence) — один и тот же иск с разным
            # исходом не переиспользует чужую реплику.
            cache_key=f"judge:{judge_evidence_hash(evidence)}",
            metadata={"room_seed": state.seed, "verdict": verdict},
        )
    except Exception as exc:  # noqa: BLE001 — исход иска уже посчитан, падает только текст
        _log_fallback("wolves_judge", model, exc, verdict=verdict)
        return JudgeCall(verdict, FALLBACK_JUDGE_LINE, None)
    _log_ok("wolves_judge", model, verdict=verdict)
    line = sanitize_utterance(raw.line, max_words=LINE_MAX_WORDS, fallback=FALLBACK_JUDGE_LINE)
    return JudgeCall(verdict, line, _checked_marker(raw.cited_marker, state))


async def generate_ticker(
    state: MatchState,
    *,
    llm: ports.LlmPort | None = None,
) -> str:
    """Газета конца слота. Сбой → FALLBACK_TICKER."""
    slot_result = build_slot_result(state)
    return await _say(
        "wolves_ticker",
        tail=slot_result,
        cue="Заголовок в номер:",
        max_words=TICKER_MAX_WORDS,
        fallback=FALLBACK_TICKER,
        cache_key=f"ticker:{hashlib.sha256(slot_result.encode()).hexdigest()[:24]}",
        metadata={"room_seed": state.seed, "slot": state.slot_index},
        llm=llm,
    )


async def generate_bark(
    state: MatchState,
    seat_id: str,
    *,
    llm: ports.LlmPort | None = None,
) -> str:
    """Реакция кандидата на свой штамп — секунда речи там, где раньше молча падала печать."""
    persona = persona_for(state, seat_id)
    stamp = state.stamps_this_slot.get(seat_id)
    return await _say(
        "wolves_bark",
        tail=build_bark_context(state, seat_id),
        cue="Твоя реакция:",
        max_words=BARK_MAX_WORDS,
        fallback=FALLBACK_BARK,
        temperature=persona.temperature,
        cache_key=f"bark:{uuid.uuid4().hex}",
        metadata={
            "room_seed": state.seed,
            "seat": seat_id,
            "stamp": stamp.value if stamp is not None else "",
        },
        llm=llm,
    )


async def generate_brief(
    state: MatchState,
    *,
    llm: ports.LlmPort | None = None,
) -> str:
    """Сцена слота: одна строка про сегодняшний день кабинета (режиссёр)."""
    tail = build_brief_context(state)
    return await _say(
        "wolves_brief",
        tail=tail,
        cue="Объявляй день:",
        max_words=BRIEF_MAX_WORDS,
        fallback=FALLBACK_BRIEF,
        cache_key=f"brief:{hashlib.sha256(tail.encode()).hexdigest()[:24]}",
        metadata={"room_seed": state.seed, "slot": state.slot_index},
        llm=llm,
    )


def bot_seat_ids_needing_line(state: MatchState) -> list[str]:
    if state.phase.value != "lines" or not state.question_chip:
        return []
    out: list[str] = []
    for seat in state.seats.values():
        if seat.kind != SeatKind.CANDIDATE or not seat.filled or not seat.is_bot:
            continue
        if seat.id in state.answers or seat.id in state.stamps_this_slot:
            continue
        out.append(seat.id)
    return sorted(out)


def bot_seat_ids_needing_bark(state: MatchState) -> list[str]:
    """Боты, которым штамп уже поставили, а сказать в ответ они ещё ничего не успели."""
    out: list[str] = []
    for seat_id in state.stamps_this_slot:
        seat = state.seats.get(seat_id)
        if seat is None or not seat.is_bot or not seat.filled:
            continue
        if seat_id in state.stamp_reactions:
            continue
        out.append(seat_id)
    return sorted(out)


__all__ = [
    "LINE_MAX_WORDS",
    "TICKER_MAX_WORDS",
    "BARK_MAX_WORDS",
    "BRIEF_MAX_WORDS",
    "STREAM_MIN_INTERVAL_S",
    "FALLBACK_BOT_LINE",
    "FALLBACK_JUDGE_LINE",
    "FALLBACK_TICKER",
    "FALLBACK_BARK",
    "FALLBACK_BRIEF",
    "LineDelta",
    "Persona",
    "JudgeCall",
    "persona_for",
    "word_count",
    "truncate_words",
    "contains_slop",
    "anglicisms_in",
    "unwrap_model_text",
    "sanitize_utterance",
    "build_line_context",
    "build_judge_evidence",
    "judge_evidence_hash",
    "build_slot_result",
    "build_bark_context",
    "build_brief_context",
    "stream_bot_line",
    "generate_bot_line",
    "generate_judge",
    "generate_ticker",
    "generate_bark",
    "generate_brief",
    "bot_seat_ids_needing_line",
    "bot_seat_ids_needing_bark",
]
