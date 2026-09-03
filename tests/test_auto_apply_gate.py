"""Гейт автооткликов: кто идёт auto/manual_review/excluded (Фаза 1, без реальной отправки).

`classify_for_auto_apply` — чистая функция, без БД: по спецификации владельца автоотклик
никогда не должен переписывать пропуск/company-avoid, и должен оставлять спорные вакансии
на ручной разбор, а не молча их отбрасывать вместе с явным «нет».
"""

from __future__ import annotations

from core.domains.opportunities.jobs import Job
from core.domains.pipeline.auto_apply.config import AutoApplyPlatformConfig
from core.domains.pipeline.auto_apply.gate import classify_for_auto_apply
from core.kernel.schemas.funnel import FunnelStatus

_ENABLED = AutoApplyPlatformConfig(enabled=True, min_score=75, manual_review_band=10)


def _job(**overrides) -> Job:
    base = dict(
        vacancy_id="1",
        vacancy_text="x" * 60,
        status=FunnelStatus.VIEWED.value,
        overall_score=None,
        recommendation=None,
        skipped=False,
    )
    base.update(overrides)
    return Job(**base)


def test_platform_disabled_excludes_everything():
    config = AutoApplyPlatformConfig(enabled=False, min_score=75)
    job = _job(overall_score=99)
    assert classify_for_auto_apply(job, config=config) == "excluded"


def test_high_score_is_auto():
    job = _job(overall_score=80)
    assert classify_for_auto_apply(job, config=_ENABLED) == "auto"


def test_score_exactly_at_threshold_is_auto():
    job = _job(overall_score=75)
    assert classify_for_auto_apply(job, config=_ENABLED) == "auto"


def test_borderline_score_is_manual_review():
    job = _job(overall_score=70)
    assert classify_for_auto_apply(job, config=_ENABLED) == "manual_review"


def test_any_score_below_threshold_is_manual_review():
    """Порог один (2026-09-01): всё ниже `min_score` разбирает человек, а не отбрасывается.
    Раньше полоса `manual_review_band` резала это на «спорные» и «слишком низкие» — второй
    ползунок в UI и тихая потеря вакансий между ними."""
    assert classify_for_auto_apply(_job(overall_score=50), config=_ENABLED) == "manual_review"
    assert classify_for_auto_apply(_job(overall_score=0), config=_ENABLED) == "manual_review"


def test_manual_review_band_is_ignored():
    """Легаси-поле конфига не влияет на решение — сохранённые значения ничего не меняют."""
    narrow = AutoApplyPlatformConfig(enabled=True, min_score=75, manual_review_band=0)
    assert classify_for_auto_apply(_job(overall_score=40), config=narrow) == "manual_review"


def test_no_score_is_excluded():
    job = _job(overall_score=None)
    assert classify_for_auto_apply(job, config=_ENABLED) == "excluded"


def test_skipped_vacancy_never_auto_even_with_top_score():
    """Пропуск побеждает высокий скор — автоотклик не может переписать решение «не подавать»."""
    job = _job(overall_score=100, skipped=True)
    assert classify_for_auto_apply(job, config=_ENABLED) == "excluded"


def test_company_avoid_gate_never_auto_even_with_top_score():
    """recommendation=skip (в т.ч. гейт по avoid_companies) — тоже жёсткий стоп."""
    job = _job(overall_score=100, recommendation="skip")
    assert classify_for_auto_apply(job, config=_ENABLED) == "excluded"


def test_already_progressed_job_is_excluded():
    """Уже «Отклик»/дальше по воронке — нечего откликать повторно."""
    job = _job(overall_score=100, status=FunnelStatus.APPLIED.value)
    assert classify_for_auto_apply(job, config=_ENABLED) == "excluded"


# --- override (Фаза E редизайна «Расширения», пункт 4: квик-экшен «переместить») -------------


def test_override_moves_low_score_to_auto():
    """Оверрайд побеждает порог скора в обе стороны, когда решение вообще легально."""
    job = _job(overall_score=50)
    assert classify_for_auto_apply(job, config=_ENABLED, override="auto") == "auto"


def test_override_moves_high_score_to_manual_review():
    job = _job(overall_score=95)
    assert classify_for_auto_apply(job, config=_ENABLED, override="manual_review") == "manual_review"


def test_override_does_not_revive_skipped_vacancy():
    """Оверрайд не переписывает пропуск/гейт — та же гарантия, что и у скора."""
    job = _job(overall_score=95, skipped=True)
    assert classify_for_auto_apply(job, config=_ENABLED, override="auto") == "excluded"


def test_override_does_not_revive_already_progressed_job():
    job = _job(overall_score=95, status=FunnelStatus.APPLIED.value)
    assert classify_for_auto_apply(job, config=_ENABLED, override="auto") == "excluded"


def test_no_override_falls_back_to_score_threshold():
    job = _job(overall_score=80)
    assert classify_for_auto_apply(job, config=_ENABLED, override=None) == "auto"
