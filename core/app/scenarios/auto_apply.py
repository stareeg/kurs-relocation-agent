"""Отчёт раннера автооткликов (Фаза 2.1/2.2) — кросс-доменный сценарий.

Раннер живёт в расширении (открытие вкладки, клик по «Откликнуться» на площадке — сама механика
физически не может жить на бэке). После каждой попытки (dry-run или реальной) расширение шлёт
сюда результат: сценарий всегда пишет структурную запись в лог (видимость важнее скорости —
владелец должен уметь объяснить себе, почему автоотклик сработал именно так), а при реальной
(не dry-run) успешной отправке — двигает стадию воронки через Channel-паттерн (A-27, см.
`core/app/channels.py`), с меткой `source=auto_apply_<platform>`, отличимой от ручного клика.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from core.app.channels import AUTO_APPLY_GETMATCH, AUTO_APPLY_HABR, AUTO_APPLY_HH, set_stage_via
from core.app.scenarios.cover_letter import schedule_cover_letter_pregen
from core.domains.opportunities.discovery_session import get_discovery_status, stop_session
from core.domains.opportunities.jobs import Job, get_job, list_jobs, update_job_anketa
from core.domains.opportunities.models import AnketaAnswer, AnketaQuestion, AnketaState
from core.domains.opportunities.service import skip_job
from core.domains.pipeline.auto_apply.anketa import generate_anketa_answers
from core.domains.pipeline.auto_apply.config import (
    AutoApplyConfig,
    AutoApplyPlatform,
    get_auto_apply_config,
    set_auto_apply_config,
)
from core.domains.pipeline.auto_apply.outcomes import (
    failure_reason_ru,
    is_failure_outcome,
    is_unconfirmed_outcome,
)
from core.domains.pipeline.auto_apply.overrides import set_override
from core.domains.pipeline.auto_apply.queue import AutoApplyQueuePreview, preview_queue
from core.domains.pipeline.auto_apply.runtime_state import (
    get_last_tick,
    last_real_apply_at,
    mark_platform_limit,
    record_real_apply,
    record_tick,
    should_log_tick,
)
from core.kernel.errors import LlmError
from core.kernel.schemas.funnel import FunnelStatus
from core.platform.observability import event

logger = logging.getLogger(__name__)

_CHANNEL_BY_PLATFORM = {
    "hh": AUTO_APPLY_HH,
    "getmatch": AUTO_APPLY_GETMATCH,
    "habr": AUTO_APPLY_HABR,
}

# Фаза 8.2: исходы флоу расширения, которые сигналят «дальше рискованно/бессмысленно» —
# площадка останавливается автоматически (не только логируется), пока владелец не разберётся
# руками. Капча/блокировка — реальный риск бана живого аккаунта; скрытое резюме — молчаливый
# провал (клики уходят, ответов не будет никогда, пока резюме не открыто).
_BLOCKER_REASONS: dict[str, str] = {
    "captcha": "подозрение на капчу/блокировку площадки",
    "resume_hidden": "резюме скрыто от работодателей — отклики уходят вслепую",
}

# Предохранитель троттлинга: два реальных отклика площадки ближе этого интервала = раннер
# обойдён/сломан (цель — 120с). Ниже порога площадка выключается автоматически (см. report_attempt).
_THROTTLE_BREAKER_S = 45


async def report_attempt(
    platform: AutoApplyPlatform,
    *,
    job_id: int,
    vacancy_id: str,
    dry_run: bool,
    account_id: int,
    outcome: str | None = None,
    anketa_questions: list[AnketaQuestion] | None = None,
) -> Job | None:
    """Записать попытку автооткликa: всегда лог, стадия воронки — только если не dry-run.

    `outcome` (Фаза 8.2) — исход DOM-флоу расширения, если раннер его прислал:
    `captcha`/`resume_hidden` останавливают площадку автоматически (ERROR в лог — эти два
    требуют ручного вмешательства владельца), `platform_limit` — тихая пауза до завтра (это
    СВОЙ лимит площадки, не наш `daily_cap`, ретраить его в тот же день бессмысленно).
    Сбои DOM (`timeout`/`no_button`/…) в боевом режиме (`dry_run=False`) переносят вакансию в
    «Ручной разбор» с русским `failure_reason` — иначе одна и та же вакансия крутилась бы в
    auto на каждом тике (инцидент 2026-08-27).
    `anketa` (Фаза 3.3) — расширение встретило анкету и прислало распарсенные вопросы
    (`anketa_questions`): генерируем черновик ответов (LLM) и паркуем как `pending` на
    `jobs.anketa` — реальная отправка ждёт подтверждения владельца (`confirm_anketa`),
    воронку не двигаем (как dry-run — попытки без реального клика не было).

    `needs_confirmation` (Фаза 3.4) — площадка в режиме «Тест» (`require_confirmation`), анкеты
    не было: раннер уже дошёл до финального клика, сгенерировал и сохранил письмо
    (`jobs.cover_letter_text`, отдельным вызовом, до этого репорта), но не кликнул — паркуем
    ту же очередь `jobs.anketa`, что и у анкеты (`questions=[]`), без LLM-вызова (нечего
    генерировать, письмо уже готово отдельно). Раннер подхватит `approved` на следующем тике
    и повторит визит с реальным кликом (`confirm_anketa`/список `list_pending_anketas`
    работают одинаково для обоих случаев — очередь общая).

    Стадию воронки двигаем только при `outcome in (None, "applied", "already_applied")` и
    `dry_run=False`. `dry_run` в запросе — настройка площадки (не «удался ли клик»).
    """
    if outcome == "anketa":
        return await _handle_anketa_outcome(
            platform,
            job_id=job_id,
            vacancy_id=vacancy_id,
            account_id=account_id,
            questions=anketa_questions,
        )

    if outcome == "needs_confirmation":
        return await _park_pending_confirmation(
            platform,
            job_id=job_id,
            vacancy_id=vacancy_id,
            account_id=account_id,
            questions=[],
            answers=[],
        )

    if outcome in _BLOCKER_REASONS:
        event(
            logger,
            "АВТООТКЛИК",
            "%s: %s — площадка остановлена автоматически (job_id=%s vacancy_id=%s)",
            platform,
            _BLOCKER_REASONS[outcome],
            job_id,
            vacancy_id,
            level=logging.ERROR,
            platform=platform,
            job_id=job_id,
            vacancy_id=vacancy_id,
            account_id=account_id,
            outcome=outcome,
        )
        await disable_platform(platform, account_id=account_id)
        return None

    if outcome == "platform_limit":
        event(
            logger,
            "АВТООТКЛИК",
            "%s: собственный дневной лимит площадки — тихая пауза до завтра "
            "(job_id=%s vacancy_id=%s)",
            platform,
            job_id,
            vacancy_id,
            platform=platform,
            job_id=job_id,
            vacancy_id=vacancy_id,
            account_id=account_id,
            outcome=outcome,
        )
        await mark_platform_limit(platform, account_id=account_id)
        return None

    # «Не смогли подтвердить» — ещё не «не отправили». Клик уже был, и площадка могла принять
    # отклик, просто маркеры успеха не проявились в отведённое окно. Контент-скрипт замечает
    # реальную отправку своим путём (`POST /funnel` → стадия `Отклик`), и этот сигнал сильнее
    # таймаута раннера: он опирается на состояние страницы, а не на «мы не дождались».
    # Прод 2026-08-31, job 867: hh.ru показал свою модалку поверх страницы, отклик ушёл, а
    # вакансия уехала в «Ручной разбор» с надписью «Сбой при отправке отклика» — владелец видел
    # бы её как несделанную работу и откликнулся второй раз.
    if not dry_run and is_unconfirmed_outcome(outcome):
        job = await get_job(job_id, account_id=account_id)
        if job is not None and job.status == FunnelStatus.APPLIED.value:
            event(
                logger,
                "АВТООТКЛИК",
                "%s: подтверждения не дождались (исход=%s), но отклик уже в воронке — "
                "засчитываю отправленным (job_id=%s vacancy_id=%s)",
                platform,
                outcome,
                job_id,
                vacancy_id,
                platform=platform,
                job_id=job_id,
                vacancy_id=vacancy_id,
                account_id=account_id,
                outcome=outcome,
            )
            await record_real_apply(platform, account_id=account_id)
            return job

    # Реальный режим + сбой DOM-флоу: раньше раннер репортил такие попытки как dry_run=true
    # («кликнул бы»), вакансия оставалась в auto и крутилась одним и тем же job_id на каждом
    # тике (прод, 2026-08-27, job 720). Переносим в «Ручной разбор» с понятной причиной.
    if not dry_run and is_failure_outcome(outcome):
        reason = failure_reason_ru(outcome)
        await set_override(job_id, "manual_review", account_id=account_id, reason=reason)
        event(
            logger,
            "АВТООТКЛИК",
            "%s: не удалось отправить — %s (job_id=%s vacancy_id=%s) → ручной разбор",
            platform,
            reason,
            job_id,
            vacancy_id,
            level=logging.WARNING,
            platform=platform,
            job_id=job_id,
            vacancy_id=vacancy_id,
            dry_run=dry_run,
            account_id=account_id,
            outcome=outcome,
            failure_reason=reason,
        )
        return None

    applied_ok = (not dry_run) and (outcome in (None, "applied", "already_applied"))
    event(
        logger,
        "АВТООТКЛИК",
        "%s: %s job_id=%s vacancy_id=%s",
        platform,
        (
            "dry-run: кликнул бы"
            if dry_run
            else ("отправлен" if applied_ok else f"исход={outcome or 'unknown'}")
        ),
        job_id,
        vacancy_id,
        platform=platform,
        job_id=job_id,
        vacancy_id=vacancy_id,
        dry_run=dry_run,
        account_id=account_id,
        outcome=outcome,
    )
    if not applied_ok:
        return None

    # Троттлинг ≤1 реального отклика в 2 мин на площадку (`auto_apply_min_real_interval_ms`).
    # Первичная защита — раннер (`awaitRealApplySlot` + серверный клок из `/daily-count`), но
    # клик уже произошёл к моменту этого репорта, поэтому здесь — только фиксация факта:
    #  • `gap < 90с` — «чуть быстрее нормы», мягкий WARNING (перезапуск SW обнулил локальный клок,
    #    первый отклик ушёл сразу — это норма);
    #  • `gap < _THROTTLE_BREAKER_S` — однозначный обход (двойной клик, модифицированный раннер):
    #    выключаем площадку (тот же путь, что капча) — один отклик проскочил, залп не пройдёт.
    prev = await last_real_apply_at(platform, account_id=account_id)
    if prev is not None:
        gap = (datetime.now(UTC) - prev).total_seconds()
        if gap < _THROTTLE_BREAKER_S:
            event(
                logger,
                "АВТООТКЛИК",
                "%s: два реальных отклика за %.0fс (< %dс) — троттлинг обойдён, площадка "
                "выключена (job_id=%s)",
                platform,
                gap,
                _THROTTLE_BREAKER_S,
                job_id,
                level=logging.ERROR,
                platform=platform,
                job_id=job_id,
                vacancy_id=vacancy_id,
                account_id=account_id,
                interval_s=round(gap, 1),
            )
            await disable_platform(platform, account_id=account_id)
        elif gap < 90:
            event(
                logger,
                "АВТООТКЛИК",
                "%s: реальные отклики чаще 1 раз в 2 мин (интервал %.0fс) — проверьте тюнинг "
                "auto_apply_min_real_interval_ms (job_id=%s)",
                platform,
                gap,
                job_id,
                level=logging.WARNING,
                platform=platform,
                job_id=job_id,
                vacancy_id=vacancy_id,
                account_id=account_id,
                interval_s=round(gap, 1),
            )
    await record_real_apply(platform, account_id=account_id)

    channel = _CHANNEL_BY_PLATFORM[platform]
    return await set_stage_via(channel, job_id, FunnelStatus.APPLIED.value, account_id=account_id)


async def report_tick_summary(
    *,
    account_id: int,
    platforms_enabled: list[str],
    platforms_ready: list[str],
    candidates: int,
    applied: int,
    needs_confirmation: int,
    anketa: int,
    failed: int,
    blocked: list[str],
    bail_reason: str | None,
) -> None:
    """Итог одного тика раннера расширения — heartbeat в журнал + `last_tick` в рантайм-стейт.

    Без этой строки «раннер молча ничего не делает» (SW усыплён / бэк-ручка отвалилась /
    очередь пуста) неотличимо в проде от «раннер жив, но тихо» — именно так инцидент
    2026-08-27..28 (alarm-баг) прожил 9 часов незамеченным.

    Уровень: WARNING, если раннер хотел работать, но не смог (`bail_reason`, `blocked`, `failed`);
    иначе INFO — рутинный heartbeat («0 кандидатов» — норма, если очередь разобрана).
    """
    problem = bool(bail_reason) or bool(blocked) or failed > 0
    activity = applied > 0 or needs_confirmation > 0 or anketa > 0
    # Проблемный тик — всегда в журнал; активность — всегда; рутинный «раннер жив» — раз в 30 мин.
    to_log = problem or activity or await should_log_tick(account_id=account_id)
    await record_tick(
        account_id=account_id,
        logged=to_log,
        summary={
            "platforms_enabled": platforms_enabled,
            "platforms_ready": platforms_ready,
            "candidates": candidates,
            "applied": applied,
            "needs_confirmation": needs_confirmation,
            "anketa": anketa,
            "failed": failed,
            "blocked": blocked,
            "bail_reason": bail_reason,
        },
    )
    if not to_log:
        return
    event(
        logger,
        "АВТООТКЛИК",
        "тик: площадки вкл=%s готовы=%s кандидатов=%d отправлено=%d "
        "на_подтверждении=%d анкет=%d сбоев=%d%s%s",
        ",".join(platforms_enabled) or "нет",
        ",".join(platforms_ready) or "нет",
        candidates,
        applied,
        needs_confirmation,
        anketa,
        failed,
        f" блокеры={','.join(blocked)}" if blocked else "",
        f" отказ={bail_reason}" if bail_reason else "",
        level=logging.WARNING if problem else logging.INFO,
        account_id=account_id,
        platforms_enabled=platforms_enabled,
        platforms_ready=platforms_ready,
        candidates=candidates,
        applied=applied,
        needs_confirmation=needs_confirmation,
        anketa=anketa,
        failed=failed,
        blocked=blocked,
        bail_reason=bail_reason,
    )


async def _handle_anketa_outcome(
    platform: AutoApplyPlatform,
    *,
    job_id: int,
    vacancy_id: str,
    account_id: int,
    questions: list[AnketaQuestion] | None,
) -> None:
    """Анкета встречена (Фаза 3.3): сгенерировать черновик ответов и запарковать `pending` на
    `jobs.anketa`. Никогда не двигает воронку — до подтверждения владельца отправки не было.
    """
    if not questions:
        event(
            logger,
            "АВТООТКЛИК",
            "%s: анкета без распарсенных вопросов от расширения, пропускаю (job_id=%s)",
            platform,
            job_id,
            level=logging.WARNING,
            platform=platform,
            job_id=job_id,
            vacancy_id=vacancy_id,
            account_id=account_id,
        )
        return None

    job = await get_job(job_id, account_id=account_id)
    if job is None:
        event(
            logger,
            "АВТООТКЛИК",
            "%s: анкета — вакансия job_id=%s не найдена, пропускаю",
            platform,
            job_id,
            level=logging.ERROR,
            platform=platform,
            job_id=job_id,
            account_id=account_id,
        )
        return None

    from core.domains.preparation.asker import record_from_request_fallback

    record = record_from_request_fallback(
        job.vacancy_id or str(job.id),
        vacancy_text=job.vacancy_text or "",
        title=job.title,
        company=job.company,
        salary_text=job.salary_text,
    )
    try:
        answers = await generate_anketa_answers(questions, record, account_id=account_id)
    except LlmError as exc:
        event(
            logger,
            "АВТООТКЛИК",
            "%s: анкета — генерация ответов не удалась: %s (job_id=%s)",
            platform,
            exc,
            job_id,
            level=logging.ERROR,
            platform=platform,
            job_id=job_id,
            vacancy_id=vacancy_id,
            account_id=account_id,
        )
        return None

    await _park_pending_confirmation(
        platform,
        job_id=job_id,
        vacancy_id=vacancy_id,
        account_id=account_id,
        questions=questions,
        answers=answers,
    )
    return None


async def _park_pending_confirmation(
    platform: AutoApplyPlatform,
    *,
    job_id: int,
    vacancy_id: str,
    account_id: int,
    questions: list[AnketaQuestion],
    answers: list[AnketaAnswer],
) -> None:
    """Записать `jobs.anketa` как `pending` — общая точка для анкеты (3.3, `questions`
    непусто) и простого подтверждения письма в режиме «Тест» (3.4, `questions=[]`, письмо
    уже лежит отдельно в `jobs.cover_letter_text`, здесь не дублируется).
    """
    state = AnketaState(
        status="pending",
        platform=platform,
        questions=questions,
        answers=answers,
        requested_at=datetime.now(UTC).isoformat(),
    )
    await update_job_anketa(vacancy_id, anketa=state.model_dump(mode="json"), account_id=account_id)
    if questions:
        event(
            logger,
            "АВТООТКЛИК",
            "%s: анкета — %d вопросов, ответы сгенерированы, жду подтверждения "
            "(job_id=%s vacancy_id=%s)",
            platform,
            len(questions),
            job_id,
            vacancy_id,
            platform=platform,
            job_id=job_id,
            vacancy_id=vacancy_id,
            account_id=account_id,
            questions=len(questions),
        )
    else:
        event(
            logger,
            "АВТООТКЛИК",
            "%s: режим «Тест» — письмо готово, жду подтверждения перед реальной отправкой "
            "(job_id=%s vacancy_id=%s)",
            platform,
            job_id,
            vacancy_id,
            platform=platform,
            job_id=job_id,
            vacancy_id=vacancy_id,
            account_id=account_id,
        )
    return None


@dataclass(frozen=True, slots=True)
class AutoApplyScheduleInfo:
    """Темп раннера для UI «через сколько следующий автоотклик» (см. `AutoApplySchedule`)."""

    runner_last_tick_at: datetime | None
    tick_seconds: int
    real_per_tick: int
    gap_seconds: int
    min_gap_seconds: int


async def auto_apply_schedule(*, account_id: int) -> AutoApplyScheduleInfo:
    """Собрать темп раннера: тик/лимит/паузы из рантайм-конфига расширения + heartbeat аккаунта.

    Фронт по этим числам и позиции строки в очереди площадки оценивает ETA каждого автоотклика —
    чтобы пользователь видел прогресс, а не чёрный ящик.
    """
    from core.domains.opportunities.extension_runtime_config import get_extension_runtime_config

    cfg = await get_extension_runtime_config()
    tuning = cfg.tuning
    delay = tuning.get("auto_apply_delay_ms") or [20_000, 90_000]
    if isinstance(delay, list) and len(delay) == 2:
        gap_ms = (int(delay[0]) + int(delay[1])) // 2
    else:
        gap_ms = 55_000

    last = await get_last_tick(account_id=account_id)
    stamp = (last or {}).get("at")
    last_at: datetime | None = None
    if isinstance(stamp, str):
        try:
            last_at = datetime.fromisoformat(stamp)
        except ValueError:
            last_at = None

    return AutoApplyScheduleInfo(
        runner_last_tick_at=last_at,
        tick_seconds=int(tuning.get("auto_apply_tick_minutes", 5)) * 60,
        real_per_tick=int(tuning.get("max_real_applications_per_tick", 1)),
        gap_seconds=max(1, gap_ms // 1000),
        min_gap_seconds=max(1, int(tuning.get("auto_apply_min_real_interval_ms", 35_000)) // 1000),
    )


async def preview_with_pregen(
    platform: AutoApplyPlatform, *, account_id: int
) -> AutoApplyQueuePreview:
    """Живое превью очереди + попутный триггер фоновой пре-генерации сопроводительных
    (UX-правка 2026-08-20, пункт 1): пока владелец смотрит на очередь «Автоотклик», письма без
    готового текста готовятся в фоне тем же путём, что и ручная кнопка — не нужно ждать первого
    визита раннера расширения или жать «Сгенерировать» самому. Только бакет `auto` — «на ручной
    разбор» ещё не решённая вакансия, письмо туда пока не нужно.
    """
    preview = await preview_queue(platform, account_id=account_id)
    for job in preview.auto:
        if job.id is not None and not (job.cover_letter_text or "").strip():
            schedule_cover_letter_pregen(job.id, job.vacancy_text or "", account_id=account_id)
    return preview


async def list_pending_anketas(
    platform: AutoApplyPlatform, *, status: str = "pending", account_id: int
) -> list[Job]:
    """Вакансии площадки в заданном статусе очереди подтверждения — анкета (Фаза 3.3,
    `questions` непусто) или простое подтверждение письма в режиме «Тест» (Фаза 3.4,
    `questions=[]`); одна и та же очередь, имя функции осталось историческим. Та же выборка
    также используется раннером для повторного визита за `status="approved"`. Живой пересчёт
    по `jobs`, тот же приём, что `preview_queue` — без отдельной таблицы/индекса, объём мал.
    """
    jobs = await list_jobs(status=FunnelStatus.VIEWED.value, limit=500, account_id=account_id)
    return [
        j
        for j in jobs
        if j.anketa and j.anketa.get("platform") == platform and j.anketa.get("status") == status
    ]


async def confirm_anketa(
    job_id: int, *, answers: list[AnketaAnswer], account_id: int
) -> Job | None:
    """Владелец подтвердил (возможно отредактированные) ответы анкеты — `pending → approved`.
    Реальную отправку выполняет раннер на следующем тике (переоткрывает вкладку, повторяет
    клик, заполняет анкету этими ответами) — веб только ставит флаг. `None` — вакансии или
    анкеты на ней нет.
    """
    job = await get_job(job_id, account_id=account_id)
    if job is None or not job.anketa:
        return None
    state = AnketaState.model_validate(job.anketa)
    state.status = "approved"
    state.answers = answers
    state.resolved_at = datetime.now(UTC).isoformat()
    updated = await update_job_anketa(
        job.vacancy_id or "", anketa=state.model_dump(mode="json"), account_id=account_id
    )
    event(
        logger,
        "АВТООТКЛИК",
        "анкета подтверждена владельцем, ждёт отправки раннером (job_id=%s)",
        job_id,
        job_id=job_id,
        account_id=account_id,
    )
    return updated


async def reject_anketa(job_id: int, *, account_id: int) -> Job | None:
    """Владелец отклонил анкету — `pending → rejected`, раннер её больше не подхватит.
    `None` — вакансии или анкеты на ней нет.
    """
    job = await get_job(job_id, account_id=account_id)
    if job is None or not job.anketa:
        return None
    state = AnketaState.model_validate(job.anketa)
    state.status = "rejected"
    state.resolved_at = datetime.now(UTC).isoformat()
    updated = await update_job_anketa(
        job.vacancy_id or "", anketa=state.model_dump(mode="json"), account_id=account_id
    )
    event(
        logger,
        "АВТООТКЛИК",
        "анкета отклонена владельцем (job_id=%s)",
        job_id,
        job_id=job_id,
        account_id=account_id,
    )
    return updated


async def disable_platform(platform: AutoApplyPlatform, *, account_id: int) -> AutoApplyConfig:
    """Остановить ОДНУ площадку автоматически (Фаза 8.2: капча/блокировка/скрытое резюме) —
    в отличие от `pause_all` (kill switch, все площадки разом по ручному действию владельца),
    здесь решение принимает сам раннер по факту блокера, соседние площадки не трогает.
    """
    config = await get_auto_apply_config(account_id=account_id)
    updated = config.model_copy(
        update={platform: config.platform(platform).model_copy(update={"enabled": False})}
    )
    await set_auto_apply_config(updated, account_id=account_id)
    return updated


_ALL_PLATFORMS: tuple[AutoApplyPlatform, ...] = ("hh", "getmatch", "habr")


async def pause_all(*, account_id: int) -> AutoApplyConfig:
    """Kill switch (Фаза 7.4, расширен 2026-08-19 пункт 8): мгновенно `enabled=False` на всех
    площадках автооткликов И останов всех идущих сессий автопросмотра разом.

    Один сценарий для обеих поверхностей (веб-тумблер «Стоп всё», `/pause_autoapply» в Telegram) —
    вместо того чтобы каждая сама гасила флаги/сессии по отдельности. `dry_run`/`daily_cap`/прочие
    настройки площадок не трогает — включить обратно можно с теми же порогами.

    Инцидент 2026-08-19: «Стоп всё» жила только в домене автооткликов и не знала про автопросмотр
    вообще — владелец жал кнопку, ожидая, что остановится ВСЁ (то, что видно под одной шапкой
    «Расширения»), а вкладки автопросмотра продолжали открываться. Автопросмотр — независимый
    процесс (своя сессия per platform в `discovery_session`), но с точки зрения владельца это одна
    кнопка аварийной остановки — гасим обе стороны пайплайна здесь, а не заводим вторую кнопку.
    """
    config = await get_auto_apply_config(account_id=account_id)
    paused = AutoApplyConfig(
        hh=config.hh.model_copy(update={"enabled": False}),
        getmatch=config.getmatch.model_copy(update={"enabled": False}),
        habr=config.habr.model_copy(update={"enabled": False}),
    )
    await set_auto_apply_config(paused, account_id=account_id)

    stopped_discovery: list[str] = []
    for platform in _ALL_PLATFORMS:
        status = await get_discovery_status(platform, account_id=account_id)
        if status.state == "idle":
            continue
        await stop_session(platform, account_id=account_id)
        stopped_discovery.append(platform)

    event(
        logger,
        "АВТООТКЛИК",
        "kill switch: все площадки автооткликов выключены, автопросмотр остановлен на %s",
        ", ".join(stopped_discovery) if stopped_discovery else "нигде не бежал",
        account_id=account_id,
        discovery_stopped=stopped_discovery,
    )
    return paused


async def resume_all(*, account_id: int) -> AutoApplyConfig:
    """Обратное к `pause_all` для операторской ручки в админке: `enabled=True` на всех трёх
    площадках автооткликов, прочие поля (dry_run/min_score/daily_cap/order) не трогаем.

    Реально «запустить» раннер отсюда нельзя — он живёт в браузере пользователя; это просто
    снимает флаг, расширение подхватит на следующем тике. Не трогавшая настройки площадка
    имеет `dry_run=True` по умолчанию — безопасно (доходит до клика, не кликает).
    """
    config = await get_auto_apply_config(account_id=account_id)
    resumed = AutoApplyConfig(
        hh=config.hh.model_copy(update={"enabled": True}),
        getmatch=config.getmatch.model_copy(update={"enabled": True}),
        habr=config.habr.model_copy(update={"enabled": True}),
    )
    await set_auto_apply_config(resumed, account_id=account_id)
    event(
        logger,
        "АВТООТКЛИК",
        "автоотклики включены на всех площадках (операторская ручка)",
        account_id=account_id,
    )
    return resumed


async def clear_queue(*, account_id: int) -> int:
    """Пункт 1 редизайна «Расширения» (2026-08-19): владелец очищает очередь автооткликов
    вручную — пропускает разом все вакансии, которые сейчас видны в превью (auto + manual_review)
    по всем площадкам. Уже отправленные («applied» в превью) не трогает — это история, не
    очередь. Тот же `skip_job`, что и одиночный квик-экшен «Пропустить» — вакансия сама выпадет
    из следующего пересчёта `preview_queue` (гейт `job.skipped`, gate.py).
    """
    cleared = 0
    for platform in _ALL_PLATFORMS:
        preview = await preview_queue(platform, account_id=account_id)
        platform_cleared = 0
        for job in (*preview.auto, *preview.manual_review):
            if job.id is None:
                continue
            await skip_job(
                job.id, "очередь автооткликов очищена владельцем вручную", account_id=account_id
            )
            cleared += 1
            platform_cleared += 1
        if platform_cleared > 0:
            event(
                logger,
                "АВТООТКЛИК",
                "очередь очищена: %s — %d вакансий пропущено (account_id=%s)",
                platform,
                platform_cleared,
                account_id,
                platform=platform,
                account_id=account_id,
            )
    return cleared


__all__ = [
    "AutoApplyScheduleInfo",
    "auto_apply_schedule",
    "clear_queue",
    "confirm_anketa",
    "disable_platform",
    "list_pending_anketas",
    "pause_all",
    "preview_with_pregen",
    "reject_anketa",
    "report_attempt",
    "report_tick_summary",
    "resume_all",
]
