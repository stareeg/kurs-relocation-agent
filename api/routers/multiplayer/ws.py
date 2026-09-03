"""WebSocket партии «Хрюши и Волки» — `/api/multiplayer/ws/{room_code}`."""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from api.security import AUTH_COOKIE, AccountContext, resolve_request_account
from core.domains.multiplayer.models import IllegalMove
from core.domains.multiplayer.session import (
    apply_client_intent,
    bind_connection,
    broadcast_state,
    claim_seat,
    host_action,
    hub,
    pause_match,
    resume_match,
    start_match_for_room,
    unbind_connection,
)
from core.platform.observability import event

logger = logging.getLogger(__name__)

router = APIRouter(tags=["multiplayer"])


async def _account_from_ws(websocket: WebSocket) -> AccountContext | None:
    """Cookie / query token / заголовки — как у HTTP, но без Depends."""
    cookie = websocket.cookies.get(AUTH_COOKIE)
    q = websocket.query_params
    token = q.get("token") or q.get("auth")
    x_api_key = websocket.headers.get("x-api-key")
    x_auth = websocket.headers.get("x-auth-token") or token
    account, authed = await resolve_request_account(x_api_key, x_auth, cookie)
    if account is not None:
        return account
    if authed:
        # bootstrap без личности — для игры нужен конкретный аккаунт
        return None
    return None


@router.websocket("/api/multiplayer/ws/{room_code}")
async def wolves_ws(websocket: WebSocket, room_code: str) -> None:
    # Accept сразу: иначе браузер/Vite-proxy даёт ложный onerror при close до handshake.
    await websocket.accept()

    account = await _account_from_ws(websocket)
    if account is None:
        await websocket.send_json({"type": "error", "detail": "auth"})
        await websocket.close(code=4401)
        return

    session = await hub().get_or_load(room_code)
    if session is None:
        await websocket.send_json({"type": "error", "detail": "closed"})
        await websocket.close(code=4404)
        return

    seat_token = websocket.query_params.get("seat_token")
    try:
        conn = await bind_connection(
            session,
            ws=websocket,
            account_id=account.account_id,
            seat_token=seat_token,
        )
    except PermissionError as exc:
        await websocket.send_json({"type": "error", "detail": str(exc)})
        await websocket.close(code=4403)
        return

    await websocket.send_json(
        {
            "type": "welcome",
            "room_code": session.room_code,
            "seat_token": conn.seat_token,
            "engine_seat_id": conn.engine_seat_id,
            "is_spectator": conn.is_spectator,
            "is_host": account.account_id == session.host_account_id,
        }
    )
    await broadcast_state(session)

    try:
        while True:
            raw: Any = await websocket.receive_json()
            if not isinstance(raw, dict):
                await websocket.send_json({"type": "error", "detail": "ожидали JSON-объект"})
                continue
            msg_type = raw.get("type")
            try:
                if msg_type == "ping":
                    await websocket.send_json({"type": "pong"})
                elif msg_type == "start":
                    await start_match_for_room(session, by_account_id=account.account_id)
                elif msg_type == "claim_seat":
                    seat_id = raw.get("seat_id")
                    if not isinstance(seat_id, str):
                        await websocket.send_json({"type": "error", "detail": "нужен seat_id"})
                        continue
                    await claim_seat(session, account_id=account.account_id, seat_id=seat_id)
                elif msg_type == "host":
                    action = raw.get("action")
                    if not isinstance(action, str):
                        await websocket.send_json({"type": "error", "detail": "нужен action"})
                        continue
                    seat_id = raw.get("seat_id")
                    target_aid = raw.get("account_id")
                    await host_action(
                        session,
                        by_account_id=account.account_id,
                        action=action,
                        seat_id=seat_id if isinstance(seat_id, str) else None,
                        account_id=int(target_aid) if target_aid is not None else None,
                    )
                elif msg_type == "intent":
                    intent = raw.get("intent")
                    if not isinstance(intent, dict):
                        await websocket.send_json(
                            {"type": "error", "detail": "intent должен быть объектом"}
                        )
                        continue
                    await apply_client_intent(
                        session, account_id=account.account_id, payload=intent
                    )
                elif msg_type == "sync":
                    # Клиент просит актуальный state (после return на вкладку) —
                    # без «догона» таймера: фаза уже тикает на сервере.
                    await broadcast_state(session)
                elif msg_type == "pause":
                    await pause_match(
                        session,
                        account_id=account.account_id,
                        by_label=session.nicks.get(account.account_id, ""),
                    )
                elif msg_type == "resume":
                    await resume_match(
                        session,
                        account_id=account.account_id,
                        by_label=session.nicks.get(account.account_id, ""),
                    )
                else:
                    await websocket.send_json(
                        {"type": "error", "detail": f"неизвестный type {msg_type!r}"}
                    )
            except (PermissionError, IllegalMove) as exc:
                # Отказ по правилу/правам. Без лога «у меня не нажимается» на проде
                # неотлаживаемо — интент видно, а причину отказа нет.
                event(
                    logger,
                    "ЗАДАЧА",
                    "mp_ws_reject code=%s type=%s intent=%s: %s",
                    session.room_code,
                    msg_type,
                    (raw.get("intent") or {}).get("type") if isinstance(raw, dict) else None,
                    str(exc),
                    room_code=session.room_code,
                    account_id=account.account_id,
                    level=logging.WARNING,
                )
                await websocket.send_json({"type": "error", "detail": str(exc)})
            except Exception as exc:  # noqa: BLE001
                event(
                    logger,
                    "ОШИБКА",
                    "mp_ws_handler code=%s: %s",
                    session.room_code,
                    exc,
                    room_code=session.room_code,
                    account_id=account.account_id,
                    level=logging.ERROR,
                    exc_info=True,
                )
                await websocket.send_json({"type": "error", "detail": "внутренняя ошибка"})
    except WebSocketDisconnect:
        pass
    finally:
        await unbind_connection(session, websocket)
        if websocket.client_state == WebSocketState.CONNECTED:
            with contextlib.suppress(Exception):
                await websocket.close()
        await hub().drop_if_empty(session.room_code)
