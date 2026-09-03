"""Настройки автооткликов (`app_settings.auto_apply_config`).

По дефолту выключено на всех площадках (см. README.md домена — Принцип L0/L1/L2/L3):
включение — осознанное действие владельца в «Расширении», не дефолт продукта. Разбито по
площадкам (hh/getmatch/habr) независимыми блоками — механика и риск бана у каждой свои,
общий тумблер «включить всё» скрыл бы это различие.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from core.platform.db.pool import Executor
from core.platform.repo.settings import get_setting, set_setting

logger = logging.getLogger(__name__)

KEY_AUTO_APPLY = "auto_apply_config"

AutoApplyPlatform = Literal["hh", "getmatch", "habr"]
# Фаза 6.1: "smart" — композитный ранг score - k*log(1+total_responses), не просто скор —
# свежая вакансия с малой конкуренцией обгоняет более скороценную, но уже разобранную
# конкурентами (см. `queue.py::_smart_rank_key`).
AutoApplyOrder = Literal["score_desc", "published_desc", "smart"]

# Жёсткий потолок реальных автооткликов на площадку в календарные сутки (2026-08-28, owner's
# spec). НЕ ручка пользователя — защита живого аккаунта от бана, а не тюнинг: слайдера в UI
# больше нет, `daily_cap` в конфиге игнорируется как потолок. hh отдаёт ~200 откликов/день,
# берём 150 с запасом; getmatch/habr — на порядок меньше вакансий, 30.
AUTO_APPLY_DAILY_HARD_CAP: dict[AutoApplyPlatform, int] = {
    "hh": 150,
    "getmatch": 30,
    "habr": 30,
}


def auto_apply_daily_hard_cap(platform: AutoApplyPlatform) -> int:
    """Потолок реальных автооткликов площадки в сутки — единственный источник `cap` для
    `GET /daily-count` и раннера. Неизвестная площадка → самый консервативный лимит."""
    return AUTO_APPLY_DAILY_HARD_CAP.get(platform, 30)


class AutoApplyPlatformConfig(BaseModel):
    """Настройки автооткликов одной площадки — независимая ручка на каждую."""

    model_config = ConfigDict(extra="ignore")

    enabled: bool = False
    # Фаза 2.2: обязательный первый режим — раннер доходит до финального клика и логирует
    # «кликнул бы», не кликая. Отдельно от `enabled`: можно включить площадку и неделю смотреть
    # dry-run логи, не рискуя ни одним реальным откликом. Дефолт True — включение площадки само
    # по себе НЕ начинает реальную отправку, нужен осознанный второй шаг (снять dry_run).
    dry_run: bool = True
    # Единственный порог очереди: скор ≥ min_score → автоотклик, всё ниже → ручной разбор.
    min_score: int = Field(default=75, ge=0, le=100)
    # ЛЕГАСИ (2026-09-01): ползунка в UI больше нет и гейт поле не читает — всё, что ниже
    # `min_score`, идёт в ручной разбор целиком (`gate.classify_for_auto_apply`). Оставлено,
    # чтобы сохранённые конфиги и админская витрина не падали на неизвестном ключе; та же
    # судьба, что у `daily_cap` после перехода на жёсткие потолки.
    manual_review_band: int = Field(default=10, ge=0, le=100)
    daily_cap: int = Field(default=5, ge=0, le=50)
    order: AutoApplyOrder = "score_desc"
    # Фаза 3.4: режим «Тест» на фронте (`PlatformPipelineSection.tsx`) — реально отправляет (dry_run=
    # False), но КАЖДЫЙ отклик ждёт подтверждения владельца в вебе перед фактическим кликом,
    # тем же механизмом, что уже несёт анкету (3.3): раннер паркует `jobs.anketa` как pending
    # (questions=[] — подтверждается только письмо), реальный клик — на следующем тике, после
    # approve, повторным визитом на вкладку. Независим от `dry_run`: «Авто» — dry_run=False +
    # require_confirmation=False (без подтверждений), «Тест» — dry_run=False +
    # require_confirmation=True.
    require_confirmation: bool = False


class AutoApplyConfig(BaseModel):
    """Полный конфиг автооткликов — по одному блоку на площадку."""

    model_config = ConfigDict(extra="ignore")

    hh: AutoApplyPlatformConfig = Field(default_factory=AutoApplyPlatformConfig)
    getmatch: AutoApplyPlatformConfig = Field(default_factory=AutoApplyPlatformConfig)
    habr: AutoApplyPlatformConfig = Field(default_factory=AutoApplyPlatformConfig)

    def platform(self, name: AutoApplyPlatform) -> AutoApplyPlatformConfig:
        return getattr(self, name)


DEFAULT_AUTO_APPLY_CONFIG = AutoApplyConfig()


def default_auto_apply_config_dict() -> dict[str, Any]:
    """Сериализованные дефолты для `default_app_settings_values`."""
    return DEFAULT_AUTO_APPLY_CONFIG.model_dump()


def auto_apply_config_from_mapping(raw: Any) -> AutoApplyConfig:
    """Разобрать jsonb; нет / мусор → дефолты (выключено везде), частичные ключи мержатся."""
    if not isinstance(raw, dict):
        return AutoApplyConfig()
    try:
        return AutoApplyConfig.model_validate(raw)
    except Exception:
        logger.debug("auto_apply_config: некорректные данные, использую дефолты: %r", raw)
        return AutoApplyConfig()


async def get_auto_apply_config(
    *, account_id: int | None, db: Executor | None = None
) -> AutoApplyConfig:
    """Текущий конфиг; нет строки / ошибка PG → дефолты (выключено)."""
    raw = await get_setting(KEY_AUTO_APPLY, default=None, account_id=account_id, db=db)
    return auto_apply_config_from_mapping(raw)


async def set_auto_apply_config(
    config: AutoApplyConfig, *, account_id: int | None, db: Executor | None = None
) -> None:
    """Записать конфиг целиком (частичный PATCH — на стороне API)."""
    await set_setting(KEY_AUTO_APPLY, config.model_dump(), account_id=account_id, db=db)


__all__ = [
    "AUTO_APPLY_DAILY_HARD_CAP",
    "DEFAULT_AUTO_APPLY_CONFIG",
    "KEY_AUTO_APPLY",
    "AutoApplyConfig",
    "AutoApplyOrder",
    "AutoApplyPlatform",
    "AutoApplyPlatformConfig",
    "auto_apply_config_from_mapping",
    "auto_apply_daily_hard_cap",
    "default_auto_apply_config_dict",
    "get_auto_apply_config",
    "set_auto_apply_config",
]
