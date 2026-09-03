"""Жизненный цикл ключа OpenRouter аккаунта: свой ключ, заявка оператору, выдача, отзыв.

Раньше это жило в `bot_app/services/openrouter_keys.py` — выдача шла кнопками в Telegram, а
оператор пересылал заявителю сырой ключ. Переезд в platform (2026-08-25): заявка приходит с
«Аккаунта», выдаёт оператор из админ-панели, ключ, выданный оператором, пользователю не
показывается вообще. Бот из этого флоу убран целиком.

Один вход на любую запись ключа (`_apply_key`), потому что запись — это ТРИ согласованных
действия, и пропуск любого ловится не сразу:

1. секрет в `account_settings.openrouter_api_key`;
2. происхождение в `openrouter_account_keys` (маска/метка/кто выдал — витрина оператора);
3. инвалидация per-account кэша ключа в `core.config` — иначе до 15 с (TTL) LLM-вызовы этого
   аккаунта идут со старым ключом, а выдача выглядит «не сработавшей».
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import httpx

from core.config import get_settings
from core.platform.http import get_http_client
from core.platform.observability import event
from core.platform.repo import openrouter_account_keys as origins
from core.platform.repo import openrouter_key_requests as requests
from core.platform.repo.accounts import get_account_by_id
from core.platform.repo.settings import get_openrouter_key_set_at, is_openrouter_key_configured
from core.platform.repo.settings import set_setting as _set_setting

logger = logging.getLogger(__name__)

KEY_SETTING = "openrouter_api_key"
Origin = Literal["self", "admin"]

# Проверка ключа — чужой сервис, оператор ждёт в форме. Не llm_timeout.
_VERIFY_TIMEOUT = httpx.Timeout(connect=10.0, read=15.0, write=10.0, pool=10.0)
_BALANCE_CONCURRENCY = 5

_ADMIN_ISSUED_KEYS_SQL = (
    "select o.account_id, a.telegram_username, s.value #>> '{}' as raw_key "
    "from openrouter_account_keys o "
    "join accounts a on a.id = o.account_id "
    "left join account_settings s "
    "  on s.account_id = o.account_id and s.key = 'openrouter_api_key' "
    "where o.origin = 'admin' "
    "order by a.telegram_username nulls last, o.account_id"
)


class OpenRouterKeyError(Exception):
    """Ожидаемый отказ операции с ключом (пустой ключ, чужой ключ, нет аккаунта)."""


def sanitize_key(raw: str) -> str:
    """Убрать пробелы и переносы: парольный менеджер часто кладёт хвост \\n."""
    return "".join((raw or "").split())


def mask_key(raw: str) -> str:
    """`sk-or-v1-…9f3a` — сколько нужно оператору, чтобы отличить ключи друг от друга.

    Формат повторён в бэкфилле миграции 0141: 9 символов префикса + хвост из 4.
    """
    key = sanitize_key(raw)
    if len(key) <= 13:
        return "…"
    return f"{key[:9]}…{key[-4:]}"


def _as_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


@dataclass(frozen=True, slots=True)
class KeyProbe:
    """Результат GET /api/v1/key. Сырого ключа здесь нет — только маска и цифры."""

    alive: bool
    network_error: bool = False
    error: str = ""
    key_hint: str = ""
    label: str | None = None
    limit: float | None = None
    usage: float = 0.0
    limit_remaining: float | None = None
    is_free_tier: bool = False


@dataclass(frozen=True, slots=True)
class IssuedKeyBalance:
    """Остаток по уже выданному (origin=admin) ключу. Секрет наружу не выходит."""

    account_id: int
    telegram_username: str | None
    probe: KeyProbe


async def verify_key(raw_key: str) -> KeyProbe:
    """Спросить OpenRouter, жив ли ключ и сколько на нём осталось.

    Сетевой сбой не бросает исключение: форма выдачи должна дать выдать и с предупреждением.
    Сырой ключ не пишется ни в лог, ни в поля события — только `key_hint`.
    """
    key = sanitize_key(raw_key)
    hint = mask_key(key)
    if not key:
        return KeyProbe(alive=False, error="Пустой ключ")
    settings = get_settings()
    url = f"{settings.openrouter_base_url.rstrip('/')}/key"
    try:
        resp = await get_http_client().get(
            url,
            headers={"Authorization": f"Bearer {key}"},
            timeout=_VERIFY_TIMEOUT,
        )
    except Exception as exc:
        event(
            logger,
            "КЛЮЧ",
            "проверка %s: сеть %s",
            hint,
            type(exc).__name__,
            level=logging.WARNING,
            action="verify",
            key_hint=hint,
            network_error=True,
        )
        return KeyProbe(
            alive=False,
            network_error=True,
            error="OpenRouter не ответил",
            key_hint=hint,
        )
    if resp.status_code in (401, 403):
        event(
            logger,
            "КЛЮЧ",
            "проверка %s: ключ не принят (%s)",
            hint,
            resp.status_code,
            level=logging.WARNING,
            action="verify",
            key_hint=hint,
            status_code=resp.status_code,
        )
        return KeyProbe(alive=False, error="ключ не принят", key_hint=hint)
    if resp.status_code >= 500 or resp.status_code == 429:
        event(
            logger,
            "КЛЮЧ",
            "проверка %s: OpenRouter %s",
            hint,
            resp.status_code,
            level=logging.WARNING,
            action="verify",
            key_hint=hint,
            status_code=resp.status_code,
            network_error=True,
        )
        return KeyProbe(
            alive=False,
            network_error=True,
            error=f"OpenRouter ответил {resp.status_code}",
            key_hint=hint,
        )
    if resp.status_code != 200:
        event(
            logger,
            "КЛЮЧ",
            "проверка %s: OpenRouter %s",
            hint,
            resp.status_code,
            level=logging.WARNING,
            action="verify",
            key_hint=hint,
            status_code=resp.status_code,
        )
        return KeyProbe(
            alive=False,
            error=f"OpenRouter ответил {resp.status_code}",
            key_hint=hint,
        )
    try:
        payload = resp.json()
    except Exception:
        return KeyProbe(
            alive=False,
            network_error=True,
            error="непонятный ответ OpenRouter",
            key_hint=hint,
        )
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return KeyProbe(
            alive=False,
            network_error=True,
            error="непонятный ответ OpenRouter",
            key_hint=hint,
        )
    remaining = _as_float(data.get("limit_remaining"))
    label_raw = data.get("name") or data.get("label")
    label = label_raw.strip() if isinstance(label_raw, str) and label_raw.strip() else None
    event(
        logger,
        "КЛЮЧ",
        "проверка %s: жив, остаток %s",
        hint,
        remaining,
        action="verify",
        key_hint=hint,
        limit_remaining=remaining,
        is_free_tier=data.get("is_free_tier") is True,
    )
    return KeyProbe(
        alive=True,
        key_hint=hint,
        label=label,
        limit=_as_float(data.get("limit")),
        usage=_as_float(data.get("usage")) or 0.0,
        limit_remaining=remaining,
        is_free_tier=data.get("is_free_tier") is True,
    )


async def refresh_admin_issued_balances() -> list[IssuedKeyBalance]:
    """Остатки по ключам, которые выдал оператор. Не автоматически — чужой внешний сервис."""
    try:
        from core.platform.db.pool import get_pool, row_to_dict

        rows = [row_to_dict(r) for r in await get_pool().fetch(_ADMIN_ISSUED_KEYS_SQL)]
    except Exception as exc:
        event(
            logger,
            "КЛЮЧ",
            "не удалось прочитать выданные ключи: %s",
            exc,
            level=logging.WARNING,
            action="balances",
        )
        return []
    if not rows:
        return []
    sem = asyncio.Semaphore(_BALANCE_CONCURRENCY)

    async def _one(row: dict[str, Any]) -> IssuedKeyBalance:
        account_id = int(row["account_id"])
        username = row.get("telegram_username")
        username_s = username if isinstance(username, str) else None
        raw = row.get("raw_key")
        cleaned = sanitize_key(raw if isinstance(raw, str) else "")
        async with sem:
            if not cleaned:
                probe = KeyProbe(alive=False, error="ключ не найден в настройках")
            else:
                probe = await verify_key(cleaned)
        return IssuedKeyBalance(account_id=account_id, telegram_username=username_s, probe=probe)

    return list(await asyncio.gather(*[_one(row) for row in rows]))


@dataclass(frozen=True, slots=True)
class KeyState:
    """Что показать владельцу ключа на «Аккаунте» и оператору в консоли."""

    configured: bool = False
    origin: Origin | None = None
    key_hint: str = ""
    label: str | None = None
    issued_at: datetime | None = None
    issued_by: int | None = None
    request_status: requests.Status | None = None


async def _apply_key(
    account_id: int | None,
    raw_key: str | None,
    *,
    origin: Origin,
    label: str | None = None,
    issued_by: int | None = None,
    touch_process_holder: bool,
) -> None:
    """Записать (или стереть) ключ аккаунта вместе с его происхождением и кэшами."""
    from core.config import cache_account_openrouter_key, set_runtime_openrouter_key

    cleaned = (raw_key or "").strip() or None
    await _set_setting(KEY_SETTING, cleaned, account_id=account_id)

    if account_id is not None:
        cache_account_openrouter_key(account_id, cleaned)
        if cleaned is None:
            await origins.delete_origin(account_id)
        else:
            await origins.upsert_origin(
                account_id,
                origin=origin,
                key_hint=mask_key(cleaned),
                label=(label or None),
                issued_by=issued_by,
            )
    if touch_process_holder:
        # Легаси процесс-вайд holder — фолбэк фоновых задач и запросов без личности
        # (bootstrap-окно тоже сюда). Трогаем только для владельца установки: правка ключа
        # member'ом не должна перетирать то, чем пользуются остальные пути.
        set_runtime_openrouter_key(cleaned)


async def _is_owner(account_id: int | None) -> bool:
    if account_id is None:
        return True  # bootstrap-окно: аккаунтов ещё нет, ключ идёт в app_settings
    account = await get_account_by_id(account_id)
    return account is not None and account.role == "owner"


# --- Владелец ключа («Аккаунт») ---


async def key_state(account_id: int | None) -> KeyState:
    """Состояние ключа глазами его владельца — без самого секрета."""
    configured = await is_openrouter_key_configured(account_id=account_id)
    if account_id is None:
        return KeyState(
            configured=configured,
            origin="self" if configured else None,
            issued_at=await get_openrouter_key_set_at(account_id=None),
        )
    record = await origins.get_origin(account_id)
    latest = await requests.get_own_latest_request(account_id)
    if not configured:
        return KeyState(request_status=latest.status if latest else None)
    return KeyState(
        configured=True,
        origin=record.origin if record else "self",
        key_hint=record.key_hint if record else "",
        label=record.label if record else None,
        issued_at=record.issued_at
        if record
        else await get_openrouter_key_set_at(account_id=account_id),
        issued_by=record.issued_by if record else None,
        request_status=latest.status if latest else None,
    )


async def save_own_key(*, account_id: int | None, raw_key: str) -> None:
    """Человек вставил свой ключ — он же им и распоряжается (origin='self').

    Свой ключ поверх выданного оператором разрешён осознанно: это единственный способ уйти с
    общего ключа на собственный биллинг, и он не отбирает у человека ничего.

    Висящая заявка «попросить ключ у админа» закрывается сама: иначе очередь внимания в
    админке копит строки по людям, у которых ключ уже есть (как у account_id=5 2026-08-26).
    """
    key = sanitize_key(raw_key)
    if not key:
        raise OpenRouterKeyError("Пустой ключ")
    await _apply_key(
        account_id,
        key,
        origin="self",
        touch_process_holder=await _is_owner(account_id),
    )
    closed = 0
    if account_id is not None:
        # resolved_by = сам заявитель: ключ появился не от оператора, а self-serve.
        closed = await requests.close_open_requests(
            account_id, status="fulfilled", resolved_by=account_id
        )
    event(
        logger,
        "КЛЮЧ",
        "свой ключ сохранён account_id=%s",
        account_id,
        action="save_own",
        account_id=account_id,
        requests_closed=closed,
    )


async def clear_own_key(*, account_id: int | None) -> None:
    """Сброс своего ключа с «Аккаунта». Ключ, выданный оператором, так сбросить нельзя —
    его выдал не пользователь, и «сбросить» для него означало бы отключить себе продукт."""
    if account_id is not None:
        record = await origins.get_origin(account_id)
        if record is not None and record.origin == "admin":
            raise OpenRouterKeyError(
                "Ключ выдан администратором — сбросить его можно только через администратора"
            )
    await _apply_key(
        account_id,
        None,
        origin="self",
        touch_process_holder=await _is_owner(account_id),
    )
    event(
        logger,
        "КЛЮЧ",
        "свой ключ сброшен account_id=%s",
        account_id,
        action="clear_own",
        account_id=account_id,
    )


@dataclass(frozen=True, slots=True)
class RequestOutcome:
    """Что случилось с кнопкой «Запросить ключ» — фронт показывает `message` как есть."""

    status: Literal["created", "already_pending", "already_has_key"]
    message: str
    request_id: int | None = None


async def request_key(*, account_id: int) -> RequestOutcome:
    """Заявка оператору. Идемпотентна: пока по первой нет решения, вторая не плодит очередь.

    Ключ уже есть → заявки нет: второй ключ человеку не нужен, оператору — лишняя строка.
    """
    if await is_openrouter_key_configured(account_id=account_id):
        return RequestOutcome(status="already_has_key", message="Ключ уже есть")
    existing = await requests.get_own_pending_request(account_id)
    if existing is not None:
        return RequestOutcome(
            status="already_pending", message="Заявка уже отправлена", request_id=existing.id
        )
    created = await requests.create_request(account_id)
    event(
        logger,
        "КЛЮЧ",
        "заявка %s от account_id=%s",
        created.id,
        account_id,
        action="request",
        request_id=created.id,
        account_id=account_id,
    )
    return RequestOutcome(status="created", message="Заявка отправлена", request_id=created.id)


# --- Оператор (админ-панель) ---


async def issue_key(
    *,
    target_account_id: int,
    raw_key: str,
    actor_id: int,
    label: str | None = None,
) -> None:
    """Выдать или перевыпустить ключ аккаунту. Открытые заявки этого человека закрываются.

    Перевыпуск поверх собственного ключа пользователя разрешён (оператор мог выдать взамен
    отозванного в кабинете OpenRouter), но перекрашивает происхождение в 'admin' — дальше
    ключ считается операторским со всеми последствиями (не показываем, не даём сбросить).
    """
    key = sanitize_key(raw_key)
    if not key:
        raise OpenRouterKeyError("Пустой ключ")
    target = await get_account_by_id(target_account_id)
    if target is None:
        raise OpenRouterKeyError("Аккаунт не найден")
    await _apply_key(
        target_account_id,
        key,
        origin="admin",
        label=label,
        issued_by=actor_id,
        touch_process_holder=target.role == "owner",
    )
    closed = await requests.close_open_requests(
        target_account_id, status="fulfilled", resolved_by=actor_id
    )
    event(
        logger,
        "КЛЮЧ",
        "ключ выдан account_id=%s оператором %s",
        target_account_id,
        actor_id,
        action="issue",
        account_id=target_account_id,
        actor_account_id=actor_id,
        requests_closed=closed,
        key_hint=mask_key(key),
    )


async def revoke_key(*, target_account_id: int, actor_id: int) -> None:
    """Убрать ключ у аккаунта (оператор погасил его в кабинете OpenRouter — тут гасим след).

    Работает и по своему ключу пользователя: оператор отключает человеку LLM целиком, это
    осознанное административное действие, а не редактирование чужих настроек.
    """
    target = await get_account_by_id(target_account_id)
    if target is None:
        raise OpenRouterKeyError("Аккаунт не найден")
    await _apply_key(
        target_account_id,
        None,
        origin="admin",
        touch_process_holder=target.role == "owner",
    )
    event(
        logger,
        "КЛЮЧ",
        "ключ отозван account_id=%s оператором %s",
        target_account_id,
        actor_id,
        action="revoke",
        account_id=target_account_id,
        actor_account_id=actor_id,
    )


async def reject_request(*, request_id: int, actor_id: int) -> int:
    """Отклонить заявку; возвращает account_id заявителя (кому слать отказ)."""
    record = await requests.get_request(request_id)
    if record is None:
        raise OpenRouterKeyError("Заявка не найдена")
    if record.status not in ("pending", "approved"):
        raise OpenRouterKeyError("Заявка уже закрыта")
    closed = await requests.close_open_requests(
        record.account_id, status="rejected", resolved_by=actor_id
    )
    if closed == 0:
        raise OpenRouterKeyError("Заявка уже закрыта")
    event(
        logger,
        "КЛЮЧ",
        "заявка %s отклонена оператором %s",
        request_id,
        actor_id,
        action="reject",
        request_id=request_id,
        account_id=record.account_id,
        actor_account_id=actor_id,
    )
    return record.account_id


# --- Уведомления в Telegram ---
#
# Второй канал, не основной: заявка приходит с сайта и решается в админ-панели. Пуш нужен,
# чтобы оператор узнал о заявке, не сидя в консоли, а заявитель — что ключ уже выдан (сам
# ключ ему не показываем нигде). Оба — реакция на явное действие человека, не рассылка.


async def _enqueue_push(*, kind: str, text: str, target_account_id: int | None, dedup: str) -> None:
    """Best-effort пуш в очередь `tg_push`: нет PG/бота — предупреждение, не отказ операции."""
    from datetime import UTC, datetime

    from core.platform.tasks import enqueue

    # kind — строкой: константы пушей живут в домене profile (telegram_push.KEY_REQUEST_KIND /
    # ADMIN_MESSAGE_KIND), а platform домены не импортирует. Значения обязаны совпадать.
    payload: dict[str, object] = {"kind": kind, "vacancy_id": "admin", "text": text}
    if target_account_id is not None:
        payload["account_id"] = target_account_id
    minute = datetime.now(UTC).strftime("%Y%m%d%H%M")
    try:
        await enqueue(
            "tg_push",
            payload=payload,
            priority=40,
            idempotency_key=f"tg_push:{kind}:{dedup}:{minute}",
            max_attempts=3,
            account_id=target_account_id,
        )
    except Exception as exc:
        logger.warning("openrouter_keys: пуш %s не поставлен в очередь: %s", kind, exc)


async def notify_operator_about_request(*, requester_account_id: int) -> None:
    """Оператору: пришла заявка на ключ. Получатель — владелец установки (payload без
    account_id → `push_handler._resolve_recipient` резолвит владельца)."""
    requester = await get_account_by_id(requester_account_id)
    who = f"@{requester.telegram_username}" if requester and requester.telegram_username else "—"
    await _enqueue_push(
        kind="key_request",
        text=f"{who} (id {requester_account_id}) просит ключ OpenRouter. Выдать — в админ-панели.",
        target_account_id=None,
        dedup=str(requester_account_id),
    )


async def notify_key_issued(*, target_account_id: int) -> None:
    await _enqueue_push(
        kind="admin_message",
        text="Ключ OpenRouter выдан — раздел «Аккаунт» на сайте уже открыт.",
        target_account_id=target_account_id,
        dedup=f"issued:{target_account_id}",
    )


async def notify_key_rejected(*, target_account_id: int) -> None:
    await _enqueue_push(
        kind="admin_message",
        text="Заявка на ключ OpenRouter отклонена. Свой ключ можно вставить в разделе «Аккаунт».",
        target_account_id=target_account_id,
        dedup=f"rejected:{target_account_id}",
    )


async def origins_by_account() -> dict[int, origins.KeyOriginRecord]:
    """Происхождение ключей всего флота — витрина «кому какой ключ выдан» в консоли."""
    return {record.account_id: record for record in await origins.list_origins()}


__all__ = [
    "KEY_SETTING",
    "IssuedKeyBalance",
    "KeyProbe",
    "KeyState",
    "OpenRouterKeyError",
    "Origin",
    "RequestOutcome",
    "clear_own_key",
    "issue_key",
    "key_state",
    "mask_key",
    "notify_key_issued",
    "notify_key_rejected",
    "notify_operator_about_request",
    "origins_by_account",
    "refresh_admin_issued_balances",
    "reject_request",
    "request_key",
    "revoke_key",
    "sanitize_key",
    "save_own_key",
    "verify_key",
]
