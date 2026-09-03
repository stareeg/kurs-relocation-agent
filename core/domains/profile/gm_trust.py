"""GM-12: мониторинг заполненности профиля getmatch (`/api/trust`).

getmatch отдаёт чеклист доверия: `trusted`, `profile_filled`, `profile_checks` (phone/email/photo/
skills/experience/education), подключения linkedin/github/hh и `socials_required`. Если
`trusted=false` или `photo=false` — работодатели видят неполный/менее «проходной» профиль.

Здесь модель чеклиста (`GmTrust`), персист последнего снимка (account-scoped + RLS, по образцу
`gm_profile.py` / `resume_stats.py`) и денормализованный счётчик заполненности (`filled_count` из
6 пунктов `profile_checks`) для плашки на вкладке «Резюме». Никакого LLM и событий — чистый
приём/выдача.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.platform.db.pool import Executor, get_pool, row_to_dict

_GM_COLS = "id, captured_at, raw, created_at"


class GmTrustProfileChecks(BaseModel):
    """Отдельные пункты чеклиста доверия getmatch."""

    model_config = ConfigDict(extra="ignore")

    phone: bool = False
    email: bool = False
    photo: bool = False
    skills: bool = False
    experience: bool = False
    education: bool = False


class GmTrust(BaseModel):
    """Чеклист доверия getmatch (`GET /api/trust`), парсится расширением."""

    model_config = ConfigDict(extra="ignore")

    trusted: bool = False
    profile_filled: bool = False
    profile_checks: GmTrustProfileChecks = Field(default_factory=GmTrustProfileChecks)
    linkedin_connected: bool = False
    github_connected: bool = False
    hh_connected: bool = False
    socials_required: bool = False

    def filled_count(self) -> int:
        """Сколько из 6 пунктов profile_checks заполнено (для «заполнен на N/6»)."""
        return sum(
            1
            for k in ("phone", "email", "photo", "skills", "experience", "education")
            if getattr(self.profile_checks, k)
        )

    def missing_checks(self) -> list[str]:
        """Имена незаполненных пунктов (для конкретных пропусков в UI)."""
        labels = {
            "phone": "Телефон",
            "email": "Почта",
            "photo": "Фото",
            "skills": "Навыки",
            "experience": "Опыт",
            "education": "Образование",
        }
        return [
            labels[k]
            for k in ("phone", "email", "photo", "skills", "experience", "education")
            if not getattr(self.profile_checks, k)
        ]

    def missing_connections(self) -> list[str]:
        """Неподключённые внешние профили (для конкретных пропусков)."""
        out: list[str] = []
        if not self.linkedin_connected:
            out.append("LinkedIn")
        if not self.github_connected:
            out.append("GitHub")
        if not self.hh_connected:
            out.append("hh.ru")
        return out


class GmTrustSnapshot(BaseModel):
    """Снимок чеклиста доверия getmatch (история; вывод — всегда по последнему)."""

    id: int | None = None
    captured_at: datetime | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class GmTrustStatus(BaseModel):
    """Текущее состояние чеклиста доверия аккаунта (для плашки на вкладке «Резюме»)."""

    available: bool = False
    trusted: bool = False
    profile_filled: bool = False
    filled_count: int = 0
    total_checks: int = 6
    missing_checks: list[str] = Field(default_factory=list)
    missing_connections: list[str] = Field(default_factory=list)


async def save_gm_trust(
    trust: GmTrust, *, account_id: int, db: Executor | None = None
) -> GmTrustSnapshot:
    """Сохранить снимок чеклиста доверия аккаунта запроса (свежий — последний)."""
    db = db or get_pool()
    row = await db.fetchrow(
        "insert into gm_trust_snapshots (account_id, captured_at, raw) "
        "values ($1, $2, $3) "
        f"returning {_GM_COLS}",
        account_id,
        datetime.now(UTC),
        trust.model_dump(mode="json"),
    )
    assert row is not None  # insert ... returning всегда отдаёт строку
    return GmTrustSnapshot(**row_to_dict(row))


async def load_latest_gm_trust(*, account_id: int, db: Executor | None = None) -> GmTrust | None:
    """Последний снимок чеклиста доверия аккаунта запроса; `None` — снимков ещё нет."""
    db = db or get_pool()
    row = await db.fetchrow(
        "select raw from gm_trust_snapshots "
        "where account_id = $1 order by captured_at desc, id desc limit 1",
        account_id,
    )
    if row is None:
        return None
    return GmTrust.model_validate(row["raw"])


def trust_to_status(trust: GmTrust) -> GmTrustStatus:
    """Доменный `GmTrust` → transport-состояние для плашки (без I/O)."""
    return GmTrustStatus(
        available=True,
        trusted=trust.trusted,
        profile_filled=trust.profile_filled,
        filled_count=trust.filled_count(),
        total_checks=6,
        missing_checks=trust.missing_checks(),
        missing_connections=trust.missing_connections(),
    )


async def ingest_gm_trust(
    raw_trust: dict[str, Any], *, account_id: int
) -> tuple[bool, GmTrustStatus]:
    """Принять чеклист доверия из расширения, сохранить снимок, вернуть состояние.

    Возвращает `(stored, status)`. Приём мягко деградирует (нет PG → `stored=False`, но статус
    всё равно считается из присланного чеклиста). Битый контракт расширения → пустой `GmTrust`
    (не 500): статус покажет «0/6», что безопаснее молчаливого пропуска.
    """
    try:
        trust = GmTrust.model_validate(raw_trust or {})
    except Exception:  # noqa: BLE001 — контракт расширения, мягко отбрасываем
        trust = GmTrust()

    stored = False
    try:
        await save_gm_trust(trust, account_id=account_id)
        stored = True
    except Exception:  # noqa: BLE001 — нет PG → не сохранили, не 500
        stored = False

    return stored, trust_to_status(trust)


async def latest_gm_trust_status(*, account_id: int) -> GmTrustStatus:
    """Состояние по последнему сохранённому снимку; `available=False` — снимка нет/PG недоступен."""
    try:
        trust = await load_latest_gm_trust(account_id=account_id)
    except Exception:  # noqa: BLE001 — нет PG → available=False, не 500
        return GmTrustStatus()

    if trust is None:
        return GmTrustStatus()
    return trust_to_status(trust)


__all__ = [
    "GmTrust",
    "GmTrustProfileChecks",
    "GmTrustSnapshot",
    "GmTrustStatus",
    "save_gm_trust",
    "load_latest_gm_trust",
    "trust_to_status",
    "ingest_gm_trust",
    "latest_gm_trust_status",
]
