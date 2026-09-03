"""Операторская консоль: сводка флота, аккаунты, ключи OpenRouter. Только role=owner."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from api.schemas.admin import (
    AdminAttention,
    AdminAuditPage,
    AdminAuditQuery,
    AdminCount,
    AdminDiagnosis,
    AdminDisableRequest,
    AdminDiscoveryStopRequest,
    AdminDiscoveryStopResponse,
    AdminExtensionRuntimeConfig,
    AdminExtensionRuntimeConfigRequest,
    AdminKeyBalances,
    AdminKeyHistory,
    AdminKeyIssueRequest,
    AdminKeyVerify,
    AdminKeyVerifyRequest,
    AdminLogPage,
    AdminLogsQuery,
    AdminNoteRequest,
    AdminOk,
    AdminPeoplePage,
    AdminPipelineCount,
    AdminPurgeRequest,
    AdminRevokeResponse,
    AdminRoleRequest,
    AdminSpend,
    AdminSpendAlert,
    AdminSpendAlertRequest,
    AdminSummary,
    AdminSupportSendRequest,
    AdminSupportThread,
    AdminTables,
    AdminTaskCancelKindRequest,
    AdminTaskDetail,
    AdminTaskRetryKindRequest,
    AdminTasks,
    AdminTasksQuery,
    AdminTelegramRequest,
    AdminUserDetail,
    AdminUserPipeline,
)
from api.security import AccountContext, invalidate_web_auth_cache, require_platform_admin
from core.domains.career import (
    ensure_all_system_admin_friendships,
    ensure_all_system_admin_friendships_throttled,
)
from core.platform.admin import (
    AdminError,
    cancel_failed_of_kind,
    cancel_task,
    clear_user_auto_apply_queue,
    clear_user_discovery_log,
    disable_user,
    enable_user,
    enqueue_admin_telegram,
    get_extension_runtime_config_admin,
    issue_user_key,
    load_attention,
    load_audit_page,
    load_key_history,
    load_logs,
    load_people,
    load_spend,
    load_summary,
    load_support_thread,
    load_tables,
    load_tasks,
    load_user_detail,
    load_user_diagnosis,
    load_user_pipeline,
    note_friendships_repair,
    pause_user_auto_apply,
    purge_logs,
    reclaim_stuck_tasks,
    refresh_key_balances,
    reject_key_request,
    resume_user_auto_apply,
    retry_failed_of_kind,
    retry_task,
    revoke_one_user_session,
    revoke_user_key,
    revoke_user_sessions,
    send_support_message,
    set_extension_runtime_config_admin,
    set_spend_alert,
    set_user_note,
    set_user_role,
    stop_user_discovery,
    user_log_bundle,
    verify_stored_user_key,
    verify_user_key,
)
from core.platform.repo.log_bundle import DEFAULT_WINDOW_HOURS, MAX_WINDOW_HOURS

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _raise(exc: AdminError) -> NoReturn:
    raise HTTPException(status_code=exc.status, detail=exc.message)


def _load_logs(params: AdminLogsQuery):
    return load_logs(
        since=params.since,
        until=params.until,
        level=params.level,
        account_id=params.account_id,
        telegram_user_id=params.telegram_user_id,
        logger_name=params.logger,
        event_name=params.event,
        query=params.q,
        cursor=params.cursor,
        limit=params.limit,
    )


def _load_audit(params: AdminAuditQuery):
    return load_audit_page(
        since=params.since,
        until=params.until,
        account_id=params.account_id,
        telegram_user_id=params.telegram_user_id,
        cursor=params.cursor,
        limit=params.limit,
    )


def _load_tasks(params: AdminTasksQuery):
    return load_tasks(status=params.status, kind=params.kind, limit=params.limit)


@router.get("/summary", response_model=AdminSummary)
async def get_summary(
    account: AccountContext = Depends(require_platform_admin),
) -> AdminSummary:
    """KPI-шапка, здоровье установки, воронка. Лёгкая ручка — опрашивается чаще остальных."""
    _ = account
    # Ремонт системных дружб — подстраховка, а не часть чтения: троттлинг держит его на одном
    # проходе в 10 минут вместо прохода на каждый опрос витрины (Этап 0.3). Жило на
    # `/overview`, переехало сюда вместе с удалением той ручки в конце Этапа 2.
    await ensure_all_system_admin_friendships_throttled()
    return await load_summary()


@router.get("/people", response_model=AdminPeoplePage)
async def get_people(
    account: AccountContext = Depends(require_platform_admin),
    q: str = Query("", max_length=120),
    status: str = Query("", pattern="^(active|disabled)?$"),
    onboarding: str = Query("", pattern="^(no_key|no_resume|no_extension|done)?$"),
    signal: str = Query("", pattern="^(errors|stale|spend)?$"),
    sort: str = Query("", max_length=32),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> AdminPeoplePage:
    _ = account
    try:
        return await load_people(
            query=q,
            status=status,
            onboarding=onboarding,
            signal=signal,
            sort=sort,
            limit=limit,
            offset=offset,
        )
    except AdminError as exc:
        _raise(exc)


@router.get("/attention", response_model=AdminAttention)
async def get_attention(
    account: AccountContext = Depends(require_platform_admin),
) -> AdminAttention:
    """Что требует решения: заявки, сбои, свежие ошибки, «отвалившиеся»."""
    _ = account
    return await load_attention()


@router.get("/spend", response_model=AdminSpend)
async def get_spend(
    account: AccountContext = Depends(require_platform_admin),
    days: int = Query(14, ge=1, le=180),
    group_by: str = Query("day", pattern="^(day|model|feature|account)$"),
    account_id: int | None = Query(None, ge=1),
) -> AdminSpend:
    _ = account
    try:
        return await load_spend(days=days, group_by=group_by, account_id=account_id)
    except AdminError as exc:
        _raise(exc)


@router.patch("/spend-alert", response_model=AdminSpendAlert)
async def patch_spend_alert(
    body: AdminSpendAlertRequest,
    account: AccountContext = Depends(require_platform_admin),
) -> AdminSpendAlert:
    try:
        usd = await set_spend_alert(body.usd, actor_id=account.account_id)
    except AdminError as exc:
        _raise(exc)
    return AdminSpendAlert(usd=usd)


@router.get("/extension-config", response_model=AdminExtensionRuntimeConfig)
async def get_extension_config(
    account: AccountContext = Depends(require_platform_admin),
) -> AdminExtensionRuntimeConfig:
    """Текущий рантайм-конфиг расширения (флаги/тюнинг/селекторы отклика), merged."""
    _ = account
    return AdminExtensionRuntimeConfig(**await get_extension_runtime_config_admin())


@router.put("/extension-config", response_model=AdminExtensionRuntimeConfig)
async def put_extension_config(
    body: AdminExtensionRuntimeConfigRequest,
    account: AccountContext = Depends(require_platform_admin),
) -> AdminExtensionRuntimeConfig:
    """Задать оверрайд (аварийный стоп площадки, замедление темпа, починка селектора «в
    субботу»). Все три секции пустые → снять оверрайд, вернуться на репозиторный дефолт."""
    try:
        result = await set_extension_runtime_config_admin(
            body.model_dump(), actor_id=account.account_id
        )
    except AdminError as exc:
        _raise(exc)
    return AdminExtensionRuntimeConfig(**result)


@router.get("/logs", response_model=AdminLogPage)
async def get_logs(
    params: Annotated[AdminLogsQuery, Query()],
    account: AccountContext = Depends(require_platform_admin),
) -> AdminLogPage:
    """Журнал copilot_logs. Заменяет scp+psql из инструкции Debugging prod."""
    _ = account
    try:
        return await _load_logs(params)
    except AdminError as exc:
        _raise(exc)


@router.get("/audit", response_model=AdminAuditPage)
async def get_audit(
    params: Annotated[AdminAuditQuery, Query()],
    account: AccountContext = Depends(require_platform_admin),
) -> AdminAuditPage:
    """Реестр действий оператора: кто, что, кому, когда."""
    _ = account
    try:
        return await _load_audit(params)
    except AdminError as exc:
        _raise(exc)


@router.get("/tasks", response_model=AdminTasks)
async def get_tasks(
    params: Annotated[AdminTasksQuery, Query()],
    account: AccountContext = Depends(require_platform_admin),
) -> AdminTasks:
    """Очередь фоновых задач: глубина, разрез по kind, список с payload."""
    _ = account
    return await _load_tasks(params)


@router.get("/tables", response_model=AdminTables)
async def get_tables(
    account: AccountContext = Depends(require_platform_admin),
) -> AdminTables:
    """Размеры ключевых таблиц Postgres."""
    _ = account
    return await load_tables()


@router.post("/tasks/reclaim", response_model=AdminCount)
async def post_tasks_reclaim(
    account: AccountContext = Depends(require_platform_admin),
) -> AdminCount:
    try:
        n = await reclaim_stuck_tasks(actor_id=account.account_id)
    except AdminError as exc:
        _raise(exc)
    return AdminCount(n=n)


@router.post("/tasks/retry", response_model=AdminCount)
async def post_tasks_retry_kind(
    body: AdminTaskRetryKindRequest,
    account: AccountContext = Depends(require_platform_admin),
) -> AdminCount:
    try:
        n = await retry_failed_of_kind(body.kind, actor_id=account.account_id, reason=body.reason)
    except AdminError as exc:
        _raise(exc)
    return AdminCount(n=n)


@router.post("/tasks/cancel-kind", response_model=AdminCount)
async def post_tasks_cancel_kind(
    body: AdminTaskCancelKindRequest,
    account: AccountContext = Depends(require_platform_admin),
) -> AdminCount:
    try:
        n = await cancel_failed_of_kind(body.kind, actor_id=account.account_id, reason=body.reason)
    except AdminError as exc:
        _raise(exc)
    return AdminCount(n=n)


@router.post("/tasks/{task_id}/retry", response_model=AdminTaskDetail)
async def post_task_retry(
    task_id: int,
    account: AccountContext = Depends(require_platform_admin),
) -> AdminTaskDetail:
    try:
        return await retry_task(task_id, actor_id=account.account_id)
    except AdminError as exc:
        _raise(exc)


@router.post("/tasks/{task_id}/cancel", response_model=AdminTaskDetail)
async def post_task_cancel(
    task_id: int,
    account: AccountContext = Depends(require_platform_admin),
) -> AdminTaskDetail:
    try:
        return await cancel_task(task_id, actor_id=account.account_id)
    except AdminError as exc:
        _raise(exc)


@router.post("/logs/purge", response_model=AdminCount)
async def post_logs_purge(
    body: AdminPurgeRequest,
    account: AccountContext = Depends(require_platform_admin),
) -> AdminCount:
    try:
        n = await purge_logs(days=body.days, actor_id=account.account_id)
    except AdminError as exc:
        _raise(exc)
    return AdminCount(n=n)


@router.post("/friendships/repair", response_model=AdminOk)
async def post_friendships_repair(
    account: AccountContext = Depends(require_platform_admin),
) -> AdminOk:
    """Полный проход ремонта дружб — то, что этап 0 убрал из горячего GET."""
    await ensure_all_system_admin_friendships()
    await note_friendships_repair(actor_id=account.account_id)
    return AdminOk()


@router.get("/users/{account_id}", response_model=AdminUserDetail)
async def get_user(
    account_id: int,
    account: AccountContext = Depends(require_platform_admin),
) -> AdminUserDetail:
    _ = account
    try:
        return await load_user_detail(account_id)
    except AdminError as exc:
        _raise(exc)


@router.get("/users/{account_id}/diagnosis", response_model=AdminDiagnosis)
async def get_user_diagnosis(
    account_id: int,
    account: AccountContext = Depends(require_platform_admin),
) -> AdminDiagnosis:
    """Что не так у человека: ключ, резюме, расширение, чат, ошибки, расход."""
    _ = account
    try:
        return await load_user_diagnosis(account_id)
    except AdminError as exc:
        _raise(exc)


@router.get("/users/{account_id}/pipeline", response_model=AdminUserPipeline)
async def get_user_pipeline(
    account_id: int,
    account: AccountContext = Depends(require_platform_admin),
) -> AdminUserPipeline:
    """Автопросмотр + автоотклики пользователя (вкладка «Автоматизация» в дровере)."""
    _ = account
    try:
        return await load_user_pipeline(account_id)
    except AdminError as exc:
        _raise(exc)


@router.post("/users/{account_id}/auto-apply/pause", response_model=AdminOk)
async def post_auto_apply_pause(
    account_id: int,
    account: AccountContext = Depends(require_platform_admin),
) -> AdminOk:
    try:
        await pause_user_auto_apply(account_id, actor_id=account.account_id)
    except AdminError as exc:
        _raise(exc)
    return AdminOk()


@router.post("/users/{account_id}/auto-apply/resume", response_model=AdminOk)
async def post_auto_apply_resume(
    account_id: int,
    account: AccountContext = Depends(require_platform_admin),
) -> AdminOk:
    try:
        await resume_user_auto_apply(account_id, actor_id=account.account_id)
    except AdminError as exc:
        _raise(exc)
    return AdminOk()


@router.post("/users/{account_id}/auto-apply/clear", response_model=AdminPipelineCount)
async def post_auto_apply_clear(
    account_id: int,
    account: AccountContext = Depends(require_platform_admin),
) -> AdminPipelineCount:
    try:
        cleared = await clear_user_auto_apply_queue(account_id, actor_id=account.account_id)
    except AdminError as exc:
        _raise(exc)
    return AdminPipelineCount(cleared=cleared)


@router.post("/users/{account_id}/discovery/stop", response_model=AdminDiscoveryStopResponse)
async def post_discovery_stop(
    account_id: int,
    body: AdminDiscoveryStopRequest | None = None,
    account: AccountContext = Depends(require_platform_admin),
) -> AdminDiscoveryStopResponse:
    try:
        stopped = await stop_user_discovery(
            account_id,
            platform=body.platform if body else None,
            actor_id=account.account_id,
        )
    except AdminError as exc:
        _raise(exc)
    return AdminDiscoveryStopResponse(stopped=stopped)


@router.post("/users/{account_id}/discovery/clear-log", response_model=AdminOk)
async def post_discovery_clear_log(
    account_id: int,
    account: AccountContext = Depends(require_platform_admin),
) -> AdminOk:
    try:
        await clear_user_discovery_log(account_id, actor_id=account.account_id)
    except AdminError as exc:
        _raise(exc)
    return AdminOk()


@router.post("/users/{account_id}/disable", response_model=AdminOk)
async def post_disable(
    account_id: int,
    account: AccountContext = Depends(require_platform_admin),
    body: AdminDisableRequest | None = None,
) -> AdminOk:
    try:
        reason = body.reason if body else ""
        await disable_user(account_id, actor_id=account.account_id, reason=reason)
    except AdminError as exc:
        _raise(exc)
    invalidate_web_auth_cache()
    return AdminOk()


@router.post("/users/{account_id}/enable", response_model=AdminOk)
async def post_enable(
    account_id: int,
    account: AccountContext = Depends(require_platform_admin),
) -> AdminOk:
    try:
        await enable_user(account_id, actor_id=account.account_id)
    except AdminError as exc:
        _raise(exc)
    return AdminOk()


@router.post("/users/{account_id}/revoke-sessions", response_model=AdminRevokeResponse)
async def post_revoke_sessions(
    account_id: int,
    account: AccountContext = Depends(require_platform_admin),
) -> AdminRevokeResponse:
    try:
        revoked = await revoke_user_sessions(account_id, actor_id=account.account_id)
    except AdminError as exc:
        _raise(exc)
    invalidate_web_auth_cache()
    return AdminRevokeResponse(revoked=revoked)


@router.post("/users/{account_id}/sessions/{session_id}/revoke", response_model=AdminOk)
async def post_revoke_one_session(
    account_id: int,
    session_id: int,
    account: AccountContext = Depends(require_platform_admin),
) -> AdminOk:
    try:
        await revoke_one_user_session(account_id, session_id, actor_id=account.account_id)
    except AdminError as exc:
        _raise(exc)
    invalidate_web_auth_cache()
    return AdminOk()


@router.get("/users/{account_id}/logs")
async def get_user_logs(
    account_id: int,
    account: AccountContext = Depends(require_platform_admin),
    hours: int = Query(DEFAULT_WINDOW_HOURS, ge=1, le=MAX_WINDOW_HOURS),
) -> StreamingResponse:
    try:
        data = await user_log_bundle(account_id, actor_id=account.account_id, hours=hours)
    except AdminError as exc:
        _raise(exc)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d-%H-%M")
    filename = f"support_bundle-{account_id}-{stamp}.zip"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(iter([data]), media_type="application/zip", headers=headers)


@router.post("/users/{account_id}/telegram", response_model=AdminOk)
async def post_telegram(
    account_id: int,
    body: AdminTelegramRequest,
    account: AccountContext = Depends(require_platform_admin),
) -> AdminOk:
    try:
        await enqueue_admin_telegram(account_id, body.text, actor_id=account.account_id)
    except AdminError as exc:
        _raise(exc)
    return AdminOk()


@router.get("/users/{account_id}/support", response_model=AdminSupportThread)
async def get_support_thread(
    account_id: int,
    account: AccountContext = Depends(require_platform_admin),
) -> AdminSupportThread:
    _ = account
    try:
        return await load_support_thread(account_id)
    except AdminError as exc:
        _raise(exc)


@router.post("/users/{account_id}/support", response_model=AdminSupportThread)
async def post_support_message(
    account_id: int,
    body: AdminSupportSendRequest,
    account: AccountContext = Depends(require_platform_admin),
) -> AdminSupportThread:
    try:
        return await send_support_message(
            account_id,
            channel=body.channel,
            text=body.text,
            actor_id=account.account_id,
            reply_to_id=body.reply_to_id,
        )
    except AdminError as exc:
        _raise(exc)


@router.post("/keys/verify", response_model=AdminKeyVerify)
async def post_key_verify(
    body: AdminKeyVerifyRequest,
    account: AccountContext = Depends(require_platform_admin),
) -> AdminKeyVerify:
    """Проверить ключ у OpenRouter до выдачи. Сеть → предупреждение, не 5xx."""
    _ = account
    return await verify_user_key(body.key)


@router.post("/keys/balances", response_model=AdminKeyBalances)
async def post_key_balances(
    account: AccountContext = Depends(require_platform_admin),
) -> AdminKeyBalances:
    """Остатки по ключам, которые выдал оператор. Кнопка, не опрос."""
    _ = account
    return await refresh_key_balances()


@router.get("/keys/history", response_model=AdminKeyHistory)
async def get_key_history(
    account: AccountContext = Depends(require_platform_admin),
) -> AdminKeyHistory:
    """Закрытые заявки и аудит выдач/отзывов."""
    _ = account
    return await load_key_history()


@router.post("/keys/{request_id}/reject", response_model=AdminOk)
async def post_key_reject(
    request_id: int,
    account: AccountContext = Depends(require_platform_admin),
) -> AdminOk:
    try:
        await reject_key_request(request_id, actor_id=account.account_id)
    except AdminError as exc:
        _raise(exc)
    return AdminOk()


@router.post("/users/{account_id}/key", response_model=AdminOk)
async def post_user_key(
    account_id: int,
    body: AdminKeyIssueRequest,
    account: AccountContext = Depends(require_platform_admin),
) -> AdminOk:
    """Выдать/перевыпустить ключ человеку. Ручка привязана к аккаунту, а не к заявке:
    перевыпустить ключ нужно и тому, кто ничего не просил (сгорел ключ, смена биллинга)."""
    try:
        await issue_user_key(account_id, body.key, actor_id=account.account_id, label=body.label)
    except AdminError as exc:
        _raise(exc)
    return AdminOk()


@router.delete("/users/{account_id}/key", response_model=AdminOk)
async def delete_user_key(
    account_id: int,
    account: AccountContext = Depends(require_platform_admin),
) -> AdminOk:
    try:
        await revoke_user_key(account_id, actor_id=account.account_id)
    except AdminError as exc:
        _raise(exc)
    return AdminOk()


@router.post("/users/{account_id}/key/verify", response_model=AdminKeyVerify)
async def post_stored_key_verify(
    account_id: int,
    account: AccountContext = Depends(require_platform_admin),
) -> AdminKeyVerify:
    """Проверить уже привязанный ключ. Сырого ключа в ответе нет."""
    _ = account
    try:
        return await verify_stored_user_key(account_id)
    except AdminError as exc:
        _raise(exc)


@router.patch("/users/{account_id}/note", response_model=AdminOk)
async def patch_note(
    account_id: int,
    body: AdminNoteRequest,
    account: AccountContext = Depends(require_platform_admin),
) -> AdminOk:
    try:
        await set_user_note(account_id, body.note, actor_id=account.account_id)
    except AdminError as exc:
        _raise(exc)
    return AdminOk()


@router.post("/users/{account_id}/role", response_model=AdminOk)
async def post_role(
    account_id: int,
    body: AdminRoleRequest,
    account: AccountContext = Depends(require_platform_admin),
) -> AdminOk:
    try:
        await set_user_role(account_id, body.role, actor_id=account.account_id)
    except AdminError as exc:
        _raise(exc)
    return AdminOk()
