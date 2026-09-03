"""Каналы владельца: web / telegram / extension — адаптеры одних сценариев.

Правило: канал не содержит доменной логики. Здесь только идентичность (`name`,
`source_tag`) и тонкие вызовы `domains.*.service`. Форматирование ответа
(HTML Telegram, JSON HTTP) остаётся в `bot_app` / `api`.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.domains.opportunities.jobs import Job
from core.domains.opportunities.service import set_job_stage, skip_job, unskip_job
from core.kernel import ports


@dataclass(slots=True)
class SurfaceChannel:
    """Идентичность поверхности. Удовлетворяет `ports.Channel`."""

    name: str
    source_tag: str


WEB = SurfaceChannel(name="web", source_tag="api_kanban")
TELEGRAM = SurfaceChannel(name="telegram", source_tag="telegram_bot")
# Расширение ходит в API; метка — для будущего явного заголовка/атрибуции.
EXTENSION = SurfaceChannel(name="extension", source_tag="vacancy_page")
# Автоотклики (Фаза 2, plans/auto_apply_roadmap_2026_08_17.md): раннер расширения, source
# отличим от ручного клика (EXTENSION/api_funnel) — доска/дневной лимит (2.7) фильтруют по нему.
AUTO_APPLY_HH = SurfaceChannel(name="auto_apply_hh", source_tag="auto_apply_hh")
AUTO_APPLY_GETMATCH = SurfaceChannel(name="auto_apply_getmatch", source_tag="auto_apply_getmatch")
AUTO_APPLY_HABR = SurfaceChannel(name="auto_apply_habr", source_tag="auto_apply_habr")


def register_builtin_channels(*, overwrite: bool = False) -> None:
    """Зарегистрировать web / telegram / extension / автоотклики в реестре портов."""
    ports.bind(
        channels={
            WEB.name: WEB,
            TELEGRAM.name: TELEGRAM,
            EXTENSION.name: EXTENSION,
            AUTO_APPLY_HH.name: AUTO_APPLY_HH,
            AUTO_APPLY_GETMATCH.name: AUTO_APPLY_GETMATCH,
            AUTO_APPLY_HABR.name: AUTO_APPLY_HABR,
        },
        overwrite=overwrite,
    )


async def skip_via(channel: ports.Channel, job_id: int, reason: str, *, account_id: int) -> Job:
    """Пропуск вакансии — один сценарий для любого канала."""
    _ = channel  # идентичность; skip не пишет source в stages
    return await skip_job(job_id, reason, account_id=account_id)


async def unskip_via(channel: ports.Channel, job_id: int, *, account_id: int) -> Job:
    """Снять пропуск — один сценарий для любого канала."""
    _ = channel
    return await unskip_job(job_id, account_id=account_id)


async def set_stage_via(channel: ports.Channel, job_id: int, stage: str, *, account_id: int) -> Job:
    """Смена стадии воронки с меткой канала в `application_stages.source`."""
    return await set_job_stage(job_id, stage, source=channel.source_tag, account_id=account_id)


__all__ = [
    "AUTO_APPLY_GETMATCH",
    "AUTO_APPLY_HABR",
    "AUTO_APPLY_HH",
    "EXTENSION",
    "TELEGRAM",
    "WEB",
    "SurfaceChannel",
    "register_builtin_channels",
    "set_stage_via",
    "skip_via",
    "unskip_via",
]
