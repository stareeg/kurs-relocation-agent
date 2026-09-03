"""Meta-справочники системы (7.4 / D2 / D3 / Э0.2).

GET /api/meta/sources — канон `ALL_JOB_SOURCES` из `core.domains.opportunities.jobs` + UI-группы.
GET /api/meta/cities — города из `jobs.work_city` и опыта резюме (подсказки «Город проживания»).

Бэк — единственный источник истины для перечня источников вакансий; фронт генерирует
`HH_SOURCES` из этого эндпоинта через `schema.d.ts` вместо хардкода (D2). При добавлении
нового источника на бэке достаточно `npm run gen-api:offline` — фронт подхватит автоматически.
"""

from __future__ import annotations

import asyncio
import json
import logging
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from api.schemas import (
    CitiesResponse,
    CitySuggestion,
    ExtensionSetupResponse,
    JobSourceItem,
    JobSourcesResponse,
)
from api.security import AccountContext, require_account
from core.domains.opportunities.jobs import (
    ALL_JOB_SOURCES,
    SOURCE_GROUPS_ORDER,
    list_seen_work_cities,
    resolve_job_source_group,
)
from core.kernel.timezones import (
    canonical_city_name,
    city_geo,
    normalize_city,
    overlap_hours,
    utc_offset_label,
)
from core.platform.repo.extension_bundle import build_extension_zip
from core.platform.repo.settings import get_extension_version

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/meta", tags=["meta"])

# Корень репозитория: api/routers/meta/meta.py → три уровня вверх (не зависит от cwd).
_REPO_ROOT = Path(__file__).resolve().parents[3]


@lru_cache(maxsize=1)
def _extension_manifest_version() -> str | None:
    """Версия расширения из `extension/manifest.json` — канон того, что собрал бэкенд.

    Лучше, чем хардкод: `manifest.json` — единственный источник истины, его же читает
    Chrome. Ошибки чтения/парсинга → None (фронт покажет «версия неизвестна»). Кэшируется
    на процесс — версия меняется только при пересборке/деплое, перечитывать файл на каждый
    опрос фронта бессмысленно.
    """
    try:
        raw = (_REPO_ROOT / "extension" / "manifest.json").read_text(encoding="utf-8")
        version = json.loads(raw).get("version")
        return version if isinstance(version, str) and version.strip() else None
    except Exception as exc:  # noqa: BLE001 — версионность декоративна, не роняет роутер
        logger.debug("meta: не удалось прочитать версию расширения: %s", exc)
        return None


@router.get("/sources", response_model=JobSourcesResponse)
async def get_job_sources() -> JobSourcesResponse:
    """Канонический справочник `jobs.source` + UI-группы (D2/D3).

    Источник истины — `ALL_JOB_SOURCES` в `core.domains.opportunities.jobs`. Группа для каждого источника
    вычисляется через `resolve_job_source_group` (тот же канон, что в UI). Порядок
    источников — детерминированный (отсортированный), чтобы дифф schema.d.ts был стабильным.
    """
    items = [
        JobSourceItem(source=s, group=resolve_job_source_group(s, None))
        for s in sorted(ALL_JOB_SOURCES)
    ]
    return JobSourcesResponse(
        sources=items,
        groups=list(SOURCE_GROUPS_ORDER),
    )


def _city_item(name: str, source: str) -> CitySuggestion:
    display = canonical_city_name(name) or name.strip()
    geo = city_geo(name)
    if geo is None:
        return CitySuggestion(city=display, source=source)
    return CitySuggestion(
        city=display,
        country=geo.country,
        timezone=geo.timezone,
        utc_offset=utc_offset_label(geo.timezone),
        overlap_emea=overlap_hours(geo.timezone, "EMEA"),
        source=source,
    )


async def _own_city_names(account_id: int | None) -> list[tuple[str, str]]:
    """(город, source) из вакансий и опыта. Пустой агрегат — []."""
    if account_id is None:
        return []
    from core.domains.profile.structured_store import read_resume_data_for_account

    ordered: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(name: str, source: str) -> None:
        key = normalize_city(name)
        if not key or key in seen:
            return
        seen.add(key)
        ordered.append((name.strip(), source))

    for city in await list_seen_work_cities(account_id=account_id):
        add(city, "jobs")
    resume = await read_resume_data_for_account(account_id)
    for exp in resume.experience:
        add(exp.area, "resume")
    return ordered


@router.get("/cities", response_model=CitiesResponse)
async def get_cities(
    account: AccountContext | None = Depends(require_account),
) -> CitiesResponse:
    """Подсказки городов из своих вакансий и опыта. Пустой агрегат — не ошибка."""
    account_id = account.account_id if account else None
    return CitiesResponse(
        items=[_city_item(n, src) for n, src in await _own_city_names(account_id)]
    )


@router.get("/extension", response_model=ExtensionSetupResponse)
async def get_extension_setup(
    account: AccountContext | None = Depends(require_account),
) -> ExtensionSetupResponse:
    """Готовность сборки + версионность расширения.

    `extension_dir` — путь на диске сервера (фронт больше не показывает, EX-14, но поле
    сохранено для совместимости). `latest_version` — из `extension/manifest.json` (канон
    собранной бэкендом версии). `installed_version` — версия, которой реально пользуется
    аккаунт (захвачена из заголовка `X-Extension-Version`); `None`, если расширение ещё ни
    разу не обращалось или версию не присылало. `dist_ready=False` — сборки ещё нет.
    """
    ext_dir = _REPO_ROOT / "extension"
    account_id = account.account_id if account else None
    installed = await get_extension_version(account_id=account_id) if account_id else None
    return ExtensionSetupResponse(
        extension_dir=str(ext_dir),
        dist_ready=(ext_dir / "dist" / "content.js").is_file(),
        latest_version=_extension_manifest_version(),
        installed_version=installed,
    )


@router.get("/extension/download")
async def download_extension_zip() -> StreamingResponse:
    """Скачивание готового архива расширения вместо локального пути на диске сервера.

    409 (а не пустой .zip/500), если `extension/dist` не собран — на VM-сервере сборку должен
    делать Docker/CI, а не локальный диск разработчика.
    """
    ext_dir = _REPO_ROOT / "extension"
    if not (ext_dir / "dist" / "content.js").is_file():
        raise HTTPException(status_code=409, detail="Сборка расширения не найдена на сервере")
    data = await asyncio.to_thread(build_extension_zip)
    headers = {"Content-Disposition": 'attachment; filename="career-copilot-extension.zip"'}
    return StreamingResponse(iter([data]), media_type="application/zip", headers=headers)
