"""Вердикт «что не так» по человеку — чистая функция без I/O.

Ручка собирает факты из снимка карточки и пробы ключа; здесь только порядок
проверок и формулировки. Сырой ключ сюда не передаётся.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from core.platform.admin.models import AdminDiagnosisItem

EXTENSION_STALE = timedelta(days=7)
SCORE_STALE = timedelta(days=14)


def _aware(value: datetime | None, *, now: datetime) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=now.tzinfo or UTC)
    return value


def _version_parts(raw: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in raw.split("."):
        digits = ""
        for char in chunk:
            if char.isdigit():
                digits += char
            else:
                break
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def version_older(seen: str, current: str) -> bool:
    """True, если увиденная версия расширения старше канона из manifest."""
    left, right = _version_parts(seen), _version_parts(current)
    if not left or not right:
        return False
    return left < right


def build_diagnosis(
    *,
    has_key: bool,
    key_alive: bool | None = None,
    key_network_error: bool = False,
    has_resume: bool,
    search_title: str = "",
    extension_confirmed: bool,
    last_extension_at: datetime | None = None,
    extension_version: str = "",
    current_extension_version: str = "",
    telegram_chat_id: int | None = None,
    errors_24h: int = 0,
    last_scored_at: datetime | None = None,
    spend_alert: bool = False,
    spend_month_usd: float = 0.0,
    now: datetime | None = None,
) -> list[AdminDiagnosisItem]:
    """Упорядоченный список проверок. Успешные тоже в ответе — фронт прячет их."""
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    last_ext = _aware(last_extension_at, now=moment)
    last_score = _aware(last_scored_at, now=moment)
    items: list[AdminDiagnosisItem] = []

    items.append(
        AdminDiagnosisItem(
            id="key",
            ok=has_key,
            title="Ключ OpenRouter",
            detail="есть" if has_key else "нет ключа — оценка и чат не работают",
            action_label="" if has_key else "Выдать ключ",
            action_kind="" if has_key else "issue_key",
        )
    )
    if has_key:
        if key_network_error:
            alive_ok = False
            detail = "OpenRouter не ответил — проверьте сеть"
        elif key_alive is False:
            alive_ok = False
            detail = "ключ не принят"
        elif key_alive is True:
            alive_ok = True
            detail = "жив"
        else:
            alive_ok = False
            detail = "не удалось проверить"
        items.append(
            AdminDiagnosisItem(
                id="key_alive",
                ok=alive_ok,
                title="Ключ жив",
                detail=detail,
                action_label="" if alive_ok else "Выдать ключ",
                action_kind="" if alive_ok else "issue_key",
            )
        )

    items.append(
        AdminDiagnosisItem(
            id="resume",
            ok=has_resume,
            title="Резюме",
            detail="есть" if has_resume else "нет резюме — скоринг не из чего считать",
        )
    )
    if has_resume:
        profile_ok = bool(search_title.strip())
        items.append(
            AdminDiagnosisItem(
                id="search_profile",
                ok=profile_ok,
                title="Профиль поиска",
                detail=search_title.strip() if profile_ok else "не выведен — резюме пустое",
            )
        )

    ext_fresh = last_ext is not None and (moment - last_ext) <= EXTENSION_STALE
    ext_ok = extension_confirmed or ext_fresh
    if ext_ok and last_ext is not None and not ext_fresh:
        ext_ok = False
    if last_ext is None and not extension_confirmed:
        ext_detail = "нет расширения"
    elif last_ext is None:
        ext_detail = "не видно в логах"
        ext_ok = False
    elif not ext_fresh:
        ext_detail = "давно не стучалось"
        ext_ok = False
    else:
        ext_detail = "на связи"
    items.append(
        AdminDiagnosisItem(
            id="extension",
            ok=ext_ok,
            title="Расширение",
            detail=ext_detail,
        )
    )
    if extension_version.strip() and current_extension_version.strip():
        stale_ver = version_older(extension_version, current_extension_version)
        items.append(
            AdminDiagnosisItem(
                id="extension_version",
                ok=not stale_ver,
                title="Версия расширения",
                detail=(
                    f"{extension_version} — старше текущей {current_extension_version}"
                    if stale_ver
                    else extension_version
                ),
            )
        )

    chat_ok = telegram_chat_id is not None
    items.append(
        AdminDiagnosisItem(
            id="telegram",
            ok=chat_ok,
            title="Чат с ботом",
            detail="привязан" if chat_ok else "нет чата — написать от Администратора нельзя",
            action_label="" if chat_ok else "Написать",
            action_kind="" if chat_ok else "contact",
        )
    )

    errors_ok = errors_24h <= 0
    items.append(
        AdminDiagnosisItem(
            id="errors",
            ok=errors_ok,
            title="Ошибки за сутки",
            detail="тихо" if errors_ok else f"{errors_24h} за сутки",
            action_label="" if errors_ok else "Открыть журнал за сутки",
            action_kind="" if errors_ok else "journal",
        )
    )

    if not has_resume:
        score_ok = True
        score_detail = "нечего оценивать"
    elif last_score is None:
        score_ok = False
        score_detail = "не оценивал"
    elif moment - last_score > SCORE_STALE:
        score_ok = False
        score_detail = "давно не скорил"
    else:
        score_ok = True
        score_detail = "свежая"
    items.append(
        AdminDiagnosisItem(
            id="last_score",
            ok=score_ok,
            title="Последняя оценка",
            detail=score_detail,
        )
    )

    items.append(
        AdminDiagnosisItem(
            id="spend",
            ok=not spend_alert,
            title="Порог расхода",
            detail="в норме" if not spend_alert else f"месяц ${spend_month_usd:.2f} выше порога",
        )
    )
    return items


def diagnosis_contains_secret(items: list[AdminDiagnosisItem], secret: str) -> bool:
    """Для теста: сырой ключ не должен протечь ни в одно поле."""
    if not secret:
        return False
    blob = " ".join(
        f"{item.id} {item.title} {item.detail} {item.action_label} {item.action_kind}"
        for item in items
    )
    return secret in blob


def facts_from_user(
    user: Any,
    snapshot: Any,
    *,
    key_alive: bool | None = None,
    key_network_error: bool = False,
    current_extension_version: str = "",
    now: datetime | None = None,
) -> list[AdminDiagnosisItem]:
    """Собрать вердикт из уже загруженной карточки — без повторных запросов."""
    return build_diagnosis(
        has_key=bool(getattr(user, "has_openrouter_key", False)),
        key_alive=key_alive,
        key_network_error=key_network_error,
        has_resume=bool(getattr(user, "has_resume", False)),
        search_title=str(getattr(snapshot, "search_title", "") or ""),
        extension_confirmed=bool(getattr(user, "extension_confirmed", False)),
        last_extension_at=getattr(snapshot, "last_extension_at", None),
        extension_version=str(getattr(snapshot, "extension_version", "") or ""),
        current_extension_version=current_extension_version,
        telegram_chat_id=getattr(user, "telegram_chat_id", None),
        errors_24h=int(getattr(user, "errors_24h", 0) or 0),
        last_scored_at=getattr(snapshot, "last_scored_at", None),
        spend_alert=bool(getattr(user, "spend_alert", False)),
        spend_month_usd=float(getattr(user, "spend_month_usd", 0.0) or 0.0),
        now=now,
    )
