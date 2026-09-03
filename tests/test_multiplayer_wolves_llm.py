"""Игровые LLM-фичи «Хрюш и Волков»: санитайзер, роли моделей, стрим, fallback.

Инвариант всех тестов ниже один: **партия не стопается и не меняет исход из-за модели**.
Провайдер лёг, ответил JSON'ом, наговорил слопа или молчит — стол продолжает играть.
"""

from __future__ import annotations

import pytest

from core.domains.multiplayer import llm as mp_llm
from core.domains.multiplayer import wolves_llm
from core.domains.multiplayer.deck import QUESTION_CHIP_PROMPTS
from core.domains.multiplayer.models import Phase, Stamp, SubRole, WolvesJudgeOut
from core.domains.multiplayer.rules import start_match
from core.kernel.errors import LlmError
from tests.fakes import FakeLlm


@pytest.fixture(autouse=True)
def _models_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Тесты про поведение фич, а не про настройку: модели считаем заданными."""
    monkeypatch.setattr(wolves_llm, "_llm_ready", lambda: True)
    monkeypatch.setattr(
        wolves_llm,
        "_model_for",
        lambda feature: f"test/{mp_llm.FEATURE_ROLE.get(feature, mp_llm.ROLE_DIRECTOR)}",
    )


def _lines_state(seed: int = 12, chip: str = "q_stack"):
    state = start_match(seed)
    state.phase = Phase.LINES
    state.question_chip = chip
    return state


def _any_candidate(state) -> str:
    return next(s.id for s in state.seats.values() if s.kind.value == "candidate")


# --- санитайзер ---------------------------------------------------------------


def test_truncate_words_hard_cap() -> None:
    text = "один два три четыре пять шесть семь восемь девять десять одиннадцать"
    out = wolves_llm.truncate_words(text, 5)
    assert out == "один два три четыре пять"
    assert wolves_llm.word_count(out) == 5


def test_sanitize_slop_falls_back() -> None:
    bad = "Мы предлагаем синергия и проактивность каждому"
    out = wolves_llm.sanitize_utterance(
        bad, max_words=wolves_llm.LINE_MAX_WORDS, fallback=wolves_llm.FALLBACK_BOT_LINE
    )
    assert out == wolves_llm.FALLBACK_BOT_LINE
    assert not wolves_llm.contains_slop(out)


def test_sanitize_extra_slop_phrases() -> None:
    for bad in (
        "Добро пожаловать в динамичная команда роста",
        "Ждём взаимовыгодное сотрудничество с вами",
    ):
        assert wolves_llm.contains_slop(bad)
        out = wolves_llm.sanitize_utterance(
            bad, max_words=wolves_llm.LINE_MAX_WORDS, fallback=wolves_llm.FALLBACK_TICKER
        )
        assert out == wolves_llm.FALLBACK_TICKER


def test_sanitize_truncates_long_line() -> None:
    words = " ".join(f"слово{i}" for i in range(30))
    out = wolves_llm.sanitize_utterance(
        words, max_words=wolves_llm.LINE_MAX_WORDS, fallback=wolves_llm.FALLBACK_BOT_LINE
    )
    assert wolves_llm.word_count(out) == wolves_llm.LINE_MAX_WORDS


def test_overlong_reply_is_cut_at_a_sentence_end() -> None:
    """Обрубок на полуслове читается как сбой, а не как реплика (живой прогон 2026-08-27)."""
    raw = "Робот отсёк — без стека. Зато вилку я всё равно закрыл на двести тысяч сверху"
    out = wolves_llm.sanitize_utterance(
        raw, max_words=wolves_llm.BARK_MAX_WORDS, fallback=wolves_llm.FALLBACK_BARK
    )
    assert out == "Робот отсёк — без стека."


def test_sentence_trim_keeps_hard_cut_when_nothing_would_be_left() -> None:
    """Если законченная фраза короче трёх слов («Да.») — лучше обрубок, чем куцая реплика."""
    raw = "Да. " + " ".join(f"слово{i}" for i in range(20))
    out = wolves_llm.sanitize_utterance(
        raw, max_words=wolves_llm.LINE_MAX_WORDS, fallback=wolves_llm.FALLBACK_BOT_LINE
    )
    assert out != "Да."
    assert wolves_llm.word_count(out) == wolves_llm.LINE_MAX_WORDS


@pytest.mark.parametrize(
    "raw",
    [
        '{"line": "Уронил прод в пятницу, поднял в девять."}',
        '```json\n{"line": "Уронил прод в пятницу, поднял в девять."}\n```',
        'Реплика: "Уронил прод в пятницу, поднял в девять."',
        '«Уронил прод в пятницу, поднял в девять.»',
        '{"line": "Уронил прод в пятницу, поднял в девять.',
    ],
)
def test_json_wrapper_is_stripped(raw: str) -> None:
    """Схем больше нет — обёртку снимаем сами, иначе игрок читает служебный JSON вслух.

    Модели тянет отвечать объектом даже без `response_format` (замер 2026-08-27: обе игровые
    модели так и делали, пока в промпте оставалось слово «JSON»).
    """
    out = wolves_llm.sanitize_utterance(
        raw, max_words=wolves_llm.LINE_MAX_WORDS, fallback=wolves_llm.FALLBACK_BOT_LINE
    )
    assert out.startswith("Уронил прод")
    assert "{" not in out and '"line"' not in out


def test_anglicisms_are_counted_not_swallowed() -> None:
    """Англицизм не должен ронять живую фразу в скучную заглушку — только логироваться."""
    line = "Мой ownership на проде был полным, лид не вмешивался."
    out = wolves_llm.sanitize_utterance(
        line, max_words=wolves_llm.LINE_MAX_WORDS, fallback=wolves_llm.FALLBACK_BOT_LINE
    )
    assert out != wolves_llm.FALLBACK_BOT_LINE
    assert wolves_llm.anglicisms_in(line) == ["ownership"]
    assert wolves_llm.anglicisms_in("Тащил сам, лид был в отпуске.") == []


# --- реплики кандидатов -------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_bot_line_fallback_on_llm_error() -> None:
    state = _lines_state(11)
    fake = FakeLlm(error=LlmError("провайдер 500"))
    line = await wolves_llm.generate_bot_line(state, _any_candidate(state), llm=fake)
    assert line == wolves_llm.FALLBACK_BOT_LINE
    assert fake.features == ["wolves_line"]


@pytest.mark.asyncio
async def test_bot_line_goes_to_the_actor_model() -> None:
    state = _lines_state(12, "q_incident")
    fake = FakeLlm(text="Поднял прод за ночь, постмортем утром.")
    line = await wolves_llm.generate_bot_line(state, _any_candidate(state), llm=fake)
    assert "прод" in line.casefold()
    assert fake.calls[0]["model_override"] == "test/actor"


@pytest.mark.asyncio
async def test_ticker_goes_to_the_director_model() -> None:
    state = start_match(16)
    state.phase = Phase.RESULT
    fake = FakeLlm(text="Оффер волку. Рынок плачет.")
    ticker = await wolves_llm.generate_ticker(state, llm=fake)
    assert wolves_llm.word_count(ticker) <= wolves_llm.TICKER_MAX_WORDS
    assert fake.calls[0]["model_override"] == "test/director"


@pytest.mark.asyncio
async def test_stream_bot_line_reports_progress_and_returns_full_line() -> None:
    """Стрим — это про ощущение стола: фраза печатается, а не всплывает готовой."""
    state = _lines_state(13)
    fake = FakeLlm(texts=["Уронил прод ", "в пятницу, ", "поднял в девять."])
    seen: list[str] = []

    async def on_delta(text: str) -> None:
        seen.append(text)

    monkey_interval = wolves_llm.STREAM_MIN_INTERVAL_S
    try:
        wolves_llm.STREAM_MIN_INTERVAL_S = 0.0  # без паузы между кадрами в тесте
        line = await wolves_llm.stream_bot_line(
            state, _any_candidate(state), on_delta=on_delta, llm=fake
        )
    finally:
        wolves_llm.STREAM_MIN_INTERVAL_S = monkey_interval

    assert line == "Уронил прод в пятницу, поднял в девять."
    assert seen, "ни одного кадра — игрок снова смотрит на пустой стол"
    assert seen[-1].endswith("девять.")
    assert fake.calls[0]["stream"] is True
    assert fake.calls[0]["model_override"] == "test/actor"


@pytest.mark.asyncio
async def test_stream_bot_line_falls_back_when_provider_dies() -> None:
    state = _lines_state(14)
    fake = FakeLlm(error=LlmError("оборвалось"))
    line = await wolves_llm.stream_bot_line(state, _any_candidate(state), llm=fake)
    assert line == wolves_llm.FALLBACK_BOT_LINE


@pytest.mark.asyncio
async def test_no_model_skips_llm_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wolves_llm, "_llm_ready", lambda: False)
    state = _lines_state(17)
    fake = FakeLlm(text="не должны увидеть")
    line = await wolves_llm.generate_bot_line(state, _any_candidate(state), llm=fake)
    assert line == wolves_llm.FALLBACK_BOT_LINE
    assert fake.calls == []


# --- суд ----------------------------------------------------------------------


def _judge_state(seed: int, *, marks: list[str], fraud: tuple[str, str] | None):
    """Состояние в фазе суда с известной подделкой у c0 — чтобы вердикт был предсказуем."""
    state = start_match(seed)
    state.phase = Phase.JUDGE
    state.pending_judge = True
    state.focus_candidate_id = "c0"
    state.discrepancy_marks = marks
    state.seats["c0"].fraud_pair = fraud
    return state


def _judge_out(line: str, marker: str) -> WolvesJudgeOut:
    return WolvesJudgeOut(line=line, cited_marker=marker)


@pytest.mark.asyncio
async def test_generate_judge_fallback_keeps_engine_verdict() -> None:
    """Падение модели меняет текст реплики, но не исход иска."""
    state = _judge_state(
        13, marks=["dates_mismatch", "stack_lie"], fraud=("stack_lie", "dates_mismatch")
    )
    fake = FakeLlm(error=LlmError("timeout"))
    call = await wolves_llm.generate_judge(state, llm=fake)
    assert call.verdict == "confirm", "иск верный — провайдер лёг, но вердикт движка не меняется"
    assert call.line == wolves_llm.FALLBACK_JUDGE_LINE
    assert call.marker is None


@pytest.mark.asyncio
async def test_judge_verdict_comes_from_engine_not_model() -> None:
    """Ключевой инвариант Э19: модель озвучивает вердикт, а не решает его.

    Подделка кандидата (`fraud_pair`) в улики не попадает и из них не выводится, поэтому
    раньше модель фактически бросала монету — а цена ошибки для игрока это выговор, три
    выговора = проигранная партия.
    """
    state = _judge_state(
        14, marks=["act_fake", "ip_surname"], fraud=("dates_mismatch", "team_size")
    )
    fake = FakeLlm(result=_judge_out("Подтверждаю: даты в акте и резюме пляшут.", "act_fake"))
    call = await wolves_llm.generate_judge(state, llm=fake)
    assert call.verdict == "reject", "улики не совпали с подделкой — иск мимо, что бы ни сказала модель"
    assert "пляшут" in call.line
    assert str(fake.calls[0].get("cache_key", "")).startswith("judge:")
    assert fake.calls[0]["model_override"] == "test/arbiter"
    assert fake.calls[0]["schema"] is WolvesJudgeOut


@pytest.mark.asyncio
async def test_judge_confirms_when_marks_match_fraud() -> None:
    state = _judge_state(15, marks=["act_fake", "ip_surname"], fraud=("ip_surname", "act_fake"))
    fake = FakeLlm(result=_judge_out("Печать плывёт, ФИО чужое. Вскрыт.", "ip_surname"))
    call = await wolves_llm.generate_judge(state, llm=fake)
    assert call.verdict == "confirm", "порядок улик не важен — важно совпадение пары"
    assert call.marker == "ip_surname"


@pytest.mark.asyncio
async def test_judge_cannot_cite_a_marker_that_was_not_filed() -> None:
    """Ради этого поля у судьи и есть schema: ссылку на улику можно сверить, фразу — нет.

    Подсветить игроку бумагу, которой в иске не было, хуже, чем не подсветить ничего:
    выглядит как решение движка, а не как оговорка модели.
    """
    state = _judge_state(16, marks=["act_fake", "ip_surname"], fraud=None)
    fake = FakeLlm(result=_judge_out("Календарь не сходится.", "calendar_clash"))
    call = await wolves_llm.generate_judge(state, llm=fake)
    assert call.line == "Календарь не сходится.", "текст остаётся — гасим только ссылку"
    assert call.marker is None


def test_judge_evidence_lists_marker_ids_for_the_model() -> None:
    """Модель может вернуть корректный id, только если он есть у неё перед глазами."""
    state = _judge_state(17, marks=["act_fake", "ip_surname"], fraud=None)
    evidence = wolves_llm.build_judge_evidence(state)
    assert 'id="act_fake"' in evidence
    assert 'id="ip_surname"' in evidence


def test_judge_evidence_states_the_engine_verdict() -> None:
    hit = _judge_state(25, marks=["act_fake", "ip_surname"], fraud=("act_fake", "ip_surname"))
    miss = _judge_state(25, marks=["act_fake", "ip_surname"], fraud=("dates_mismatch", "team_size"))
    assert "ИСК ВЕРНЫЙ" in wolves_llm.build_judge_evidence(hit)
    assert "ИСК МИМО" in wolves_llm.build_judge_evidence(miss)
    # Разный исход по тем же уликам обязан давать разный ключ кэша реплики.
    assert wolves_llm.judge_evidence_hash(
        wolves_llm.build_judge_evidence(hit)
    ) != wolves_llm.judge_evidence_hash(wolves_llm.build_judge_evidence(miss))


def test_evidence_hash_stable() -> None:
    a = wolves_llm.judge_evidence_hash("same")
    b = wolves_llm.judge_evidence_hash("same")
    c = wolves_llm.judge_evidence_hash("other")
    assert a == b
    assert a != c


# --- газета / реакции / сцена слота -------------------------------------------


@pytest.mark.asyncio
async def test_generate_ticker_fallback() -> None:
    state = start_match(15)
    state.phase = Phase.RESULT
    fake = FakeLlm(error=LlmError("down"))
    assert await wolves_llm.generate_ticker(state, llm=fake) == wolves_llm.FALLBACK_TICKER


def test_slot_result_speaks_russian_stamps() -> None:
    state = start_match(26)
    state.stamps_this_slot = {"c0": Stamp.REJECT, "c1": Stamp.OFFER}
    out = wolves_llm.build_slot_result(state)
    assert "ОТКАЗ" in out and "ОФФЕР" in out
    assert "c0=reject" not in out, "движковые ярлыки газета не печатает"


@pytest.mark.asyncio
async def test_bark_knows_which_stamp_landed() -> None:
    """Реакция должна быть на смысл штампа, а не на слово: контекст объясняет, что случилось."""
    state = start_match(27)
    state.phase = Phase.STAMP
    state.stamps_this_slot = {"c0": Stamp.REJECT}
    ctx = wolves_llm.build_bark_context(state, "c0")
    assert "ОТКАЗ" in ctx
    assert "при всех" in ctx

    fake = FakeLlm(text="Ну да. Четвёртый кабинет за неделю, все вежливые.")
    bark = await wolves_llm.generate_bark(state, "c0", llm=fake)
    assert wolves_llm.word_count(bark) <= wolves_llm.BARK_MAX_WORDS
    assert fake.calls[0]["model_override"] == "test/actor"


def test_bark_queue_only_covers_bots_without_a_reaction() -> None:
    state = start_match(28)
    state.stamps_this_slot = {"c0": Stamp.REJECT, "c1": Stamp.INTERVIEW}
    state.seats["c1"].is_bot = False
    assert wolves_llm.bot_seat_ids_needing_bark(state) == ["c0"]
    state.stamp_reactions["c0"] = "уже сказал"
    assert wolves_llm.bot_seat_ids_needing_bark(state) == []


@pytest.mark.asyncio
async def test_brief_is_director_work_and_never_invents_rules() -> None:
    state = start_match(29)
    ctx = wolves_llm.build_brief_context(state)
    assert "СЦЕНА" in ctx and "Выговоры хрюши" in ctx
    fake = FakeLlm(text="Бюджет заморожен, оффер закрыт. Смотрим людей на будущее.")
    brief = await wolves_llm.generate_brief(state, llm=fake)
    assert wolves_llm.word_count(brief) <= wolves_llm.BRIEF_MAX_WORDS
    assert fake.calls[0]["model_override"] == "test/director"


# --- сцена в контексте --------------------------------------------------------


def test_line_context_carries_the_scene() -> None:
    """Раньше в промпт уезжали только вопрос, фракция и day_label — модель отвечала «вообще
    про найм». Теперь в хвосте должны быть ставки, гейт слота и своя карта своими словами."""
    state = _lines_state(21)
    seat_id = _any_candidate(state)
    state.seats[seat_id].played = list(state.seats[seat_id].hand[:1])

    ctx = wolves_llm.build_line_context(state, seat_id)

    assert "СЦЕНА" in ctx and "ВОПРОС ХРЮШИ" in ctx
    assert "Выговоры хрюши" in ctx, "без ставок реплика не может быть про этот стол"
    assert QUESTION_CHIP_PROMPTS["q_stack"] in ctx, "вопрос должен быть формулировкой, не id"
    played = state.card_by_id[state.seats[seat_id].played[0]]
    assert played.title in ctx, "своя карта должна быть названием, а не тегом"
    assert f"{played.tag.value}:" not in ctx, "служебный тег движка в промпт не уезжает"
    assert wolves_llm.persona_for(state, seat_id).label in ctx


def test_line_context_tells_wolf_it_is_a_wolf() -> None:
    state = start_match(22)
    wolf = next(
        s for s in state.seats.values() if s.faction is not None and s.faction.value == "wolf"
    )
    human = next(
        s
        for s in state.seats.values()
        if s.kind.value == "candidate" and s.faction is not None and s.faction.value == "human"
    )
    assert "волк" in wolves_llm.build_line_context(state, wolf.id).casefold()
    assert "ты человек" in wolves_llm.build_line_context(state, human.id).casefold()


def test_line_context_carries_sub_role_and_pack() -> None:
    """Э19.8: место знало про себя две вещи (волк/человек и карты) — все амплуа звучали одинаково."""
    state = start_match(24)
    seat_id = _any_candidate(state)
    state.seats[seat_id].sub_role = SubRole.SECOND_SHIFT
    ctx = wolves_llm.build_line_context(state, seat_id)
    assert "уже где-то работаешь" in ctx

    # Стая: волк должен знать своих — иначе он играет в одиночную игру.
    wolves = [s for s in state.seats.values() if s.faction is not None and s.faction.value == "wolf"]
    for extra in [s for s in state.seats.values() if s.kind.value == "candidate"][:2]:
        extra.faction = wolves[0].faction
    pack_ctx = wolves_llm.build_line_context(state, wolves[0].id)
    assert "тоже волк" in pack_ctx


def test_persona_is_stable_within_match_and_varies_across_seats() -> None:
    state = start_match(23)
    seat_ids = [s.id for s in state.seats.values() if s.kind.value == "candidate"]
    first = {sid: wolves_llm.persona_for(state, sid) for sid in seat_ids}
    again = {sid: wolves_llm.persona_for(state, sid) for sid in seat_ids}
    assert first == again, "амплуа обязано держаться всю партию"

    # Разные партии — разные голоса. Проверяем по десятку сидов, а не по паре: мест за
    # столом мало, амплуа шесть, и совпадение на одном соседнем сиде — норма, а не регресс.
    across_seeds = {wolves_llm.persona_for(start_match(s), "c0").label for s in range(30, 40)}
    assert len(across_seeds) > 1, "амплуа не зависит от seed — все партии звучат одинаково"
