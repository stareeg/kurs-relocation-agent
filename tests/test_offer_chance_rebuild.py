"""Пересборка методики «Шанс офферов» (2026-08-09): якоря не хардкод под владельца,
градиентные сигналы воронки вместо бинарных, min-data gate, перераспределение весов
при отсутствии данных (не «баллы из воздуха»).

Чистые тесты над `compute_offer_chance` — без БД, как остальные unit-тесты домена market.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

from core.domains.market.pulse import (
    APPLICATIONS_TARGET,
    LEVEL_POINTS,
    NEW_30D_TARGET,
    RESPONSE_RATE_TARGET,
    SCORED_7D_TARGET,
    TOPIC_SATURATION_TARGET,
    _DAMPING_FLOOR,
    _MIN_APPLIED,
    _application_days_signals,
    _apply_progress_shift,
    _latest_topic_levels,
    _log_norm,
    _Offer,
    _progress_level,
    _skill_signal,
    _weighted_offer_signal,
    OfferChanceInput,
    compute_offer_chance,
)
from core.kernel.schemas.funnel import FunnelStatus


def _full_input(**overrides) -> OfferChanceInput:
    """Полный вход «сильная позиция»: 30 откликов, 33% ответов, 5 скринингов, 1 оффер,
    рынок под тебя, хорошее резюме, активность, уверенная техготовность (competency).
    Поля переопределяются через kwargs.
    """
    base = dict(
        response_rate=0.33,
        applied=30,
        interviewing=5,
        rejected=8,
        weighted_offer_signal=2.0,
        avg_score=70.0,
        gate_both=8,
        gate_total=20,
        salary_meets_pct=60.0,
        real_remote=15,
        measured_remote=20,
        resume_quality_total=75,
        new_30d=30,
        scored_7d=15,
        skill_topics={"python": "confident", "sql": "medium"},
    )
    base.update(overrides)
    return OfferChanceInput(**base)


def test_bootstrap_no_data_is_zero():
    """Нет вообще никаких данных — честный 0, не «баллы из воздуха»."""
    inp = OfferChanceInput(
        response_rate=None,
        applied=0,
        interviewing=0,
        rejected=0,
        weighted_offer_signal=0.0,
        avg_score=0.0,
        gate_both=0,
        gate_total=0,
        salary_meets_pct=0.0,
        real_remote=0,
        measured_remote=0,
    )
    r = compute_offer_chance(inp)
    assert r.score == 0
    assert r.preliminary is True
    # Все факторы обнулены.
    assert all(c.contribution == 0.0 for c in r.components)


def test_empty_funnel_does_not_give_air_points():
    """Пустая воронка (applied=0), но техготовность + рынок + резюме есть — композит держат
    только они, не «нейтральные 0.4» старой логики. Score > 0 только из-за skill/market/
    resume_quality, веса funnel/depth/activity обнулены и перераспределены.
    """
    inp = _full_input(
        applied=0,
        response_rate=None,
        interviewing=0,
        weighted_offer_signal=0.0,
        new_30d=0,
        scored_7d=0,
    )
    r = compute_offer_chance(inp)
    weights = {c.key: c.weight for c in r.components}
    assert weights["funnel"] == 0.0
    assert weights["depth"] == 0.0
    assert weights["activity"] == 0.0
    # Рынок и качество резюме получили перераспределённый вес (> исходных базовых 0.15/0.15).
    assert weights["market"] > 0.15
    assert weights["resume_quality"] > 0.15
    # Сумма весов ≈ 1.0 (перераспределение сохраняет норму, допускаем округление до 4 знаков).
    assert round(sum(weights.values()), 3) == 1.0


def test_min_applied_marks_preliminary():
    """Меньше _MIN_APPLIED откликов — preliminary=True (фронт рисует пунктир)."""
    inp = _full_input(applied=_MIN_APPLIED - 1)
    r = compute_offer_chance(inp)
    assert r.preliminary is True
    inp_enough = _full_input(applied=_MIN_APPLIED)
    assert compute_offer_chance(inp_enough).preliminary is False


def test_graded_funnel_signals_not_binary():
    """Один скрининг ≠ несколько: градиентный сигнал насыщается плавно, не прыгает.

    Старая логика: interview_sig = 1.0 if interviewing > 0 — 1 и 50 скринингов давали
    одинаковый вклад. Теперь log1p — вклад funnel-фактора строго растёт с interviewing.
    Проверяем суб-балл funnel-компонента (не итоговый score — он насыщается другими факторами).
    """
    one = compute_offer_chance(_full_input(interviewing=1))
    two = compute_offer_chance(_full_input(interviewing=2))
    three = compute_offer_chance(_full_input(interviewing=3))
    f_one = next(c for c in one.components if c.key == "funnel").score
    f_two = next(c for c in two.components if c.key == "funnel").score
    f_three = next(c for c in three.components if c.key == "funnel").score
    assert f_one < f_two < f_three, f"ожидали строгий рост funnel: {f_one} < {f_two} < {f_three}"


def test_graded_offer_signal_not_binary():
    """Слабый offer-сигнал ≠ сильный — градиентный offer_sig (log1p), не бинарный 0/1."""
    one = _full_input(weighted_offer_signal=0.5)
    ten = _full_input(weighted_offer_signal=5.0)
    # weighted_offer_signal > 0 в обоих, но вклад должен расти.
    assert compute_offer_chance(one).score < compute_offer_chance(ten).score


def test_full_strong_position_scores_high():
    """Полная сильная позиция (всё есть, цифры крепкие) — score заметно выше середины."""
    r = compute_offer_chance(_full_input())
    assert r.score >= 70, f"сильная позиция ожидала >=70, получили {r.score}"
    assert r.preliminary is False


def test_weights_sum_to_one_with_full_data():
    """При всех данных сумма весов = 1.0 (никакого перераспределения)."""
    r = compute_offer_chance(_full_input())
    assert round(sum(c.weight for c in r.components), 4) == 1.0


# --- Шаг 6: интеграция skill/веса §1/`_apply_progress_shift` в `compute_offer_chance` ---


def test_weights_table_matches_plan_section_1():
    """`_WEIGHTS` — ровно 7 факторов §1 плана, сумма базовых весов = 1.0."""
    from core.domains.market.pulse import _WEIGHTS

    by_key = {k: w for k, _, w in _WEIGHTS}
    assert by_key == {
        "funnel": 0.25,
        "skill": 0.25,
        "resume_quality": 0.15,
        "market": 0.15,
        "applications": 0.08,
        "activity": 0.07,
        "depth": 0.05,
    }
    assert round(sum(by_key.values()), 6) == 1.0


def test_skill_factor_present_and_zeroed_without_competency_data():
    """`skill` — настоящий компонент композита (не заглушка): есть без competency-данных
    (зануляется через `has_data`, вес перераспределяется) и весит > 0, когда темы есть."""
    without = compute_offer_chance(_full_input(skill_topics={}))
    with_data = compute_offer_chance(_full_input())
    w_without = next(c for c in without.components if c.key == "skill")
    w_with = next(c for c in with_data.components if c.key == "skill")
    assert w_without.weight == 0.0
    assert w_without.score == 0.0
    assert w_with.weight > 0.0
    assert w_with.score > 0.0


def test_stronger_skill_data_raises_score_at_equal_weight():
    """Тот же охват тем (значит, тот же вес фактора), но выше уровень — итоговый score выше:
    седьмой фактор реально что-то весит в композите, не просто присутствует в списке компонентов."""
    weak = compute_offer_chance(_full_input(skill_topics={"python": "weak", "sql": "weak"}))
    confident = compute_offer_chance(
        _full_input(skill_topics={"python": "confident", "sql": "confident"})
    )
    assert confident.score > weak.score


def test_progress_shift_wired_into_compute_offer_chance():
    """§1.3 подключён: прогресс до Финала/Оффера двигает эффективный вес `funnel` вверх
    относительно позиции без прогресса (только «Отклик»), при прочих равных."""
    low_progress = compute_offer_chance(
        _full_input(interviewing=0, weighted_offer_signal=0.0, responded=0, reached_final=False)
    )
    peak_progress = compute_offer_chance(
        _full_input(interviewing=0, weighted_offer_signal=0.0, responded=0, reached_final=True)
    )
    w_low = next(c for c in low_progress.components if c.key == "funnel").weight
    w_peak = next(c for c in peak_progress.components if c.key == "funnel").weight
    assert w_peak > w_low


def test_response_rate_target_not_owner_hardcoded():
    """Якорь response_rate не заниженный 0.30 (старый owner-hardcode) — теперь 0.20 (либеральный).

    Это часть no-owner-hardcode правила: PM/junior/не-удалёнщик не должны получать заниженный скор
    из-за якоря, подобранного под senior-IC-remote владельца.
    """
    assert RESPONSE_RATE_TARGET == 0.20  # не 0.30 (старый owner-калиброванный)


def test_anchors_present_and_reasonable():
    """Ключевые якоря существуют и в разумном диапазоне (не вырождены в 0/бесконечность)."""
    for anchor in (RESPONSE_RATE_TARGET, APPLICATIONS_TARGET, NEW_30D_TARGET, SCORED_7D_TARGET):
        assert anchor > 0
    assert _MIN_APPLIED > 0


def test_preliminary_field_exists_on_response():
    """OfferChance.preliminary — новое поле, фронт по нему рисует пунктир."""
    r = compute_offer_chance(_full_input())
    assert hasattr(r, "preliminary")
    assert isinstance(r.preliminary, bool)


def test_log_norm_saturation_shape():
    """_log_norm: 0 в нуле, ~1.0 в target, >1.0 дальше (clamp в 1.0)."""
    assert _log_norm(0, 5) == 0.0
    assert round(_log_norm(5, 5), 2) == 1.0  # в точке target
    assert _log_norm(50, 5) == 1.0  # clamp
    # Плавный рост между 0 и target.
    assert 0.0 < _log_norm(1, 5) < _log_norm(3, 5) < 1.0


def test_delta_does_not_break_build():
    """build_pulse всё ещё собирается с новой методикой (delta ставится отдельно)."""
    # Не тянем БД — только проверяем, что импорт и сигнатура живы.
    from core.domains.market.pulse import build_pulse, compute_offer_chance

    assert callable(compute_offer_chance)
    assert callable(build_pulse)
    sig = inspect.signature(compute_offer_chance)
    assert "inp" in sig.parameters


def test_weighted_offer_signal_dedups_by_vacancy_and_weighs_by_confidence():
    """Шаг 2 offer_chance_rework: устный/письменный/подписанный офферы весят по-разному,
    вакансия с обоими признаками (дошла до Оффера И есть запись) учитывается один раз."""
    funnel_jobs = [(1, None), (2, None), (3, None)]
    funnel_stages = [
        (1, FunnelStatus.OFFER, datetime(2026, 8, 1, tzinfo=UTC)),  # verbal-only
        (3, FunnelStatus.OFFER, datetime(2026, 8, 1, tzinfo=UTC)),  # + accepted OfferRecord
    ]
    vacancy_id_by_job = {1: "v1", 2: "v2", 3: "v3"}
    offers_by_vacancy = {
        "v2": _Offer(status="thinking", created_at=None, vacancy_id="v2", raw_text="письмо от HR"),
        "v3": _Offer(status="accepted", created_at=None, vacancy_id="v3", raw_text="письмо от HR"),
    }
    total = _weighted_offer_signal(funnel_jobs, funnel_stages, vacancy_id_by_job, offers_by_vacancy)
    # v1 verbal (0.5) + v2 written (0.85) + v3 signed (1.0), не 4 отдельных сигнала.
    assert total == 0.5 + 0.85 + 1.0


def test_weighted_offer_signal_no_data_is_zero():
    """Ни одна вакансия не дошла до Оффера и нет записей — честный 0, не «баллы из воздуха»."""
    total = _weighted_offer_signal([(1, None)], [], {1: "v1"}, {})
    assert total == 0.0


def test_latest_topic_levels_dedups_keeping_freshest():
    """§1.2 Шаг 3: несколько прогонов по одной теме — берём самый свежий уровень, не среднее."""
    rows = [
        ("python", "weak", datetime(2026, 1, 1, tzinfo=UTC)),
        ("python", "confident", datetime(2026, 6, 1, tzinfo=UTC)),  # свежее
        ("sql", "medium", datetime(2026, 3, 1, tzinfo=UTC)),
    ]
    assert _latest_topic_levels(rows) == {"python": "confident", "sql": "medium"}


def test_skill_signal_no_topics_is_zero():
    """0 тем в периоде (кандидат не проходил интервью с извлечённой competency-картой) → 0.0,
    не нейтральный балл «из воздуха» — вызывающий (интеграция в Шаге 6) решает has_data сам."""
    assert _skill_signal({}) == 0.0


def test_skill_signal_higher_level_scores_higher_at_equal_coverage():
    """Один и тот же охват (1 тема), но выше уровень — выше суб-балл."""
    weak = _skill_signal({"python": "weak"})
    medium = _skill_signal({"python": "medium"})
    confident = _skill_signal({"python": "confident"})
    assert weak < medium < confident


def test_skill_signal_saturates_with_topic_coverage_not_binary():
    """Одна тема на confident ≠ шесть тем на confident — та же средняя оценка (avg_ratio=1.0),
    но охват растёт саturation-множитель (0.5 + 0.5·saturation), не бинарный скачок."""
    one_topic = _skill_signal({"a": "confident"})
    six_topics = _skill_signal({f"t{i}": "confident" for i in range(TOPIC_SATURATION_TARGET)})
    assert 0.0 < one_topic < six_topics <= 1.0


def test_level_points_and_saturation_target_reasonable():
    """Якоря существуют и упорядочены по возрастанию (confident > medium > weak)."""
    assert LEVEL_POINTS["confident"] > LEVEL_POINTS["medium"] > LEVEL_POINTS["weak"] > 0
    assert TOPIC_SATURATION_TARGET > 0


# --- §1.3 Шаг 4: динамический сдвиг весов по стадии воронки (_progress_level / _apply_progress_shift) ---


def test_progress_level_stage_thresholds():
    """Ступень прогресса — по самой дальней фактически достигнутой стадии воронки."""
    assert (
        _progress_level(
            reached_final=False, weighted_offer_signal=0.0, interviewing=0, responded=0
        )
        == 0.0
    )
    assert (
        _progress_level(
            reached_final=False, weighted_offer_signal=0.0, interviewing=0, responded=3
        )
        == 0.33
    )
    assert (
        _progress_level(
            reached_final=False, weighted_offer_signal=0.0, interviewing=2, responded=3
        )
        == 0.66
    )
    assert (
        _progress_level(
            reached_final=True, weighted_offer_signal=0.0, interviewing=0, responded=0
        )
        == 1.0
    )


def test_progress_level_offer_signal_alone_maxes_out():
    """Ненулевой offer-сигнал (даже устный) даёт максимум прогресса без «Финала» в истории —
    кейс «Сбер»: не всегда через Финал доходит вакансия до Оффера."""
    assert (
        _progress_level(
            reached_final=False, weighted_offer_signal=0.5, interviewing=0, responded=0
        )
        == 1.0
    )


_TARGET_WEIGHTS: dict[str, float] = {
    "funnel": 25.0,
    "skill": 25.0,
    "resume_quality": 15.0,
    "market": 15.0,
    "applications": 8.0,
    "activity": 7.0,
    "depth": 5.0,
}


def test_apply_progress_shift_zero_level_is_noop():
    """progress_level=0.0 — веса не меняются (нет прогресса — нет сдвига)."""
    assert _apply_progress_shift(_TARGET_WEIGHTS, 0.0) == _TARGET_WEIGHTS


def test_apply_progress_shift_peak_moves_volume_pool_into_progress_pool():
    """progress_level=1.0 (пик) — весь сдвиг (8 п.п.) перетекает из объёма (applications+
    activity) в прогресс (funnel+skill), поровну между funnel/skill (равные базовые веса);
    resume_quality/market/depth не трогаются; сумма весов сохраняется."""
    shifted = _apply_progress_shift(_TARGET_WEIGHTS, 1.0)
    assert shifted["funnel"] == 29.0
    assert shifted["skill"] == 29.0
    assert shifted["resume_quality"] == 15.0
    assert shifted["market"] == 15.0
    assert shifted["depth"] == 5.0
    assert round(shifted["applications"], 4) == round(8.0 - 8.0 * (8.0 / 15.0), 4)
    assert round(shifted["activity"], 4) == round(7.0 - 8.0 * (7.0 / 15.0), 4)
    assert round(sum(shifted.values()), 6) == round(sum(_TARGET_WEIGHTS.values()), 6)


def test_apply_progress_shift_is_linear_in_progress_level():
    """Промежуточная ступень — сдвиг ровно пропорционален progress_level (0.66 от пика)."""
    peak = _apply_progress_shift(_TARGET_WEIGHTS, 1.0)
    mid = _apply_progress_shift(_TARGET_WEIGHTS, 0.66)
    for key in _TARGET_WEIGHTS:
        expected = _TARGET_WEIGHTS[key] + 0.66 * (peak[key] - _TARGET_WEIGHTS[key])
        assert round(mid[key], 6) == round(expected, 6)


def test_apply_progress_shift_ignores_missing_keys():
    """Урезанная таблица весов (без skill/depth и т.п.) — недостающие ключи тихо пропускаются,
    не падаем с KeyError."""
    partial = {"funnel": 25.0, "applications": 8.0}
    shifted = _apply_progress_shift(partial, 1.0)
    assert shifted["funnel"] > 25.0
    assert shifted["applications"] < 8.0


# --- §1.4 Шаг 5: дисконт «Отклики»/«Активность» при нулевой конверсии ---


def test_zero_conversion_discounts_applications_and_activity_to_floor():
    """Высокий `applied` + `response_rate=0` — льём воду мимо цели: суб-баллы «Отклики»/
    «Активность» придавлены к полу 0.4 от недисконтированного значения, не к нулю."""
    full = _full_input(response_rate=0.33)
    zero_conversion = _full_input(response_rate=0.0)
    r_full = compute_offer_chance(full)
    r_zero = compute_offer_chance(zero_conversion)
    apps_full = next(c for c in r_full.components if c.key == "applications").score
    apps_zero = next(c for c in r_zero.components if c.key == "applications").score
    act_full = next(c for c in r_full.components if c.key == "activity").score
    act_zero = next(c for c in r_zero.components if c.key == "activity").score
    assert round(apps_zero, 3) == round(apps_full * _DAMPING_FLOOR, 3)
    assert round(act_zero, 3) == round(act_full * _DAMPING_FLOOR, 3)
    assert apps_zero > 0.0
    assert act_zero > 0.0


def test_no_response_rate_data_does_not_discount():
    """`response_rate is None` — не штраф (недостаток данных, не «нулевая конверсия»):
    суб-балл «Отклики» не отличается от недисконтированного (conversion_mult=1.0)."""
    inp = _full_input(response_rate=None)
    r = compute_offer_chance(inp)
    apps = next(c for c in r.components if c.key == "applications").score
    assert round(apps, 3) == round(_log_norm(float(inp.applied), APPLICATIONS_TARGET), 3)


def test_partial_conversion_discount_between_floor_and_one():
    """Промежуточная конверсия (между 0 и target) — дисконт строго между полом 0.4 и 1.0."""
    full = _full_input(response_rate=RESPONSE_RATE_TARGET)
    half = _full_input(response_rate=RESPONSE_RATE_TARGET / 2)
    apps_full = next(c for c in compute_offer_chance(full).components if c.key == "applications").score
    apps_half = next(c for c in compute_offer_chance(half).components if c.key == "applications").score
    assert 0.0 < apps_half < apps_full


# --- Правка 2026-08-14: «Отклики» (динамика) + «Общение» (скорость Чатов) ---


def test_applications_respond_to_daily_regularity_not_just_volume():
    """«Отклики» реагируют на регулярность, не только на объём (правка 2026-08-14).

    Тот же объём `applied` за тот же период, но разбросанный по большему числу дней —
    выше суб-балл «Отклики»: система поощряет откликаться каждый день, а не «20 откликов
    в один день и тишина».
    """
    # 14 дней периода, 14 откликов: вариант А — все в один день (regularity=1/14),
    # вариант Б — по одному каждый день (regularity=14/14=1.0). Темп одинаковый (1/день),
    # разница только в регулярности.
    burst = _full_input(applied=14, application_days_active=1, application_days_total=14)
    daily = _full_input(applied=14, application_days_active=14, application_days_total=14)
    apps_burst = next(c for c in compute_offer_chance(burst).components if c.key == "applications").score
    apps_daily = next(c for c in compute_offer_chance(daily).components if c.key == "applications").score
    assert apps_daily > apps_burst


def test_applications_falls_back_to_volume_when_period_not_set():
    """Старые вызовы без application_days_* (период не задан) — фолбэк на объёмный сигнал,
    как раньше. Обратная совместимость для тестов/прямых вызовов."""
    inp = _full_input(application_days_active=0, application_days_total=0)
    r = compute_offer_chance(inp)
    apps = next(c for c in r.components if c.key == "applications").score
    assert round(apps, 3) == round(_log_norm(float(inp.applied), APPLICATIONS_TARGET), 3)


def test_activity_uses_chat_progress_ratio():
    """«Общение» — доля двигающихся тредов (chat_progressing / chat_active), не поток новых
    вакансий (правка 2026-08-14). Все треды двигаются — выше, чем половина зависла."""
    all_progress = _full_input(
        chat_active_threads=10, chat_stalled_threads=0, chat_progressing_threads=10
    )
    half_stalled = _full_input(
        chat_active_threads=10, chat_stalled_threads=5, chat_progressing_threads=5
    )
    act_all = next(c for c in compute_offer_chance(all_progress).components if c.key == "activity").score
    act_half = next(c for c in compute_offer_chance(half_stalled).components if c.key == "activity").score
    assert act_all > act_half


def test_activity_falls_back_to_new_vacancies_when_no_chats():
    """Нет chat_* сигналов, но есть new_30d/scored_7d — фолбэк на старую потоковую логику,
    чтобы не занулять фактор для аккаунтов, где Чаты ещё не используются."""
    inp = _full_input(
        chat_active_threads=0, chat_stalled_threads=0, chat_progressing_threads=0,
        new_30d=30, scored_7d=15,
    )
    r = compute_offer_chance(inp)
    act = next(c for c in r.components if c.key == "activity").score
    assert act > 0.0


def test_activity_zero_when_no_chats_and_no_new_vacancies():
    """Ни Чатов, ни новых вакансий — фактор «Общение» занулён через has_data, не «баллы из воздуха»."""
    inp = _full_input(
        chat_active_threads=0, chat_stalled_threads=0, chat_progressing_threads=0,
        new_30d=0, scored_7d=0,
    )
    r = compute_offer_chance(inp)
    act = next(c for c in r.components if c.key == "activity")
    assert act.score == 0.0
    assert act.weight == 0.0


# --- _application_days_signals (правка 2026-08-14) ---


def test_application_days_signals_counts_distinct_active_days_in_window():
    """Сколько разных дней пользователь откликался в периоде — чистая функция над строками."""
    now = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
    start = now - timedelta(days=14)
    rows = [
        # Два отклика в один день (10 авг 10:00 и 10 авг 15:00) — считаются как 1 активный день.
        {"stage": FunnelStatus.APPLIED, "changed_at": datetime(2026, 8, 10, 10, 0, tzinfo=UTC)},
        {"stage": FunnelStatus.APPLIED, "changed_at": datetime(2026, 8, 10, 15, 0, tzinfo=UTC)},
        {"stage": FunnelStatus.APPLIED, "changed_at": datetime(2026, 8, 8, 12, 0, tzinfo=UTC)},
        {"stage": FunnelStatus.APPLIED, "changed_at": datetime(2026, 8, 5, 12, 0, tzinfo=UTC)},
        {"stage": FunnelStatus.SCREENING, "changed_at": datetime(2026, 8, 9, 12, 0, tzinfo=UTC)},  # не Отклик
        {"stage": FunnelStatus.APPLIED, "changed_at": datetime(2026, 7, 20, 12, 0, tzinfo=UTC)},  # вне окна
    ]
    active, total = _application_days_signals(rows, period_start=start, period_end=now)
    assert active == 3  # 3 разных дня (5, 8, 10 авг)
    assert total == 14


def test_application_days_signals_empty_when_no_applied_in_window():
    """Нет откликов в окне — 0 активных дней, длина периода всё равно считается."""
    now = datetime(2026, 8, 14, tzinfo=UTC)
    start = now - timedelta(days=7)
    rows = [{"stage": FunnelStatus.SCREENING, "changed_at": now - timedelta(days=1)}]
    active, total = _application_days_signals(rows, period_start=start, period_end=now)
    assert active == 0
    assert total == 7
