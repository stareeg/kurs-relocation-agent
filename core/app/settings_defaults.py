"""Полный набор дефолтов `app_settings`/`account_settings`, собранный из доменов.

Отдельно от `core.platform.repo.settings` намеренно: та часть — чистая инфраструктура
(read/write jsonb-строки, без знания о доменах), а `default_app_settings_values()` ниже
собирает готовые дефолты из `profile` (веса/резюме уже не хардкод — E-02/A-21) и других
доменов. `app` может зависеть от доменов, `platform` — нет (docs/ARCHITECTURE.md, «Правила
зависимостей»).
"""

from __future__ import annotations

from typing import Any

from core.platform.repo.settings import DEFAULT_COMPANY_ADJUSTMENTS


def default_app_settings_values() -> dict[str, Any]:
    from core.domains.opportunities.discovery_session import default_discovery_config_dict
    from core.domains.pipeline.auto_apply import default_auto_apply_config_dict
    from core.domains.profile.anonymize import default_disclosure_policy_dict
    from core.domains.profile.profile import default_candidate_profile_setting
    from core.domains.profile.skill_suggest import (
        DEFAULT_MIN_REFRESH_INTERVAL_HOURS as _skills_min_refresh_interval_hours,
    )
    from core.domains.profile.skill_suggest import (
        DEFAULT_NEW_VACANCIES_THRESHOLD as _skills_new_vacancies_threshold,
    )
    from core.domains.profile.skills_corpus import DEFAULT_MIN_SCORE as _skills_min_score
    from core.domains.profile.telegram_prefs import default_telegram_prefs_dict

    return {
        # scoring_weights/scoring_importance НЕ здесь (Этап 8 §8.5, D14): скоринг с переходом на
        # derive_auto_scoring_weights их не читает — это не управляемый продуктовый дефолт, а
        # инертный API-round-trip прошлого поколения (веса теперь выводятся из резюме). GET
        # /api/settings по-прежнему отдаёт исходное значение через DEFAULT_SCORING_WEIGHTS
        # напрямую (см. api/routers/profile/settings.py) — фронт всё ещё показывает его как
        # «X из Y» в разборе балла (`useScoringWeights`), поэтому строку из ответа не убираем.
        "company_adjustments": DEFAULT_COMPANY_ADJUSTMENTS,
        "salary_min_override": None,
        "skills_selection_min_score": _skills_min_score,
        # E-02: порог автопересборки снимка навыков и нижняя граница между пересборками.
        "skills_snapshot_new_vacancies_threshold": _skills_new_vacancies_threshold,
        "skills_snapshot_min_interval_hours": _skills_min_refresh_interval_hours,
        # A-21: карьерный слой CandidateProfile (без хардкода владельца).
        "candidate_profile": default_candidate_profile_setting(),
        # TB-2.1: пуши бота (дайджест / прогрев / стиль карточки / уборка батча).
        "telegram_prefs": default_telegram_prefs_dict(),
        # Автоотклики (hh/getmatch/habr) — выключено везде по умолчанию, см.
        # core/domains/pipeline/auto_apply/README.md.
        "auto_apply_config": default_auto_apply_config_dict(),
        # Discovery (авто-открытие вакансий фоновыми вкладками) — выключено везде по умолчанию,
        # см. core/domains/opportunities/discovery_session.py.
        "discovery_config": default_discovery_config_dict(),
        # Э4.2 dual_employment_and_contracting_2026.md: что скрывать в исходящих письмах под
        # международный рынок (текущий работодатель по умолчанию скрыт).
        "disclosure_policy": default_disclosure_policy_dict(),
    }


__all__ = ["default_app_settings_values"]
