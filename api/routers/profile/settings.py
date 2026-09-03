"""Раздел «Аккаунт»: чтение/частичное обновление настроек аккаунта.

GET /api/settings — текущие значения + состояние ключа OpenRouter (сам секрет не уходит:
только флаг наличия, происхождение и статус заявки).
PATCH /api/settings — частичное обновление; `openrouter_api_key` write-only (пустая строка =
очистить свой ключ, поле отсутствует = не трогать).
POST /api/settings/openrouter-key/request — заявка оператору на ключ (раньше — кнопка в боте).
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from api.schemas import (
    AppSettingsResponse,
    AppSettingsUpdate,
    CompanyAdjustment,
    DisclosurePolicy,
    FixedScoringWeights,
    OpenRouterKeyRequestResponse,
    ScoringImportance,
    ScoringWeights,
    TelegramPrefs,
)
from api.security import AccountContext, require_account, require_account_context
from core.app.settings_defaults import default_app_settings_values
from core.domains.opportunities.discovery_session import (
    discovery_config_from_mapping,
    set_discovery_config,
)
from core.domains.opportunities.score_breakdown import MANAGEMENT_WEIGHT, SALARY_WEIGHT
from core.domains.pipeline import auto_apply as auto_apply_settings
from core.domains.profile import anonymize as disclosure_settings
from core.domains.profile import telegram_prefs as tg_prefs
from core.platform import openrouter_keys
from core.platform.repo.settings import (
    DEFAULT_SCORING_WEIGHTS,
    get_setting,
    is_extension_confirmed,
    set_extension_confirmed,
    set_setting,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])

_WEIGHT_KEYS = ("salary", "work_format", "grade_match", "role_content", "management", "company")


def _validate_scoring_weights(weights: ScoringWeights) -> None:
    total = weights.total()
    if total != 100:
        raise HTTPException(
            status_code=400,
            detail=f"Сумма весов скоринга должна быть 100, получено {total}",
        )


def _importance_from_weights(weights: ScoringWeights) -> ScoringImportance:
    """Фолбэк для старых БД без scoring_importance: round(weight/5) ≈ уровни дефолта."""
    raw = {key: max(1, min(5, round(int(getattr(weights, key)) / 5))) for key in _WEIGHT_KEYS}
    return ScoringImportance.model_validate(raw)


def _validate_company_adjustments(rules: list[CompanyAdjustment]) -> None:
    seen_signatures: set[tuple[str, ...]] = set()
    seen_substrings: set[str] = set()
    for rule in rules:
        normalized = tuple(sorted(m.strip().lower() for m in rule.match if m.strip()))
        if not normalized:
            raise HTTPException(
                status_code=400,
                detail="У правила калибровки компаний должен быть хотя бы один непустой match",
            )
        if normalized in seen_signatures:
            raise HTTPException(
                status_code=400,
                detail=f"Дублирующееся правило калибровки: «{normalized[0]}»",
            )
        seen_signatures.add(normalized)
        for substring in normalized:
            if substring in seen_substrings:
                raise HTTPException(
                    status_code=400,
                    detail=f"Подстрока «{substring}» повторяется в нескольких правилах калибровки",
                )
            seen_substrings.add(substring)


async def _load_response(*, account_id: int | None) -> AppSettingsResponse:
    defaults = default_app_settings_values()
    # None у importance = ключа ещё нет → восстановить уровни из процентов (не подставлять
    # дефолт шкалы, иначе кастомные веса после reload выглядят как «сброс»).
    (
        raw_weights,
        raw_importance,
        raw_adjustments,
        salary_override,
        raw_tg_prefs,
        raw_auto_apply,
        raw_discovery,
        raw_disclosure,
    ) = await asyncio.gather(
        get_setting("scoring_weights", default=DEFAULT_SCORING_WEIGHTS, account_id=account_id),
        get_setting("scoring_importance", default=None, account_id=account_id),
        get_setting(
            "company_adjustments", default=defaults["company_adjustments"], account_id=account_id
        ),
        get_setting(
            "salary_min_override", default=defaults["salary_min_override"], account_id=account_id
        ),
        get_setting("telegram_prefs", default=defaults["telegram_prefs"], account_id=account_id),
        get_setting(
            "auto_apply_config", default=defaults["auto_apply_config"], account_id=account_id
        ),
        get_setting(
            "discovery_config", default=defaults["discovery_config"], account_id=account_id
        ),
        get_setting(
            "disclosure_policy", default=defaults["disclosure_policy"], account_id=account_id
        ),
    )
    try:
        scoring_weights = ScoringWeights.model_validate(raw_weights)
        if raw_importance is None:
            scoring_importance = _importance_from_weights(scoring_weights)
        else:
            try:
                scoring_importance = ScoringImportance.model_validate(raw_importance)
            except ValidationError:
                scoring_importance = _importance_from_weights(scoring_weights)
        company_adjustments = [CompanyAdjustment.model_validate(item) for item in raw_adjustments]
        telegram_prefs = TelegramPrefs.model_validate(
            tg_prefs.prefs_from_mapping(raw_tg_prefs).model_dump()
        )
        # AutoApplyConfig — та же модель, что в домене (api.schemas.auto_apply реэкспортирует
        # её как есть), поэтому без промежуточного dict-round-trip, в отличие от telegram_prefs.
        auto_apply_config = auto_apply_settings.auto_apply_config_from_mapping(raw_auto_apply)
        discovery_config = discovery_config_from_mapping(raw_discovery)
        disclosure_policy = DisclosurePolicy.model_validate(
            disclosure_settings.policy_from_mapping(raw_disclosure).model_dump()
        )
    except ValidationError as exc:
        logger.error("app_settings: некорректные данные в БД: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Параметры в БД повреждены — проверьте таблицу app_settings",
        ) from exc
    key_state = await openrouter_keys.key_state(account_id)
    return AppSettingsResponse(
        scoring_weights=scoring_weights,
        scoring_importance=scoring_importance,
        fixed_scoring_weights=FixedScoringWeights(
            salary=SALARY_WEIGHT, management=MANAGEMENT_WEIGHT
        ),
        company_adjustments=company_adjustments,
        salary_min_override=salary_override,
        openrouter_key_configured=key_state.configured,
        openrouter_key_set_at=key_state.issued_at,
        openrouter_key_origin=key_state.origin,
        openrouter_key_request_status=key_state.request_status,
        extension_confirmed=await is_extension_confirmed(account_id=account_id),
        telegram_prefs=telegram_prefs,
        auto_apply_config=auto_apply_config,
        discovery_config=discovery_config,
        disclosure_policy=disclosure_policy,
    )


@router.get("", response_model=AppSettingsResponse)
async def get_app_settings(
    account: AccountContext | None = Depends(require_account),
) -> AppSettingsResponse:
    """Текущие параметры приложения (без секрета OpenRouter)."""
    return await _load_response(account_id=account.account_id if account else None)


@router.patch("", response_model=AppSettingsResponse)
async def patch_app_settings(
    body: AppSettingsUpdate,
    account: AccountContext | None = Depends(require_account),
) -> AppSettingsResponse:
    """Частичное обновление параметров; невалидные веса/дубли компаний → 400."""
    fields_set = body.model_fields_set
    account_id = account.account_id if account else None

    if "scoring_weights" in fields_set and body.scoring_weights is not None:
        _validate_scoring_weights(body.scoring_weights)
        await set_setting(
            "scoring_weights", body.scoring_weights.model_dump(), account_id=account_id
        )

    if "scoring_importance" in fields_set and body.scoring_importance is not None:
        await set_setting(
            "scoring_importance", body.scoring_importance.model_dump(), account_id=account_id
        )
    elif "scoring_weights" in fields_set and body.scoring_weights is not None:
        # Старый клиент прислал только проценты — держим уровни в синхроне.
        await set_setting(
            "scoring_importance",
            _importance_from_weights(body.scoring_weights).model_dump(),
            account_id=account_id,
        )

    if "company_adjustments" in fields_set and body.company_adjustments is not None:
        _validate_company_adjustments(body.company_adjustments)
        await set_setting(
            "company_adjustments",
            [item.model_dump() for item in body.company_adjustments],
            account_id=account_id,
        )

    if "salary_min_override" in fields_set:
        await set_setting("salary_min_override", body.salary_min_override, account_id=account_id)

    if "openrouter_api_key" in fields_set:
        # Секрет, кэши и происхождение ключа пишет один вход — core.platform.openrouter_keys
        # (пустая строка = сброс своего ключа; ключ, выданный оператором, так не сбросить).
        key = body.openrouter_api_key
        cleaned = key.strip() if key and key.strip() else None
        try:
            if cleaned is None:
                await openrouter_keys.clear_own_key(account_id=account_id)
            else:
                await openrouter_keys.save_own_key(account_id=account_id, raw_key=cleaned)
        except openrouter_keys.OpenRouterKeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if "extension_confirmed" in fields_set and body.extension_confirmed is not None:
        await set_extension_confirmed(body.extension_confirmed, account_id=account_id)

    if "telegram_prefs" in fields_set and body.telegram_prefs is not None:
        await tg_prefs.set_telegram_prefs(
            tg_prefs.TelegramPrefs.model_validate(body.telegram_prefs.model_dump()),
            account_id=account_id,
        )

    if "auto_apply_config" in fields_set and body.auto_apply_config is not None:
        await auto_apply_settings.set_auto_apply_config(
            body.auto_apply_config, account_id=account_id
        )

    if "discovery_config" in fields_set and body.discovery_config is not None:
        await set_discovery_config(body.discovery_config, account_id=account_id)

    if "disclosure_policy" in fields_set and body.disclosure_policy is not None:
        await disclosure_settings.set_disclosure_policy(
            disclosure_settings.DisclosurePolicy.model_validate(
                body.disclosure_policy.model_dump()
            ),
            account_id=account_id,
        )

    return await _load_response(account_id=account_id)


@router.post("/openrouter-key/request", response_model=OpenRouterKeyRequestResponse)
async def post_openrouter_key_request(
    account: AccountContext = Depends(require_account_context),
) -> OpenRouterKeyRequestResponse:
    """«Запросить ключ» на «Аккаунте»: заявка оператору вместо кнопки в боте.

    Идемпотентна (см. `openrouter_keys.request_key`); оператора уведомляем только о реально
    новой заявке — повторный клик не должен слать ему второе сообщение.
    """
    outcome = await openrouter_keys.request_key(account_id=account.account_id)
    if outcome.status == "created":
        await openrouter_keys.notify_operator_about_request(requester_account_id=account.account_id)
    return OpenRouterKeyRequestResponse(status=outcome.status, message=outcome.message)
